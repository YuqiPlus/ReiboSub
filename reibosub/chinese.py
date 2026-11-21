"""Lazy, local script conversion. No application configuration or model calls."""
from __future__ import annotations

import re

from .errors import MissingDependencyError, ValidationError
from .models import Subtitle


def convert_script(subtitle: Subtitle, script: str) -> Subtitle:
    if script not in {"simplified", "traditional"}:
        raise ValidationError("script must be simplified or traditional")
    try:
        from opencc import OpenCC
    except ImportError:
        raise MissingDependencyError("Install opencc-python-reimplemented to convert Chinese scripts") from None
    converter = OpenCC("t2s" if script == "simplified" else "s2t")

    def transform(text: str) -> str:
        return "".join(part if index % 2 else converter.convert(part)
                       for index, part in enumerate(re.split(r"(<[^>]*>|\{\\[^}]*\})", text)))

    return subtitle.map_text(transform)
