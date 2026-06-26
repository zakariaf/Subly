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


class _ScriptedCompletions:
    """Returns canned responses in order — one per create() call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self.responses.pop(0) if self.responses else "{}")


class _ScriptedClient:
    def __init__(self, *responses):
        self.chat = SimpleNamespace(completions=_ScriptedCompletions(responses))


# --- _translate_batch: two-block parsing ----------------------------------- #

def _batch():
    return [(0, Segment(0, 1, "Hello")), (1, Segment(1, 2, "World"))]


def test_parses_two_block_reply_and_extracts_glossary():
    content = (
        '<glossary>{"prompt":"پرامپت"}</glossary>'
        '<translation>{"segments":[{"id":0,"text":"Hola"},{"id":1,"text":"Mundo"}]}</translation>'
    )
    segs, gloss = translate._translate_batch(_FakeClient(content), "m", _batch(), "Spanish", "en", {})
    assert segs == {0: "Hola", 1: "Mundo"}
    assert gloss == {"prompt": "پرامپت"}


def test_parses_translation_block_with_fences():
    content = '<translation>```json\n{"segments":[{"id":0,"text":"Hola"}]}\n```</translation>'
    segs, _ = translate._translate_batch(_FakeClient(content), "m", _batch(), "Spanish", "en", {})
    assert segs == {0: "Hola"}


def test_bare_json_without_blocks_still_parses():
    # Tolerant fallback: a reply that's just the segments JSON, no <translation> tag.
    segs, gloss = translate._translate_batch(
        _FakeClient('{"segments":[{"id":0,"text":"Hola"}]}'), "m", _batch(), "Spanish", "en", {}
    )
    assert segs == {0: "Hola"}
    assert gloss == {}


def test_malformed_reply_yields_empty():
    segs, gloss = translate._translate_batch(
        _FakeClient("not json at all"), "m", _batch(), "Spanish", "en", {}
    )
    assert segs == {} and gloss == {}


# --- the prompt contract --------------------------------------------------- #

def test_prompt_keeps_process_and_output_contract():
    # The self-review step, the sync contract, and the two output blocks the parser
    # reads must all survive any future edit to the prompt.
    p = translate.SYSTEM_PROMPT.lower()
    assert "review" in p
    assert "one id in -> one id out" in p
    assert "<glossary>" in p and "<translation>" in p


def test_prompt_permits_within_sentence_redistribution():
    # A sentence split across cues may be re-spread across its own lines so it reads
    # naturally — but never across a sentence boundary, and the id count/order is
    # untouched (the timeline stays sacred; only word-to-cue locality is relaxed).
    p = translate.SYSTEM_PROMPT.lower()
    assert "sentence" in p and "redistribute" in p
    assert "sentence boundary" in p
    assert "one id in -> one id out" in p


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


# --- glossary carry-over between chunks ------------------------------------ #

def test_glossary_threads_from_one_chunk_into_the_next(monkeypatch):
    client = _ScriptedClient(
        '<glossary>{"prompt":"پرامپت"}</glossary>'
        '<translation>{"segments":[{"id":0,"text":"a"}]}</translation>',
        '<glossary>{"prompt":"پرامپت"}</glossary>'
        '<translation>{"segments":[{"id":1,"text":"b"}]}</translation>',
    )
    monkeypatch.setattr(translate, "_make_client", lambda cfg: client)
    segs = [Segment(0, 1, "the prompt"), Segment(1, 2, "again")]
    out = translate.translate_segments(segs, "Persian", Config(translation_batch_size=1))
    assert out == ["a", "b"]
    # The second chunk's request carries the glossary learned in the first.
    second_user = client.chat.completions.calls[1]["messages"][1]["content"]
    assert "پرامپت" in second_user


# --- caption (describe) ---------------------------------------------------- #

def test_describe_returns_stripped_caption(monkeypatch):
    monkeypatch.setattr(
        translate, "_make_client", lambda cfg: _FakeClient("  A fun clip about cats  ")
    )
    segs = [Segment(0, 1, "Cats are great."), Segment(1, 2, "Very fluffy.")]
    assert translate.describe(segs, "English", Config()) == "A fun clip about cats"


def test_describe_skips_llm_when_no_transcript(monkeypatch):
    calls = []
    monkeypatch.setattr(
        translate, "_make_client", lambda cfg: calls.append(1) or _FakeClient("x")
    )
    assert translate.describe([], "English", Config()) == ""
    assert calls == []  # no client built / no API call
