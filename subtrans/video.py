"""Step 5 (optional) — attach subtitles to the video.

Two ways to "attach":

  burn_subtitles  — render text onto the pixels (HARD subs). Always visible,
                    shows in Telegram's player, but re-encodes the video.
  mux_subtitles   — add the SRT as a separate track (SOFT subs). Instant, no
                    re-encode, toggleable — but NOT shown by Telegram's player.
                    Good for .mkv / desktop players (VLC, mpv).
"""

import os
import re
import subprocess

from .audio import ensure_ffmpeg
from .srt import is_rtl

# We burn with ffmpeg's `ass` filter and shaping=complex — NOT the `subtitles`
# filter, which only does *simple* shaping. Simple shaping joins Arabic letters via
# precomposed presentation forms, but Kurdish (Sorani) letters like ێ ڵ ۆ have none,
# so they render disconnected; complex (HarfBuzz) shaping joins them. The `ass`
# filter needs an ASS file, so burn_subtitles wraps the SRT cues in one with the
# style baked in: white text on a semi-opaque black box (BorderStyle=3 fills it with
# OutlineColour, Outline=1 is its padding, Alignment=2 is bottom-centre; colours are
# &HAABBGGRR, AA=00 opaque). PlayResY is 288 — what the `subtitles` filter assumed
# for SRT — so _font_size still maps to the same on-screen size.
_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H40000000,&H00000000,0,0,0,0,100,100,0,0,3,1,0,2,10,10,28,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_timestamp(srt_timestamp: str) -> str:
    """SRT 'HH:MM:SS,mmm' -> ASS 'H:MM:SS.cc' (centiseconds)."""
    hours, minutes, rest = srt_timestamp.strip().split(":")
    seconds, millis = rest.split(",")
    return f"{int(hours)}:{minutes}:{seconds}.{int(millis) // 10:02d}"


def _ass_document(srt_text: str, font: str, font_size: int) -> str:
    """Wrap SRT cues in a styled ASS document so the burn can shape complex scripts."""
    parts = [_ASS_HEADER.format(font=font, font_size=font_size)]
    for block in re.split(r"\n[ \t]*\n", srt_text.strip()):
        rows = block.splitlines()
        timing = next((r for r in rows if "-->" in r), None)
        if timing is None:
            continue
        start, end = timing.split("-->")
        text = "\\N".join(rows[rows.index(timing) + 1:])
        parts.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{text}\n"
        )
    return "".join(parts)


def has_video_stream(path: str) -> bool:
    """True if the file actually has a video track (vs. audio-only)."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return "video" in proc.stdout


def video_dimensions(path: str) -> tuple[int, int, int]:
    """Return (width, height, duration_seconds) of the first video stream.

    Passed to Telegram's send_video so the inline (non-fullscreen) preview uses
    the real aspect ratio instead of a square default. Each value is 0 if it
    can't be probed — callers should treat 0 as "unknown" and omit it.
    """
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    parts = proc.stdout.split()

    def _int(i: int) -> int:
        try:
            return int(float(parts[i]))
        except (IndexError, ValueError):
            return 0

    return _int(0), _int(1), _int(2)


def _font_size(width: int, height: int) -> int:
    """Pick a libass FontSize that reads consistently across aspect ratios.

    libass scales FontSize to the video HEIGHT, so a height-proportional size
    looks right on tall/square clips but tiny on wide (16:9) ones — a landscape
    video is displayed in a short strip. Portrait/square stay at the base size;
    landscape scales up linearly with the aspect ratio (~1.8x at 16:9), capped at
    2x so an ultra-wide clip doesn't blow the text up. Unknown dimensions (0) fall
    back to the base size.
    """
    ratio = (width / height) if (width and height) else 1.0
    return round(16 * min(2.0, max(1.0, ratio)))


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    language: str = "",
    crf: int = 23,
    preset: str = "veryfast",
) -> str:
    """Burn subtitles into the video frames (re-encodes video, copies audio).

    Renders with the `ass` filter and complex (HarfBuzz) shaping so Arabic-script
    text — including Kurdish (Sorani) — joins correctly; the `subtitles` filter only
    does simple shaping, which breaks those joins. We write the styled ASS next to
    the SRT and run ffmpeg from that directory, referencing it by basename — libass
    filter paths have fragile escaping a bare filename avoids.
    """
    ensure_ffmpeg()
    work_dir = os.path.dirname(os.path.abspath(srt_path)) or "."
    ass_name = os.path.splitext(os.path.basename(srt_path))[0] + ".ass"

    with open(srt_path, encoding="utf-8") as f:
        srt_text = f.read()
    w, h, _ = video_dimensions(os.path.abspath(video_path))
    font = "Noto Sans Arabic" if is_rtl(language) else "DejaVu Sans"
    with open(os.path.join(work_dir, ass_name), "w", encoding="utf-8") as f:
        f.write(_ass_document(srt_text, font, _font_size(w, h)))

    cmd = [
        "ffmpeg",
        "-i", os.path.abspath(video_path),
        "-vf", f"ass={ass_name}:shaping=complex",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",            # broad player compatibility
        "-c:a", "copy",                   # keep original audio untouched
        "-movflags", "+faststart",        # lets the file start playing while loading
        "-y", "-loglevel", "error",
        os.path.abspath(out_path),
    ]
    proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg burn-in failed:\n{proc.stderr.strip()}")
    return out_path


def mux_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    language: str = "und",
) -> str:
    """Embed the SRT as a soft subtitle track (no re-encode).

    .mkv keeps it as SRT; .mp4/.mov uses mov_text. Remember: Telegram's player
    won't show these — use burn_subtitles for that.
    """
    ensure_ffmpeg()
    codec = "srt" if out_path.lower().endswith(".mkv") else "mov_text"
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", srt_path,
        "-map", "0", "-map", "1",
        "-c", "copy", "-c:s", codec,
        "-metadata:s:s:0", f"language={language}",
        "-y", "-loglevel", "error",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed:\n{proc.stderr.strip()}")
    return out_path
