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

_MAX_CUE_CHARS = 84  # ~2 subtitle lines; keeps cues readable for dense speech


def _words_to_segments(words: list, max_duration: float = 6.0, max_gap: float = 1.0) -> list[Segment]:
    """Pack timed words into subtitle cues, in order, broken at natural pauses.

    AssemblyAI returns whole sentences (often 20-30s), so we build cues from its
    word-level timestamps instead. A cue grows until the next word would either
    follow a silence longer than `max_gap` seconds (a natural pause), push the cue
    past `max_duration` seconds, or overflow `_MAX_CUE_CHARS` — then it breaks at
    that word boundary. start/end come straight from the words, so cues never
    desync (see the subtitle-pipeline skill).
    """
    segments: list[Segment] = []
    cue: list = []
    for word in words:
        if not (word.text and word.text.strip()):
            continue
        if cue:
            gap = (word.start - cue[-1].end) / 1000.0
            span = (word.end - cue[0].start) / 1000.0
            chars = sum(len(w.text) + 1 for w in cue) + len(word.text)
            if gap > max_gap or span > max_duration or chars > _MAX_CUE_CHARS:
                segments.append(_to_cue(cue))
                cue = []
        cue.append(word)
    if cue:
        segments.append(_to_cue(cue))
    return segments


def _to_cue(words: list) -> Segment:
    return Segment(
        start=words[0].start / 1000.0,
        end=words[-1].end / 1000.0,
        text=" ".join(w.text.strip() for w in words),
    )


def _transcribe_assemblyai(
    audio_path: str,
    api_key: str,
    base_url: str = "https://api.assemblyai.com",
    speech_models: tuple[str, ...] = ("universal-2",),
    language: str | None = None,
    timeout: float = 60.0,
) -> tuple[list, str]:
    """Transcribe with AssemblyAI; return its word list (ms timestamps) + detected language.

    Grouping words into subtitle cues is the caller's job (see `_segment`), so this
    function does one thing: get the transcript.
    """
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

    detected = transcript.json_response.get("language_code") or language or "unknown"
    return transcript.words or [], detected


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def _segment(words: list, cfg) -> list[Segment]:
    """Group transcribed words into subtitle cues — AI (V2) or rule-based (V1)."""
    if cfg.ai_segmentation:
        from .segment import segment_words

        return segment_words(words, cfg)
    return _words_to_segments(words, cfg.max_subtitle_duration, cfg.max_subtitle_gap)


def transcribe(audio_path: str, cfg, language: str | None = None) -> tuple[list[Segment], str]:
    """Dispatch to the configured backend. `cfg` is a subtrans.config.Config."""
    if cfg.transcribe_backend == "assemblyai" and cfg.assemblyai_api_key:
        try:
            words, detected = _transcribe_assemblyai(
                audio_path,
                api_key=cfg.assemblyai_api_key,
                base_url=cfg.assemblyai_base_url,
                speech_models=cfg.assemblyai_speech_models,
                language=language,
                timeout=cfg.request_timeout,
            )
            return _segment(words, cfg), detected
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
