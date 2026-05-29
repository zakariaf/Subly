"""Tests for env-driven configuration."""

from subtrans.config import Config

_ENV_VARS = [
    "TELEGRAM_BOT_TOKEN", "MAX_FILE_MB", "TRANSCRIBE_BACKEND", "WHISPER_MODEL",
    "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "TRANSLATION_MODEL", "TRANSLATION_BATCH_SIZE", "OPENAI_TIMEOUT",
    "OPENAI_MAX_RETRIES", "DEFAULT_TARGET_LANGUAGE",
]


def _clear_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults(monkeypatch):
    _clear_env(monkeypatch)
    cfg = Config.from_env()
    assert cfg.transcribe_backend == "local"
    assert cfg.whisper_model == "small"
    assert cfg.max_file_mb == 20
    assert cfg.translation_batch_size == 40
    assert cfg.openai_timeout == 60.0
    assert cfg.openai_max_retries == 2
    assert cfg.default_target_language == "English"


def test_overrides_and_type_coercion(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MAX_FILE_MB", "50")
    monkeypatch.setenv("TRANSLATION_BATCH_SIZE", "10")
    monkeypatch.setenv("OPENAI_TIMEOUT", "30.5")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "5")
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "openai")
    cfg = Config.from_env()
    assert cfg.max_file_mb == 50
    assert cfg.translation_batch_size == 10
    assert cfg.openai_timeout == 30.5
    assert cfg.openai_max_retries == 5
    assert cfg.transcribe_backend == "openai"


def test_values_are_stripped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DEFAULT_TARGET_LANGUAGE", "  French  ")
    assert Config.from_env().default_target_language == "French"
