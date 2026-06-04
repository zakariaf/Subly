# Contributing & conventions

How we write code in this project. These are not suggestions — read them before
your first PR. Every rule below maps to something already in the codebase, so when
in doubt, copy the pattern from the file referenced.

## Guiding principles

1. **Simplicity first.** Write the minimum code that solves the problem. No
   speculative abstractions, no config knobs nobody asked for, no error handling
   for impossible cases. If a senior engineer would call it overcomplicated, it is.
2. **Surgical changes.** Touch only what the task requires. Don't reformat,
   rename, or "improve" adjacent code in an unrelated PR. Match the existing style
   even if you'd personally do it differently.
3. **One stage, one module.** The pipeline is deliberately split
   (`audio` → `transcribe` → `translate` → `srt` → `video`). Keep stages
   independent and pure where possible; put orchestration in `pipeline.py` or the
   entry points, not inside a stage.

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest
cp .env.example .env                  # fill in the two secrets
pytest                                # must be green before you push
```

## Project layout

```
subtrans/        the library — importable, no side effects at import time
  config.py      all configuration, env-driven (see "Configuration")
  audio.py       ffmpeg audio extraction
  transcribe.py  Whisper backends (local + OpenAI)
  translate.py   chunked, glossary-consistent, id-stable translation
  srt.py         pure timestamp + SRT assembly
  video.py       burn-in / mux subtitles
  pipeline.py    glue: wires the stages together
