"""Step 2b (optional, V2) — let the LLM decide subtitle cue boundaries.

Enabled by AI_SEGMENTATION. The model only chooses WHERE to break the word sequence
— it returns break indices, never rewritten text — so every cue is built from the
original timestamped words by index. Timestamps therefore always come from the words,
and the result can never desync (the subtitle-pipeline invariant). Anything unusable
falls back to the rule-based packing in `transcribe._words_to_segments`.

The LLM call reuses `translate`'s bounded, endpoint-portable client helpers.
"""

import json
import logging

from .transcribe import Segment, _words_to_segments
from .translate import _complete, _loads_object, _make_client

log = logging.getLogger(__name__)

SEGMENTATION_PROMPT = """\
You split a transcript into subtitle cues. You are given WORDS: a JSON array of the
transcript's words, in order. Decide where each on-screen subtitle line should END so
that every line is short and readable — ideally a clause or sentence, never a long
paragraph (aim for at most ~12 words per line).

Return ONLY a JSON object: {"breaks":[i, j, k, ...]} where each number is the 0-based
index (into WORDS) of the LAST word of a cue. Indices must be strictly increasing and
in range. Do NOT reorder, add, remove, or rewrite any words — only choose break points.
This is for subtitles: never put a long paragraph on one line.
"""


def segment_words(words: list, cfg) -> list[Segment]:
    """Group words into subtitle cues via the LLM, falling back to rule-based packing.

    One cue per group of consecutive words, in order. Cannot desync — every cue's
    start/end come from the original words — and the duration/length caps still hold.
    """
    if not words:
        return []
    breaks = None
    try:
        breaks = _ai_breaks(words, cfg)
    except Exception as e:
        # Broad on purpose: any failure of the optional AI pass (network, auth, bad
        # reply) must degrade to the deterministic rules, never fail the job.
        log.warning("AI segmentation failed; using rule-based cues: %s", e)
    if not breaks:
        return _words_to_segments(words, cfg.max_subtitle_duration, cfg.max_subtitle_gap)
    return _cues_from_breaks(words, breaks, cfg.max_subtitle_duration)


def _ai_breaks(words: list, cfg) -> list[int]:
    """Ask the LLM for cue break-points; return cleaned indices ([] if unusable)."""
    client = _make_client(cfg)
    payload = json.dumps([w.text for w in words], ensure_ascii=False)
    messages = [
        {"role": "system", "content": SEGMENTATION_PROMPT},
        {"role": "user", "content": f"WORDS:\n{payload}"},
    ]
    content = _complete(client, cfg.translation_model, messages, json_mode=True)
    return _parse_breaks(content, len(words))


def _parse_breaks(content: str, num_words: int) -> list[int]:
    """Parse {"breaks":[...]} into clean, in-range, strictly-increasing indices.

    Returns [] if nothing usable, so the caller falls back to rule-based packing.
    """
    data = _loads_object(content)
    if not isinstance(data, dict):
        return []
    seen: set[int] = set()
    for value in data.get("breaks", []):
        try:
            idx = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < num_words:
            seen.add(idx)
    return sorted(seen)


def _cues_from_breaks(words: list, breaks: list[int], max_duration: float) -> list[Segment]:
    """Split words at the break indices (each is a cue's last word), capping each cue.

    The caps are re-applied per group via `_words_to_segments` (gap disabled, since the
    LLM already chose the breaks), so even a too-greedy grouping can't exceed them.
    """
    bounds = list(breaks)
    if not bounds or bounds[-1] != len(words) - 1:
        bounds.append(len(words) - 1)

    segments: list[Segment] = []
    start = 0
    for last in bounds:
        group = words[start:last + 1]
        segments.extend(_words_to_segments(group, max_duration, max_gap=float("inf")))
        start = last + 1
    return segments
