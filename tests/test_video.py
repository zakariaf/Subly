"""Tests for the pure logic in video.py (the ffmpeg calls are not unit-tested)."""

from subtrans.video import _font_size, _style


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


def test_rtl_uses_a_font_that_shapes_kurdish():
    assert "Scheherazade New" in _style(40, rtl=True)


def test_ltr_uses_latin_font():
    assert "DejaVu Sans" in _style(40, rtl=False)
