"""Glue: media file -> translated SRT, with optional stage callbacks.

The stages are also exported individually so callers (e.g. the Telegram bot)
can run them one at a time in worker threads and report progress between each.
"""

from .audio import extract_audio
from .transcribe import transcribe
from .translate import translate_segments
from .srt import build_srt, is_rtl


def run(
    media_path: str,
    target_language: str,
    cfg,
    source_language: str | None = None,
    bilingual: bool = False,
    on_stage=None,
) -> str:
    """Full pipeline. Returns the SRT text.

    `on_stage(name)` — optional sync callback called before each stage with one
    of: 'extract', 'transcribe', 'translate', 'build'.
    """
    def stage(name):
        if on_stage:
            on_stage(name)

    stage("extract")
    audio_path = extract_audio(media_path)

    stage("transcribe")
    segments, detected = transcribe(audio_path, cfg, language=source_language)
    if not segments:
        raise RuntimeError("No speech detected in the file.")

    stage("translate")
    translations = translate_segments(
        segments, target_language, cfg, source_language=source_language or detected
    )

    stage("build")
    return build_srt(segments, translations, bilingual=bilingual, rtl=is_rtl(target_language))
