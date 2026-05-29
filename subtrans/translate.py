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


def _make_client(cfg):
    from openai import OpenAI

    return OpenAI(
        api_key=cfg.openai_api_key,
        base_url=cfg.openai_base_url,
        timeout=cfg.openai_timeout,
        max_retries=cfg.openai_max_retries,
    )


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

    # Try JSON mode first; fall back to plain if the provider/model rejects it.
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
        )

    content = resp.choices[0].message.content or "{}"
    content = content.strip()
    # Be forgiving about stray markdown fences.
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{"):]

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
