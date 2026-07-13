import json
from pathlib import Path

from video_translate.models import OCRBox, TextTrack, TrackKind
from video_translate.ocr.classifier import ClassificationConfig, classify_tracks
from video_translate.ocr.text_track import build_text_tracks
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.models import SubtitleCue
from video_translate.pipeline import CueTimingConfig, _apply_region_ocr_track_policy, _build_subtitle_snapshots, _choose_snapshot_text, extract_subtitles_from_video, write_extraction_outputs


def test_snapshot_text_uses_spatial_consensus_for_progressive_caption() -> None:
    ha = "\uD558"
    jinja = "\uC9C4\uC790"
    jinjja = "\uC9C4\uC9DC"
    michigetne = "\uBBF8\uCE58\uACA0\uB124"
    ichigetne = "\uC774\uCE58\uACA0\uB124"
    boxes = [
        OCRBox("X", (860, 210, 1250, 610), 0.95, 1.0, 1, "bottom"),
        OCRBox(ha, (560, 860, 670, 960), 0.98, 1.0, 1, "bottom"),
        OCRBox(jinja, (760, 850, 970, 980), 0.90, 1.0, 1, "bottom"),
        OCRBox(ha, (560, 860, 670, 960), 0.98, 1.2, 2, "bottom"),
        OCRBox(jinjja, (760, 850, 970, 980), 0.96, 1.2, 2, "bottom"),
        OCRBox(michigetne, (970, 850, 1360, 980), 0.94, 1.2, 2, "bottom"),
        OCRBox(ha, (560, 860, 670, 960), 0.98, 1.4, 3, "bottom"),
        OCRBox(jinjja, (760, 850, 970, 980), 0.96, 1.4, 3, "bottom"),
        OCRBox(ichigetne, (970, 850, 1360, 980), 0.92, 1.4, 3, "bottom"),
        OCRBox(ha, (560, 860, 670, 960), 0.98, 1.6, 4, "bottom"),
        OCRBox(jinjja, (760, 850, 970, 980), 0.96, 1.6, 4, "bottom"),
        OCRBox(michigetne, (970, 850, 1360, 980), 0.94, 1.6, 4, "bottom"),
        OCRBox(ha, (560, 860, 670, 960), 0.98, 1.8, 5, "bottom"),
        OCRBox(jinja, (760, 850, 970, 980), 0.90, 1.8, 5, "bottom"),
        OCRBox(michigetne, (970, 850, 1360, 980), 0.94, 1.8, 5, "bottom"),
    ]

    assert _choose_snapshot_text(_build_subtitle_snapshots(boxes)) == f"{ha} {jinjja} {michigetne}"


def test_snapshot_text_keeps_words_on_separate_rows() -> None:
    boxes = []
    for index, time in enumerate([1.0, 1.2, 1.4], start=1):
        boxes.extend(
            [
                OCRBox("wow", (660, 410, 820, 470), 0.99, time, index, "bottom"),
                OCRBox("open", (660, 500, 820, 570), 0.99, time, index, "bottom"),
                OCRBox("this", (830, 500, 970, 570), 0.99, time, index, "bottom"),
                OCRBox("door", (980, 500, 1130, 570), 0.99, time, index, "bottom"),
            ]
        )

    assert _choose_snapshot_text(_build_subtitle_snapshots(boxes)) == "wow\nopen this door"


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


def test_non_bottom_caption_is_promoted_when_no_bottom_subtitle() -> None:
    boxes = [
        OCRBox("위쪽 자막", (520, 410, 1180, 470), 0.94, 1.0, 30, "full_middle"),
        OCRBox("위쪽 자막", (522, 412, 1178, 472), 0.93, 1.33, 40, "full_middle"),
    ]

    tracks = build_text_tracks(boxes)
    classify_tracks(tracks, ClassificationConfig(video_duration=30.0))

    assert tracks[0].kind == TrackKind.MAIN_SUBTITLE
    assert tracks[0].reason == "non_bottom_fallback_without_bottom_overlap"


def test_narrow_vertical_non_bottom_text_is_not_promoted() -> None:
    boxes = [
        OCRBox("최고가매입", (628, 343, 656, 469), 0.98, 10.67, 320, "full_middle"),
        OCRBox("최고가매입", (634, 347, 658, 470), 0.94, 11.01, 330, "full_middle"),
    ]

    tracks = build_text_tracks(boxes)
    classify_tracks(tracks, ClassificationConfig(video_duration=600.0))

    assert tracks[0].kind != TrackKind.MAIN_SUBTITLE
    assert tracks[0].reason == "non_bottom_narrow_visual_text"


def test_non_bottom_caption_is_suppressed_when_bottom_subtitle_exists() -> None:
    boxes = [
        OCRBox("화면 글자", (520, 410, 1180, 470), 0.94, 1.0, 30, "full_middle"),
        OCRBox("화면 글자", (522, 412, 1178, 472), 0.93, 1.33, 40, "full_middle"),
        OCRBox("아래 자막", (520, 900, 1180, 960), 0.95, 1.0, 30, "bottom"),
        OCRBox("아래 자막", (522, 902, 1178, 962), 0.95, 1.33, 40, "bottom"),
    ]

    tracks = build_text_tracks(boxes)
    classify_tracks(tracks, ClassificationConfig(video_duration=30.0))
    kinds = {track.text: track.kind for track in tracks}
    reasons = {track.text: track.reason for track in tracks}

    assert kinds["아래 자막"] == TrackKind.MAIN_SUBTITLE
    assert kinds["화면 글자"] == TrackKind.SECONDARY_CAPTION
    assert reasons["화면 글자"] == "non_bottom_suppressed_by_bottom_subtitle"


