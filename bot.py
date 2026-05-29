"""Telegram bot — send a video/audio file, get back translated subtitles.

Usage:
    /start, /help        — info
    /lang <language>     — set your target language (persists per chat for the session)
    /output srt|video|both, /bilingual
    send a video/audio   — if no language is set, the bot shows a language picker;
                           tap one (or caption the file with a language name) and it
                           transcribes, translates, and returns the subtitles.

Heavy work (ffmpeg, Whisper, the LLM calls) is blocking, so each stage runs in a
worker thread via asyncio.to_thread; the bot edits a status message between stages
so the event loop never stalls and the user sees progress.
"""

import asyncio
import logging
import os
import shutil
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

# Quick-pick languages shown when a chat hasn't chosen one yet. Any other language
# is still reachable with `/lang <language>` or by captioning the file.
LANGUAGES = ["English", "Persian", "Kurdish (Sorani)", "Spanish", "German", "Arabic"]

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
    lang = _chat_language(context)
    lang_line = f"*{lang}*" if lang else "_not set yet — I'll ask when you send a file_"
    await update.message.reply_text(
        "👋 Send me a video or audio file and I'll return translated subtitles.\n\n"
        f"Target language: {lang_line}  (set with `/lang Spanish`)\n"
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
        "Just send a file: if no language is set I'll show buttons to pick one. "
        "You can also caption a file with a language name to override for that one file.\n"
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


def _chat_language(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """The chat's saved target language, or None if not chosen yet."""
    return context.chat_data.get("target_language")


def _output_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.chat_data.get("output_mode", "both")


def _language_keyboard(pending_key: str) -> InlineKeyboardMarkup:
    """Inline keyboard of quick-pick languages, two per row.

    callback_data encodes the index into LANGUAGES plus the stash key for the
    file that's waiting to be processed: "lang:<pending_key>:<index>".
    """
    buttons = [
        InlineKeyboardButton(lang, callback_data=f"lang:{pending_key}:{i}")
        for i, lang in enumerate(LANGUAGES)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


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
    """Thin router: validate size, decide the language, then process or ask."""
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

    # Language: a caption wins, else the chat's saved language, else ask the user.
    caption = (update.message.caption or "").strip()
    chat_lang = _chat_language(context)
    if caption:
        target = caption.title()
    elif chat_lang:
        target = chat_lang
    else:
        key = str(update.message.message_id)
        context.chat_data.setdefault("pending_media", {})[key] = {
            "file_id": media.file_id, "filename": filename,
        }
        await update.message.reply_text(
            "🌐 Which language should I translate into?\n(or send /lang <any other language>)",
            reply_markup=_language_keyboard(key),
        )
        return

    bilingual = context.chat_data.get("bilingual", False)
    status = await update.message.reply_text("⬇️ Downloading…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    await _process_media(
        context, update.effective_chat.id, media.file_id, filename, target, bilingual, status
    )


async def on_language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A language button was tapped: resolve the stashed file and process it."""
    query = update.callback_query
    await query.answer()
    try:
        _, key, idx = query.data.split(":")
        lang = LANGUAGES[int(idx)]
    except (ValueError, IndexError):
        await query.edit_message_text("Sorry — I didn't understand that choice.")
        return

    pending = context.chat_data.get("pending_media", {}).pop(key, None)
    if pending is None:
        await query.edit_message_text("That file has expired — please send it again.")
        return

    # Remember the choice so we don't ask again (change later with /lang).
    context.chat_data["target_language"] = lang
    bilingual = context.chat_data.get("bilingual", False)
    await query.edit_message_text(f"🌐 Translating into {lang}…")
    await _process_media(
        context, query.message.chat_id, pending["file_id"], pending["filename"],
        lang, bilingual, query.message,
    )


async def _process_media(context, chat_id, file_id, filename, target, bilingual, status) -> None:
    """Download → transcribe → translate → build → (optional burn) → send.

    Shared by the direct path and the language-picker callback. `status` is a
    Message we edit to report progress between the blocking stages.
    """
    workdir = tempfile.mkdtemp(prefix="subtrans_")
    media_path = os.path.join(workdir, filename)

    async def show(stage):
        try:
            await status.edit_text(STAGE_TEXT[stage])
        except Exception:
            pass  # ignore "message not modified" etc.

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(media_path)

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

        mode = context.chat_data.get("output_mode", "both")
        is_video = has_video_stream(media_path)

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

            burned_mb = os.path.getsize(burned_path) / (1024 * 1024)
            if burned_mb > SEND_LIMIT_MB:
                await status.edit_text(
                    f"✅ Subtitles done, but the rendered video is {burned_mb:.0f} MB — over "
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
        logger.exception("Failed to process media for chat %s", chat_id)
        await status.edit_text("❌ Something went wrong while processing that file. Please try again.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
    app.add_handler(CallbackQueryHandler(on_language_choice, pattern=r"^lang:"))
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
