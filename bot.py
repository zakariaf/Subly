"""Telegram bot — send a video/audio file, get back a translated .srt.

Usage:
    /start, /help        — info
    /lang <language>     — set your target language (persists per chat for the session)
    send a video/audio   — bot transcribes, translates, returns an .srt
    (caption a file with a language name to translate into that language for one job)

Heavy work (ffmpeg, Whisper, the LLM calls) is blocking, so each stage runs in a
worker thread via asyncio.to_thread; the bot edits a status message between stages
so the event loop never stalls and the user sees progress.
"""

import asyncio
import logging
import os
import tempfile

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from subtrans.config import Config
from subtrans.audio import extract_audio
from subtrans.transcribe import transcribe
from subtrans.translate import translate_segments
from subtrans.srt import build_srt
from subtrans.video import has_video_stream, burn_subtitles

logger = logging.getLogger(__name__)

CFG = Config.from_env()

# Standard Bot API lets bots SEND files up to 50 MB (2 GB with a local Bot API server).
SEND_LIMIT_MB = 50

STAGE_TEXT = {
    "extract": "🎬 Extracting audio…",
    "transcribe": "🎙 Transcribing (this is the slow part)…",
    "translate": "🌐 Translating…",
    "build": "📝 Building subtitles…",
    "burn": "🔥 Burning subtitles into the video (re-encoding)…",
}


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Send me a video or audio file and I'll return translated subtitles.\n\n"
        f"Target language: *{_target_lang(context)}*  (change with `/lang Spanish`)\n"
        f"Output: *{_output_mode(context)}*  (change with `/output srt|video|both`)\n"
        f"Max file size: {CFG.max_file_mb} MB.",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/lang <language> — set target language\n"
        "/output srt|video|both — what to send back:\n"
        "   • srt — just the .srt file\n"
        "   • video — the video with subtitles burned in\n"
        "   • both — .srt *and* the burned video (default)\n"
        "/bilingual — toggle keeping the original text under each line\n\n"
        "Tip: caption a file with a language name to override for that one file.\n"
        "Note: 'video' re-encodes (slow on CPU) and burns the text onto the picture "
        "so it shows in Telegram's player. Audio-only files always come back as .srt.",
    )


