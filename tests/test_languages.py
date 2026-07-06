from __future__ import annotations

import pytest

from video_translate.languages import (
    asr_language_for_source,
    normalize_source_language,
    ocr_language_for_source,
    youtube_language_for_source,
)


def test_source_language_helpers_map_japanese_to_tool_languages():
    assert normalize_source_language("ja") == "japanese"
    assert normalize_source_language("日本語") == "japanese"
    assert ocr_language_for_source("japanese") == "japan"
    assert asr_language_for_source("japanese") == "japanese"
    assert youtube_language_for_source("japanese") == "ja"


def test_source_language_helpers_keep_korean_defaults():
    assert normalize_source_language("") == "auto"
    assert ocr_language_for_source("auto") == "korean"
    assert ocr_language_for_source("ko") == "korean"
    assert asr_language_for_source("ko") == "korean"
    assert youtube_language_for_source("ko") == "ko"


def test_source_language_helpers_reject_unknown_language():
    with pytest.raises(ValueError):
        normalize_source_language("martian")
