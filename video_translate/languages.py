from __future__ import annotations

from typing import Any

_SOURCE_LANGUAGE_ALIASES = {
    "": "auto",
    "auto": "auto",
    "unknown": "auto",
    "ko": "korean",
    "kor": "korean",
    "kr": "korean",
    "korean": "korean",
    "한국어": "korean",
    "韓語": "korean",
    "韩语": "korean",
    "ja": "japanese",
    "jp": "japanese",
    "jpn": "japanese",
    "japanese": "japanese",
    "日本語": "japanese",
    "日语": "japanese",
    "日語": "japanese",
    "en": "english",
    "eng": "english",
    "english": "english",
    "英语": "english",
    "英語": "english",
    "zh": "chinese",
    "cn": "chinese",
    "chinese": "chinese",
    "中文": "chinese",
}

_OCR_LANGUAGE_MAP = {
    "auto": "korean",
    "korean": "korean",
    "japanese": "japan",
    "english": "en",
    "chinese": "ch",
}

_ASR_LANGUAGE_MAP = {
    "auto": "auto",
    "korean": "korean",
    "japanese": "japanese",
    "english": "english",
    "chinese": "chinese",
}

_YOUTUBE_LANGUAGE_MAP = {
    "auto": "",
    "korean": "ko",
    "japanese": "ja",
    "english": "en",
    "chinese": "zh",
}


def normalize_source_language(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in _SOURCE_LANGUAGE_ALIASES:
        return _SOURCE_LANGUAGE_ALIASES[key]
    raise ValueError(f"不支持的源语言: {value}")


def ocr_language_for_source(value: Any) -> str:
    return _OCR_LANGUAGE_MAP[normalize_source_language(value)]


def asr_language_for_source(value: Any) -> str:
    return _ASR_LANGUAGE_MAP[normalize_source_language(value)]


def youtube_language_for_source(value: Any) -> str:
    return _YOUTUBE_LANGUAGE_MAP[normalize_source_language(value)]
