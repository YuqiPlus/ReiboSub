from __future__ import annotations

import json
import csv
from pathlib import Path
from dataclasses import dataclass

from video_translate.models import OCRBox, SubtitleCue, TextTrack, TrackKind
from video_translate.ocr.classifier import ClassificationConfig, classify_tracks
from video_translate.ocr.extractor import ExtractConfig, extract_video_ocr
from video_translate.ocr.text_track import build_text_tracks
from video_translate.subtitle.srt import write_srt
from video_translate.utils.text import text_similarity


@dataclass(slots=True)
class CueTimingConfig:
    merge_gap_seconds: float = 0.85
    end_padding_seconds: float = 0.35
    min_duration_seconds: float = 0.60
    same_text_similarity: float = 0.88
    max_next_overlap_seconds: float = 0.04
    enforce_no_overlap: bool = True
    merge_same_start_seconds: float = 0.16
    merge_short_fragment_gap_seconds: float = 0.50
    short_fragment_max_chars: int = 14
    short_fragment_similarity: float = 0.55


def extract_subtitles_from_video(
    video_path: Path,
    out_dir: Path,
    *,
    lang: str,
    sample_fps: float = 3.0,
    bottom_ratio: float = 0.42,
    scan_full_frame: bool = False,
    device: str = "auto",
    ignored_texts: list[str] | None = None,
    ignored_contains: list[str] | None = None,
    ignored_patterns: list[str] | None = None,
    cue_timing: CueTimingConfig | None = None,
) -> dict[str, Path]:
    boxes = extract_video_ocr(
        video_path,
        lang=lang,
        config=ExtractConfig(
            sample_fps=sample_fps,
            bottom_ratio=bottom_ratio,
            scan_full_frame=scan_full_frame,
            device=device,
        ),
    )
    tracks = build_text_tracks(boxes)
    classify_tracks(
        tracks,
        ClassificationConfig(
            video_duration=_video_duration_hint(boxes),
            ignored_texts=tuple(ignored_texts or []),
            ignored_contains=tuple(ignored_contains or []),
            ignored_patterns=tuple(ignored_patterns or []),
        ),
    )
    return write_extraction_outputs(tracks, out_dir, cue_timing=cue_timing)


def merge_ocr_samples(
    ocr_json_path: Path,
    out_dir: Path,
    video_duration: float | None = None,
    ignored_texts: list[str] | None = None,
    ignored_contains: list[str] | None = None,
    ignored_patterns: list[str] | None = None,
    cue_timing: CueTimingConfig | None = None,
) -> dict[str, Path]:
    raw = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    boxes = [OCRBox.from_dict(item) for item in raw]
    tracks = build_text_tracks(boxes)
    classify_tracks(
        tracks,
        ClassificationConfig(
            video_duration=video_duration,
            ignored_texts=tuple(ignored_texts or []),
            ignored_contains=tuple(ignored_contains or []),
            ignored_patterns=tuple(ignored_patterns or []),
        ),
    )
    return write_extraction_outputs(tracks, out_dir, cue_timing=cue_timing)


def reprocess_tracks_json(
    tracks_json_path: Path,
    out_dir: Path,
    video_duration: float | None = None,
    ignored_texts: list[str] | None = None,
    ignored_contains: list[str] | None = None,
    ignored_patterns: list[str] | None = None,
    cue_timing: CueTimingConfig | None = None,
) -> dict[str, Path]:
    raw = json.loads(tracks_json_path.read_text(encoding="utf-8"))
    tracks = [TextTrack.from_dict(item) for item in raw]
    classify_tracks(
        tracks,
        ClassificationConfig(
            video_duration=video_duration or _tracks_duration_hint(tracks),
            ignored_texts=tuple(ignored_texts or []),
            ignored_contains=tuple(ignored_contains or []),
            ignored_patterns=tuple(ignored_patterns or []),
        ),
    )
    return write_extraction_outputs(tracks, out_dir, cue_timing=cue_timing)


