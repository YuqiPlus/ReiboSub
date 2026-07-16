from __future__ import annotations

from video_translate.models import OCRBox
from video_translate.ocr.geometry_track import build_geometry_text_tracks


def _box(text: str, bbox, time: float, frame: int) -> OCRBox:
    return OCRBox(text, bbox, 0.95, time, frame, "full_middle", angle_degrees=0.0)


def test_geometry_tracker_keeps_equal_text_at_two_x_positions_separate() -> None:
    boxes = [
        _box("흔들", (100, 500, 220, 560), 1.0, 6),
        _box("흔들", (900, 500, 1020, 560), 1.0, 6),
        _box("흔들", (105, 502, 225, 562), 1.2, 7),
        _box("흔들", (905, 502, 1025, 562), 1.2, 7),
    ]

    tracks = build_geometry_text_tracks(boxes)

    assert len(tracks) == 2
    assert sorted(track.sample_count for track in tracks) == [2, 2]
    assert tracks[0].average_bbox[0] < 300
    assert tracks[1].average_bbox[0] > 700


def test_geometry_tracker_follows_moving_object_text_across_frames() -> None:
    boxes = [
        _box("상품명", (100, 400, 260, 470), 1.0, 6),
        _box("상품명", (150, 420, 315, 492), 1.2, 7),
        _box("상품명", (220, 450, 390, 525), 1.4, 8),
    ]

    tracks = build_geometry_text_tracks(boxes)

    assert len(tracks) == 1
    assert tracks[0].sample_count == 3
    assert tracks[0].start == 1.0
    assert tracks[0].end == 1.4
