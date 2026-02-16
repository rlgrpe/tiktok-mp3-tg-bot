import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set — create .env file from .env.example")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

TIKTOK_URL_RE = re.compile(
    r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+"
)


def download_mp3(url: str, output_dir: str) -> Path | None:
    """Download TikTok audio as MP3 using yt-dlp + ffmpeg. Returns path to the file."""
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            return None
        video_id = info.get("id", "audio")

    # Find the downloaded file
    downloaded_files = list(Path(output_dir).glob(f"{video_id}.*"))
    if not downloaded_files:
        return None

    downloaded = downloaded_files[0]
    mp3_path = Path(output_dir) / f"{video_id}.mp3"

    if downloaded.suffix == ".mp3":
        return downloaded

    # Convert to mp3 with ffmpeg directly (bypasses ffprobe codec detection)
    result = subprocess.run(
        ["ffmpeg", "-i", str(downloaded), "-vn", "-acodec", "libmp3lame",
         "-ab", "192k", "-y", str(mp3_path)],
        capture_output=True,
    )
    if result.returncode == 0 and mp3_path.exists():
        return mp3_path
    return None


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Отправь мне ссылку на TikTok видео, "
        "и я пришлю тебе аудио в формате MP3."
    )


@dp.message(F.text)
async def handle_url(message: Message) -> None:
    text = message.text or ""
    match = TIKTOK_URL_RE.search(text)
    if not match:
        await message.answer("Отправь ссылку на TikTok видео.")
        return

    url = match.group(0)
    progress = await message.answer("Скачиваю аудио...")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            loop = asyncio.get_running_loop()
            mp3_path = await loop.run_in_executor(None, download_mp3, url, tmpdir)

            if mp3_path is None:
                await progress.edit_text("Не удалось скачать аудио. Проверь ссылку.")
                return

            audio_file = FSInputFile(mp3_path)
            await message.answer_audio(audio=audio_file)
            await progress.delete()
    except Exception:
        logging.exception("Error downloading %s", url)
        await progress.edit_text(
            "Произошла ошибка при скачивании. Попробуй другую ссылку."
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
