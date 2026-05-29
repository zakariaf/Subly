---
name: telegram-bot
description: Use BEFORE writing or modifying any handler, command, or wiring in bot.py. Owns the rules that handlers stay thin and async, blocking work runs in a thread, errors never leak to the chat, and the bot never crashes on an unhandled exception.
---

# Skill: telegram-bot

`bot.py` is the IO edge — it talks to Telegram and delegates everything else.
Source: `CONTRIBUTING.md` → "Telegram bot conventions", "Errors & logging".

## When to invoke

Invoke this skill before:
- Adding or editing a `CommandHandler` / `MessageHandler` callback in `bot.py`.
- Changing how media is downloaded, processed, or sent back.
- Adding logging, error handling, or status messages to the bot.
- Wiring handlers in `main()`.

## Hard rules

1. **Handlers are thin and async.** A handler parses the update, calls into
   `subtrans/`, and sends a reply. Business logic does not live in `bot.py` — if
   you're writing pipeline logic in a handler, move it to a module so it's testable
   without Telegram.

2. **Never block the event loop.** ffmpeg, Whisper, and LLM calls are blocking; run
   each in a worker thread via `await asyncio.to_thread(fn, ...)` and edit the
   status message between stages (`handle_media`). A blocking call in the event
   loop stalls every other chat.

3. **Never leak internals to the user.** On failure, `logger.exception(...)` the
   full traceback for us and send the user a **generic** message. Raw exception
   text can contain file paths, tokens, or stack details. (See the `except` block
   in `handle_media`.)

4. **Register a central error handler** with `app.add_error_handler(on_error)` so an
   unhandled exception in any callback logs instead of crashing the bot.

5. **Use `logging`, never `print()`.** `logger = logging.getLogger(__name__)` at
   module level; `logging.basicConfig(...)` once in `main()`.

6. **Always clean up temp files** in a `finally` block
   (`shutil.rmtree(workdir, ignore_errors=True)`). A job that fails must not leak a
   temp directory.

7. **Enforce file-size limits before downloading.** Check `media.file_size` against
   `CFG.max_file_mb` and refuse early with a clear message — don't download then
   discover it's too big. On send, fall back to the `.srt` if the rendered video
   exceeds the send limit.

8. **Per-job overrides don't mutate chat defaults.** A caption-language override
   applies to that one job; the chat's `/lang` setting in `chat_data` is untouched.

## The shape

```python
# Blocking stages run in threads; status edits keep the user informed.
await show("transcribe")
segments, detected = await asyncio.to_thread(transcribe, audio_path, CFG, None)
```

```python
except Exception:
    # Log the full traceback for us; show the user a generic message so we never
    # leak internal paths, tokens, or stack details into the chat.
    logger.exception("Failed to process media for chat %s", update.effective_chat.id)
    await status.edit_text("❌ Something went wrong while processing that file. Please try again.")
finally:
    shutil.rmtree(workdir, ignore_errors=True)
```

```python
async def on_error(update, context):
    logger.error("Unhandled exception while processing an update", exc_info=context.error)
# ...
app.add_error_handler(on_error)
```

## Anti-patterns to flag

- ✗ A blocking call (`subprocess`, `model.transcribe`, `client.chat...`) awaited directly in a handler instead of via `asyncio.to_thread`.
- ✗ `await status.edit_text(f"❌ Failed: {e}")` or any raw exception text sent to the chat.
- ✗ `print(...)` in `bot.py`.
- ✗ No `app.add_error_handler(...)` registered.
- ✗ Pipeline/business logic written inline in a handler.
- ✗ Missing `finally` cleanup of the temp working directory.
- ✗ Downloading a file before checking its size against `CFG.max_file_mb`.
- ✗ A caption override that overwrites `chat_data["target_language"]`.

## Why these rules

The bot serves many chats on one event loop. A single blocking call freezes
everyone; a single unhandled exception without an error handler can take the
process down. Generic user-facing errors keep tokens and paths out of a channel we
don't control. And thin handlers mean the real logic lives in `subtrans/`, where
it can be unit-tested without a Telegram token.
