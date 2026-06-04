"""Step 3 — translate timed segments with an LLM.

One LLM call per chunk does all the work in its prompt: pick consistent renderings
for recurring terms, translate, then self-review and fix. A glossary of term
decisions is threaded from each chunk into the next so terminology stays consistent
across the whole transcript. Every segment keeps a stable integer id — the model is
told to return the *same ids*, and any id it fails to return falls back to the
original text, so the subtitles can never desync from the timestamps.
"""

import json

from .transcribe import Segment

SYSTEM_PROMPT = """\
<role>
You are a professional subtitle translator and editor — a native-level speaker of the
target language with subject-matter fluency in the transcript's domain. You turn spoken
transcripts into natural, screen-readable subtitles.
</role>

<task>
You receive (a) the TARGET LANGUAGE, (b) a GLOSSARY of terms already decided in earlier
parts of this transcript (may be empty), and (c) a list of SEGMENTS — one continuous
transcript from a single speaker on one topic. Translate every segment and return the result.
</task>

<process>
Work in this order:

1. TERMS — Read all segments. Identify recurring domain terms, jargon, and proper nouns.
   For each term: if it is already in the incoming GLOSSARY, reuse that rendering exactly;
   otherwise choose ONE target-language rendering and use it everywhere. Transliterate
   established loanwords (e.g. "prompt", "token") instead of forcing a literal translation.
   Never render the same term two different ways.

2. TRANSLATE — Translate each segment for MEANING, not word-for-word: natural, concise, and
   short enough to read on screen in the time a viewer has. Apply the glossary from step 1.
   Keep proper nouns, numbers, and units intact. Match the speaker's register.

3. REVIEW — Re-read all your translations as one continuous text. Fix every mistranslation,
   wrong word choice, grammar error, awkward phrasing, and term inconsistency before you
   finalize. Be a strict editor — this pass matters most.
</process>

<rules>
- Each segment has an integer id. Return exactly one translation per id: one id in -> one id out.
- Never merge, split, reorder, or drop segments.
- If a segment is non-lexical (e.g. "[Music]", "[Applause]") or empty, return it unchanged.
- Output text values must be valid JSON: escape quotes and newlines.
</rules>

<output_format>
Return exactly two blocks and nothing else:

<glossary>
A compact JSON object merging the incoming glossary with any new terms you fixed:
{"source term":"target rendering", ...}. This is fed into the next chunk for consistency.
</glossary>
<translation>
{"segments":[{"id":0,"text":"..."},{"id":1,"text":"..."}]}
</translation>
</output_format>

<example>
TARGET LANGUAGE: German
GLOSSARY: {}
SEGMENTS:
[{"id":0,"text":"Today we're talking about prompt engineering."},
 {"id":1,"text":"The key idea is to give the model a clear role."}]

<glossary>
{"prompt engineering":"Prompt Engineering","model":"Modell"}
</glossary>
<translation>
{"segments":[{"id":0,"text":"Heute geht es um Prompt Engineering."},{"id":1,"text":"Die Kernidee: Gib dem Modell eine klare Rolle."}]}
</translation>
</example>"""

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


def _extract_block(content: str, tag: str) -> str:
    """Return the inner text of <tag>...</tag>, or "" if the open tag is absent."""
    low = content.lower()
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    i = low.find(open_t)
    if i == -1:
        return ""
    start = i + len(open_t)
    j = low.find(close_t, start)
    return content[start:(j if j != -1 else len(content))].strip()


def _loads_object(text: str):
    """Best-effort parse of the first {...} JSON object in text, or None.

    Tolerant of stray markdown fences and surrounding prose, so a slightly
    chatty model reply still yields usable data instead of nothing.
    """
    text = text.strip().strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_segments(block: str) -> dict[int, str]:
    out: dict[int, str] = {}
    data = _loads_object(block)
    if isinstance(data, dict):
        for item in data.get("segments", []):
            try:
                out[int(item["id"])] = str(item["text"]).strip()
            except (KeyError, TypeError, ValueError):
                pass  # skip a malformed entry -> caller backfills with the original
    return out


def _parse_glossary(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    data = _loads_object(block)
    if isinstance(data, dict):
        for key, value in data.items():
            term, rendering = str(key).strip(), str(value).strip()
            if term and rendering:
                out[term] = rendering
    return out


def _translate_batch(client, model, batch, target_language, source_language, glossary):
    """One call: translate the batch and return (translations, updated_glossary).

    The prompt runs terms -> translate -> review in a single pass and replies in two
    blocks; we parse <translation> into {id: text} and <glossary> into the running
    term map. Any id the model omits is left out for the caller to backfill.
    """
    payload = [{"id": i, "text": s.text} for i, s in batch]
    user = (
        f"TARGET LANGUAGE: {target_language}\n"
        f"SOURCE LANGUAGE: {source_language or 'auto-detect'}\n"
        f"GLOSSARY: {json.dumps(glossary, ensure_ascii=False)}\n"
        f"SEGMENTS:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    # No json_mode: the two-block reply isn't a single JSON object, so response_format
    # would forbid it. The block parser tolerates fences and stray prose instead.
    content = _complete(client, model, messages, json_mode=False)
    translation = _extract_block(content, "translation") or content
    return _parse_segments(translation), _parse_glossary(_extract_block(content, "glossary"))


def translate_segments(
    segments: list[Segment],
    target_language: str,
    cfg,
    source_language: str | None = None,
) -> list[str]:
    """Return a list of translated strings, one per input segment (same order).

    Translates chunk by chunk, threading a glossary of term decisions from each
    chunk into the next for consistent terminology. Any id the model doesn't return
    falls back to the original text, so the output is never shorter than the input.
    """
    if not segments:
        return []

    client = _make_client(cfg)
    model = cfg.translation_model
    batch_size = max(1, cfg.translation_batch_size)

    indexed = list(enumerate(segments))
    translations: dict[int, str] = {}
    glossary: dict[str, str] = {}

    for start in range(0, len(indexed), batch_size):
        batch = indexed[start:start + batch_size]
        translated, new_terms = _translate_batch(
            client, model, batch, target_language, source_language, glossary
        )
        translations.update(translated)
        glossary = {**glossary, **new_terms}

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
