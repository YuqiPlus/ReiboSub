from pathlib import Path

from video_translate.models import OCRBox, TextTrack, TrackKind
from video_translate.ocr.classifier import ClassificationConfig, classify_tracks
from video_translate.ocr.text_track import build_text_tracks
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.models import SubtitleCue
from video_translate.pipeline import CueTimingConfig, write_extraction_outputs


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


def test_cue_end_extends_from_ocr_sample_interval(tmp_path: Path) -> None:
    track = TextTrack(
        id=1,
        text="안녕하세요",
        start=1.0,
        end=2.0,
        kind=TrackKind.MAIN_SUBTITLE,
        boxes=[
            OCRBox("안녕하세요", (500, 900, 1200, 960), 0.95, 1.0, 30, "bottom"),
            OCRBox("안녕하세요", (502, 902, 1198, 962), 0.95, 2.0, 60, "bottom"),
        ],
    )

    outputs = write_extraction_outputs(
        [track],
        tmp_path,
        cue_timing=CueTimingConfig(
            sample_interval_seconds=0.5,
            sample_end_extension_ratio=0.75,
            end_padding_seconds=0.0,
            min_duration_seconds=0.1,
        ),
    )

    cues = read_srt(outputs["source_srt"])

    assert cues[0].start == 1.0
    assert cues[0].end == 2.375



def test_snapshot_cues_filter_numeric_visual_noise_and_keep_caption(tmp_path: Path) -> None:
    tracks = [
        TextTrack(
            id=1,
            text="76정1098",
            start=10.0,
            end=10.0,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[OCRBox("76정1098", (120, 860, 320, 920), 0.98, 10.0, 300, "bottom"),
                OCRBox("76정", (120, 860, 240, 920), 0.98, 10.333, 310, "bottom"),
            ],
        ),
        TextTrack(
            id=2,
            text="쪼꼬미대장 등장",
            start=10.0,
            end=10.0,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[OCRBox("쪼꼬미대장 등장", (520, 900, 1220, 960), 0.96, 10.0, 300, "bottom")],
        ),
        TextTrack(
            id=3,
            text="쪼꼬미매장",
            start=10.333,
            end=10.333,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[OCRBox("쪼꼬미매장", (520, 900, 1040, 960), 0.99, 10.333, 310, "bottom")],
        ),
    ]

    outputs = write_extraction_outputs(
        tracks,
        tmp_path,
        cue_timing=CueTimingConfig(sample_interval_seconds=1 / 3, end_padding_seconds=0.0),
    )

    cues = read_srt(outputs["source_srt"])

    assert len(cues) == 1
    assert "76정1098" not in cues[0].text
    assert "76정" not in cues[0].text
    assert cues[0].text == "쪼꼬미대장 등장"


def test_snapshot_cues_drop_isolated_low_confidence_flash(tmp_path: Path) -> None:
    tracks = [
        TextTrack(
            id=1,
            text="고과출",
            start=20.0,
            end=20.0,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[OCRBox("고과출", (520, 900, 760, 960), 0.58, 20.0, 600, "bottom")],
        ),
        TextTrack(
            id=2,
            text="안녕하세요",
            start=22.0,
            end=22.333,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[
                OCRBox("안녕하세요", (520, 900, 1060, 960), 0.96, 22.0, 660, "bottom"),
                OCRBox("안녕하세요", (520, 900, 1060, 960), 0.96, 22.333, 670, "bottom"),
            ],
        ),
    ]

    outputs = write_extraction_outputs(
        tracks,
        tmp_path,
        cue_timing=CueTimingConfig(sample_interval_seconds=1 / 3, end_padding_seconds=0.0),
    )

    cues = read_srt(outputs["source_srt"])

    assert [cue.text for cue in cues] == ["안녕하세요"]
