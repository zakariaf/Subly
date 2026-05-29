---
name: llm-translation
description: Use BEFORE writing or modifying any call to an OpenAI-compatible API (translate.py, transcribe.py's openai backend) or the translation prompt. Owns client configuration (timeout/retries), endpoint portability, and the structured-output parsing contract.
---

# Skill: llm-translation

Every model call must be bounded, portable across providers, and impossible to
desync. Source: `CONTRIBUTING.md` → "Calling external services (OpenAI / Whisper)".

## When to invoke

Invoke this skill before:
- Adding or editing any `client.chat.completions.create(...)` or `audio.transcriptions.create(...)` call.
- Constructing an OpenAI client (`OpenAI(...)`).
- Changing the translation system prompt or the response parser in `translate.py`.
- Adding retry, timeout, or batching logic for model calls.

## Hard rules

1. **Build clients from `Config`, with explicit `timeout` and `max_retries`.** The
   SDK's default timeout is **10 minutes** — unacceptable for a request a user is
   waiting on. Use `cfg.openai_timeout` / `cfg.openai_max_retries`
   (`translate._make_client`, `transcribe._transcribe_openai`). Never construct a
   client with default timeouts.

2. **Stay endpoint-portable.** Use `response_format={"type":"json_object"}` *with a
   try/except fallback to a plain call* (see `translate._translate_batch`), plus a
   forgiving parser that strips markdown fences and tolerates malformed output.
   Do **not** "upgrade" to strict Pydantic `.parse()` / `json_schema` — it breaks
   non-OpenAI endpoints (Together, DeepSeek, local servers) we explicitly support.

3. **Catch specific exceptions when you act on them** — `RateLimitError`,
   `APITimeoutError`, `APIConnectionError`, `APIStatusError` — not bare `Exception`.
   The one tolerated broad `except` is the JSON-mode→plain fallback, and it exists
   only to detect a provider that rejects `response_format`.

4. **The prompt is a `Final`-style constant, not an f-string.** `SYSTEM_PROMPT`
   lives at module level. The per-request data goes in the user message as JSON,
   not concatenated into the prompt.

5. **The prompt enforces the sync contract: one id in → one id out, never merge /
   split / reorder / drop.** If you edit the prompt, that instruction stays. The
   parser returns a `dict[int, str]`; the *caller* fills gaps with originals (see
   the `subtitle-pipeline` skill — this is the invariant).

6. **One client per job, batched.** Construct the client once in
   `translate_segments`, then loop batches of `cfg.translation_batch_size`. Don't
   build a client per batch or per segment.

7. **Translation is `temperature=0.2`-ish and deterministic-leaning.** Keep proper
   nouns and numbers intact (the prompt says so). Don't crank temperature for
   "creativity" — these are subtitles.

## The shape

```python
def _make_client(cfg):
    from openai import OpenAI
    return OpenAI(
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url,
        timeout=cfg.openai_timeout,       # explicit — never the 10-min default
        max_retries=cfg.openai_max_retries,
    )
```

```python
# Portable structured output: try JSON mode, fall back if the provider rejects it.
try:
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=0.2,
        response_format={"type": "json_object"},
    )
except Exception:
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=0.2,
    )
```

## Anti-patterns to flag

- ✗ `OpenAI(api_key=..., base_url=...)` with no `timeout` / `max_retries`.
- ✗ Switching to `.parse()` / strict `json_schema` without preserving a fallback.
- ✗ `except Exception:` wrapping a call for any reason *other* than the JSON-mode fallback.
- ✗ Building the prompt with an f-string instead of the `SYSTEM_PROMPT` constant + JSON payload.
- ✗ A prompt edit that drops the "one id in → one id out, never drop/merge" rule.
- ✗ Constructing a new client per batch or per segment.
- ✗ Letting an `openai.*` SDK object escape `translate.py` / `transcribe.py` to a caller.
- ✗ Parsing the model response without tolerating markdown fences / malformed JSON.

## Why these rules

A bounded client is the difference between "the bot is slow" and "the bot is hung
for ten minutes." Endpoint portability is a product promise — swap backends via
`.env`, no code changes — and strict schema mode silently breaks it. And the
id-stable prompt + forgiving parser is half of the sync invariant: the model is
told to behave, but we never *trust* it to, because the caller backfills any gap.
