"""Translation targets, distinct from OCR/ASR source-language identifiers."""
from __future__ import annotations

TARGET_LANGUAGES = {'zh': '简体中文', 'en': '英语', 'ja': '日语', 'ko': '韩语'}
_ALIASES = {
    'chinese': 'zh', '简体中文': 'zh', '中文': 'zh', 'zh-hans': 'zh', 'zh-cn': 'zh',
    'english': 'en', '英语': 'en', '英文': 'en',
    'japanese': 'ja', '日语': 'ja', '日文': 'ja',
    'korean': 'ko', '韩语': 'ko', '韩文': 'ko',
}


def target_language_code(value=None) -> str:
    raw = str(value or 'zh').strip().lower().replace('_', '-')
    code = _ALIASES.get(raw, raw)
    if code not in TARGET_LANGUAGES:
        raise ValueError('目标语言须选择中文、英语、日语或韩语')
    return code


def target_language_name(value=None) -> str:
    return TARGET_LANGUAGES[target_language_code(value)]


def default_translation_target(url: str) -> str:
    from video_translate.video_source import video_platform
    return 'en' if video_platform(url) == 'bilibili' else 'zh'
