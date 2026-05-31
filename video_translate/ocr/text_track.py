from __future__ import annotations

from collections import defaultdict

from video_translate.models import OCRBox, TextTrack
from video_translate.utils.text import choose_best_text, normalize_ocr_text, text_similarity


def build_text_tracks(
    boxes: list[OCRBox],
    *,
    max_gap_seconds: float = 0.85,
    text_similarity_threshold: float = 0.82,
    vertical_tolerance: float = 56.0,
) -> list[TextTrack]:
    sorted_boxes = sorted(boxes, key=lambda box: (box.time, box.bbox[1], box.bbox[0]))
    active: list[TextTrack] = []
    finished: list[TextTrack] = []
    next_id = 1

    for box in sorted_boxes:
        text = normalize_ocr_text(box.text)
        if not text:
            continue

        match = _find_matching_track(
            active,
            box,
            text,
            max_gap_seconds=max_gap_seconds,
            text_similarity_threshold=text_similarity_threshold,
            vertical_tolerance=vertical_tolerance,
        )
        if match is None:
            track = TextTrack(id=next_id, text=text, start=box.time, end=box.time, boxes=[box])
            next_id += 1
            active.append(track)
        else:
            match.boxes.append(box)
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
    return _deduplicate_tracks(finished)


def _find_matching_track(
    tracks: list[TextTrack],
    box: OCRBox,
    text: str,
    *,
    max_gap_seconds: float,
    text_similarity_threshold: float,
    vertical_tolerance: float,
) -> TextTrack | None:
    best_track: TextTrack | None = None
    best_score = 0.0
    box_center_y = (box.bbox[1] + box.bbox[3]) / 2

    for track in tracks:
        if box.time - track.end > max_gap_seconds:
            continue
        track_bbox = track.average_bbox
        track_center_y = (track_bbox[1] + track_bbox[3]) / 2
        if abs(track_center_y - box_center_y) > vertical_tolerance:
            continue
        score = text_similarity(track.text, text)
        if score >= text_similarity_threshold and score > best_score:
            best_track = track
            best_score = score

    return best_track


def _deduplicate_tracks(tracks: list[TextTrack]) -> list[TextTrack]:
    grouped: dict[tuple[str, int, int], list[TextTrack]] = defaultdict(list)
    for track in tracks:
        bbox = track.average_bbox
        key = (normalize_ocr_text(track.text), round(bbox[0] / 20), round(bbox[1] / 20))
        grouped[key].append(track)

    merged: list[TextTrack] = []
    for candidates in grouped.values():
        base = candidates[0]
        for extra in candidates[1:]:
            if extra.start - base.end <= 0.35 or base.start - extra.end <= 0.35:
                base.start = min(base.start, extra.start)
                base.end = max(base.end, extra.end)
                base.boxes.extend(extra.boxes)
                base.text = choose_best_text([box.text for box in base.boxes])
            else:
                merged.append(extra)
        merged.append(base)

    merged.sort(key=lambda track: (track.start, track.end))
    for new_id, track in enumerate(merged, start=1):
        track.id = new_id
    return merged
