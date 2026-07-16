from __future__ import annotations

import math

from video_translate.models import OCRBox, TextTrack
from video_translate.utils.text import choose_best_text, normalize_ocr_text, text_similarity


def build_geometry_text_tracks(
    boxes: list[OCRBox],
    *,
    max_gap_seconds: float = 0.85,
    text_similarity_threshold: float = 0.68,
    max_center_distance_heights: float = 5.0,
    max_size_ratio: float = 2.5,
) -> list[TextTrack]:
    """Build OCR 3.0 tracks without merging equal text at different x positions.

    OCR 1.0/2.0 intentionally keep using ``build_text_tracks``. This matcher
    adds a same-frame exclusivity rule and follows the latest quadrilateral,
    which lets moving object text remain one track while two equal captions on
    opposite sides of a frame remain distinct geometry evidence.
    """

    ordered = sorted(boxes, key=lambda box: (box.time, box.frame_index, box.bbox[1], box.bbox[0]))
    active: list[TextTrack] = []
    finished: list[TextTrack] = []
    next_id = 1

    for box in ordered:
        text = normalize_ocr_text(box.text)
        if not text:
            continue
        match = _find_geometry_match(
            active,
            box,
            text,
            max_gap_seconds=max_gap_seconds,
            text_similarity_threshold=text_similarity_threshold,
            max_center_distance_heights=max_center_distance_heights,
            max_size_ratio=max_size_ratio,
        )
        if match is None:
            match = TextTrack(id=next_id, text=text, start=box.time, end=box.time, boxes=[])
            next_id += 1
            active.append(match)
        match.boxes.append(box)
        match.start = min(match.start, box.time)
        match.end = max(match.end, box.time)
        match.text = choose_best_text([sample.text for sample in match.boxes])

        still_active: list[TextTrack] = []
        for track in active:
            if box.time - track.end > max_gap_seconds:
                finished.append(track)
            else:
                still_active.append(track)
        active = still_active

    finished.extend(active)
    finished.sort(key=lambda track: (track.start, track.end, track.average_bbox[1], track.average_bbox[0]))
    for track_id, track in enumerate(finished, start=1):
        track.id = track_id
    return finished


def _find_geometry_match(
    tracks: list[TextTrack],
    box: OCRBox,
    text: str,
    *,
    max_gap_seconds: float,
    text_similarity_threshold: float,
    max_center_distance_heights: float,
    max_size_ratio: float,
) -> TextTrack | None:
    best: TextTrack | None = None
    best_score = float("-inf")
    for track in tracks:
        gap = box.time - track.end
        if gap > max_gap_seconds:
            continue
        # The same recognized word can appear twice in one frame. It must form
        # two tracks, otherwise the downstream motion statistic is fabricated.
        if any(sample.frame_index == box.frame_index for sample in track.boxes):
            continue
        similarity = text_similarity(track.text, text)
        if similarity < text_similarity_threshold:
            continue
        previous = max(track.boxes, key=lambda sample: (sample.time, sample.frame_index))
        previous_width, previous_height = _bbox_size(previous.bbox)
        width, height = _bbox_size(box.bbox)
        width_ratio = max(previous_width, width) / max(1.0, min(previous_width, width))
        height_ratio = max(previous_height, height) / max(1.0, min(previous_height, height))
        if max(width_ratio, height_ratio) > max_size_ratio:
            continue
        distance = _center_distance(previous.bbox, box.bbox)
        normalized_distance = distance / max(1.0, previous_height, height)
        overlap = _bbox_iou(previous.bbox, box.bbox)
        if overlap <= 0.01 and normalized_distance > max_center_distance_heights:
            continue
        score = (
            similarity * 3.0
            + min(1.0, overlap) * 1.5
            + max(0.0, 1.0 - normalized_distance / max_center_distance_heights)
            - max(0.0, gap) / max(0.001, max_gap_seconds)
        )
        if score > best_score:
            best = track
            best_score = score
    return best


def _bbox_size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return max(1.0, bbox[2] - bbox[0]), max(1.0, bbox[3] - bbox[1])


def _center_distance(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    left_x = (left[0] + left[2]) / 2
    left_y = (left[1] + left[3]) / 2
    right_x = (right[0] + right[2]) / 2
    right_y = (right[1] + right[3]) / 2
    return math.hypot(right_x - left_x, right_y - left_y)


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    intersection_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    intersection_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = intersection_width * intersection_height
    if intersection <= 0:
        return 0.0
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / max(1.0, left_area + right_area - intersection)
