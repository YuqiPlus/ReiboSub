from __future__ import annotations

import json
from pathlib import Path

from video_translate.llm_config import LLMTaskConfig
from video_translate.models import OCRBox, TextTrack
from video_translate.ocr import geometry_refine
from video_translate.ocr.geometry_refine import (
    GeometryDecision,
    GeometryRefinementConfig,
    apply_geometry_decisions,
    build_geometry_refinement_payload,
    build_track_geometry_evidence,
    derive_geometry_action,
    parse_geometry_refinement_response,
    refine_ocr_geometry_with_llm,
)
from video_translate.subtitle.srt import read_srt


def _box(
    text: str,
    time: float,
    frame: int,
    bbox: tuple[float, float, float, float],
    *,
    angle: float | None = None,
    polygon: tuple[tuple[float, float], ...] | None = None,
    region: str = "full_middle",
) -> OCRBox:
    return OCRBox(
        text=text,
        bbox=bbox,
        confidence=0.96,
        time=time,
        frame_index=frame,
        region=region,
        polygon=polygon,
        angle_degrees=angle,
    )


def _track(track_id: int, text: str, boxes: list[OCRBox]) -> TextTrack:
    return TextTrack(
        id=track_id,
        text=text,
        start=min(box.time for box in boxes),
        end=max(box.time for box in boxes),
        boxes=boxes,
    )


def _moving_scene_track(track_id: int = 2) -> TextTrack:
    samples = [
        _box(
            "상품명",
            2.0,
            20,
            (100, 300, 200, 340),
            polygon=((100, 300), (200, 300), (190, 340), (105, 340)),
        ),
        _box(
            "상품명",
            2.2,
            22,
            (240, 290, 380, 348),
            polygon=((240, 290), (380, 295), (350, 348), (250, 342)),
        ),
        _box(
            "상품명",
            2.4,
            24,
            (430, 270, 630, 360),
            polygon=((430, 270), (630, 285), (570, 360), (445, 345)),
        ),
    ]
    return _track(track_id, "상품명", samples)


def test_geometry_payload_contains_soft_angle_and_strict_decision_schema() -> None:
    boxes = [
        _box("부끄", 1.0, 10, (500, 300, 760, 380), angle=17.0),
        _box("부끄", 1.2, 12, (502, 301, 762, 381), angle=17.5),
        _box("부끄", 1.4, 14, (501, 300, 761, 380), angle=16.5),
    ]
    track = _track(1, "부끄", boxes)

    payload = build_geometry_refinement_payload([track], boxes, model="lite")
    prompt = payload["messages"][0]["content"]
    content = payload["messages"][1]["content"]

    assert "angle 的绝对值再大也不能单独证明" in prompt
    assert "不得输出 keep/drop/action" in prompt
    assert "stable_slanted_program_candidate" in content
    assert "moving_slanted_surface_candidate" in content
    assert '"angle_alone_can_drop":false' in content
    assert '"classification":"subtitle"' in content
    assert set(geometry_refine.GEOMETRY_CLASSIFICATIONS) == {
        "subtitle",
        "program_caption",
        "visual_annotation",
        "scene_text",
        "logo",
        "uncertain",
    }


def test_stable_slanted_program_text_is_protected_from_scene_text_drop() -> None:
    boxes = [
        _box("두근", 1.0, 10, (500, 300, 760, 380), angle=19.0),
        _box("두근", 1.2, 12, (501, 301, 761, 381), angle=18.0),
        _box("두근", 1.4, 14, (499, 300, 759, 380), angle=20.0),
    ]
    track = _track(1, "두근", boxes)
    evidence = build_track_geometry_evidence(track, boxes)
    decision = GeometryDecision(
        track_id=1,
        classification="scene_text",
        evidence=("scene_object_semantics",),
        reason="斜着的字",
    )

    action = derive_geometry_action(track, decision, evidence)

    assert evidence["geometry"]["angle"]["median_abs_degrees"] == 19.0
    assert evidence["server_features"]["stable_slanted_program_candidate"] is True
    assert evidence["server_features"]["angle_alone_can_drop"] is False
    assert action.action == "keep"
    assert "protection" in action.reason


