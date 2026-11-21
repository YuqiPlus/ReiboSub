"""Explicit file I/O, independent of application storage/configuration."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Subtitle

if TYPE_CHECKING:
    from .formats import FormatRegistry


def load(path: str | Path, *, format: str | None = None, encoding: str = "utf-8-sig", registry: FormatRegistry | None = None) -> Subtitle:
    source = Path(path).expanduser()
    return Subtitle.loads(source.read_text(encoding=encoding), format=format or source.suffix.lstrip("."), registry=registry)


def save(subtitle: Subtitle, path: str | Path, *, format: str | None = None, encoding: str = "utf-8", overwrite: bool = False, registry: FormatRegistry | None = None) -> Path:
    destination = Path(path).expanduser()
    content = subtitle.dumps(format or destination.suffix.lstrip("."), registry=registry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, dir=destination.parent, prefix=".reibosub-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        if overwrite:
            os.replace(temporary, destination)
        else:
            # Atomic no-clobber publication, including existing/broken symlinks.
            os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def convert(source: str | Path, destination: str | Path, *, input_format: str | None = None, output_format: str | None = None, encoding: str = "utf-8-sig", overwrite: bool = False, registry: FormatRegistry | None = None) -> Path:
    return load(source, format=input_format, encoding=encoding, registry=registry).save(destination, format=output_format, overwrite=overwrite, registry=registry)
