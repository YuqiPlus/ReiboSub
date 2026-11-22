"""Runtime-independent recognition contracts. Importing never loads a model."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .errors import OperationCancelled, ValidationError
from .models import Progress, Subtitle

ProgressCallback = Callable[[Progress], None]
CancelCheck = Callable[[], bool]


def check_cancelled(cancelled: CancelCheck | None) -> None:
    if cancelled is not None and cancelled():
        raise OperationCancelled("Recognition cancelled")


def local_file(source: str | Path) -> Path:
    if not isinstance(source, (str, Path)):
        raise ValidationError("source must be a local file path")
    path = Path(source).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def path_option(value: str | Path | None, name: str) -> Path | None:
    """Anchor an optional model/cache path without creating or accessing it."""
    if value is None:
        return None
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValidationError(f"{name} must be a non-empty path or None")
    return Path(value).expanduser().absolute()


def finite(value: float, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValidationError(f"{name} must be a finite number >= {minimum}")
    return float(value)


@dataclass(frozen=True, slots=True)
class TextRegion:
    """An image text polygon, in pixels in the input image coordinate system."""

    text: str
    confidence: float
    polygon: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValidationError("region text must be a string")
        score = finite(self.confidence, "confidence")
        if score > 1:
            raise ValidationError("confidence must be <= 1")
        try:
            points = tuple(tuple(point) for point in self.polygon)
        except TypeError:
            raise ValidationError("polygon must contain at least three (x, y) points") from None
        if len(points) < 3 or any(len(point) != 2 for point in points):
            raise ValidationError("polygon must contain at least three (x, y) points")
        points = tuple((finite(x, "polygon x"), finite(y, "polygon y")) for x, y in points)
        object.__setattr__(self, "confidence", score)
        object.__setattr__(self, "polygon", points)


class ASRBackend(Protocol):
    """A local or remote implementation; authentication belongs to its caller."""

    def transcribe(
        self, source: Path, *, language: str | None,
        on_progress: ProgressCallback | None, cancelled: CancelCheck | None,
    ) -> Subtitle: ...


class OCRBackend(Protocol):
    """Accept a local image path or a BGR ndarray; return pixel polygons."""

    def recognize(self, image: Any) -> tuple[TextRegion, ...]: ...
