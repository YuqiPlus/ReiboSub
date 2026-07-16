from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


BBox = tuple[float, float, float, float]
Point = tuple[float, float]
Polygon = tuple[Point, ...]


class TrackKind(str, Enum):
    MAIN_SUBTITLE = "main_subtitle"
    SECONDARY_CAPTION = "secondary_caption"
    PERSISTENT_OVERLAY = "persistent_overlay"
    SCENE_TEXT = "scene_text"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class OCRBox:
    text: str
    bbox: BBox
    confidence: float
    time: float
    frame_index: int
    region: str = "unknown"
    polygon: Polygon | None = None
    angle_degrees: float | None = None
    shape_hint: str | None = None
    shape_limit_degrees: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "text": self.text,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "time": self.time,
            "frame_index": self.frame_index,
            "region": self.region,
        }
        # Geometry is opt-in so OCR 1.0/2.0 JSON remains byte-for-byte compatible
        # at the schema level. OCR 3.0 populates these fields from PaddleOCR's
        # original quadrilateral.
        if self.polygon is not None:
            data["polygon"] = [list(point) for point in self.polygon]
        if self.angle_degrees is not None:
            data["angle_degrees"] = self.angle_degrees
        if self.shape_hint is not None:
            data["shape_hint"] = self.shape_hint
        if self.shape_limit_degrees is not None:
            data["shape_limit_degrees"] = self.shape_limit_degrees
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OCRBox":
        raw_polygon = data.get("polygon")
        polygon: Polygon | None = None
        if isinstance(raw_polygon, (list, tuple)):
            points: list[Point] = []
            for raw_point in raw_polygon:
                if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                    continue
                points.append((float(raw_point[0]), float(raw_point[1])))
            if points:
                polygon = tuple(points)
        raw_angle = data.get("angle_degrees")
        raw_shape_limit = data.get("shape_limit_degrees")
        return cls(
            text=str(data["text"]),
            bbox=tuple(float(v) for v in data["bbox"]),  # type: ignore[arg-type]
            confidence=float(data.get("confidence", 0.0)),
            time=float(data["time"]),
            frame_index=int(data.get("frame_index", 0)),
            region=str(data.get("region", "unknown")),
            polygon=polygon,
            angle_degrees=float(raw_angle) if raw_angle is not None else None,
            shape_hint=str(data.get("shape_hint")) if data.get("shape_hint") is not None else None,
            shape_limit_degrees=float(raw_shape_limit) if raw_shape_limit is not None else None,
        )


@dataclass(slots=True)
class TextTrack:
    id: int
    text: str
    start: float
    end: float
    boxes: list[OCRBox] = field(default_factory=list)
    kind: TrackKind = TrackKind.UNKNOWN
    reason: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def sample_count(self) -> int:
        return len(self.boxes)

    @property
    def average_confidence(self) -> float:
        if not self.boxes:
            return 0.0
        return sum(box.confidence for box in self.boxes) / len(self.boxes)

    @property
    def average_bbox(self) -> BBox:
        if not self.boxes:
            return (0.0, 0.0, 0.0, 0.0)
        count = len(self.boxes)
        return tuple(sum(box.bbox[i] for box in self.boxes) / count for i in range(4))  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "kind": self.kind.value,
            "reason": self.reason,
            "average_confidence": self.average_confidence,
            "average_bbox": list(self.average_bbox),
            "boxes": [box.to_dict() for box in self.boxes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextTrack":
        return cls(
            id=int(data["id"]),
            text=str(data["text"]),
            start=float(data["start"]),
            end=float(data["end"]),
            boxes=[OCRBox.from_dict(item) for item in data.get("boxes", [])],
            kind=TrackKind(str(data.get("kind", TrackKind.UNKNOWN.value))),
            reason=str(data.get("reason", "")),
        )


@dataclass(slots=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str
    source_track_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "source_track_id": self.source_track_id,
        }
