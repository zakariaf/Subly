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
    max_file_mb: int = 20  # Bot API getFile limit is 20MB unless you run a local Bot API server

    # --- Transcription ---
    # backend: "local" (faster-whisper) or "openai" (Whisper API)
    transcribe_backend: str = "local"
    whisper_model: str = "small"        # tiny | base | small | medium | large-v3
    whisper_device: str = "auto"        # auto | cpu | cuda
    whisper_compute_type: str = "int8"  # int8 (cpu) | float16 (gpu) | default

    # --- Translation (OpenAI-compatible) ---
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    translation_model: str = "gpt-4o-mini"
    translation_batch_size: int = 40
    # The SDK default timeout is 10 minutes — far too long for a request that's
    # blocking a user. Keep it tight and let max_retries handle transient errors.
    openai_timeout: float = 60.0
    openai_max_retries: int = 2

    # --- Defaults ---
    default_target_language: str = "English"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=_get("TELEGRAM_BOT_TOKEN"),
            max_file_mb=int(_get("MAX_FILE_MB", "20")),
            transcribe_backend=_get("TRANSCRIBE_BACKEND", "local"),
            whisper_model=_get("WHISPER_MODEL", "small"),
            whisper_device=_get("WHISPER_DEVICE", "auto"),
            whisper_compute_type=_get("WHISPER_COMPUTE_TYPE", "int8"),
            openai_api_key=_get("OPENAI_API_KEY"),
            openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            translation_model=_get("TRANSLATION_MODEL", "gpt-4o-mini"),
            translation_batch_size=int(_get("TRANSLATION_BATCH_SIZE", "40")),
            openai_timeout=float(_get("OPENAI_TIMEOUT", "60")),
            openai_max_retries=int(_get("OPENAI_MAX_RETRIES", "2")),
            default_target_language=_get("DEFAULT_TARGET_LANGUAGE", "English"),
        )
