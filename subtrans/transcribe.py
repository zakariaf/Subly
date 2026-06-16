"""Step 2 — transcribe audio into timed segments.

Three backends:
  - "local":      faster-whisper, runs on your machine, free, no API key.
  - "openai":     OpenAI Whisper API (verbose_json), needs OPENAI_API_KEY.
  - "assemblyai": AssemblyAI Speech-to-Text, needs ASSEMBLYAI_API_KEY; falls back
                  to "local" on any failure.

All return (segments, detected_language).
"""

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str


# --------------------------------------------------------------------------- #
# Local backend (faster-whisper)
# --------------------------------------------------------------------------- #

_model_cache: dict = {}


def _get_local_model(model_size: str, device: str, compute_type: str):
    key = (model_size, device, compute_type)
    if key not in _model_cache:
        from faster_whisper import WhisperModel

        _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _model_cache[key]


def _transcribe_local(
    audio_path: str,
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
) -> tuple[list[Segment], str]:
    model = _get_local_model(model_size, device, compute_type)
    seg_iter, info = model.transcribe(
        audio_path,
        language=language,        # None => auto-detect
        vad_filter=True,          # skip long silences -> tighter timestamps
        beam_size=5,
    )
    segments = [
        Segment(start=s.start, end=s.end, text=s.text.strip())
        for s in seg_iter
        if s.text and s.text.strip()
    ]
    return segments, info.language


# --------------------------------------------------------------------------- #
# OpenAI Whisper API backend
# --------------------------------------------------------------------------- #

def _transcribe_openai(
    audio_path: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = "whisper-1",
    language: str | None = None,
    timeout: float = 60.0,
    max_retries: int = 2,
) -> tuple[list[Segment], str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=model,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language=language,
        )
    segments = [
        Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in (resp.segments or [])
        if s.text and s.text.strip()
    ]
    return segments, getattr(resp, "language", language or "unknown")


# --------------------------------------------------------------------------- #
# AssemblyAI backend
# --------------------------------------------------------------------------- #

def _sentences_to_segments(sentences: list) -> list[Segment]:
    """Map AssemblyAI sentences (timestamps in ms) to Segments (seconds), in order.

    One sentence -> one Segment; empties are dropped. Order is preserved so the SRT
    can never desync from its timestamps (see the subtitle-pipeline skill).
    """
    return [
        Segment(start=s.start / 1000.0, end=s.end / 1000.0, text=s.text.strip())
        for s in sentences
        if s.text and s.text.strip()
    ]


def _transcribe_assemblyai(
    audio_path: str,
    api_key: str,
    base_url: str = "https://api.assemblyai.com",
    speech_models: tuple[str, ...] = ("universal-2",),
    language: str | None = None,
    timeout: float = 60.0,
) -> tuple[list[Segment], str]:
    import assemblyai as aai

    aai.settings.api_key = api_key
    aai.settings.base_url = base_url
    aai.settings.http_timeout = timeout  # bound each HTTP call; never the SDK default

    config = aai.TranscriptionConfig(
        speech_models=list(speech_models),
        language_code=language,             # None => let AssemblyAI detect it
        language_detection=language is None,
    )
    transcript = aai.Transcriber(config=config).transcribe(audio_path)
    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(transcript.error)

    segments = _sentences_to_segments(transcript.get_sentences())
    detected = transcript.json_response.get("language_code") or language or "unknown"
    return segments, detected


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def transcribe(audio_path: str, cfg, language: str | None = None) -> tuple[list[Segment], str]:
    """Dispatch to the configured backend. `cfg` is a subtrans.config.Config."""
    if cfg.transcribe_backend == "assemblyai" and cfg.assemblyai_api_key:
        try:
            return _transcribe_assemblyai(
                audio_path,
                api_key=cfg.assemblyai_api_key,
                base_url=cfg.assemblyai_base_url,
                speech_models=cfg.assemblyai_speech_models,
                language=language,
                timeout=cfg.request_timeout,
            )
        except Exception as e:
            # Broad on purpose: the user opted into "if AssemblyAI is unavailable,
            # use Whisper", so every failure mode (network, auth, quota, outage) must
            # degrade to the local backend rather than fail the request. Logged, not
            # swallowed; the exception message carries no secret.
            log.warning("AssemblyAI transcription failed; falling back to local Whisper: %s", e)
    if cfg.transcribe_backend == "openai":
        return _transcribe_openai(
            audio_path,
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            language=language,
            timeout=cfg.request_timeout,
            max_retries=cfg.max_retries,
        )
    return _transcribe_local(
        audio_path,
        model_size=cfg.whisper_model,
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        language=language,
    )
