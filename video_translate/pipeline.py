from __future__ import annotations

import json
import csv
from pathlib import Path

from video_translate.models import OCRBox, SubtitleCue, TextTrack, TrackKind
from video_translate.ocr.classifier import ClassificationConfig, classify_tracks
from video_translate.ocr.extractor import ExtractConfig, extract_video_ocr
from video_translate.ocr.text_track import build_text_tracks
from video_translate.subtitle.srt import write_srt


def extract_subtitles_from_video(
    video_path: Path,
    out_dir: Path,
    *,
    lang: str,
    sample_fps: float = 3.0,
    bottom_ratio: float = 0.42,
    scan_full_frame: bool = False,
    device: str = "auto",
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
    classify_tracks(tracks, ClassificationConfig(video_duration=_video_duration_hint(boxes)))
    return write_extraction_outputs(tracks, out_dir)


def merge_ocr_samples(ocr_json_path: Path, out_dir: Path, video_duration: float | None = None) -> dict[str, Path]:
    raw = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    boxes = [OCRBox.from_dict(item) for item in raw]
    tracks = build_text_tracks(boxes)
    classify_tracks(tracks, ClassificationConfig(video_duration=video_duration))
    return write_extraction_outputs(tracks, out_dir)


def reprocess_tracks_json(tracks_json_path: Path, out_dir: Path, video_duration: float | None = None) -> dict[str, Path]:
    raw = json.loads(tracks_json_path.read_text(encoding="utf-8"))
    tracks = [TextTrack.from_dict(item) for item in raw]
    classify_tracks(tracks, ClassificationConfig(video_duration=video_duration or _tracks_duration_hint(tracks)))
    return write_extraction_outputs(tracks, out_dir)


def write_extraction_outputs(tracks: list[TextTrack], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    main_tracks = [track for track in tracks if track.kind == TrackKind.MAIN_SUBTITLE]
    ignored_tracks = [track for track in tracks if track.kind == TrackKind.PERSISTENT_OVERLAY]
    cues = _tracks_to_cues(main_tracks)

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


def _tracks_to_cues(tracks: list[TextTrack]) -> list[SubtitleCue]:
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

    cues: list[SubtitleCue] = []
    for index, group in enumerate(grouped, start=1):
        ordered = sorted(group, key=lambda item: (round(item.average_bbox[1] / 24), item.average_bbox[0]))
        text = "\n".join(_dedupe_texts([track.text for track in ordered]))
        start = min(track.start for track in group)
        end = max(track.end for track in group)
        cues.append(
            SubtitleCue(
                index=index,
                start=start,
                end=max(end, start + 0.35),
                text=text,
                source_track_id=ordered[0].id,
            )
        )
    return cues


def _belongs_to_cue_group(track: TextTrack, group: list[TextTrack]) -> bool:
    start = min(item.start for item in group)
    end = max(item.end for item in group)
    return abs(track.start - start) <= 0.35 and abs(track.end - end) <= 0.75


def _dedupe_texts(texts: list[str]) -> list[str]:
    result: list[str] = []
    for text in texts:
        stripped = text.strip()
        if stripped and stripped not in result:
            result.append(stripped)
    return result


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