def test_moving_slanted_surface_does_not_receive_static_program_protection() -> None:
    boxes = [
        _box("사장박영희", 1.8, 55, (827, 465, 1083, 629), angle=25.8),
        _box("사장박영희", 2.6, 80, (780, 400, 1033, 562), angle=26.1),
        _box("사장박영희", 3.5, 105, (864, 430, 1122, 598), angle=26.8),
        _box("사장박영희", 4.3, 130, (925, 511, 1164, 667), angle=26.2),
    ]
    track = _track(14, "사장박영희", boxes)

    evidence = build_track_geometry_evidence(track, boxes)
    decision = GeometryDecision(
        track_id=14,
        classification="scene_text",
        evidence=("scene_object_semantics", "center_motion"),
        reason="휴대전화 화면과 함께 이동하는 글자",
    )
    action = derive_geometry_action(track, decision, evidence)

    assert evidence["geometry"]["motion"]["center_motion"] is True
    assert evidence["server_features"]["moving_slanted_surface_candidate"] is True
    assert evidence["server_features"]["stable_slanted_program_candidate"] is False
    # The composite hint is intentionally soft. One dynamic signal still
    # cannot make the geometry-only diagnostic erase a programme caption.
    assert action.action == "keep"
    assert "only 1" in action.reason


def test_scene_text_requires_two_server_computed_dynamic_or_perspective_signals() -> None:
    track = _moving_scene_track()
    evidence = build_track_geometry_evidence(track, track.boxes)
    decision = GeometryDecision(
        track_id=track.id,
        classification="scene_text",
        evidence=("scene_object_semantics", "center_motion", "scale_change"),
        reason="文字随商品移动并缩放",
    )

    action = derive_geometry_action(track, decision, evidence)

    assert evidence["geometry"]["motion"]["center_motion"] is True
    assert evidence["geometry"]["scale"]["scale_change"] is True
    assert evidence["server_features"]["dynamic_perspective_evidence_count"] >= 2
    assert action.action == "drop"


def test_scene_text_with_only_motion_is_conservatively_kept() -> None:
    boxes = [
        _box("가게", 3.0, 30, (100, 300, 240, 350)),
        _box("가게", 3.2, 32, (250, 300, 390, 350)),
        _box("가게", 3.4, 34, (400, 300, 540, 350)),
    ]
    track = _track(3, "가게", boxes)
    evidence = build_track_geometry_evidence(track, boxes)
    decision = GeometryDecision(3, "scene_text", ("scene_object_semantics", "center_motion"), "随镜头移动")

    action = derive_geometry_action(track, decision, evidence)

    assert evidence["server_features"]["dynamic_perspective_flags"] == ["center_motion"]
    assert action.action == "keep"
    assert "only 1" in action.reason


def test_logo_semantics_without_long_persistence_is_conservatively_kept() -> None:
    boxes = [
        _box("방송 로고", 1.0, 10, (1700, 40, 1860, 90), angle=0.0),
        _box("방송 로고", 1.2, 12, (1700, 40, 1860, 90), angle=0.0),
        _box("방송 로고", 1.4, 14, (1700, 40, 1860, 90), angle=0.0),
    ]
    track = _track(8, "방송 로고", boxes)
    evidence = build_track_geometry_evidence(track, boxes)
    decision = GeometryDecision(8, "logo", ("logo_semantics", "stable_position"), "台标")

    action = derive_geometry_action(track, decision, evidence)

    assert evidence["server_features"]["persistent_logo_candidate"] is False
    assert action.action == "keep"


def test_long_persistent_semantic_logo_can_be_dropped() -> None:
    boxes = [
        _box("MBC", float(index), index, (1700, 40, 1860, 90), angle=0.0)
        for index in range(9)
    ]
    track = _track(9, "MBC", boxes)
    evidence = build_track_geometry_evidence(track, boxes)
    decision = GeometryDecision(9, "logo", ("logo_semantics", "persistent_position"), "固定台标")

    action = derive_geometry_action(track, decision, evidence)

    assert evidence["server_features"]["persistent_logo_candidate"] is True
    assert action.action == "drop"


def test_global_ocr_boxes_restore_polygon_geometry_missing_from_tracks_json() -> None:
    track_samples = [
        _box("간판", 4.0, 40, (100, 200, 300, 260)),
        _box("간판", 4.2, 42, (100, 200, 300, 260)),
    ]
    geometry_samples = [
        _box(
            "간판",
            sample.time,
            sample.frame_index,
            sample.bbox,
            polygon=((100, 200), (300, 210), (260, 260), (120, 250)),
        )
        for sample in track_samples
    ]
    track = _track(4, "간판", track_samples)

    evidence = build_track_geometry_evidence(track, geometry_samples)

    assert evidence["geometry"]["perspective"]["sample_count"] == 2
    assert all(item["perspective_distortion"] is not None for item in evidence["observations"])


