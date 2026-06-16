"""Tests for the transcription backend dispatch and the AssemblyAI mapping."""

from types import SimpleNamespace

from subtrans import transcribe
from subtrans.config import Config
from subtrans.transcribe import Segment


def _word(start_ms, end_ms, text):
    """Stand-in for an AssemblyAI SDK Word (timestamps in milliseconds)."""
    return SimpleNamespace(start=start_ms, end=end_ms, text=text, confidence=1.0)


def _explode(*args, **kwargs):
    raise AssertionError("the AssemblyAI backend must not run here")


# --- _words_to_segments: pack timed words into capped, in-sync subtitle cues ---

def test_words_pack_into_one_cue_when_short():
    out = transcribe._words_to_segments(
        [_word(0, 500, "Hello"), _word(500, 1000, "there")], max_duration=6.0
    )
    assert out == [Segment(0.0, 1.0, "Hello there")]


def test_words_split_when_duration_exceeds_cap():
    out = transcribe._words_to_segments(
        [_word(0, 3000, "one"), _word(3000, 6000, "two"), _word(6000, 9000, "three")],
        max_duration=6.0,
    )
    assert out == [Segment(0.0, 6.0, "one two"), Segment(6.0, 9.0, "three")]


def test_words_split_on_char_cap():
    words = [_word(i * 100, i * 100 + 100, "alpha") for i in range(20)]
    out = transcribe._words_to_segments(words, max_duration=60.0)
    assert len(out) > 1
    assert all(len(s.text) <= 84 for s in out)


def test_words_skip_empty_text_and_preserve_order():
    out = transcribe._words_to_segments(
        [_word(0, 500, "Hi"), _word(500, 600, "  "), _word(600, 1000, "there")],
        max_duration=6.0,
    )
    assert out == [Segment(0.0, 1.0, "Hi there")]


def test_no_words_yields_no_segments():
    assert transcribe._words_to_segments([], max_duration=6.0) == []


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