async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/lang Spanish`", parse_mode="Markdown")
        return
    lang = " ".join(context.args).strip().title()
    context.chat_data["target_language"] = lang
    await update.message.reply_text(f"✅ Target language set to *{lang}*", parse_mode="Markdown")


async def set_output(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    choice = (context.args[0].lower() if context.args else "")
    if choice not in ("srt", "video", "both"):
        await update.message.reply_text(
            "Usage: `/output srt` | `/output video` | `/output both`", parse_mode="Markdown"
        )
        return
    context.chat_data["output_mode"] = choice
    await update.message.reply_text(f"✅ Output set to *{choice}*", parse_mode="Markdown")


async def toggle_bilingual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    new = not context.chat_data.get("bilingual", False)
    context.chat_data["bilingual"] = new
    await update.message.reply_text(
        f"Bilingual subtitles {'ON (original kept under translation)' if new else 'OFF'}."
    )


def _target_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.chat_data.get("target_language", CFG.default_target_language)


def _output_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.chat_data.get("output_mode", "both")


# --------------------------------------------------------------------------- #
# File handling
# --------------------------------------------------------------------------- #

def _pick_media(update: Update):
    """Return (telegram_file_object, original_filename) or (None, None)."""
    msg = update.message
    if msg.video:
        return msg.video, "video.mp4"
    if msg.audio:
        return msg.audio, msg.audio.file_name or "audio.mp3"
    if msg.voice:
        return msg.voice, "voice.ogg"
    if msg.video_note:
        return msg.video_note, "note.mp4"
    if msg.document:
        return msg.document, msg.document.file_name or "file"
    return None, None


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    media, filename = _pick_media(update)
    if media is None:
        return

    size_mb = (media.file_size or 0) / (1024 * 1024)
    if size_mb > CFG.max_file_mb:
        await update.message.reply_text(
            f"⚠️ That file is {size_mb:.0f} MB. My limit is {CFG.max_file_mb} MB "
            "(Telegram's getFile cap for bots). Trim the clip or run a local Bot API server."
        )
        return

    # Per-job language: caption overrides the chat default.
    target = _target_lang(context)
    if update.message.caption and update.message.caption.strip():
        target = update.message.caption.strip().title()
    bilingual = context.chat_data.get("bilingual", False)

    status = await update.message.reply_text("⬇️ Downloading…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    workdir = tempfile.mkdtemp(prefix="subtrans_")
    media_path = os.path.join(workdir, filename)

    try:
        tg_file = await media.get_file()
        await tg_file.download_to_drive(media_path)

        async def show(stage):
            try:
                await status.edit_text(STAGE_TEXT[stage])
            except Exception:
                pass  # ignore "message not modified" etc.

        # Run blocking stages in threads, editing the status message between them.
        await show("extract")
        audio_path = await asyncio.to_thread(extract_audio, media_path)

        await show("transcribe")
        segments, detected = await asyncio.to_thread(transcribe, audio_path, CFG, None)
        if not segments:
            await status.edit_text("🤔 I couldn't find any speech in that file.")
            return

        await show("translate")
        translations = await asyncio.to_thread(
            translate_segments, segments, target, CFG, detected
        )

        await show("build")
        srt_text = build_srt(segments, translations, bilingual=bilingual)

        base = os.path.splitext(filename)[0]
        srt_path = os.path.join(workdir, f"{base}.{target.lower()}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_text)

        mode = _output_mode(context)
        is_video = has_video_stream(media_path)
        chat_id = update.effective_chat.id

        # Send the .srt when asked for it, or as a fallback when video was
        # requested but the input has no video track (audio-only file).
        if mode in ("srt", "both") or (mode == "video" and not is_video):
            with open(srt_path, "rb") as f:
                await context.bot.send_document(
                    chat_id, document=f, filename=os.path.basename(srt_path),
                    caption=f"Subtitles in {target}" + (" (bilingual)" if bilingual else ""),
                )

        # Burn the subtitles into the video and send it back.
        if mode in ("video", "both") and is_video:
            await show("burn")
            burned_path = os.path.join(workdir, f"{base}.{target.lower()}.subbed.mp4")
            await asyncio.to_thread(burn_subtitles, media_path, srt_path, burned_path)

            size_mb = os.path.getsize(burned_path) / (1024 * 1024)
            if size_mb > SEND_LIMIT_MB:
                await status.edit_text(
                    f"✅ Subtitles done, but the rendered video is {size_mb:.0f} MB — over "
                    f"Telegram's {SEND_LIMIT_MB} MB send limit for bots. Sent the .srt instead."
                )
                if mode == "video":  # srt wasn't sent above; send it now
                    with open(srt_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id, document=f, filename=os.path.basename(srt_path),
                        )
            else:
                with open(burned_path, "rb") as f:
                    await context.bot.send_video(
                        chat_id, video=f, supports_streaming=True,
                        caption=f"Subtitled · {target}",
                    )

        await status.edit_text(f"✅ Done — {len(segments)} lines → {target}")
    except Exception:
        # Log the full traceback for us; show the user a generic message so we
        # never leak internal paths, tokens, or stack details into the chat.
        logger.exception("Failed to process media for chat %s", update.effective_chat.id)
        await status.edit_text("❌ Something went wrong while processing that file. Please try again.")
    finally:
        # best-effort cleanup
        try:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all so an unhandled error in a callback never crashes the bot."""
    logger.error("Unhandled exception while processing an update", exc_info=context.error)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    if not CFG.telegram_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your environment / .env file.")

    app = Application.builder().token(CFG.telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", set_lang))
    app.add_handler(CommandHandler("output", set_output))
    app.add_handler(CommandHandler("bilingual", toggle_bilingual))
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE
            | filters.Document.VIDEO | filters.Document.AUDIO,
            handle_media,
        )
    )
    app.add_error_handler(on_error)

    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
