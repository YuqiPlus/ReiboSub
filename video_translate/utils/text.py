from __future__ import annotations

import re
from difflib import SequenceMatcher


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。！？、,.!?~…·・:：;；'\"“”‘’()\[\]{}<>《》「」『』]")


def normalize_ocr_text(text: str) -> str:
    text = text.strip()
    text = _SPACE_RE.sub(" ", text)
    return text


def comparable_text(text: str) -> str:
    text = normalize_ocr_text(text).lower()
    text = _PUNCT_RE.sub("", text)
    return text.replace(" ", "")


def text_similarity(left: str, right: str) -> float:
    left_key = comparable_text(left)
    right_key = comparable_text(right)
    if not left_key or not right_key:
        return 0.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def choose_best_text(texts: list[str]) -> str:
    if not texts:
        return ""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for text in texts:
        normalized = comparable_text(text)
        counts[normalized] = counts.get(normalized, 0) + 1
        display.setdefault(normalized, normalize_ocr_text(text))
    best_key = max(counts, key=counts.get)
    return display[best_key]
