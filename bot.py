import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set — create .env file from .env.example")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
TIKTOK_URL_RE = re.compile(
    r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+"
)
TIKTOK_CANONICAL_URL_RE = re.compile(
    r"^https?://(?:www\.)?tiktok\.com/@(?P<user>[^/?#]+)/"
    r"(?P<kind>video|photo)/(?P<id>\d+)"
)


@dataclass(frozen=True)
class TikTokRequest:
    original_url: str
    resolved_url: str
    download_url: str
    content_type: str
    post_id: str


class TikTokDownloadError(Exception):
    def __init__(
        self,
        error_type: str,
        user_message: str,
        stage: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(detail or user_message)
        self.error_type = error_type
        self.user_message = user_message
        self.stage = stage
        self.detail = detail or user_message


class SilentYtDlpLogger:
    def debug(self, msg: str) -> None:
        return None

    def warning(self, msg: str) -> None:
        return None

    def error(self, msg: str) -> None:
        return None


def strip_url_query(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_tiktok_url(user_handle: str, content_type: str, post_id: str) -> str:
    return f"https://www.tiktok.com/@{user_handle}/{content_type}/{post_id}"


def parse_tiktok_url(url: str) -> tuple[str, str, str] | None:
    match = TIKTOK_CANONICAL_URL_RE.match(url)
    if not match:
        return None
    return match.group("user"), match.group("kind"), match.group("id")


def resolve_redirect_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": BROWSER_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.geturl()
    except urllib.error.URLError as exc:
        raise TikTokDownloadError(
            error_type="temporary_tiktok_failure",
            user_message="TikTok временно недоступен, попробуйте позже.",
            stage="resolve",
            detail=str(exc),
        ) from exc


def normalize_tiktok_request(url: str) -> TikTokRequest:
    original_url = url.strip()
    direct_url = strip_url_query(original_url)
    parsed = parse_tiktok_url(direct_url)

    if parsed is None:
        resolved_url = strip_url_query(resolve_redirect_url(original_url))
        parsed = parse_tiktok_url(resolved_url)
    else:
        resolved_url = direct_url

    if parsed is None:
        raise TikTokDownloadError(
            error_type="unsupported_url",
            user_message="Не удалось распознать ссылку TikTok.",
            stage="resolve",
            detail=f"Unsupported TikTok URL: {original_url}",
        )

    user_handle, content_type, post_id = parsed
    download_url = build_tiktok_url(
        user_handle,
        "video" if content_type == "photo" else content_type,
        post_id,
    )
    canonical_resolved_url = build_tiktok_url(user_handle, content_type, post_id)
    return TikTokRequest(
        original_url=original_url,
        resolved_url=canonical_resolved_url,
        download_url=download_url,
        content_type=content_type,
        post_id=post_id,
    )


def map_download_error(
    exc: Exception,
    request: TikTokRequest,
    stage: str = "extract",
) -> TikTokDownloadError:
    message = str(exc)
    lowered = message.lower()

    if "log in for access" in lowered or "cookies" in lowered:
        return TikTokDownloadError(
            error_type="login_required",
            user_message=(
                "Этот TikTok пост требует авторизацию, "
                "поэтому сейчас я не могу скачать звук."
            ),
            stage=stage,
            detail=message,
        )

    if any(marker in lowered for marker in (
        "timed out",
        "timeout",
        "too many requests",
        "http error 429",
        "temporarily unavailable",
        "server error",
        "connection reset",
        "server disconnected",
    )):
        return TikTokDownloadError(
            error_type="temporary_tiktok_failure",
            user_message="TikTok временно недоступен, попробуйте позже.",
            stage=stage,
            detail=message,
        )

    if request.content_type == "photo":
        return TikTokDownloadError(
            error_type="photo_sound_unavailable",
            user_message="В этом TikTok photo-посте не удалось найти доступный звук.",
            stage=stage,
            detail=message,
        )

    if "unsupported url" in lowered:
        return TikTokDownloadError(
            error_type="unsupported_url",
            user_message="Не удалось распознать ссылку TikTok.",
            stage=stage,
            detail=message,
        )

    return TikTokDownloadError(
        error_type="download_failed",
        user_message="Не удалось скачать аудио из TikTok.",
        stage=stage,
        detail=message,
    )


def convert_to_mp3(downloaded: Path, mp3_path: Path) -> Path:
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(downloaded),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "192k",
            "-y",
            str(mp3_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and mp3_path.exists():
        return mp3_path

    raise TikTokDownloadError(
        error_type="conversion_failed",
        user_message="Не удалось обработать аудио после скачивания.",
        stage="convert",
        detail=result.stderr.strip() or result.stdout.strip() or "ffmpeg conversion failed",
    )


def download_mp3(request: TikTokRequest, output_dir: str) -> Path:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": SilentYtDlpLogger(),
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(request.download_url, download=True)
    except DownloadError as exc:
        raise map_download_error(exc, request) from exc
    except Exception as exc:
        raise map_download_error(exc, request, stage="download") from exc

    if info is None:
        raise TikTokDownloadError(
            error_type=(
                "photo_sound_unavailable"
                if request.content_type == "photo"
                else "download_failed"
            ),
            user_message=(
                "В этом TikTok photo-посте не удалось найти доступный звук."
                if request.content_type == "photo"
                else "Не удалось скачать аудио из TikTok."
            ),
            stage="download",
        )

    video_id = str(info.get("id") or request.post_id or "audio")

    downloaded_files = sorted(
        Path(output_dir).glob(f"{video_id}.*"),
        key=lambda path: (path.suffix.lower() != ".mp3", path.name),
    )
    if not downloaded_files:
        raise TikTokDownloadError(
            error_type=(
                "photo_sound_unavailable"
                if request.content_type == "photo"
                else "download_failed"
            ),
            user_message=(
                "В этом TikTok photo-посте не удалось найти доступный звук."
                if request.content_type == "photo"
                else "Не удалось скачать аудио из TikTok."
            ),
            stage="download",
        )

    downloaded = downloaded_files[0]
    if downloaded.suffix.lower() == ".mp3":
        return downloaded

    mp3_path = Path(output_dir) / f"{video_id}.mp3"
    return convert_to_mp3(downloaded, mp3_path)


def process_tiktok_request(url: str, output_dir: str) -> tuple[TikTokRequest, Path]:
    request = normalize_tiktok_request(url)
    return request, download_mp3(request, output_dir)


def log_request_result(
    level: int,
    request_id: str,
    original_url: str,
    duration_ms: int,
    *,
    outcome: str,
    stage: str,
    request: TikTokRequest | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    payload = {
        "request_id": request_id,
        "original_url": original_url,
        "resolved_url": request.resolved_url if request else None,
        "post_id": request.post_id if request else None,
        "content_type": request.content_type if request else None,
        "stage": stage,
        "outcome": outcome,
        "error_type": error_type,
        "error_message": error_message,
        "duration_ms": duration_ms,
    }
    logging.log(
        level,
        "tiktok_request %s",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Отправь мне ссылку на TikTok видео или photo-пост, "
        "и я пришлю тебе аудио в формате MP3."
    )


@dp.message(F.text)
async def handle_url(message: Message) -> None:
    text = message.text or ""
    match = TIKTOK_URL_RE.search(text)
    if not match:
        await message.answer("Отправь ссылку на TikTok видео или photo-пост.")
        return

    url = match.group(0)
    request_id = uuid4().hex[:8]
    started_at = time.monotonic()
    request: TikTokRequest | None = None
    progress = await message.answer("Скачиваю аудио...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            loop = asyncio.get_running_loop()
            request, mp3_path = await loop.run_in_executor(
                None,
                process_tiktok_request,
                url,
                tmpdir,
            )

            audio_file = FSInputFile(mp3_path)
            await message.answer_audio(audio=audio_file)
            await progress.delete()
            log_request_result(
                logging.INFO,
                request_id,
                url,
                int((time.monotonic() - started_at) * 1000),
                request=request,
                outcome="success",
                stage="send",
            )
    except TikTokDownloadError as exc:
        log_request_result(
            logging.WARNING,
            request_id,
            url,
            int((time.monotonic() - started_at) * 1000),
            request=request,
            outcome="failure",
            stage=exc.stage,
            error_type=exc.error_type,
            error_message=exc.detail,
        )
        await progress.edit_text(exc.user_message)
    except Exception as exc:
        logging.exception("Unhandled request error %s", request_id)
        log_request_result(
            logging.ERROR,
            request_id,
            url,
            int((time.monotonic() - started_at) * 1000),
            request=request,
            outcome="failure",
            stage="send" if request else "resolve",
            error_type="unexpected_error",
            error_message=str(exc),
        )
        await progress.edit_text(
            "Не удалось обработать ссылку TikTok. Попробуйте позже."
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
