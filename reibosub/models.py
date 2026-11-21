"""Immutable, engine-independent public subtitle data structures."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, overload

from .errors import ValidationError

if TYPE_CHECKING:
    from .formats import FormatRegistry


@dataclass(frozen=True, slots=True)
class Cue:
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 1:
            raise ValidationError("cue index must be a positive integer")
        for key in ("start", "end"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValidationError(f"cue {key} must be finite seconds")
            object.__setattr__(self, key, float(value))
        if self.start < 0 or self.end <= self.start:
            raise ValidationError("cue timing requires 0 <= start < end")
        if not isinstance(self.text, str) or (self.speaker is not None and not isinstance(self.speaker, str)):
            raise ValidationError("cue text and optional speaker must be strings")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
                raise ValidationError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        value = {"index": self.index, "start": self.start, "end": self.end, "text": self.text}
        if self.speaker is not None:
            value["speaker"] = self.speaker
        if self.confidence is not None:
            value["confidence"] = self.confidence
        return value


@dataclass(frozen=True, slots=True)
class SubtitleIssue:
    code: str
    message: str
    cue_indexes: tuple[int, ...]
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class Progress:
    completed: int
    total: int
    stage: str = "translation"


@dataclass(frozen=True, slots=True)
class Subtitle:
    cues: tuple[Cue, ...]
    language: str | None = None
    source_format: str | None = None
    notices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cues", tuple(self.cues))
        object.__setattr__(self, "notices", tuple(self.notices))
        if any(not isinstance(cue, Cue) for cue in self.cues):
            raise ValidationError("cues must contain Cue objects")
        if len({cue.index for cue in self.cues}) != len(self.cues):
            raise ValidationError("cue indexes must be unique")
        if self.language is not None and not isinstance(self.language, str):
            raise ValidationError("language must be a string or None")
        if self.source_format is not None and not isinstance(self.source_format, str):
            raise ValidationError("source_format must be a string or None")
        if any(not isinstance(notice, str) for notice in self.notices):
            raise ValidationError("notices must contain strings")

    def __iter__(self) -> Iterator[Cue]:
        return iter(self.cues)

    def __len__(self) -> int:
        return len(self.cues)

    @overload
    def __getitem__(self, key: int) -> Cue: ...

    @overload
    def __getitem__(self, key: slice) -> tuple[Cue, ...]: ...

    def __getitem__(self, key: int | slice) -> Cue | tuple[Cue, ...]:
        return self.cues[key]

    @classmethod
    def load(cls, path: str | Path, *, format: str | None = None, encoding: str = "utf-8-sig", registry: FormatRegistry | None = None) -> Subtitle:
        from .io import load
        return load(path, format=format, encoding=encoding, registry=registry)

    @classmethod
    def loads(cls, text: str, *, format: str = "srt", registry: FormatRegistry | None = None) -> Subtitle:
        from .formats import default_registry
        return (registry if registry is not None else default_registry()).loads(text, format)

    def dumps(self, format: str = "srt", *, registry: FormatRegistry | None = None) -> str:
        from .formats import default_registry
        return (registry if registry is not None else default_registry()).dumps(self, format)

    def save(self, path: str | Path, *, format: str | None = None, encoding: str = "utf-8", overwrite: bool = False, registry: FormatRegistry | None = None) -> Path:
        from .io import save
        return save(self, path, format=format, encoding=encoding, overwrite=overwrite, registry=registry)

    def map_text(self, transform: Callable[[str], str]) -> Subtitle:
        return replace(self, cues=tuple(replace(cue, text=transform(cue.text)) for cue in self))

    def to_simplified(self) -> Subtitle:
        from .chinese import convert_script
        return convert_script(self, "simplified")

    def to_traditional(self) -> Subtitle:
        from .chinese import convert_script
        return convert_script(self, "traditional")

    def to_text(self, *, timestamps: bool = False) -> str:
        from .formats import format_time
        return "\n".join((f"[{format_time(cue.start)} --> {format_time(cue.end)}] " if timestamps else "") + cue.text for cue in self)

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "language": self.language, "cues": [cue.to_dict() for cue in self]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subtitle:
        if not isinstance(data, dict) or type(data.get("version", 1)) is not int or data.get("version", 1) != 1 or not isinstance(data.get("cues"), list):
            raise ValidationError("expected version 1 subtitle data with a cues array")
        cues = []
        for index, row in enumerate(data["cues"], 1):
            if not isinstance(row, dict):
                raise ValidationError("every cue must be an object")
            try:
                cues.append(Cue(index=row.get("index", index), start=row["start"], end=row["end"], text=row["text"], speaker=row.get("speaker"), confidence=row.get("confidence")))
            except KeyError as exc:
                raise ValidationError(f"missing cue field: {exc.args[0]}") from None
        return cls(tuple(cues), language=data.get("language"))

    def check(self) -> tuple[SubtitleIssue, ...]:
        issues = []
        for cue in self:
            if not cue.text.strip():
                issues.append(SubtitleIssue("empty_text", "Subtitle text is empty", (cue.index,)))
        for previous, current in zip(self.cues, self.cues[1:]):
            if current.start < previous.start:
                issues.append(SubtitleIssue("non_monotonic", "Cue order is not chronological", (previous.index, current.index)))
        latest = None
        for cue in sorted(self, key=lambda item: item.start):
            if latest is not None and cue.start < latest.end:
                issues.append(SubtitleIssue("overlap", "Subtitle intervals overlap", (latest.index, cue.index)))
            if latest is None or cue.end > latest.end:
                latest = cue
        return tuple(issues)
