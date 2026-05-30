<p align="center">
  <img src="assets/logo.png" alt="Subly" width="128">
</p>

# Subly — subtitle translation bot

A focused subtitle pipeline (Python package: `subtrans`) — **no TTS, no dubbing, no remux**. It takes a video/audio file,
transcribes the speech with timestamps, translates it with an LLM, and produces an
**SRT** file. Exposed as a **Telegram bot** (and a CLI for testing).

```
media file
   │
   ├─ ffmpeg ─────────► 16 kHz mono WAV
   ├─ Whisper ────────► timed segments  (start, end, text)
   ├─ LLM ────────────► translate each segment (batched, ids preserved)
   ├─ build SRT ──────► subtitles.srt  (mono or bilingual)
   └─ ffmpeg (opt) ───► burn subtitles into the video → subbed.mp4
```

## Attaching subtitles to the video

There are two ways to "attach" subtitles, and they behave very differently:

- **Burned-in (hard)** — text is rendered onto the pixels. Always visible, **shows
  in Telegram's player**, but re-encodes the video (slower, CPU-heavy) and can't be
  turned off. This is the default for the bot.
- **Embedded (soft)** — the SRT becomes a separate track in the container (instant,
  no re-encode, toggleable). **Telegram's player won't show these** — only desktop
  players like VLC/mpv. Available via `mux_subtitles()` in `subtrans/video.py`,
  best with `.mkv`.

In the bot, `/output` chooses what comes back: `srt`, `video` (burned), or `both`
(default). Audio-only files always return just the `.srt`.

## Why it stays in sync

Subtitles desync the moment a translator merges or drops a line. Each segment is
tagged with a stable integer id and the model is told to return the *same ids*;
any id it fails to return falls back to the original text, so the SRT is **never
shorter than the transcript** and timestamps always line up.

## Setup

Requires **Python 3.10+** and **ffmpeg** on PATH.

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in TELEGRAM_BOT_TOKEN and LLM_API_KEY
```

Get a Telegram token from [@BotFather](https://t.me/BotFather).

## Run the bot

```bash
python bot.py
```

Then in Telegram, send a video or audio file. If you haven't set a language yet, the
bot shows a **language picker** — tap one (English, Persian, Kurdish (Sorani),
Spanish, German, Arabic) or use `/lang <any other language>`. `/output srt|video|both`
picks what's returned; `/bilingual` keeps the original under each translated line;
caption a file with a language name to override it for one file.

Right-to-left languages (Persian, Arabic, Kurdish Sorani, …) render with the correct
bidi direction, so embedded Latin words and numbers stay in place — in both the `.srt`
and the burned-in video.

## Run with Docker

No local Python or ffmpeg needed — the image bakes in ffmpeg:

```bash
cp .env.example .env        # fill in your tokens
docker compose up --build
```

The faster-whisper model is cached in a named volume, so it's downloaded once.
For deploying to a server, see `config/deploy.yml` (Kamal).

## Run the CLI (no Telegram needed)

```bash
python cli.py lecture.mp4 -l Chinese -o lecture.zh.srt
python cli.py talk.mp4 -l Japanese --bilingual
python cli.py talk.mp4 -l Spanish --burn      # also writes talk.subbed.mp4
```

## Swapping backends — all via `.env`, no code changes

Transcription and translation are configured **independently**, so they can use
different providers — e.g. local Whisper for transcription + DeepSeek for translation.

**Transcription** — `TRANSCRIBE_BACKEND=local` runs faster-whisper on your machine
(CPU, free, no key; `WHISPER_MODEL=small` is the default, `medium` is a step up in
quality, `large-v3` is best). Set `TRANSCRIBE_BACKEND=openai` for the OpenAI Whisper
API (`OPENAI_API_KEY`).

**Translation** — any OpenAI-compatible LLM. Point `LLM_BASE_URL`, `LLM_API_KEY`,
and `TRANSLATION_MODEL` at:
- **OpenAI** — `https://api.openai.com/v1`, e.g. `gpt-4o-mini`
- **DeepSeek** — `https://api.deepseek.com`, `deepseek-chat`
- **Gemini** — `https://generativelanguage.googleapis.com/v1beta/openai/`,
  `gemini-2.5-flash` (free tier ~1,500 requests/day; the Gemini 3.x Flash models
  are paid preview). Gemini exposes an OpenAI-compatible endpoint, so no extra
  SDK is needed.
- a local server (Ollama, vLLM, …), etc.

## Larger files: the local Bot API server

Telegram's **cloud** Bot API caps bot **downloads at 20 MB** and **sends at 50 MB**, so
a long or re-encoded video can fail to come back (the bot then sends just the `.srt`).
To lift those caps — **downloads unlimited, uploads up to 2 GB** — run a
[local Bot API server](https://github.com/tdlib/telegram-bot-api) alongside the bot.
It's wired up both ways:

- **Docker Compose:** `docker compose --profile local-api up --build`
- **Kamal:** the `telegram-bot-api` accessory in `config/deploy.yml`

Both need an **`api_id` + `api_hash`** from [my.telegram.org](https://my.telegram.org)
(`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`). You then point the bot at the server with
`TELEGRAM_API_BASE` + `TELEGRAM_LOCAL_MODE=1` and raise `MAX_FILE_MB` / `SEND_LIMIT_MB`
(see `.env.example`). The bot and the server share a data volume so the bot reads the
files directly off disk.

Burning is also the slow step on CPU; use `/output srt` if you only need the file.

## Layout

```
subtrans/
  audio.py       ffmpeg audio extraction
  transcribe.py  faster-whisper + OpenAI Whisper backends
  translate.py   batched, id-stable LLM translation
  srt.py         timestamp + SRT assembly
  video.py       burn-in (hard) + mux (soft) subtitles
  pipeline.py    glue + stage callbacks
  config.py      env-driven settings
bot.py           Telegram bot
cli.py           command-line tool
```