bot.py           Telegram entry point (IO only)
cli.py           CLI entry point (IO only)
tests/           pytest, mirrors module names: test_<module>.py
```

**Where does new code go?** Logic goes in `subtrans/`. Entry points (`bot.py`,
`cli.py`) stay thin — they parse input, call the library, and handle IO. If you
find yourself writing business logic in `bot.py`, move it into a module so it can
be tested without Telegram.

## Python style

- **Target Python 3.10+.** Use modern syntax: `str | None`, not `Optional[str]`.
- **Type-hint every function signature.** See `srt.py` / `translate.py` for the bar.
- **Module + public-function docstrings** explaining *why*, not *what*. One line is
  often enough (`audio.py`). Skip docstrings on obvious private helpers.
- **`@dataclass` for plain data** (`Segment`, `Config`). Don't hand-roll `__init__`.
- **Naming:** `snake_case` functions/vars, `_leading_underscore` for module-private
  helpers (`_translate_batch`, `_make_client`), `UPPER_CASE` for constants
  (`SYSTEM_PROMPT`, `DEFAULT_STYLE`).
- **No import-time side effects** in `subtrans/` beyond `config.py`'s `load_dotenv()`.
  Heavy/optional deps (`faster_whisper`, `openai`) are imported *inside* the
  function that needs them — this keeps imports fast and lets tests run without
  every library installed. Keep it that way.

## Configuration & secrets

- **All configuration lives in `config.py`** and is read from environment variables
  via `Config.from_env()`. No magic numbers or endpoints scattered through the code.
- **Every new setting gets:** a typed field on `Config`, a line in `from_env()` with
  a sensible default, and an entry in `.env.example` with a comment.
- **Never commit secrets.** `.env` is git-ignored; `.env.example` holds the *keys*
  with blank values. Never hardcode a token or key, and never log one.

## Errors & logging

- **Use the `logging` module, never `print()`** in long-running code. Get a logger
  with `logger = logging.getLogger(__name__)`; configure it once in the entry point
  (`bot.py:main` calls `logging.basicConfig`).
- **Never leak internals to users.** Log the full traceback for us
  (`logger.exception(...)`) and show the user a generic message — see the
  `except` block in `bot.py:handle_media`. Raw exception text can contain file
  paths, tokens, or stack details.
- **Raise, don't swallow, in the library.** Stages (`subtrans/*`) raise
  `RuntimeError` with a clear message (`audio.py`, `video.py`); the entry point
  decides how to present it. The only bare `except` we tolerate is the
  best-effort `status.edit_text` in the bot (a failed status edit must not abort a
  job) — and it's commented as such.

## Calling external services (OpenAI / Whisper)

- **Always set `timeout` and `max_retries`** on the client — the SDK default
  timeout is *10 minutes*, which would hang a user's request. We construct clients
  from `Config` (`translate._make_client`, `transcribe._transcribe_openai`) so the
  values come from `REQUEST_TIMEOUT` / `MAX_RETRIES`.
- **Translation and transcription use separate credentials.** The LLM client reads
  `LLM_API_KEY` / `LLM_BASE_URL`; the OpenAI Whisper client reads `OPENAI_API_KEY` /
  `OPENAI_BASE_URL`. This lets you translate with DeepSeek while transcribing
  locally or with OpenAI Whisper.
- **Catch specific exceptions** when you act on them (`RateLimitError`,
  `APITimeoutError`, `APIConnectionError`, `APIStatusError`) rather than bare
  `Exception`.
- **Stay endpoint-portable.** Avoid strict Pydantic `.parse()` / `json_schema`,
  which OpenAI-compatible endpoints (Together, DeepSeek, Gemini, local servers)
  often don't support. Translation asks for a two-block reply — a `<glossary>` and a
  `<translation>` JSON object — so it runs in non-JSON mode (a single
  `response_format=json_object` would forbid the glossary block), and a forgiving
  parser (`translate._translate_batch`) tolerates fences and stray prose. `_complete`
  still drops any optional param a model rejects (`response_format` in json mode,
  then `temperature`). Don't "upgrade" to strict schema mode.

## Telegram bot conventions

- **Handlers are thin and async.** Each `CommandHandler`/`MessageHandler` callback
  parses the update and delegates to the library.
- **Never block the event loop.** ffmpeg, Whisper, and LLM calls are blocking — run
  them in a worker thread with `await asyncio.to_thread(...)` and edit a status
  message between stages (`bot.py:handle_media`). A blocking call in the event loop
  stalls every other chat.
- **Register a central error handler** with `app.add_error_handler(...)` so an
  unhandled exception logs instead of crashing the bot (`bot.py:on_error`).
- **Clean up temp files** in a `finally` block (`shutil.rmtree(..., ignore_errors=True)`).

## The subtitle-sync invariant (read this)

This is the one domain rule that must never break. Subtitles desync the moment a
translation step merges, splits, reorders, or drops a line relative to the
timestamps. So:

- Every segment carries a **stable integer id**, and the model is told to return
  the *same ids* (`translate.SYSTEM_PROMPT`).
- Any id the model fails to return **falls back to the original text**
  (`translate.translate_segments`), so the output list is **never shorter than the
  transcript** and timestamps always line up.

If you change the translation path, the tests in `tests/test_translate.py`
(`test_missing_ids_fall_back_to_original`, `test_output_is_never_shorter_than_input`)
must still pass. If you add a new way to transform segments, preserve this property
and add a test for it.

## Testing

- **`pytest`, mirroring module names** — `tests/test_<module>.py`.
- **Test the pure logic; mock the IO.** We test `srt`, `translate`, and `config`
  directly. Network is stubbed with a fake client (see the `_FakeClient` in
  `tests/test_translate.py`) — tests must run with **no API key and no network**,
  and without `openai`/`telegram`/`faster_whisper` installed.
- **Cover the edges and the invariants**, not just the happy path: timestamp
  rounding/clamping, malformed LLM output, the id-fallback rule, env type coercion.
- **`pytest` must be green before every push.** A PR that changes `subtrans/`
  without touching `tests/` should explain why.

## Dependencies

- **Runtime deps go in `requirements.txt`; test/dev deps in `requirements-dev.txt`.**
  Keep runtime lean — if a dependency is only used by tests or tooling, it does not
  belong in `requirements.txt`.
- Pin a sensible lower bound (`>=`) as the existing entries do; don't add a
  dependency to do something the standard library already does well.

## Commits & PRs

- **Small, focused commits** with imperative messages ("Add OpenAI client timeout",
  not "fixes"). One logical change per PR.
- **A PR should leave the repo green** (`pytest`) and the README/`.env.example`
  consistent with any config you added.
- Don't mix a refactor with a feature. Don't delete pre-existing dead code you
  didn't introduce — flag it instead.
