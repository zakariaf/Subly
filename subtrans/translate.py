"""Step 3 — translate timed segments with an LLM.

Key idea: translate in batches, but tag every segment with a stable integer id
and ask the model to return the *same ids*. That way the model can use
surrounding context for better translations, but it cannot silently merge,
split, or drop lines — which would desync the subtitles from the timestamps.
Any id the model fails to return falls back to the original text.
"""

import json

from .transcribe import Segment

SYSTEM_PROMPT = (
    "You are a professional subtitle translator. You translate spoken-language "
    "transcripts into natural, concise subtitles in the target language. "
    "Rules:\n"
    "- Translate the MEANING, not word-for-word. Keep it short enough to read on screen.\n"
    "- Each input segment has an integer id. Return a translation for every id.\n"
    "- Never merge, split, reorder, or drop segments. One id in -> one id out.\n"
    "- Keep proper nouns and numbers intact.\n"
    "- Return ONLY a JSON object of the form "
    '{"segments":[{"id":0,"text":"..."}]} with no extra commentary.'
)

CAPTION_PROMPT = (
    "You write an engaging caption for a video — like a social-media post — from "
    "its transcript. Rules:\n"
    "- Write it in {language}.\n"
    "- A short paragraph is good: roughly 1–4 sentences (up to ~60 words). A couple "
    "of fitting emojis are welcome; no surrounding quotes.\n"
    "- Capture what the video is about and its hook — don't just transcribe it.\n"
    "Reply with ONLY the caption."
)


def _make_client(cfg):
    from openai import OpenAI

    return OpenAI(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
    )


def _complete(client, model, messages, *, json_mode: bool) -> str:
    """One chat completion, dropping the optional params a model/endpoint rejects.

    Sends `response_format` (when json_mode) and a low `temperature` first, then
    progressively drops them — `response_format` (non-OpenAI endpoints) and a
    non-default `temperature` (e.g. reasoning models). Re-raises only if even a
    minimal request fails, so real errors (bad key, quota) still surface.
    Returns the message content (possibly "").
    """
    rf = {"response_format": {"type": "json_object"}} if json_mode else {}
    variants = [{**rf, "temperature": 0.2}, dict(rf), {"temperature": 0.2}, {}]
    resp = None
    last_err: Exception | None = None
    for extra in variants:
        try:
            resp = client.chat.completions.create(model=model, messages=messages, **extra)
            break
        except Exception as e:
            last_err = e
    if resp is None:
        raise last_err
    return resp.choices[0].message.content or ""


def _translate_batch(client, model, batch, target_language, source_language) -> dict[int, str]:
    payload = {
        "target_language": target_language,
        "source_language": source_language or "auto-detect",
        "segments": [{"id": i, "text": s.text} for i, s in batch],
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    content = _complete(client, model, messages, json_mode=True).strip()
    # Be forgiving about stray markdown fences.
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{"):]
    content = content or "{}"

    out: dict[int, str] = {}
    try:
        data = json.loads(content)
        for item in data.get("segments", []):
            out[int(item["id"])] = str(item["text"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass  # leave out empty -> caller fills gaps with originals
    return out


def translate_segments(
    segments: list[Segment],
    target_language: str,
    cfg,
    source_language: str | None = None,
) -> list[str]:
    """Return a list of translated strings, one per input segment (same order)."""
    if not segments:
        return []

    client = _make_client(cfg)
    model = cfg.translation_model
    batch_size = max(1, cfg.translation_batch_size)

    indexed = list(enumerate(segments))
    translations: dict[int, str] = {}

    for start in range(0, len(indexed), batch_size):
        batch = indexed[start:start + batch_size]
        translations.update(
            _translate_batch(client, model, batch, target_language, source_language)
        )

    # Fill any missing ids with the original text so the SRT is never short.
    return [translations.get(i) or segments[i].text for i in range(len(segments))]


def describe(segments: list[Segment], target_language: str, cfg) -> str:
    """A short, post-style caption for the video, written in the target language.

    Returns "" if there's nothing to summarise. Built from the transcript (capped
    so the prompt stays small); the LLM also translates it into target_language.
    """
    transcript = " ".join(s.text for s in segments).strip()[:4000]
    if not transcript:
        return ""
    client = _make_client(cfg)
    messages = [
        {"role": "system", "content": CAPTION_PROMPT.format(language=target_language)},
        {"role": "user", "content": transcript},
    ]
    return _complete(client, cfg.translation_model, messages, json_mode=False).strip()
