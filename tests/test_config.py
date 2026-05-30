"""Tests for env-driven configuration."""

from subtrans.config import Config

_ENV_VARS = [
    "TELEGRAM_BOT_TOKEN", "MAX_FILE_MB", "SEND_LIMIT_MB", "TELEGRAM_API_BASE",
    "TELEGRAM_LOCAL_MODE", "TRANSCRIBE_BACKEND", "WHISPER_MODEL",
    "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "LLM_API_KEY", "LLM_BASE_URL", "TRANSLATION_MODEL", "TRANSLATION_BATCH_SIZE",
    "REQUEST_TIMEOUT", "MAX_RETRIES", "DEFAULT_TARGET_LANGUAGE",
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
    assert cfg.send_limit_mb == 50
    assert cfg.telegram_api_base == ""
    assert cfg.telegram_local_mode is False
    assert cfg.translation_batch_size == 40
    assert cfg.llm_base_url == "https://api.openai.com/v1"
    assert cfg.request_timeout == 60.0
    assert cfg.max_retries == 2
    assert cfg.default_target_language == "English"


def test_local_bot_api_mode(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_API_BASE", "http://telegram-bot-api:8081")
    monkeypatch.setenv("TELEGRAM_LOCAL_MODE", "1")
    monkeypatch.setenv("SEND_LIMIT_MB", "2000")
    cfg = Config.from_env()
    assert cfg.telegram_api_base == "http://telegram-bot-api:8081"
    assert cfg.telegram_local_mode is True
    assert cfg.send_limit_mb == 2000


def test_overrides_and_type_coercion(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MAX_FILE_MB", "50")
    monkeypatch.setenv("TRANSLATION_BATCH_SIZE", "10")
    monkeypatch.setenv("REQUEST_TIMEOUT", "30.5")
    monkeypatch.setenv("MAX_RETRIES", "5")
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("TRANSLATION_MODEL", "deepseek-chat")
    cfg = Config.from_env()
    assert cfg.max_file_mb == 50
    assert cfg.translation_batch_size == 10
    assert cfg.request_timeout == 30.5
    assert cfg.max_retries == 5
    assert cfg.transcribe_backend == "openai"
    assert cfg.llm_base_url == "https://api.deepseek.com"
    assert cfg.translation_model == "deepseek-chat"


def test_values_are_stripped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DEFAULT_TARGET_LANGUAGE", "  French  ")
    assert Config.from_env().default_target_language == "French"
