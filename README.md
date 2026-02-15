# TikTok MP3 Telegram Bot

Telegram bot that extracts audio from TikTok videos and sends it back as MP3.

Send a TikTok link — get an MP3 in return.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/)

## Setup

```bash
git clone <repo-url>
cd tiktok_mp3_tg_bot
uv sync
```

Create a bot via [@BotFather](https://t.me/BotFather) and copy the token:

```bash
cp .env.example .env
```

Set your token in `.env`:

```
BOT_TOKEN=123456:ABC-DEF...
```

## Run

```bash
uv run python bot.py
```

## Deploy (Docker)

```bash
docker build -t tiktok-mp3-bot .
docker run -e BOT_TOKEN=your_token tiktok-mp3-bot
```

## Stack

- [aiogram](https://docs.aiogram.dev/) — Telegram Bot API
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — audio extraction
- ffmpeg — MP3 conversion
