from pathlib import Path

from video_translate.models import OCRBox, TrackKind
from video_translate.ocr.classifier import ClassificationConfig, classify_tracks
from video_translate.ocr.text_track import build_text_tracks
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.models import SubtitleCue


def test_persistent_overlay_is_filtered() -> None:
    boxes = [
        OCRBox("런닝맨", (1700, 40, 1880, 110), 0.96, time, index, "full")
        for index, time in enumerate([0, 10, 20, 30, 40, 50])
    ]
    boxes.extend(
        [
            OCRBox("안녕하세요", (520, 900, 1200, 960), 0.92, 2.0, 20, "bottom"),
            OCRBox("안녕하세요", (522, 902, 1198, 962), 0.91, 2.33, 23, "bottom"),
        ]
    )

    tracks = build_text_tracks(boxes, max_gap_seconds=12.0)
    classify_tracks(tracks, ClassificationConfig(video_duration=60.0, persistent_min_seconds=30.0))

    kinds = {track.text: track.kind for track in tracks}
    assert kinds["런닝맨"] == TrackKind.PERSISTENT_OVERLAY
    assert kinds["안녕하세요"] == TrackKind.MAIN_SUBTITLE


def test_srt_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "sample.srt"
    write_srt([SubtitleCue(1, 1.25, 3.5, "안녕하세요")], path)
    cues = read_srt(path)
    assert cues[0].start == 1.25
    assert cues[0].end == 3.5
    assert cues[0].text == "안녕하세요"
