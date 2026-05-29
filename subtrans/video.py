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
DEFAULT_STYLE = (
    "FontName=DejaVu Sans,FontSize=24,"
    "PrimaryColour=&H00FFFFFF,"      # text: opaque white
    "OutlineColour=&H40000000,"      # box: ~75%-opaque black
    "BorderStyle=3,Outline=5,Shadow=0,MarginV=30"
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


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    style: str = DEFAULT_STYLE,
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

    vf = f"subtitles={srt_name}"
    if style:
        vf += f":force_style='{style}'"

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
