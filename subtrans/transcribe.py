"""Step 2 — transcribe audio into timed segments.

Two backends:
  - "local":  faster-whisper, runs on your machine, free, no API key.
  - "openai": OpenAI Whisper API (verbose_json), needs OPENAI_API_KEY.

Both return (segments, detected_language).
"""

from dataclasses import dataclass


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
# Public entry point
# --------------------------------------------------------------------------- #

def transcribe(audio_path: str, cfg, language: str | None = None) -> tuple[list[Segment], str]:
    """Dispatch to the configured backend. `cfg` is a subtrans.config.Config."""
    if cfg.transcribe_backend == "openai":
        return _transcribe_openai(
            audio_path,
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            language=language,
            timeout=cfg.openai_timeout,
            max_retries=cfg.openai_max_retries,
        )
    return _transcribe_local(
        audio_path,
        model_size=cfg.whisper_model,
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        language=language,
    )
