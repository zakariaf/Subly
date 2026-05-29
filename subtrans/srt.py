"""Step 4 — assemble timed text into an SRT subtitle file."""

from .transcribe import Segment


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
) -> str:
    """Build SRT text. If bilingual, stack translation over the original line."""
    blocks: list[str] = []
    for idx, (seg, translated) in enumerate(zip(segments, translations), start=1):
        if bilingual and seg.text.strip() != translated.strip():
            body = f"{translated}\n{seg.text}"
        else:
            body = translated
        blocks.append(
            f"{idx}\n"
            f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n"
            f"{body}\n"
        )
    return "\n".join(blocks)