def write_extraction_outputs(
    tracks: list[TextTrack],
    out_dir: Path,
    *,
    cue_timing: CueTimingConfig | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    main_tracks = [track for track in tracks if track.kind == TrackKind.MAIN_SUBTITLE]
    ignored_tracks = [track for track in tracks if track.kind == TrackKind.PERSISTENT_OVERLAY]
    cues = _tracks_to_cues(main_tracks, cue_timing or CueTimingConfig())

    tracks_path = out_dir / "tracks.json"
    debug_csv_path = out_dir / "tracks_debug.csv"
    ignored_path = out_dir / "ignored_tracks.json"
    source_srt_path = out_dir / "source.srt"

    tracks_path.write_text(
        json.dumps([track.to_dict() for track in tracks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ignored_path.write_text(
        json.dumps([track.to_dict() for track in ignored_tracks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_tracks_debug_csv(tracks, debug_csv_path)
    write_srt(cues, source_srt_path)

    return {
        "tracks": tracks_path,
        "tracks_debug": debug_csv_path,
        "ignored_tracks": ignored_path,
        "source_srt": source_srt_path,
    }


def _video_duration_hint(boxes: list[OCRBox]) -> float | None:
    if not boxes:
        return None
    return max(box.time for box in boxes)


def _tracks_duration_hint(tracks: list[TextTrack]) -> float | None:
    if not tracks:
        return None
    return max(track.end for track in tracks)


def _tracks_to_cues(tracks: list[TextTrack], timing: CueTimingConfig) -> list[SubtitleCue]:
    grouped: list[list[TextTrack]] = []
    for track in sorted(tracks, key=lambda item: (item.start, item.end, item.average_bbox[1], item.average_bbox[0])):
        placed = False
        for group in grouped:
            if _belongs_to_cue_group(track, group):
                group.append(track)
                placed = True
                break
        if not placed:
            grouped.append([track])

    raw_cues: list[SubtitleCue] = []
    for index, group in enumerate(grouped, start=1):
        text = _merge_group_text(group)
        start = min(track.start for track in group)
        end = max(track.end for track in group)
        raw_cues.append(
            SubtitleCue(
                index=index,
                start=start,
                end=max(end, start + 0.35),
                text=text,
                source_track_id=group[0].id,
            )
        )
    return _retime_cues(_merge_adjacent_cues(raw_cues, timing), timing)


def _belongs_to_cue_group(track: TextTrack, group: list[TextTrack]) -> bool:
    start = min(item.start for item in group)
    end = max(item.end for item in group)
    return abs(track.start - start) <= 0.35 and abs(track.end - end) <= 0.75


def _merge_adjacent_cues(cues: list[SubtitleCue], timing: CueTimingConfig) -> list[SubtitleCue]:
    merged: list[SubtitleCue] = []
    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        if merged and _should_merge_cues(merged[-1], cue, timing):
            previous = merged[-1]
            previous.end = max(previous.end, cue.end)
            previous.text = _merge_cue_text(previous.text, cue.text)
            continue
        merged.append(cue)

    for index, cue in enumerate(merged, start=1):
        cue.index = index
    return merged


def _should_merge_cues(left: SubtitleCue, right: SubtitleCue, timing: CueTimingConfig) -> bool:
    if abs(right.start - left.start) <= timing.merge_same_start_seconds and left.end >= right.start:
        return True
    gap = right.start - left.end
    if gap < -0.10 or gap > timing.merge_gap_seconds:
        return False
    left_text = _single_line_text(left.text)
    right_text = _single_line_text(right.text)
    if left_text == right_text:
        return True
    if text_similarity(left_text, right_text) >= timing.same_text_similarity:
        return True
    return gap <= timing.merge_short_fragment_gap_seconds and _short_fragment_related(left_text, right_text, timing)


def _merge_cue_text(left: str, right: str) -> str:
    if _single_line_text(left) == _single_line_text(right):
        return left
    if text_similarity(_single_line_text(left), _single_line_text(right)) >= 0.96:
        return left if len(left) >= len(right) else right
    pieces = _remove_contained_texts(
        [line.strip() for line in left.splitlines() if line.strip()]
        + [line.strip() for line in right.splitlines() if line.strip()]
    )
    if len(pieces) > 1:
        best = max(pieces, key=len)
        if any(_short_fragment_related(best, piece, CueTimingConfig()) for piece in pieces if piece != best):
            return best
    return "\n".join(pieces)


def _short_fragment_related(left: str, right: str, timing: CueTimingConfig) -> bool:
    left_key = _compact_text(left)
    right_key = _compact_text(right)
    if not left_key or not right_key:
        return False
    shorter, longer = sorted([left_key, right_key], key=len)
    if len(shorter) > timing.short_fragment_max_chars:
        return False
    if shorter in longer:
        return True
    return text_similarity(left_key, right_key) >= timing.short_fragment_similarity


def _compact_text(text: str) -> str:
    return "".join(_single_line_text(text).split()).lower()


def _retime_cues(cues: list[SubtitleCue], timing: CueTimingConfig) -> list[SubtitleCue]:
    for index, cue in enumerate(cues):
        padded_end = max(cue.end + timing.end_padding_seconds, cue.start + timing.min_duration_seconds)
        if index + 1 < len(cues):
            next_start = cues[index + 1].start
            if timing.enforce_no_overlap:
                padded_end = min(padded_end, next_start - timing.max_next_overlap_seconds)
            else:
                padded_end = min(padded_end, max(cue.end, next_start - timing.max_next_overlap_seconds))
        cue.end = max(padded_end, cue.start + 0.12)
        if index + 1 < len(cues) and timing.enforce_no_overlap:
            cue.end = min(cue.end, max(cue.start + 0.12, cues[index + 1].start - timing.max_next_overlap_seconds))
        cue.index = index + 1
    return cues


def _single_line_text(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _dedupe_texts(texts: list[str]) -> list[str]:
    result: list[str] = []
    for text in texts:
        stripped = text.strip()
        if stripped and stripped not in result:
            result.append(stripped)
    return result


def _merge_group_text(group: list[TextTrack]) -> str:
    rows: list[list[TextTrack]] = []
    for track in sorted(group, key=lambda item: (_bbox_center_y(item), item.average_bbox[0])):
        for row in rows:
            if abs(_bbox_center_y(track) - _row_center_y(row)) <= 42:
                row.append(track)
                break
        else:
            rows.append([track])

    lines: list[str] = []
    for row in sorted(rows, key=_row_center_y):
        ordered = sorted(row, key=lambda item: item.average_bbox[0])
        pieces = _remove_contained_texts([track.text for track in ordered])
        line = _join_text_fragments(pieces)
        if line:
            lines.append(line)
    return "\n".join(_dedupe_texts(lines))


def _remove_contained_texts(texts: list[str]) -> list[str]:
    result: list[str] = []
    for text in _dedupe_texts(texts):
        stripped = text.strip()
        if not stripped:
            continue
        if any(stripped != other and stripped in other for other in texts):
            continue
        result.append(stripped)
    return result


def _join_text_fragments(texts: list[str]) -> str:
    joined = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if not joined:
            joined = text
        elif _needs_space(joined, text):
            joined = f"{joined} {text}"
        else:
            joined = f"{joined}{text}"
    return joined


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left[-1] in "([{\"'“‘《「『":
        return False
    if right[0] in ")]}\"'”’。，、！？!?；;：:,.》」』":
        return False
    # Hangul and latin words need a separator more often than CJK text.
    return bool(
        _is_hangul_or_latin(left[-1])
        or _is_hangul_or_latin(right[0])
        or left[-1].isdigit()
        or right[0].isdigit()
    )


def _is_hangul_or_latin(char: str) -> bool:
    return ("A" <= char <= "Z") or ("a" <= char <= "z") or ("\uac00" <= char <= "\ud7af")


def _bbox_center_y(track: TextTrack) -> float:
    bbox = track.average_bbox
    return (bbox[1] + bbox[3]) / 2


def _row_center_y(row: list[TextTrack]) -> float:
    return sum(_bbox_center_y(track) for track in row) / len(row)


def _write_tracks_debug_csv(tracks: list[TextTrack], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "kind",
                "reason",
                "start",
                "end",
                "duration",
                "confidence",
                "x1",
                "y1",
                "x2",
                "y2",
                "text",
            ]
        )
        for track in sorted(tracks, key=lambda item: (item.start, item.end, item.id)):
            bbox = track.average_bbox
            writer.writerow(
                [
                    track.id,
                    track.kind.value,
                    track.reason,
                    f"{track.start:.3f}",
                    f"{track.end:.3f}",
                    f"{track.duration:.3f}",
                    f"{track.average_confidence:.3f}",
                    f"{bbox[0]:.1f}",
                    f"{bbox[1]:.1f}",
                    f"{bbox[2]:.1f}",
                    f"{bbox[3]:.1f}",
                    track.text,
                ]
            )
