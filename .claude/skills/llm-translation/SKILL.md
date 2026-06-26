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
   waiting on. The translation client uses `cfg.llm_api_key` / `cfg.llm_base_url`
   (`translate._make_client`); transcription's OpenAI Whisper client uses the
   *separate* `cfg.openai_api_key` / `cfg.openai_base_url` (`transcribe._transcribe_openai`).
   Both share `cfg.request_timeout` / `cfg.max_retries`. Never construct a client
   with default timeouts.

2. **Stay endpoint-portable.** Translation asks for a two-block reply — a
   `<glossary>` and a `<translation>` JSON object — so `translate._translate_batch`
   calls `_complete` with `json_mode=False` (a single `response_format=json_object`
   would forbid the glossary block). The block parser (`_extract_block` +
   `_loads_object`) strips markdown fences and tolerates stray prose, and
   `_complete` still drops any optional param a model/endpoint rejects
   (`response_format` in json mode, then `temperature`). This is what lets OpenAI,
   DeepSeek, **Gemini** (OpenAI-compatible at
   `https://generativelanguage.googleapis.com/v1beta/openai/`, still beta — rejects
   some params), and local servers all work. Do **not** "upgrade" to strict
   Pydantic `.parse()` / `json_schema` — it breaks the non-OpenAI endpoints we support.

3. **Catch specific exceptions when you act on them** — `RateLimitError`,
   `APITimeoutError`, `APIConnectionError`, `APIStatusError` — not bare `Exception`.
   The tolerated broad `except` is inside the param-dropping fallback ladder, which
   exists only to detect params a provider/model rejects (`response_format`, `temperature`)
   and re-raises the real error if even a minimal request fails.

4. **The prompt is a `Final`-style constant, not an f-string.** `SYSTEM_PROMPT`
   lives at module level. The per-request data goes in the user message as JSON,
   not concatenated into the prompt.

5. **The prompt enforces the sync contract: one id in → one id out, in order, never
   merge / split / reorder / drop / empty an id.** If you edit the prompt, that
   instruction stays. The prompt *does* let the model redistribute a sentence's words
   across that sentence's own lines for natural word order — that relaxes word-to-cue
   locality, not the id count / order / timestamps (see the `subtitle-pipeline`
   skill). `_translate_batch` returns `(translations, glossary)`; `translate_segments`
   threads the glossary from each chunk into the next for consistent terminology and
   fills any missing id with the original (this is the invariant).

6. **One client per job, batched.** Construct the client once in
   `translate_segments`, then loop batches of `cfg.translation_batch_size`. Don't
   build a client per batch or per segment.

7. **Translation leans deterministic (`temperature=0.2`) where supported.** Some
   models (OpenAI reasoning models, Gemini beta) reject a custom temperature; the
   fallback ladder drops it so the model uses its default. Keep proper nouns and
   numbers intact (the prompt says so); don't crank temperature for "creativity".

## The shape

```python
def _make_client(cfg):
    from openai import OpenAI
    return OpenAI(
        api_key=cfg.llm_api_key,          # translation provider (OpenAI, DeepSeek, ...)
        base_url=cfg.llm_base_url,
        timeout=cfg.request_timeout,      # explicit — never the 10-min default
        max_retries=cfg.max_retries,
    )
```

```python
# Portable structured output: try the richest request, drop rejected params, retry.
variants = [
    {"response_format": {"type": "json_object"}, "temperature": 0.2},
    {"response_format": {"type": "json_object"}},
    {"temperature": 0.2},
    {},
]
resp, last_err = None, None
for extra in variants:
    try:
        resp = client.chat.completions.create(model=model, messages=messages, **extra)
        break
    except Exception as e:
        last_err = e
if resp is None:
    raise last_err  # real error (bad key, quota) — surface it
```

```python
# Translation: a two-block reply, glossary threaded chunk -> chunk, ids backfilled.
content = _complete(client, model, messages, json_mode=False)   # not json_object
translations = _parse_segments(_extract_block(content, "translation") or content)
glossary = {**glossary, **_parse_glossary(_extract_block(content, "glossary"))}
```

## Anti-patterns to flag

- ✗ `OpenAI(api_key=..., base_url=...)` with no `timeout` / `max_retries`.
- ✗ Switching to `.parse()` / strict `json_schema` without preserving a fallback.
- ✗ `except Exception:` wrapping a call for any reason *other* than the param-dropping fallback ladder.
- ✗ Building the prompt with an f-string instead of the `SYSTEM_PROMPT` constant + JSON payload.
- ✗ A prompt edit that drops the "one id in → one id out, never drop/merge" rule.
- ✗ Constructing a new client per batch or per segment.
- ✗ Letting an `openai.*` SDK object escape `translate.py` / `transcribe.py` to a caller.
- ✗ Parsing the model response without tolerating markdown fences / malformed JSON.
- ✗ Re-enabling `response_format=json_object` for the translation call — it forbids the `<glossary>` block the prompt emits.

## Why these rules

A bounded client is the difference between "the bot is slow" and "the bot is hung
for ten minutes." Endpoint portability is a product promise — swap backends via
`.env`, no code changes — and strict schema mode silently breaks it. And the
id-stable prompt + forgiving parser is half of the sync invariant: the model is
told to behave, but we never *trust* it to, because the caller backfills any gap.
