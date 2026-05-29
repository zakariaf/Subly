"""Tests for SRT assembly — pure logic, no IO."""

from subtrans.srt import format_timestamp, build_srt, is_rtl
from subtrans.transcribe import Segment


# --- format_timestamp ------------------------------------------------------ #

def test_zero():
    assert format_timestamp(0) == "00:00:00,000"


def test_negative_clamps_to_zero():
    assert format_timestamp(-5) == "00:00:00,000"


def test_hours_minutes_seconds_millis():
    # 2h 2m 5s 125ms
    assert format_timestamp(7325.125) == "02:02:05,125"


def test_subsecond_millis():
    assert format_timestamp(1.5) == "00:00:01,500"


# --- build_srt ------------------------------------------------------------- #

def _segs():
    return [
        Segment(start=0.0, end=1.0, text="Hello"),
        Segment(start=1.0, end=2.0, text="World"),
    ]


def test_build_mono_structure():
    srt = build_srt(_segs(), ["Hola", "Mundo"])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\nHola\n")
    # Sequential, 1-based indices.
    assert "\n2\n00:00:01,000 --> 00:00:02,000\nMundo\n" in srt


def test_build_bilingual_stacks_original_under_translation():
    srt = build_srt(_segs(), ["Hola", "Mundo"], bilingual=True)
    assert "Hola\nHello" in srt
    assert "Mundo\nWorld" in srt


def test_bilingual_does_not_duplicate_when_translation_equals_original():
    segs = [Segment(start=0.0, end=1.0, text="Stop")]
    srt = build_srt(segs, ["Stop"], bilingual=True)
    # Should not render "Stop\nStop".
    assert srt.count("Stop") == 1


def test_one_block_per_segment():
    srt = build_srt(_segs(), ["a", "b"])
    # Two numbered blocks => indices "1" and "2" each begin a block.
    assert srt.count(" --> ") == 2


# --- RTL handling ---------------------------------------------------------- #

def test_is_rtl():
    assert is_rtl("Persian")
    assert is_rtl("Kurdish (Sorani)")
    assert is_rtl("Arabic")
    assert not is_rtl("Spanish")
    assert not is_rtl("English")


def test_rtl_wraps_each_translated_line_in_embedding_marks():
    srt = build_srt([Segment(0.0, 1.0, "Hello")], ["سلام"], rtl=True)
    assert "\u202bسلام\u202c" in srt


def test_ltr_has_no_embedding_marks():
    srt = build_srt([Segment(0.0, 1.0, "Hello")], ["Hola"], rtl=False)
    assert "\u202b" not in srt and "\u202c" not in srt
