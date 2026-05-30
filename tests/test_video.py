"""Tests for the pure logic in video.py (the ffmpeg calls are not unit-tested)."""

from subtrans.video import _font_size, _ass_timestamp, _ass_document


def test_portrait_and_square_use_the_base_size():
    assert _font_size(720, 1280) == 16   # 9:16
    assert _font_size(1080, 1080) == 16  # 1:1


def test_landscape_scales_up_roughly_double():
    assert _font_size(1280, 720) == 51   # 16:9 ~ 2x the portrait size


def test_mild_landscape_scales_between():
    assert _font_size(1024, 768) == 28   # 4:3 sits between square and 16:9


def test_ultrawide_is_capped():
    assert _font_size(2560, 720) == 56   # cap at 3.5x base


def test_unknown_dimensions_fall_back_to_base():
    assert _font_size(0, 0) == 16


def test_ass_timestamp_converts_srt_to_centiseconds():
    assert _ass_timestamp("00:01:02,500") == "0:01:02.50"
    assert _ass_timestamp("01:00:00,000") == "1:00:00.00"


def test_ass_document_bakes_in_the_style_and_a_dialogue_line():
    out = _ass_document("1\n00:00:00,000 --> 00:00:02,000\nHello\n", "Noto Sans Arabic", 24)
    assert "Style: Default,Noto Sans Arabic,24," in out
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Hello" in out
    assert "shaping" not in out  # shaping is a filter option, never written to the file


def test_ass_document_joins_multiline_cues_with_hard_breaks():
    out = _ass_document("1\n00:00:00,000 --> 00:00:02,000\nLine1\nLine2\n", "DejaVu Sans", 16)
    assert "Line1\\NLine2" in out
