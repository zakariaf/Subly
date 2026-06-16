"""Step 4 — assemble timed text into an SRT subtitle file."""

import re

from .transcribe import Segment

# Unicode bidi embedding: force a right-to-left base direction for RTL languages
# so embedded Latin words and numbers land in the correct place within the line.
_RLE = "\u202b"  # RIGHT-TO-LEFT EMBEDDING
_PDF = "\u202c"  # POP DIRECTIONAL FORMATTING

# Matched against the target-language name we receive ("Persian", "Kurdish (Sorani)"…).
_RTL_LANGUAGES = (
    "arabic", "persian", "farsi", "hebrew", "urdu", "pashto",
    "sorani", "sindhi", "uyghur", "dhivehi", "yiddish",
)


def is_rtl(language: str) -> bool:
    """True if the target language is written right-to-left."""
    name = language.strip().lower()
    return any(tok in name for tok in _RTL_LANGUAGES)


# Spelled-out Islamic honorifics collapse to their single Unicode ligature (Arabic
# Presentation Forms-A). Applied to RTL text only; whitespace between words is
# flexible. The RTL burn font (Noto Sans Arabic) covers these codepoints.
# `_Y` accepts the three ways "yeh" is written across the scripts we target —
# Arabic yeh, Farsi/Kurdish yeh, and alef maksura — so Persian spellings match too.
_Y = "[يیى]"
_HONORIFICS = (
    # ﷺ sallallahu alayhi wa sallam — صلى الله عليه وسلم
    (re.compile(rf"صل{_Y}\s+الله\s+عل{_Y}ه\s+وسلم"), "ﷺ"),
    # ﷻ jalla jalaluhu — جل جلاله
    (re.compile(r"جل\s+جلاله"), "ﷻ"),
)


def _apply_honorifics(text: str) -> str:
    """Collapse spelled-out Islamic honorifics to their Unicode ligature."""
    for pattern, ligature in _HONORIFICS:
        text = pattern.sub(ligature, text)
    return text


def format_timestamp(seconds: float) -> str:
    """Seconds -> SRT timestamp 'HH:MM:SS,mmm'."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, total_ms = divmod(total_ms, 3_600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(
    segments: list[Segment],
    translations: list[str],
    bilingual: bool = False,
    rtl: bool = False,
) -> str:
    """Build SRT text. If bilingual, stack translation over the original line.

    For right-to-left targets (rtl=True), each translated line is wrapped in
    Unicode bidi-embedding marks so its base direction is RTL — otherwise
    embedded Latin words and numbers get reordered incorrectly (see is_rtl()) —
    and spelled-out Islamic honorifics are collapsed to their Unicode ligature.
    """
    blocks: list[str] = []
    for idx, (seg, translated) in enumerate(zip(segments, translations), start=1):
        if rtl:
            translated = _apply_honorifics(translated)
        line = f"{_RLE}{translated}{_PDF}" if rtl else translated
        if bilingual and seg.text.strip() != translated.strip():
            body = f"{line}\n{seg.text}"
        else:
            body = line
        blocks.append(
            f"{idx}\n"
            f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n"
            f"{body}\n"
        )
    return "\n".join(blocks)
