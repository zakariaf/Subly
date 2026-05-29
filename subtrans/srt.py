"""Step 4 — assemble timed text into an SRT subtitle file."""

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
    embedded Latin words and numbers get reordered incorrectly. See is_rtl().
    """
    blocks: list[str] = []
    for idx, (seg, translated) in enumerate(zip(segments, translations), start=1):
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
