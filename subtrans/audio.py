"""Step 1 — pull a clean mono 16kHz WAV out of any video/audio file via ffmpeg."""

import os
import shutil
import subprocess
import tempfile


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH. Install it (e.g. `apt install ffmpeg` or `brew install ffmpeg`).")


def extract_audio(media_path: str, out_path: str | None = None) -> str:
    """Extract audio as 16kHz mono WAV — the format Whisper wants.

    Works for video *or* audio input. Returns the output path.
    """
    ensure_ffmpeg()
    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

    cmd = [
        "ffmpeg",
        "-i", media_path,
        "-vn",            # drop video
        "-ac", "1",       # mono
        "-ar", "16000",   # 16 kHz
        "-c:a", "pcm_s16le",
        "-y",             # overwrite
        "-loglevel", "error",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr.strip()}")
    return out_path
