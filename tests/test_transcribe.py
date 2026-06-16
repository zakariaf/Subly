"""Tests for the transcription backend dispatch and the AssemblyAI mapping."""

from types import SimpleNamespace

from subtrans import transcribe
from subtrans.config import Config
from subtrans.transcribe import Segment


def _sentence(start_ms, end_ms, text):
    """Stand-in for an AssemblyAI SDK Sentence (timestamps in milliseconds)."""
    return SimpleNamespace(start=start_ms, end=end_ms, text=text)


def _explode(*args, **kwargs):
    raise AssertionError("the AssemblyAI backend must not run here")


# --- _sentences_to_segments: ms -> s, strip, drop empties, preserve order ---

def test_sentences_to_segments_converts_ms_to_seconds():
    out = transcribe._sentences_to_segments(
        [_sentence(0, 1500, "Hello."), _sentence(1500, 3200, "World.")]
    )
    assert out == [Segment(0.0, 1.5, "Hello."), Segment(1.5, 3.2, "World.")]


def test_sentences_to_segments_strips_and_drops_empty():
    out = transcribe._sentences_to_segments(
        [_sentence(0, 1000, "  Hi  "), _sentence(1000, 2000, "   "), _sentence(2000, 3000, "")]
    )
    assert out == [Segment(0.0, 1.0, "Hi")]


# --- transcribe() dispatch + the Whisper fallback ---

def test_assemblyai_backend_without_key_uses_local(monkeypatch):
    monkeypatch.setattr(transcribe, "_transcribe_assemblyai", _explode)
    monkeypatch.setattr(
        transcribe, "_transcribe_local",
        lambda audio_path, **kwargs: ([Segment(0, 1, "local")], "en"),
    )
    cfg = Config(transcribe_backend="assemblyai", assemblyai_api_key="")
    assert transcribe.transcribe("a.wav", cfg) == ([Segment(0, 1, "local")], "en")


def test_assemblyai_backend_with_key_uses_assemblyai(monkeypatch):
    expected = ([Segment(0, 2, "from aai")], "ar")
    monkeypatch.setattr(transcribe, "_transcribe_assemblyai", lambda *a, **k: expected)
    monkeypatch.setattr(transcribe, "_transcribe_local", _explode)
    cfg = Config(transcribe_backend="assemblyai", assemblyai_api_key="key123")
    assert transcribe.transcribe("a.wav", cfg) == expected


def test_assemblyai_failure_falls_back_to_local(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("AssemblyAI down")

    expected_local = ([Segment(0, 1, "local text")], "en")
    monkeypatch.setattr(transcribe, "_transcribe_assemblyai", boom)
    monkeypatch.setattr(transcribe, "_transcribe_local", lambda *a, **k: expected_local)
    cfg = Config(transcribe_backend="assemblyai", assemblyai_api_key="key123")
    assert transcribe.transcribe("a.wav", cfg) == expected_local
