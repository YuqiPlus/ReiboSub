import pytest

from reibosub import Cue, Subtitle, ValidationError, convert_text


def test_text_conversion_preserves_inline_tags():
    assert convert_text('<span title="繁體">繁體字幕</span>', 'simplified') == '<span title="繁體">繁体字幕</span>'
    assert convert_text('简体字幕', 'traditional') == '簡體字幕'


def test_empty_subtitles_still_validate_requested_script():
    from reibosub.chinese import convert_script
    with pytest.raises(ValidationError):
        convert_script(Subtitle(()), 'invalid')


def test_conversion_is_immutable_and_timing_locked():
    source = Subtitle((Cue(9, .25, 3.75, '繁體字幕'),))
    target = source.to_simplified()
    assert source[0].text == '繁體字幕'
    assert target[0].text == '繁体字幕'
    assert (target[0].index, target[0].start, target[0].end) == (9, .25, 3.75)
