"""Tests for AI subtitle segmentation (V2) — pure logic + the rule-based fallback.

No network: the LLM call (`_ai_breaks`) is the seam we patch.
"""

from types import SimpleNamespace

from subtrans import segment
from subtrans.config import Config
from subtrans.transcribe import Segment


def _word(start_ms, end_ms, text):
    """Stand-in for an AssemblyAI SDK Word (timestamps in milliseconds)."""
    return SimpleNamespace(start=start_ms, end=end_ms, text=text, confidence=1.0)


# --- _parse_breaks: clean, in-range, strictly-increasing indices ------------ #

def test_parse_breaks_sorts_dedupes_and_keeps_in_range():
    assert segment._parse_breaks('{"breaks":[3,1,1,8]}', num_words=12) == [1, 3, 8]


def test_parse_breaks_drops_out_of_range_and_non_ints():
    assert segment._parse_breaks('{"breaks":[2,"x",99,-1]}', num_words=5) == [2]


def test_parse_breaks_returns_empty_when_unusable():
    assert segment._parse_breaks("not json at all", num_words=5) == []
    assert segment._parse_breaks('{"other":[1]}', num_words=5) == []


# --- _cues_from_breaks: partition by break indices, caps still enforced ----- #

def test_cues_from_breaks_partitions_at_indices():
    words = [_word(i * 1000, i * 1000 + 900, f"w{i}") for i in range(6)]
    cues = segment._cues_from_breaks(words, [2, 4], max_duration=60.0)
    assert cues == [
        Segment(0.0, 2.9, "w0 w1 w2"),
        Segment(3.0, 4.9, "w3 w4"),
        Segment(5.0, 5.9, "w5"),
    ]


def test_cues_from_breaks_still_caps_a_too_long_group():
    # 10 contiguous 1s words in one AI cue -> the duration cap must split it.
    words = [_word(i * 1000, i * 1000 + 1000, f"w{i}") for i in range(10)]
    cues = segment._cues_from_breaks(words, [9], max_duration=6.0)
    assert len(cues) > 1
    assert all((c.end - c.start) <= 6.0 + 1e-9 for c in cues)


# --- segment_words: AI path + fallback to rule-based packing ---------------- #

def test_segment_words_uses_ai_breaks(monkeypatch):
    monkeypatch.setattr(segment, "_ai_breaks", lambda words, cfg: [0])
    words = [_word(0, 500, "A"), _word(600, 1000, "B")]
    assert segment.segment_words(words, Config()) == [
        Segment(0.0, 0.5, "A"), Segment(0.6, 1.0, "B"),
    ]


def test_segment_words_falls_back_when_ai_returns_nothing(monkeypatch):
    monkeypatch.setattr(segment, "_ai_breaks", lambda words, cfg: [])
    words = [_word(0, 500, "Hello"), _word(500, 1000, "there")]
    # Rule-based packing keeps them together (no pause, under the caps).
    assert segment.segment_words(words, Config()) == [Segment(0.0, 1.0, "Hello there")]


def test_segment_words_falls_back_when_ai_raises(monkeypatch):
    def boom(words, cfg):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(segment, "_ai_breaks", boom)
    assert segment.segment_words([_word(0, 500, "Hi")], Config()) == [Segment(0.0, 0.5, "Hi")]


def test_segment_words_empty():
    assert segment.segment_words([], Config()) == []
