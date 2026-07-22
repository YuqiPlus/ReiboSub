from __future__ import annotations

import json
from pathlib import Path

from video_translate.llm_config import LLMTaskConfig
from video_translate.models import OCRBox, SubtitleCue
from video_translate.ocr import layered_refine
from video_translate.ocr.layered_refine import (
    LayeredOCRRefinementConfig,
    apply_layered_events,
    apply_spatial_role_guard,
    build_cue_layer_evidence,
    build_layered_refinement_payload,
    parse_layered_refinement_response,
    refine_ocr_layers_with_llm,
)
from video_translate.subtitle.srt import read_srt, write_srt


def _event(*layers: dict[str, object]) -> list[dict[str, object]]:
    return [{"cue_id": 1, "layers": list(layers)}]


def test_visual_annotation_is_attached_directly_before_dialogue() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="机器 OCR")]
    events = _event(
        {"id": "annotation", "role": "visual_annotation", "text": "脸红", "attach_to": "dialogue"},
        {"id": "dialogue", "role": "dialogue", "text": "我有点害羞"},
    )

    result = apply_layered_events(cues, events)

    assert len(result) == 1
    assert result[0].text == "[脸红]我有点害羞"
    assert (result[0].start, result[0].end) == (1.0, 2.0)


def test_subject_label_is_bracketed_with_space_before_main_caption() -> None:
    cues = [SubtitleCue(index=1, start=18.0, end=19.0, text="이선빈 섭외한 방으로 피신")]
    events = _event(
        {
            "id": "subject",
            "role": "subject_label",
            "text": "[이선빈]",
            "attach_to": "main",
            "evidence_layer_ids": ["L1"],
        },
        {
            "id": "main",
            "role": "dialogue",
            "text": "섭외한 방으로 피신",
            "evidence_layer_ids": ["L3"],
        },
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "[이선빈] 섭외한 방으로 피신"
    assert (result[0].start, result[0].end) == (18.0, 19.0)


def test_multiple_visual_annotations_follow_speaker_and_precede_dialogue() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="机器 OCR")]
    events = _event(
        {"id": "speaker", "role": "speaker_label", "text": "主角", "attach_to": "dialogue"},
        {"id": "a1", "role": "visual_annotation", "text": "[脸红]", "attach_to": "dialogue"},
        {"id": "a2", "role": "visual_annotation", "text": "低头", "attach_to": "dialogue"},
        {"id": "dialogue", "role": "dialogue", "text": "我有点害羞"},
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "主角: [脸红][低头]我有点害羞"


def test_visual_annotation_without_dialogue_is_kept_as_bracketed_text() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="节目说明")]
    events = _event(
        {
            "id": "annotation",
            "role": "visual_annotation",
            "text": "照片里的发型 / 眼前的发型",
        }
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "[照片里的发型 / 眼前的发型]"


def test_layered_events_attach_speaker_with_ascii_colon() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="안녕")]
    events = _event(
        {"id": "speaker", "role": "speaker_label", "text": "박보영：", "attach_to": "dialogue"},
        {"id": "dialogue", "role": "dialogue", "text": "안녕하세요"},
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "박보영: 안녕하세요"


def test_layered_events_keep_all_labels_attached_to_same_dialogue() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="안녕")]
    events = _event(
        {"id": "role", "role": "speaker_label", "text": "[꽃게]", "attach_to": "dialogue"},
        {"id": "name", "role": "speaker_label", "text": "이선빈", "attach_to": "dialogue"},
        {"id": "dialogue", "role": "dialogue", "text": "안녕하세요"},
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "[꽃게] 이선빈: 안녕하세요"


def test_layered_events_keep_dialogue_without_decorating_it() -> None:
    cues = [SubtitleCue(index=1, start=3.0, end=4.0, text="원본")]
    events = _event({"role": "dialogue", "text": "괜찮아요"})

    result = apply_layered_events(cues, events)

    assert result[0].text == "괜찮아요"


def test_refine_layers_invalid_json_safely_falls_back_to_machine_cues(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.machine.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.layered.srt"
    debug_path = tmp_path / "source.layered.debug.json"
    machine = [
        SubtitleCue(index=1, start=1.0, end=2.0, text="첫 번째 원문"),
        SubtitleCue(index=2, start=2.1, end=3.0, text="두 번째 원문"),
    ]
    write_srt(machine, source)
    boxes_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    monkeypatch.setattr(layered_refine, "_request_translation", lambda *args, **kwargs: "not-json")
    progress: list[str] = []

    result = refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        config=LayeredOCRRefinementConfig(batch_size=8),
        progress_callback=progress.append,
    )

    assert [cue.text for cue in read_srt(out)] == ["첫 번째 원문", "두 번째 원문"]
    assert result == {"refined_srt": out, "debug_json": debug_path}
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["version"] == 2
    assert debug["mode"] == "ocr2_semantic_layered_refinement"
    assert "geometry_json" not in debug
    assert "geometry_hint_count" not in debug
    assert "pipeline_version" not in debug["config"]
    assert "max_geometry_hints_per_cue" not in debug["config"]
    assert debug["batches"][0]["status"] == "fallback"
    assert any(message.startswith("ocr_layered_refine_fallback:") for message in progress)


def test_v3_retries_once_when_the_whole_response_is_not_strict_json(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.v3.refined.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.v3.layered.srt"
    debug_path = tmp_path / "ocr_v3_layers.json"
    write_srt([SubtitleCue(index=1, start=1.0, end=2.0, text="주차장")], source)
    boxes_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    responses = iter(
        [
            '{"events":[{"cue_id":1,"layers":[{"role":"noise","text":"주차장"}]}]}}',
            '{"events":[{"cue_id":1,"layers":[{"role":"noise","text":"주차장"}]}]}',
        ]
    )
    payloads: list[dict[str, object]] = []

    def fake_request(endpoint, api_key, payload):
        del endpoint, api_key
        payloads.append(payload)
        return next(responses)

    monkeypatch.setattr(layered_refine, "_request_translation", fake_request)
    progress: list[str] = []

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        config=LayeredOCRRefinementConfig(pipeline_version="v3"),
        progress_callback=progress.append,
    )

    assert read_srt(out) == []
    assert len(payloads) == 2
    assert len(payloads[1]["messages"]) == len(payloads[0]["messages"]) + 1
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["batches"][0]["status"] == "refined"
    assert debug["batches"][0]["schema_retry_error"].startswith("JSONDecodeError:")
    assert "schema_retry_raw_response" in debug["batches"][0]
    assert any(message.startswith("ocr_layered_refine_schema_retry: 1/1") for message in progress)


def test_v3_retries_only_invalid_events_and_keeps_first_valid_decisions(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.v3.refined.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.v3.layered.srt"
    debug_path = tmp_path / "ocr_v3_layers.json"
    write_srt(
        [
            SubtitleCue(index=1, start=1.0, end=2.0, text="첫 기준"),
            SubtitleCue(index=2, start=2.1, end=3.0, text="이선빈 본문"),
        ],
        source,
    )
    boxes_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    responses = iter(
        [
            json.dumps(
                {
                    "events": [
                        {"cue_id": 1, "layers": [{"role": "dialogue", "text": "첫 결정"}]},
                        {"cue_id": 2, "layers": [{"role": "subject_label", "text": "이선빈"}]},
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "events": [
                        {
                            "cue_id": 2,
                            "layers": [
                                {
                                    "id": "subject",
                                    "role": "subject_label",
                                    "text": "이선빈",
                                    "attach_to": "main",
                                },
                                {"id": "main", "role": "dialogue", "text": "본문"},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )
    monkeypatch.setattr(layered_refine, "_request_translation", lambda *args, **kwargs: next(responses))
    progress: list[str] = []

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        config=LayeredOCRRefinementConfig(pipeline_version="v3"),
        progress_callback=progress.append,
    )

    assert [cue.text for cue in read_srt(out)] == ["첫 결정", "[이선빈] 본문"]
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    batch = debug["batches"][0]
    assert batch["status"] == "refined"
    assert batch["event_retry_ids"] == [2]
    assert batch["event_retry_repaired_ids"] == [2]
    assert "event_errors" not in batch
    assert any(message == "ocr_layered_refine_event_retry: 1/1 repaired 2" for message in progress)


def test_refine_layers_only_falls_back_the_invalid_cue_in_a_valid_json_batch(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.track_refined.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.layered.srt"
    debug_path = tmp_path / "ocr_layers.json"
    machine = [
        SubtitleCue(index=1, start=1.0, end=2.0, text="完整基线一"),
        SubtitleCue(index=2, start=2.1, end=3.0, text="完整基线二"),
    ]
    write_srt(machine, source)
    boxes_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    response = {
        "events": [
            {"cue_id": 1, "layers": [{"role": "dialogue", "text": "精修后的一"}]},
            {
                "cue_id": 2,
                "layers": [
                    {"id": "speaker", "role": "speaker_label", "text": "某人", "attach_to": "missing"}
                ],
            },
        ]
    }
    monkeypatch.setattr(
        layered_refine,
        "_request_translation",
        lambda *args, **kwargs: json.dumps(response, ensure_ascii=False),
    )
    progress: list[str] = []

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        config=LayeredOCRRefinementConfig(batch_size=8),
        progress_callback=progress.append,
    )

    assert [cue.text for cue in read_srt(out)] == ["精修后的一", "完整基线二"]
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["batches"][0]["status"] == "partial"
    assert "2" in debug["batches"][0]["event_errors"]
    assert any(message == "ocr_layered_refine_partial: 1/1 fallback cues 2" for message in progress)


def test_refine_layers_recovers_only_stable_uncovered_raw_cue(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.track_refined.srt"
    recovery = tmp_path / "source.before_cleanup.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.layered.srt"
    debug_path = tmp_path / "ocr_layers.json"
    write_srt([SubtitleCue(index=1, start=10.0, end=11.0, text="기존 자막")], source)
    write_srt(
        [
            SubtitleCue(index=1, start=0.0, end=0.8, text="NM"),
            SubtitleCue(index=2, start=2.0, end=3.0, text="으허성 000"),
            SubtitleCue(index=3, start=10.0, end=11.0, text="중복 원문"),
        ],
        recovery,
    )
    boxes = [
        OCRBox("NM", (100, 100, 160, 140), 0.99, 0.4, 4, "full_middle"),
        *[
            OCRBox("으허성", (500, 600, 800, 680), 0.96, time, frame, "full_middle")
            for frame, time in enumerate((2.05, 2.25, 2.45, 2.65, 2.85), start=20)
        ],
    ]
    boxes_path.write_text(
        json.dumps([box.to_dict() for box in boxes], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )

    def fake_request(endpoint, api_key, payload):
        del endpoint, api_key
        evidence = json.loads(payload["messages"][1]["content"].split("输入：\n", 1)[1])
        events = []
        for cue in evidence["cue_evidence"]:
            if cue["baseline_kind"] == "orphan_candidate":
                layer_id = next(
                    candidate["layer_id"]
                    for candidate in cue["layer_candidates"]
                    if candidate["recovery_eligible"]
                )
                layers = [
                    {
                        "id": "effect",
                        "role": "visual_annotation",
                        "text": "으허엉...",
                        "evidence_layer_ids": [layer_id],
                    }
                ]
            else:
                layers = [{"id": "main", "role": "dialogue", "text": cue["machine_text"]}]
            events.append({"cue_id": cue["cue_id"], "layers": layers})
        return json.dumps({"events": events}, ensure_ascii=False)

    monkeypatch.setattr(layered_refine, "_request_translation", fake_request)

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        recovery_srt=recovery,
        config=LayeredOCRRefinementConfig(batch_size=8),
    )

    assert [cue.text for cue in read_srt(out)] == ["[으허엉...]", "기존 자막"]
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["baseline_cue_count"] == 1
    assert debug["recovery"]["accepted_count"] == 1
    assert debug["recovery"]["accepted"][0]["provisional_text"] == "으허성"
    assert debug["recovery"]["rejected_counts"] == {
        "no_stable_text": 1,
        "covered_by_baseline": 1,
    }


def test_refine_layers_drops_recovery_candidate_when_model_response_fails(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.track_refined.srt"
    recovery = tmp_path / "source.before_cleanup.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.layered.srt"
    debug_path = tmp_path / "ocr_layers.json"
    write_srt([SubtitleCue(index=1, start=10.0, end=11.0, text="신뢰 기준선")], source)
    write_srt([SubtitleCue(index=1, start=2.0, end=3.0, text="으허성")], recovery)
    boxes = [
        OCRBox("으허성", (500, 600, 800, 680), 0.96, time, frame, "full_middle")
        for frame, time in enumerate((2.05, 2.25, 2.45, 2.65, 2.85), start=20)
    ]
    boxes_path.write_text(
        json.dumps([box.to_dict() for box in boxes], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    monkeypatch.setattr(layered_refine, "_request_translation", lambda *args, **kwargs: "not-json")

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        recovery_srt=recovery,
        config=LayeredOCRRefinementConfig(batch_size=8),
    )

    assert [cue.text for cue in read_srt(out)] == ["신뢰 기준선"]
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["recovery"]["accepted_count"] == 1
    assert debug["batches"][0]["status"] == "fallback"


def test_layered_payload_preserves_bbox_y_and_separate_vertical_layers() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="화면 문구\n대화")]
    boxes = [
        OCRBox("화면 문구", (300, 260, 900, 320), 0.95, 1.2, 36, "full_middle"),
        OCRBox("대화", (500, 850, 1000, 920), 0.98, 1.2, 36, "bottom"),
        OCRBox("화면 문구", (302, 262, 902, 322), 0.96, 1.6, 48, "full_middle"),
        OCRBox("대화", (502, 852, 1002, 922), 0.99, 1.6, 48, "bottom"),
    ]

    payload = build_layered_refinement_payload(cues, boxes, model="lite")
    content = payload["messages"][1]["content"]
    evidence = json.loads(content.split("输入：\n", 1)[1])["cue_evidence"][0]

    first_frame_rows = evidence["frame_observations"][0]["rows"]
    assert [row["text"] for row in first_frame_rows] == ["화면 문구", "대화"]
    assert first_frame_rows[0]["bbox"] == [300, 260, 900, 320]
    assert first_frame_rows[0]["center_y"] == 290.0
    assert len(evidence["layer_candidates"]) == 2
    assert {candidate["text"] for candidate in evidence["layer_candidates"]} == {"화면 문구", "대화"}
    assert all("average_bbox" in candidate and "average_center_y" in candidate for candidate in evidence["layer_candidates"])
    assert "不同 y 行" in payload["messages"][0]["content"]
    assert "按语义而不是位置" in payload["messages"][0]["content"]
    assert "upper_text_candidate" in payload["messages"][0]["content"]
    assert "[脸红]我有点害羞" in payload["messages"][0]["content"]
    assert "一个字或一个词逐步出现" in payload["messages"][0]["content"]
    assert "停车场字样" in payload["messages"][0]["content"]
    assert "[이선빈] 섭외한 방으로 피신" in payload["messages"][0]["content"]
    assert "subject_label='이선빈'" in payload["messages"][0]["content"]
    assert "完整的节目叙述或主说明" in payload["messages"][0]["content"]


def test_layered_evidence_uniformly_samples_frames_but_uses_full_support() -> None:
    cues = [SubtitleCue(index=1, start=0.0, end=3.0, text="계속 보이는 자막")]
    boxes = [
        OCRBox("계속 보이는 자막", (400, 850, 1200, 920), 0.98, index / 10, index, "bottom")
        for index in range(30)
    ]
    config = LayeredOCRRefinementConfig(max_frames_per_cue=5)

    payload = build_layered_refinement_payload(cues, boxes, model="lite", config=config)
    evidence = json.loads(payload["messages"][1]["content"].split("输入：\n", 1)[1])["cue_evidence"][0]

    assert evidence["observed_frame_count"] == 30
    assert evidence["sampled_frame_count"] == 5
    assert evidence["frame_sampling"] == {
        "strategy": "uniform_with_endpoints",
        "total": 30,
        "included": 5,
    }
    assert [frame["frame_index"] for frame in evidence["frame_observations"]][0::4] == [0, 29]
    assert evidence["layer_candidates"][0]["frame_support"] == 30
    assert evidence["layer_candidates"][0]["support_ratio"] == 1.0


def test_orphan_variant_family_combines_same_position_ocr_spellings() -> None:
    cue = SubtitleCue(
        index=1,
        start=1.0,
        end=2.3,
        text="으허성",
        source_track_id=-1_000_001,
    )
    spellings = ("으허성", "으허엉 000", "으허성 000", "으허성", "으허엉 000", "으허성 000")
    boxes = [
        OCRBox(text, (470, 348, 702, 441), 0.92, 1.1 + index * 0.2, 30 + index, "full_middle")
        for index, text in enumerate(spellings)
    ]

    evidence = build_cue_layer_evidence(cue, boxes)

    assert len(evidence["variant_families"]) == 1
    family = evidence["variant_families"][0]
    assert family["frame_support"] == 6
    assert family["recovery_eligible"] is True
    assert {variant["text"] for variant in family["variants"]} == {
        "으허성",
        "으허엉 000",
        "으허성 000",
    }
    assert all(candidate["recovery_eligible"] for candidate in evidence["layer_candidates"])


def test_recovery_candidate_timing_is_trimmed_to_observed_family() -> None:
    raw = [SubtitleCue(index=1, start=0.0, end=10.0, text="긴 원시 구간")]
    boxes = [
        OCRBox("흔들", (500, 600, 800, 680), 0.96, time, frame, "full_middle")
        for frame, time in enumerate((5.0, 5.2, 5.4, 5.6), start=20)
    ]

    merged, debug = layered_refine._merge_recovery_cues(
        [],
        raw,
        boxes,
        config=LayeredOCRRefinementConfig(),
    )

    assert debug["accepted_count"] == 1
    assert len(merged) == 1
    assert merged[0].start == 4.9
    assert merged[0].end == 5.85


def test_recovery_merges_high_confidence_single_syllable_effect_lead_in() -> None:
    raw = [
        SubtitleCue(index=1, start=1.0, end=1.6, text="핵-"),
        SubtitleCue(index=2, start=1.64, end=2.8, text="X X"),
    ]
    boxes = [
        *[
            OCRBox("핵-", (700, 330, 850, 450), 0.99, time, frame, "full_middle")
            for frame, time in enumerate((1.0, 1.2, 1.4), start=10)
        ],
        *[
            OCRBox("핵-", (702, 332, 852, 452), 0.99, time, frame, "full_middle")
            for frame, time in enumerate((1.7, 1.9, 2.1, 2.3, 2.5), start=20)
        ],
    ]

    merged, debug = layered_refine._merge_recovery_cues(
        [],
        raw,
        boxes,
        config=LayeredOCRRefinementConfig(),
    )

    assert debug["accepted_count"] == 1
    assert debug["accepted"][0]["merged_raw_ids"] == [1, 2]
    assert len(merged) == 1
    assert merged[0].start == 1.0
    assert merged[0].end == 2.75


def test_orphan_guard_requires_real_stable_evidence_reference() -> None:
    event = {
        "cue_id": 1,
        "layers": [{"id": "effect", "role": "visual_annotation", "text": "凭空字幕"}],
    }
    evidence = {
        "cue_id": 1,
        "baseline_kind": "orphan_candidate",
        "machine_text": "빼콤",
        "layer_candidates": [
            {
                "layer_id": "L1",
                "text": "빼콤",
                "recovery_eligible": True,
            }
        ],
    }

    guarded = apply_spatial_role_guard([event], [evidence])

    assert guarded == [{"cue_id": 1, "layers": []}]


def test_orphan_guard_forces_known_mbc_transition_bumper_to_noise() -> None:
    event = {
        "cue_id": 1,
        "layers": [
            {
                "id": "wrong_main",
                "role": "dialogue",
                "text": "에뜨는 -",
                "evidence_layer_ids": ["L1"],
            }
        ],
    }
    evidence = {
        "cue_id": 1,
        "baseline_kind": "orphan_candidate",
        "machine_text": "에뜨는 -",
        "layer_candidates": [
            {"layer_id": "L1", "text": "에뜨는 -", "recovery_eligible": True},
            {"layer_id": "L2", "text": "미또루", "recovery_eligible": True},
        ],
    }

    guarded = apply_spatial_role_guard([event], [evidence])

    assert guarded[0]["layers"][0]["role"] == "noise"
    assert guarded[0]["layers"][0]["reason"] == "known full-screen transition bumper"


def test_dense_upper_text_cannot_evict_lower_dialogue_row() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="아래 대화")]
    boxes = [
        OCRBox(f"위{index}", (index * 20, 250, index * 20 + 18, 290), 0.999, 1.2, 36, "full_middle")
        for index in range(30)
    ]
    boxes.append(OCRBox("아래 대화", (500, 850, 1100, 920), 0.80, 1.2, 36, "bottom"))
    config = LayeredOCRRefinementConfig(max_boxes_per_frame=8)

    payload = build_layered_refinement_payload(cues, boxes, model="lite", config=config)
    evidence = json.loads(payload["messages"][1]["content"].split("输入：\n", 1)[1])["cue_evidence"][0]
    rows = evidence["frame_observations"][0]["rows"]

    assert len(rows) == 2
    assert rows[1]["text"] == "아래 대화"
    assert rows[0]["box_count"] == 30
    assert sum(row["sampled_box_count"] for row in rows) == 8
    assert any(candidate["text"] == "아래 대화" for candidate in evidence["layer_candidates"])


def test_identical_text_at_two_y_positions_stays_two_layer_candidates() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="같은 글자")]
    boxes = [
        OCRBox("같은 글자", (300, 250, 900, 310), 0.95, 1.2, 36, "full_middle"),
        OCRBox("같은 글자", (500, 850, 1100, 920), 0.98, 1.2, 36, "bottom"),
    ]

    payload = build_layered_refinement_payload(cues, boxes, model="lite")
    evidence = json.loads(payload["messages"][1]["content"].split("输入：\n", 1)[1])["cue_evidence"][0]

    assert len(evidence["layer_candidates"]) == 2
    assert [candidate["average_center_y"] for candidate in evidence["layer_candidates"]] == [280.0, 885.0]


def test_layer_candidate_clustering_survives_height_jitter_and_old_bin_boundary() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="[꽃게]")]
    boxes = [
        # Centers 887/889 straddle the old fixed 48px rounded-bin boundary,
        # while box heights vary substantially. They are one visual line.
        OCRBox("[꽃게]", (300, 872, 500, 902), 0.95, 1.1, 33, "bottom"),
        OCRBox("[꽃게]", (302, 839, 502, 939), 0.96, 1.4, 42, "full_lower"),
        OCRBox("[꽃게]", (301, 854, 501, 924), 0.97, 1.7, 51, "bottom"),
        # Identical text at a genuinely different y remains a second layer.
        OCRBox("[꽃게]", (300, 490, 500, 550), 0.94, 1.4, 42, "full_middle"),
    ]

    payload = build_layered_refinement_payload(cues, boxes, model="lite")
    evidence = json.loads(payload["messages"][1]["content"].split("输入：\n", 1)[1])["cue_evidence"][0]
    candidates = [candidate for candidate in evidence["layer_candidates"] if candidate["text"] == "[꽃게]"]

    assert len(candidates) == 2
    assert sorted(candidate["frame_support"] for candidate in candidates) == [1, 3]
    assert sorted(round(candidate["average_center_y"]) for candidate in candidates) == [520, 888]


def test_upper_text_hint_does_not_override_dialogue_semantics() -> None:
    cue = SubtitleCue(index=1, start=1.0, end=2.0, text="我有点害羞")
    boxes = [
        OCRBox("我有点", (300, 490, 900, 552), 0.96, time, frame, "full_middle")
        for time, frame in ((1.1, 33), (1.5, 45), (1.9, 57))
    ] + [
        OCRBox("我有点害羞", (500, 880, 1200, 958), 0.98, time, frame, "bottom")
        for time, frame in ((1.1, 33), (1.5, 45), (1.9, 57))
    ]
    evidence = build_cue_layer_evidence(cue, boxes)
    assert [(item["layer_id"], item["role_hint"]) for item in evidence["layer_candidates"]] == [
        ("L1", "upper_text_candidate"),
        ("L2", "lower_text_candidate"),
    ]
    model_events = [
        {
            "cue_id": 1,
            "layers": [
                {"id": "upper", "role": "dialogue", "text": "我有点", "evidence_layer_ids": ["L1"]},
                {"id": "lower", "role": "dialogue", "text": "我有点害羞", "evidence_layer_ids": ["L2"]},
            ],
        }
    ]

    guarded = apply_spatial_role_guard(model_events, [evidence])
    rendered = apply_layered_events([cue], guarded)

    assert [layer["role"] for layer in guarded[0]["layers"]] == ["dialogue", "dialogue"]
    assert rendered[0].text == "我有点害羞"
    assert (rendered[0].start, rendered[0].end) == (1.0, 2.0)


def test_short_bracketed_hint_is_semantically_neutral() -> None:
    cue = SubtitleCue(index=1, start=1.0, end=2.0, text="[꽃게] 이선빈 안녕하세요")
    boxes = [
        OCRBox("[꽃게]", (300, 825, 480, 875), 0.97, time, frame, "bottom")
        for time, frame in ((1.1, 33), (1.5, 45), (1.9, 57))
    ] + [
        OCRBox("안녕하세요", (650, 880, 1200, 950), 0.98, time, frame, "bottom")
        for time, frame in ((1.1, 33), (1.5, 45), (1.9, 57))
    ]
    evidence = build_cue_layer_evidence(cue, boxes)
    assert [item["role_hint"] for item in evidence["layer_candidates"]] == [
        "short_bracketed_candidate",
        "lower_text_candidate",
    ]
    model_events = [
        {
            "cue_id": 1,
            "layers": [
                {"id": "speaker", "role": "dialogue", "text": "[꽃게]", "evidence_layer_ids": ["L1"]},
                {"id": "dialogue", "role": "dialogue", "text": "안녕하세요", "evidence_layer_ids": ["L2"]},
            ],
        }
    ]

    guarded = apply_spatial_role_guard(model_events, [evidence])
    rendered = apply_layered_events([cue], guarded)

    assert [layer["role"] for layer in guarded[0]["layers"]] == ["dialogue", "dialogue"]
    assert rendered[0].text == "[꽃게]\n안녕하세요"


def test_duplicate_dialogue_variants_keep_only_the_most_complete_text() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="我有点害羞")]
    events = _event(
        {"id": "upper", "role": "dialogue", "text": "我有点"},
        {"id": "lower", "role": "dialogue", "text": "我有点害羞"},
        {"id": "duplicate", "role": "dialogue", "text": "我 有点害羞！"},
    )

    result = apply_layered_events(cues, events)

    assert result[0].text == "我 有点害羞！"


def test_layered_parser_rejects_free_timestamps_and_missing_cues() -> None:
    with_timestamp = json.dumps(
        {
            "events": [
                {
                    "cue_id": 1,
                    "start": "00:00:00,000",
                    "layers": [{"role": "dialogue", "text": "안녕"}],
                }
            ]
        },
        ensure_ascii=False,
    )

    try:
        parse_layered_refinement_response(with_timestamp, {1})
    except ValueError as exc:
        assert "cue_id and layers" in str(exc)
    else:
        raise AssertionError("free timestamps must be rejected")

    try:
        parse_layered_refinement_response('{"events":[]}', {1})
    except ValueError as exc:
        assert "cover every target cue" in str(exc)
    else:
        raise AssertionError("missing target cue must be rejected")


def test_layered_parser_accepts_semantic_labels_and_rejects_old_position_role() -> None:
    content = json.dumps(
        {
            "events": [
                {
                    "cue_id": 1,
                    "layers": [
                        {
                            "id": "annotation",
                            "role": "visual_annotation",
                            "text": "脸红",
                            "attach_to": "dialogue",
                        },
                        {
                            "id": "subject",
                            "role": "subject_label",
                            "text": "主角",
                            "attach_to": "dialogue",
                        },
                        {"id": "dialogue", "role": "dialogue", "text": "我有点害羞"},
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )

    events = parse_layered_refinement_response(content, {1})

    assert events[0]["layers"][0]["role"] == "visual_annotation"
    assert events[0]["layers"][1]["role"] == "subject_label"

    old_role = content.replace("visual_annotation", "screen_caption")
    try:
        parse_layered_refinement_response(old_role, {1})
    except ValueError as exc:
        assert "invalid role" in str(exc)
    else:
        raise AssertionError("position-based screen_caption role must be rejected")


def test_default_v2_payload_has_no_geometry_contract() -> None:
    cue = SubtitleCue(index=1, start=1.0, end=2.0, text="안녕하세요")
    boxes = [
        OCRBox("안녕하세요", (500, 850, 1100, 930), 0.98, 1.4, 42, "bottom"),
    ]

    payload = build_layered_refinement_payload([cue], boxes, model="lite")
    system_prompt = payload["messages"][0]["content"]
    user_prompt = payload["messages"][1]["content"]
    evidence = json.loads(user_prompt.split("输入：\n", 1)[1])

    assert evidence["context_cues"][0]["baseline_kind"] == "ocr2_refined"
    assert evidence["cue_evidence"][0]["baseline_kind"] == "ocr2_refined"
    assert "geometry_hints" not in evidence["cue_evidence"][0]
    assert "OCR 3.0" not in system_prompt
    assert "软先验而不是删除指令" not in system_prompt
    assert "尚未完成物品字/环境字的语义筛选" not in system_prompt
    assert "ocr2_refined 不确定时沿用 machine_text" in user_prompt


def test_v3_geometry_hint_mapping_prioritizes_related_track_before_longer_unrelated_overlap() -> None:
    cue = SubtitleCue(index=1, start=1.0, end=2.0, text="안녕하세요")
    boxes = [
        OCRBox("안녕하세요", (500, 850, 1100, 930), 0.98, 1.45, 43, "bottom"),
    ]
    geometry_hints = [
        {
            "track_id": 10,
            "text": "MBC",
            "start": 1.0,
            "end": 2.0,
            "sample_count": 30,
            "classification": "logo",
            "server_action": "drop",
            "stable_slanted_program_candidate": False,
            "soft_prior_only": True,
        },
        {
            "track_id": 20,
            "text": "안녕하세요",
            "start": 1.40,
            "end": 1.55,
            "sample_count": 2,
            "classification": "subtitle",
            "server_action": "keep",
            "stable_slanted_program_candidate": False,
            "soft_prior_only": True,
        },
    ]

    payload = build_layered_refinement_payload(
        [cue],
        boxes,
        model="lite",
        config=LayeredOCRRefinementConfig(
            pipeline_version="v3",
            max_geometry_hints_per_cue=1,
        ),
        geometry_hints=geometry_hints,
    )
    system_prompt = payload["messages"][0]["content"]
    user_prompt = payload["messages"][1]["content"]
    evidence = json.loads(user_prompt.split("输入：\n", 1)[1])
    cue_evidence = evidence["cue_evidence"][0]

    assert cue_evidence["baseline_kind"] == "ocr3_refined"
    assert [item["track_id"] for item in cue_evidence["geometry_hints"]] == [20]
    assert cue_evidence["geometry_hints"][0]["soft_prior_only"] is True
    assert "软先验而不是删除指令" in system_prompt
    assert "server_action='drop'" in system_prompt
    assert "尚未完成物品字/环境字的语义筛选" in system_prompt
    assert "停车场标识" in system_prompt
    assert "不是所谓 previous-cue leakage" in system_prompt
    assert "[선물 줍줍]아니 왜냐면!" in system_prompt
    assert "[박보영] 이렇게 하고 나갔는데" in system_prompt
    assert "QC、AU、TDKO" in system_prompt
    assert "moving_slanted_surface_candidate" in system_prompt
    assert "사장 박영희" in system_prompt
    assert "클래식 명패" in system_prompt
    assert "ocr3_refined 不确定时沿用 machine_text" in user_prompt


def test_v3_geometry_drop_is_only_a_prompt_hint_and_debug_records_its_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.v3.refined.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    geometry_path = tmp_path / "ocr_geometry.json"
    out = tmp_path / "source.v3.layered.srt"
    debug_path = tmp_path / "ocr_v3_layers.json"
    write_srt(
        [SubtitleCue(index=1, start=1.0, end=2.0, text="클래식 명패")],
        source,
    )
    boxes = [
        OCRBox("클래식 명패", (420, 360, 1020, 450), 0.96, 1.2, 36, "full_middle"),
        OCRBox("클래식 명패", (422, 362, 1022, 452), 0.97, 1.6, 48, "full_middle"),
    ]
    boxes_path.write_text(
        json.dumps([box.to_dict() for box in boxes], ensure_ascii=False),
        encoding="utf-8",
    )
    geometry_path.write_text(
        json.dumps(
            {
                "version": 3,
                "mode": "ocr3_geometry_semantic_refinement",
                "track_evidence": [
                    {
                        "track_id": 7,
                        "text": "클래식 명패",
                        "start": 1.0,
                        "end": 2.0,
                        "sample_count": 6,
                        "average_confidence": 0.96,
                        "average_bbox": [420, 360, 1020, 450],
                        "geometry": {"angle": {"median_abs_degrees": 21.0}},
                        "server_features": {
                            "dynamic_perspective_flags": ["center_motion", "scale_change"],
                            "dynamic_perspective_evidence_count": 2,
                            "stable_slanted_program_candidate": False,
                            "persistent_logo_candidate": False,
                        },
                    }
                ],
                "actions": [
                    {
                        "track_id": 7,
                        "classification": "scene_text",
                        "action": "drop",
                        "reason": "scene text geometry",
                        "fallback": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(layered_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(
        layered_refine,
        "load_llm_task_config",
        lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"),
    )
    captured_payload: dict[str, object] = {}

    def fake_request(endpoint, api_key, payload):
        del endpoint, api_key
        captured_payload.update(payload)
        return json.dumps(
            {
                "events": [
                    {
                        "cue_id": 1,
                        "layers": [
                            {
                                "id": "main",
                                "role": "dialogue",
                                "text": "클래식 명패",
                                "evidence_layer_ids": ["L1"],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(layered_refine, "_request_translation", fake_request)

    refine_ocr_layers_with_llm(
        source,
        boxes_path,
        out,
        debug_path,
        geometry_json=geometry_path,
        config=LayeredOCRRefinementConfig(pipeline_version="v3"),
    )

    assert [cue.text for cue in read_srt(out)] == ["클래식 명패"]
    payload_evidence = json.loads(
        str(captured_payload["messages"][1]["content"]).split("输入：\n", 1)[1]
    )["cue_evidence"][0]
    assert payload_evidence["geometry_hints"][0]["classification"] == "scene_text"
    assert payload_evidence["geometry_hints"][0]["server_action"] == "drop"
    assert payload_evidence["geometry_hints"][0]["soft_prior_only"] is True

    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    assert debug["version"] == 3
    assert debug["mode"] == "ocr3_geometry_assisted_layered_refinement"
    assert debug["policy_revision"] == "v3.1-moving-surface-v1"
    assert debug["geometry_json"] == str(geometry_path)
    assert debug["geometry_hint_count"] == 1
    assert debug["batches"][0]["evidence"][0]["geometry_hints"][0]["track_id"] == 7


def test_old_v3_geometry_hint_normalizes_moving_slanted_text_without_static_protection(
    tmp_path: Path,
) -> None:
    geometry_path = tmp_path / "ocr_geometry.json"
    geometry_path.write_text(
        json.dumps(
            {
                "track_evidence": [
                    {
                        "track_id": 14,
                        "text": "사장박영희",
                        "start": 1.835,
                        "end": 4.338,
                        "sample_count": 14,
                        "average_confidence": 0.91,
                        "average_bbox": [861.86, 441.36, 1114.21, 604.43],
                        "geometry": {
                            "angle": {"median_abs_degrees": 26.251},
                            "motion": {
                                "center_range_box_diagonals": 0.4292,
                                "direct_displacement_box_diagonals": 0.3203,
                            },
                        },
                        "server_features": {
                            "dynamic_perspective_flags": [],
                            "dynamic_perspective_evidence_count": 0,
                            # This is how the pre-3.1 artifact was stored.
                            "stable_slanted_program_candidate": True,
                        },
                    }
                ],
                "actions": [
                    {
                        "track_id": 14,
                        "classification": "program_caption",
                        "action": "keep",
                        "reason": "semantic class program_caption",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    hints = layered_refine._load_geometry_hints(geometry_path)

    assert hints[0]["moving_slanted_surface_candidate"] is True
    assert hints[0]["stable_slanted_program_candidate"] is False


def test_old_v3_geometry_hint_does_not_infer_surface_text_without_legacy_stability(
    tmp_path: Path,
) -> None:
    geometry_path = tmp_path / "ocr_geometry.json"
    geometry_path.write_text(
        json.dumps(
            {
                "track_evidence": [
                    {
                        "track_id": 9,
                        "text": "회전하는 프로그램 자막",
                        "start": 1.0,
                        "end": 2.0,
                        "sample_count": 6,
                        "geometry": {
                            "angle": {"median_abs_degrees": 22.0},
                            "motion": {
                                "center_range_box_diagonals": 0.8,
                                "direct_displacement_box_diagonals": 0.6,
                            },
                        },
                        "server_features": {
                            "dynamic_perspective_flags": ["center_motion", "rotation_change"],
                            "stable_slanted_program_candidate": False,
                        },
                    }
                ],
                "actions": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    hints = layered_refine._load_geometry_hints(geometry_path)

    assert hints[0]["moving_slanted_surface_candidate"] is False
    assert hints[0]["stable_slanted_program_candidate"] is False
