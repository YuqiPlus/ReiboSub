from __future__ import annotations

import re
from dataclasses import dataclass

from video_translate.models import TextTrack, TrackKind
from video_translate.utils.text import comparable_text


_LETTER_RE = re.compile(r"[\u3040-\u30ff\u3130-\u318f\uac00-\ud7af\u4e00-\u9fffA-Za-z]")
_CJK_OR_HANGUL_RE = re.compile(r"[\u3040-\u30ff\u3130-\u318f\uac00-\ud7af\u4e00-\u9fff]")


@dataclass(slots=True)
class ClassificationConfig:
    video_duration: float | None = None
    persistent_min_seconds: float = 30.0
    persistent_duration_ratio: float = 0.20
    stable_position_tolerance: float = 24.0
    grouped_stable_position_tolerance: float = 120.0
    bottom_region_threshold: float = 0.52
    min_main_subtitle_confidence: float = 0.45
    min_subtitle_duration: float = 0.45


def classify_tracks(tracks: list[TextTrack], config: ClassificationConfig | None = None) -> list[TextTrack]:
    config = config or ClassificationConfig()
    for track in tracks:
        track.kind, track.reason = classify_track(track, config)
    _mark_grouped_persistent_overlays(tracks, config)
    _mark_short_noise(tracks, config)
    return tracks


def classify_track(track: TextTrack, config: ClassificationConfig) -> tuple[TrackKind, str]:
    if _is_short_noise(track, config):
        return TrackKind.UNKNOWN, "short_junk_text"

    if _is_persistent_overlay(track, config):
        return TrackKind.PERSISTENT_OVERLAY, "long_duration_stable_position"

    bbox = track.average_bbox
    center_y = (bbox[1] + bbox[3]) / 2
    frame_height = _estimate_frame_height(track)
    normalized_center_y = center_y / frame_height if frame_height else 0.0

    if (
        normalized_center_y >= config.bottom_region_threshold
        and track.average_confidence >= config.min_main_subtitle_confidence
    ):
        return TrackKind.MAIN_SUBTITLE, "bottom_region_temporal_track"

    if track.sample_count >= 2 and track.duration < config.persistent_min_seconds:
        return TrackKind.SECONDARY_CAPTION, "non_bottom_short_lived_text"

    return TrackKind.UNKNOWN, "low_evidence"


def _mark_grouped_persistent_overlays(tracks: list[TextTrack], config: ClassificationConfig) -> None:
    groups: dict[str, list[TextTrack]] = {}
    for track in tracks:
        key = comparable_text(track.text)
        if len(key) < 3:
            continue
        groups.setdefault(key, []).append(track)

    for candidates in groups.values():
        total_duration = sum(track.duration for track in candidates)
        duration_ratio = 0.0
        if config.video_duration and config.video_duration > 0:
            duration_ratio = total_duration / config.video_duration
        if total_duration < config.persistent_min_seconds and duration_ratio < config.persistent_duration_ratio:
            continue
        if not _group_position_is_stable(candidates, config.grouped_stable_position_tolerance):
            continue
        for track in candidates:
            track.kind = TrackKind.PERSISTENT_OVERLAY
            track.reason = "repeated_text_stable_position"


def _mark_short_noise(tracks: list[TextTrack], config: ClassificationConfig) -> None:
    for track in tracks:
        if _is_short_noise(track, config):
            track.kind = TrackKind.UNKNOWN
            track.reason = "short_junk_text"


def _is_short_noise(track: TextTrack, config: ClassificationConfig) -> bool:
    key = comparable_text(track.text)
    if not key:
        return True
    if track.duration > config.min_subtitle_duration or track.sample_count > 2:
        return False
    if len(key) <= 2:
        return True
    has_letter = bool(_LETTER_RE.search(track.text))
    has_cjk_or_hangul = bool(_CJK_OR_HANGUL_RE.search(track.text))
    if not has_letter:
        return True
    if not has_cjk_or_hangul and len(key) <= 4:
        return True
    return False


def _is_persistent_overlay(track: TextTrack, config: ClassificationConfig) -> bool:
    duration_ratio = 0.0
    if config.video_duration and config.video_duration > 0:
        duration_ratio = track.duration / config.video_duration
    is_long = track.duration >= config.persistent_min_seconds or duration_ratio >= config.persistent_duration_ratio
    return is_long and _position_is_stable(track, config.stable_position_tolerance)


def _position_is_stable(track: TextTrack, tolerance: float) -> bool:
    if len(track.boxes) < 2:
        return False
    avg = track.average_bbox
    max_delta = 0.0
    for box in track.boxes:
        max_delta = max(max_delta, max(abs(box.bbox[i] - avg[i]) for i in range(4)))
    return max_delta <= tolerance


def _group_position_is_stable(tracks: list[TextTrack], tolerance: float) -> bool:
    if len(tracks) <= 1:
        return _position_is_stable(tracks[0], tolerance) if tracks else False
    centers = []
    for track in tracks:
        bbox = track.average_bbox
        centers.append(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
    avg_x = sum(center[0] for center in centers) / len(centers)
    avg_y = sum(center[1] for center in centers) / len(centers)
    return all(abs(x - avg_x) <= tolerance and abs(y - avg_y) <= tolerance for x, y in centers)


def _estimate_frame_height(track: TextTrack) -> float:
    max_y = max((box.bbox[3] for box in track.boxes), default=1080.0)
    if max_y <= 720:
        return 720.0
    if max_y <= 1080:
        return 1080.0
    if max_y <= 1440:
        return 1440.0
    return 2160.0
