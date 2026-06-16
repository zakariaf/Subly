"""Configuration, loaded from environment variables (.env supported)."""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    # --- Telegram ---
    telegram_token: str = ""
    max_file_mb: int = 20    # cloud Bot API getFile cap; raise it with a local Bot API server
    send_limit_mb: int = 50  # cloud Bot API send cap; up to 2000 with a local server
    # Optional local Bot API server (https://github.com/tdlib/telegram-bot-api) to lift the
    # caps above. Empty -> Telegram's cloud API. e.g. "http://telegram-bot-api:8081".
    telegram_api_base: str = ""
    telegram_local_mode: bool = False

    # --- Transcription ---
    # backend: "local" (faster-whisper, CPU, free) or "openai" (OpenAI Whisper API)
    transcribe_backend: str = "local"
    # local backend (faster-whisper) — CPU by default; no GPU assumed.
    whisper_model: str = "small"        # tiny | base | small | medium | large-v3
    whisper_device: str = "auto"        # auto | cpu | cuda
    whisper_compute_type: str = "int8"  # int8 (cpu) | float16 (gpu) | default
    # openai backend (OpenAI Whisper API) — only used when transcribe_backend == "openai".
    # Kept separate from the translation LLM below: most LLM providers (e.g. DeepSeek)
    # have no transcription endpoint, so this stays pointed at OpenAI.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # assemblyai backend (AssemblyAI Speech-to-Text) — used when
    # transcribe_backend == "assemblyai"; falls back to the local backend on any
    # failure. EU users point the base URL at https://api.eu.assemblyai.com.
    assemblyai_api_key: str = ""
    assemblyai_base_url: str = "https://api.assemblyai.com"
    # Ordered fallback list of speech models. Universal-2 is the default because
    # Universal-3 Pro doesn't cover some languages we need (e.g. Arabic, Persian).
    assemblyai_speech_models: tuple[str, ...] = ("universal-2",)

    # --- Translation (any OpenAI-compatible LLM: OpenAI, DeepSeek, Together, local) ---
    # Independent of the transcription credentials above, so you can translate with
    # DeepSeek while transcribing locally (or with OpenAI Whisper).
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    translation_model: str = "gpt-4o-mini"
    translation_batch_size: int = 40

    # --- Shared HTTP behaviour (both API clients) ---
    # The SDK default timeout is 10 minutes — far too long for a request that's
    # blocking a user. Keep it tight and let max_retries handle transient errors.
    request_timeout: float = 60.0
    max_retries: int = 2

    # --- Concurrency ---
    # Media jobs processed in parallel (Telegram updates handled concurrently).
    # I/O-bound stages (transcribe/translate) overlap across jobs; the CPU-bound
    # video burn is bounded separately below.
    max_concurrent_jobs: int = 4
    # Simultaneous video burns (re-encode). x264 already uses every core, so 1 keeps
    # parallel jobs from thrashing the CPU; raise only on a large multi-core host.
    max_concurrent_burns: int = 1

    # --- Defaults ---
    default_target_language: str = "English"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=_get("TELEGRAM_BOT_TOKEN"),
            max_file_mb=int(_get("MAX_FILE_MB", "20")),
            send_limit_mb=int(_get("SEND_LIMIT_MB", "50")),
            telegram_api_base=_get("TELEGRAM_API_BASE"),
            telegram_local_mode=_get("TELEGRAM_LOCAL_MODE").lower() in ("1", "true", "yes"),
            transcribe_backend=_get("TRANSCRIBE_BACKEND", "local"),
            whisper_model=_get("WHISPER_MODEL", "small"),
            whisper_device=_get("WHISPER_DEVICE", "auto"),
            whisper_compute_type=_get("WHISPER_COMPUTE_TYPE", "int8"),
            openai_api_key=_get("OPENAI_API_KEY"),
            openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            assemblyai_api_key=_get("ASSEMBLYAI_API_KEY"),
            assemblyai_base_url=_get("ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com"),
            assemblyai_speech_models=tuple(
                m.strip()
                for m in _get("ASSEMBLYAI_SPEECH_MODELS", "universal-2").split(",")
                if m.strip()
            ),
            llm_api_key=_get("LLM_API_KEY"),
            llm_base_url=_get("LLM_BASE_URL", "https://api.openai.com/v1"),
            translation_model=_get("TRANSLATION_MODEL", "gpt-4o-mini"),
            translation_batch_size=int(_get("TRANSLATION_BATCH_SIZE", "40")),
            request_timeout=float(_get("REQUEST_TIMEOUT", "60")),
            max_retries=int(_get("MAX_RETRIES", "2")),
            max_concurrent_jobs=int(_get("MAX_CONCURRENT_JOBS", "4")),
            max_concurrent_burns=int(_get("MAX_CONCURRENT_BURNS", "1")),
            default_target_language=_get("DEFAULT_TARGET_LANGUAGE", "English"),
        )
