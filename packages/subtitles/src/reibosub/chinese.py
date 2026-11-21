"""Lazy, local script conversion. No application configuration or model calls."""
from __future__ import annotations

import re
from functools import lru_cache

from .errors import MissingDependencyError, ValidationError
from .models import Subtitle


@lru_cache(maxsize=2)
def _converter(script: str):
    from opencc import OpenCC
    return OpenCC("t2s" if script == "simplified" else "s2t")


def convert_text(text: str, script: str, *, install_missing: bool = False) -> str:
    """Convert plain/marked-up text without altering inline subtitle tags."""
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    if script not in {"simplified", "traditional"}:
        raise ValidationError("script must be simplified or traditional")
    try:
        converter = _converter(script)
    except ImportError:
        if not install_missing:
            raise MissingDependencyError("Install opencc-python-reimplemented or explicitly use install_missing=True in a venv/Conda environment") from None
        from .dependencies import ensure_feature
        ensure_feature("core", install=True)
        converter = _converter(script)
    return "".join(part if index % 2 else converter.convert(part)
                   for index, part in enumerate(re.split(r"(<[^>]*>|\{\\[^}]*\})", text)))


def convert_script(subtitle: Subtitle, script: str, *, install_missing: bool = False) -> Subtitle:
    convert_text("", script, install_missing=install_missing)
    return subtitle.map_text(lambda text: convert_text(text, script, install_missing=install_missing))
