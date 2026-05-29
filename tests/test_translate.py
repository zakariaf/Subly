"""Tests for translation — the response parsing and the id-stability invariant.

No network: we stub the OpenAI client so the LLM call returns canned content.
"""

from types import SimpleNamespace

from subtrans import translate
from subtrans.config import Config
from subtrans.transcribe import Segment


# --- a fake OpenAI client -------------------------------------------------- #

def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self.content)


class _FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


# --- _translate_batch parsing ---------------------------------------------- #

def _batch():
    return [(0, Segment(0, 1, "Hello")), (1, Segment(1, 2, "World"))]


def test_parses_clean_json():
    client = _FakeClient('{"segments":[{"id":0,"text":"Hola"},{"id":1,"text":"Mundo"}]}')
    out = translate._translate_batch(client, "m", _batch(), "Spanish", "en")
    assert out == {0: "Hola", 1: "Mundo"}


def test_strips_markdown_fences():
    client = _FakeClient('```json\n{"segments":[{"id":0,"text":"Hola"}]}\n```')
    out = translate._translate_batch(client, "m", _batch(), "Spanish", "en")
    assert out == {0: "Hola"}


def test_malformed_json_yields_empty():
    client = _FakeClient("not json at all")
    out = translate._translate_batch(client, "m", _batch(), "Spanish", "en")
    assert out == {}


# --- the id-stability invariant -------------------------------------------- #

def test_missing_ids_fall_back_to_original(monkeypatch):
    # Model only returns a translation for id 0; id 1 must fall back.
    monkeypatch.setattr(
        translate, "_make_client",
        lambda cfg: _FakeClient('{"segments":[{"id":0,"text":"Hola"}]}'),
    )
    segs = [Segment(0, 1, "Hello"), Segment(1, 2, "World")]
    out = translate.translate_segments(segs, "Spanish", Config())
    assert out == ["Hola", "World"]


def test_output_is_never_shorter_than_input(monkeypatch):
    # Model returns nothing usable -> every line falls back, length preserved.
    monkeypatch.setattr(translate, "_make_client", lambda cfg: _FakeClient("garbage"))
    segs = [Segment(i, i + 1, f"line {i}") for i in range(5)]
    out = translate.translate_segments(segs, "Spanish", Config())
    assert out == ["line 0", "line 1", "line 2", "line 3", "line 4"]


def test_empty_input_returns_empty():
    assert translate.translate_segments([], "Spanish", Config()) == []