def test_strict_parser_isolates_invalid_and_missing_track_decisions() -> None:
    content = json.dumps(
        {
            "decisions": [
                {
                    "track_id": 1,
                    "classification": "program_caption",
                    "evidence": ["program_graphics_semantics"],
                    "reason": "节目花字",
                },
                {
                    "track_id": 2,
                    "classification": "delete",
                    "evidence": [],
                    "reason": "非法类别",
                },
            ]
        },
        ensure_ascii=False,
    )

    parsed = parse_geometry_refinement_response(content, [1, 2, 3])

    assert list(parsed.decisions) == [1]
    assert parsed.errors[2].startswith("invalid classification")
    assert parsed.errors[3] == "missing decision"

    tracks = [
        _track(index, text, [_box(text, float(index), index, (100, 300, 300, 350))])
        for index, text in ((1, "节目字"), (2, "坏响应"), (3, "缺响应"))
    ]
    kept, actions = apply_geometry_decisions(tracks, parsed.decisions)
    assert [track.id for track in kept] == [1, 2, 3]
    assert [action.fallback for action in actions] == [False, True, True]


def test_refine_geometry_writes_srt_and_debug_with_server_derived_actions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    stable_boxes = [
        _box("두근", 1.0, 10, (500, 300, 760, 380), angle=16.0),
        _box("두근", 1.2, 12, (500, 300, 760, 380), angle=16.5),
        _box("두근", 1.4, 14, (500, 300, 760, 380), angle=15.5),
    ]
    program_track = _track(1, "두근", stable_boxes)
    scene_track = _moving_scene_track(2)
    tracks = [program_track, scene_track]
    all_boxes = stable_boxes + scene_track.boxes
    tracks_json = tmp_path / "tracks.json"
    boxes_json = tmp_path / "ocr_boxes.json"
    out_srt = tmp_path / "source.geometry_refined.srt"
    debug_json = tmp_path / "ocr_geometry.json"
    tracks_json.write_text(json.dumps([track.to_dict() for track in tracks], ensure_ascii=False), encoding="utf-8")
    boxes_json.write_text(json.dumps([box.to_dict() for box in all_boxes], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(geometry_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        geometry_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    monkeypatch.setattr(
        geometry_refine,
        "_request_translation",
        lambda *args, **kwargs: json.dumps(
            {
                "decisions": [
                    {
                        "track_id": 1,
                        "classification": "visual_annotation",
                        "evidence": ["annotation_semantics", "stable_slanted_style"],
                        "reason": "节目拟声花字",
                    },
                    {
                        "track_id": 2,
                        "classification": "scene_text",
                        "evidence": ["scene_object_semantics", "center_motion", "scale_change"],
                        "reason": "商品包装文字随物品移动缩放",
                    },
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = refine_ocr_geometry_with_llm(tracks_json, boxes_json, out_srt, debug_json)

    assert result == {"refined_srt": out_srt, "debug_json": debug_json}
    assert [cue.text for cue in read_srt(out_srt)] == ["두근"]
    debug = json.loads(debug_json.read_text(encoding="utf-8"))
    assert debug["mode"] == "ocr3_geometry_semantic_refinement"
    assert [item["action"] for item in debug["actions"]] == ["keep", "drop"]
    assert debug["batches"][0]["status"] == "ok"


def test_invalid_whole_llm_response_keeps_every_track(monkeypatch, tmp_path: Path) -> None:
    boxes = [
        _box("원문 A", 1.0, 10, (100, 300, 300, 350)),
        _box("원문 B", 2.0, 20, (100, 300, 300, 350)),
    ]
    tracks = [_track(1, "원문 A", [boxes[0]]), _track(2, "원문 B", [boxes[1]])]
    tracks_json = tmp_path / "tracks.json"
    boxes_json = tmp_path / "ocr_boxes.json"
    out_srt = tmp_path / "source.geometry_refined.srt"
    debug_json = tmp_path / "ocr_geometry.json"
    tracks_json.write_text(json.dumps([track.to_dict() for track in tracks], ensure_ascii=False), encoding="utf-8")
    boxes_json.write_text(json.dumps([box.to_dict() for box in boxes], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(geometry_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        geometry_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    monkeypatch.setattr(geometry_refine, "_request_translation", lambda *args, **kwargs: "not-json")

    refine_ocr_geometry_with_llm(tracks_json, boxes_json, out_srt, debug_json)

    assert [cue.text for cue in read_srt(out_srt)] == ["원문 A", "원문 B"]
    debug = json.loads(debug_json.read_text(encoding="utf-8"))
    assert all(item["action"] == "keep" and item["fallback"] for item in debug["actions"])
    assert set(debug["decision_errors"]) == {"1", "2"}
