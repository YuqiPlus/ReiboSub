"""Lazy, local script conversion. No application configuration or model calls."""
from __future__ import annotations

import re

from .errors import MissingDependencyError, ValidationError
from .models import Subtitle


def convert_script(subtitle: Subtitle, script: str, *, install_missing: bool = False) -> Subtitle:
    if script not in {"simplified", "traditional"}:
        raise ValidationError("script must be simplified or traditional")
    try:
        from opencc import OpenCC
    except ImportError:
        if not install_missing:
            raise MissingDependencyError("Install opencc-python-reimplemented or explicitly use install_missing=True in a venv/Conda environment") from None
        from .dependencies import ensure_feature
        ensure_feature("core", install=True)
        from opencc import OpenCC
    converter = OpenCC("t2s" if script == "simplified" else "s2t")

    def transform(text: str) -> str:
        return "".join(part if index % 2 else converter.convert(part)
                       for index, part in enumerate(re.split(r"(<[^>]*>|\{\\[^}]*\})", text)))

    return subtitle.map_text(transform)
