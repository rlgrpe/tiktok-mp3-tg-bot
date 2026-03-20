# TikTok MP3 Telegram Bot

Telegram bot that extracts audio from TikTok posts and sends it back as MP3.

Send a TikTok link — get an MP3 in return.

## Supported links

- TikTok video posts
- TikTok photo posts with attached sound
- `vm.tiktok.com` and `vt.tiktok.com` short links

For TikTok `photo` posts, the bot resolves the short link if needed, normalizes the post URL, and downloads the audio track associated with the same TikTok post ID.

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

## User-facing behavior

The bot replies in Russian and returns explicit error messages for common cases, for example:

- TikTok link cannot be recognized
- photo post has no downloadable sound
- post requires login/cookies
- TikTok is temporarily unavailable
- audio conversion failed

## Deploy (Docker)

```bash
docker build -t tiktok-mp3-bot .
docker run -e BOT_TOKEN=your_token tiktok-mp3-bot
```

## Logging

Each request is logged in a structured format so failures can be reproduced later.

Logged fields include:

- `request_id`
- `original_url`
- `resolved_url`
- `post_id`
- `content_type`
- `stage`
- `outcome`
- `error_type`
- `error_message`
- `duration_ms`

The bot does not log the full user message text.

## Current limitations

- Posts that require TikTok login/cookies are detected and reported to the user, but cookies-based access is not implemented yet.
- Temporary Telegram polling or TikTok network issues may still happen and are treated as transient failures.

## Stack

- [aiogram](https://docs.aiogram.dev/) — Telegram Bot API
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — audio extraction
- ffmpeg — MP3 conversion
