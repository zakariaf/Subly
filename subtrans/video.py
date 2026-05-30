"""Step 5 (optional) — attach subtitles to the video.

Two ways to "attach":

  burn_subtitles  — render text onto the pixels (HARD subs). Always visible,
                    shows in Telegram's player, but re-encodes the video.
  mux_subtitles   — add the SRT as a separate track (SOFT subs). Instant, no
                    re-encode, toggleable — but NOT shown by Telegram's player.
                    Good for .mkv / desktop players (VLC, mpv).
"""

import os
import subprocess

from .audio import ensure_ffmpeg

# libass style string. Colours are &HAABBGGRR (alpha+BGR), so AA=00 is opaque.
# White text on a semi-opaque black box (BorderStyle=3 → the box is filled with
# OutlineColour; Outline sets its padding) so it stays readable over any scene.
#
# Font is picked per script: DejaVu Sans (Latin default) renders Arabic codepoints
# UNSHAPED, and the Noto Arabic faces fake Kurdish (Sorani) letters with detachable
# marks that come out disconnected. So for right-to-left targets we use Scheherazade
# New — a traditional Arabic Naskh face (the style iOS uses) with genuine, joined
# Kurdish glyphs — vendored into the image (see Dockerfile). FontSize is chosen by
# _font_size from the video's aspect. Outline is the box padding — 1 so two-line
# boxes don't overlap.
def _style(font_size: int, rtl: bool = False) -> str:
    font = "Scheherazade New" if rtl else "DejaVu Sans"
    return (
        f"FontName={font},FontSize={font_size},"
        "PrimaryColour=&H00FFFFFF,"      # text: opaque white
        "OutlineColour=&H40000000,"      # box: ~75%-opaque black
        "BorderStyle=3,Outline=1,Shadow=0,MarginV=28"
    )


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
    landscape scales up with the squared aspect ratio (empirically ~2x at 16:9),
    capped so an ultra-wide clip doesn't blow the text up. Unknown dimensions
    (0) fall back to the base size.
    """
    ratio = (width / height) if (width and height) else 1.0
    return round(16 * min(3.5, max(1.0, ratio) ** 2))


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    rtl: bool = False,
    crf: int = 23,
    preset: str = "veryfast",
) -> str:
    """Burn subtitles into the video frames (re-encodes video, copies audio).

    We run ffmpeg with cwd set to the SRT's directory and reference it by
    basename — the `subtitles` filter has fragile path escaping (colons, commas,
    quotes), and a bare filename sidesteps all of it.
    """
    ensure_ffmpeg()
    srt_dir = os.path.dirname(os.path.abspath(srt_path)) or "."
    srt_name = os.path.basename(srt_path)

    w, h, _ = video_dimensions(os.path.abspath(video_path))
    font_size = _font_size(w, h)
    vf = f"subtitles={srt_name}:force_style='{_style(font_size, rtl)}'"

    cmd = [
        "ffmpeg",
        "-i", os.path.abspath(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",            # broad player compatibility
        "-c:a", "copy",                   # keep original audio untouched
        "-movflags", "+faststart",        # lets the file start playing while loading
        "-y", "-loglevel", "error",
        os.path.abspath(out_path),
    ]
    proc = subprocess.run(cmd, cwd=srt_dir, capture_output=True, text=True)
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