def test_region_ocr_policy_keeps_selected_area_tracks_as_main_subtitles() -> None:
    tracks = [
        TextTrack(
            id=1,
            text="화면 안 자막",
            start=1.0,
            end=1.33,
            kind=TrackKind.PERSISTENT_OVERLAY,
            reason="old_classifier_reason",
            boxes=[OCRBox("화면 안 자막", (400, 520, 900, 580), 0.92, 1.0, 30, "crop")],
        ),
        TextTrack(id=2, text="   ", start=2.0, end=2.0, kind=TrackKind.UNKNOWN),
    ]

    _apply_region_ocr_track_policy(tracks)

    assert tracks[0].kind == TrackKind.MAIN_SUBTITLE
    assert tracks[0].reason == "region_ocr_selected_area"
    assert tracks[1].kind == TrackKind.UNKNOWN
    assert tracks[1].reason == "region_ocr_empty_text"


def test_snapshot_cues_use_complete_text_for_typing_subtitles(tmp_path: Path) -> None:
    boxes = [
        OCRBox("안", (400, 800, 450, 850), 0.95, 1.033, 31, "bottom"),
        OCRBox("안녕", (400, 800, 500, 850), 0.95, 1.067, 32, "bottom"),
        OCRBox("안녕하세요", (400, 800, 650, 850), 0.95, 1.100, 33, "bottom"),
        OCRBox("안녕하세요", (400, 800, 650, 850), 0.96, 1.133, 34, "bottom"),
    ]
    tracks = build_text_tracks(boxes)
    _apply_region_ocr_track_policy(tracks)

    outputs = write_extraction_outputs(
        tracks,
        tmp_path,
        cue_timing=CueTimingConfig(sample_interval_seconds=1 / 30, end_padding_seconds=0.0, min_duration_seconds=0.1),
    )
    cues = read_srt(outputs["source_srt"])

    assert len(cues) == 1
    assert cues[0].start == 1.033
    assert cues[0].text == "안녕하세요"


def test_extraction_writes_raw_ocr_boxes_grouped_by_sampled_frame(monkeypatch, tmp_path: Path) -> None:
    boxes = [OCRBox("테스트", (100, 500, 300, 560), 0.31, 1.5, 45, "bottom")]

    def fake_extract(video_path, lang, config, sampled_frames=None):
        assert config.min_confidence == 0.3
        assert sampled_frames is not None
        sampled_frames.extend(
            [
                {"frame_index": 30, "time": 1.0, "boxes": []},
                {"frame_index": 45, "time": 1.5, "boxes": [boxes[0].to_dict()]},
            ]
        )
        return boxes

    monkeypatch.setattr("video_translate.pipeline.extract_video_ocr", fake_extract)

    outputs = extract_subtitles_from_video(
        tmp_path / "demo.mp4",
        tmp_path / "output",
        lang="korean",
        sample_fps=6,
        min_confidence=0.3,
        extraction_mode="region",
    )

    raw_samples = json.loads(outputs["ocr_sample_frames"].read_text(encoding="utf-8"))
    assert raw_samples["sample_fps"] == 6
    assert raw_samples["min_confidence"] == 0.3
    assert raw_samples["frames"][0]["boxes"] == []
    assert raw_samples["frames"][1]["boxes"][0]["text"] == "테스트"


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


def test_snapshot_cues_smooth_short_flicker_between_related_captions(tmp_path: Path) -> None:
    tracks = [
        TextTrack(
            id=1,
            text="caption",
            start=10.0,
            end=10.167,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[
                OCRBox("caption", (520, 900, 1060, 960), 0.99, 10.0, 300, "bottom"),
                OCRBox("caption", (520, 900, 1060, 960), 0.99, 10.167, 301, "bottom"),
            ],
        ),
        TextTrack(
            id=2,
            text="FLASH",
            start=10.333,
            end=10.333,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[OCRBox("FLASH", (520, 900, 760, 960), 0.99, 10.333, 302, "bottom")],
        ),
        TextTrack(
            id=3,
            text="caption",
            start=10.5,
            end=10.667,
            kind=TrackKind.MAIN_SUBTITLE,
            boxes=[
                OCRBox("caption", (520, 900, 1060, 960), 0.99, 10.5, 303, "bottom"),
                OCRBox("caption", (520, 900, 1060, 960), 0.99, 10.667, 304, "bottom"),
            ],
        ),
    ]

    outputs = write_extraction_outputs(
        tracks,
        tmp_path,
        cue_timing=CueTimingConfig(
            sample_interval_seconds=1 / 6,
            end_padding_seconds=0.0,
            flicker_smoothing_max_duration_seconds=0.55,
        ),
    )

    cues = read_srt(outputs["source_srt"])

    assert [cue.text for cue in cues] == ["caption"]


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
