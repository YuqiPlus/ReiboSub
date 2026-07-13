from __future__ import annotations

import json
from pathlib import Path

from video_translate.llm_config import LLMTaskConfig
from video_translate.models import OCRBox, SubtitleCue
from video_translate import run_config as run_config_mod
from video_translate.ocr import llm_refine
from video_translate.ocr.llm_refine import (
    OCRRefinementConfig,
    SourceCleanupConfig,
    apply_ocr_refinement_actions,
    build_ocr_refinement_payload,
    cleanup_ocr_source_with_llm,
    refine_ocr_source_with_llm,
)
from video_translate.subtitle.srt import read_srt, write_srt


def test_build_ocr_refinement_payload_contains_track_evidence() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="안녕\n하세요")]
    boxes = [OCRBox("안녕하세요", (500, 880, 1200, 940), 0.96, 1.2, 36, "bottom")]

    payload = build_ocr_refinement_payload(cues, boxes, model="lite", config=OCRRefinementConfig())
    content = payload["messages"][1]["content"]

    assert "cue_evidence" in content
    assert "machine_text" in content
    assert "reading_candidates" in content
    assert "token_candidates" in content
    assert "evidence_strength" in content
    assert "context_cues" in content
    assert "안녕하세요" in content
    assert "bottom" in content
    system_prompt = payload["messages"][0]["content"]
    assert "必须先把每个目标分类" in system_prompt
    assert "绝对不要串接 machine_text 与候选" in system_prompt


def test_build_ocr_refinement_payload_adds_visual_reading_order() -> None:
    cues = [SubtitleCue(index=1, start=13.9, end=16.5, text="뭔가 아")]
    boxes = [
        OCRBox("뭔가", (670, 831, 892, 910), 1.0, 14.2, 426, "bottom"),
        OCRBox("두고", (890, 837, 1096, 912), 1.0, 14.2, 426, "bottom"),
        OCRBox("갔에!", (1094, 831, 1356, 914), 0.97, 14.2, 426, "bottom"),
        OCRBox("아", (569, 863, 663, 934), 1.0, 14.2, 426, "bottom"),
    ]

    payload = build_ocr_refinement_payload(cues, boxes, model="lite")
    content = payload["messages"][1]["content"]

    assert '"text": "아 뭔가 두고 갔에!"' in content


def test_build_ocr_refinement_payload_marks_single_frame_noise_as_weak_evidence() -> None:
    cues = [SubtitleCue(index=1, start=11.0, end=12.8, text="똑똑똑 V0")]
    boxes = [
        OCRBox("똑똑똑", (700, 850, 1040, 930), 0.98, 11.1, 333, "bottom"),
        OCRBox("똑똑똑", (700, 850, 1040, 930), 0.99, 11.3, 339, "bottom"),
        OCRBox("똑똑똑", (700, 850, 1040, 930), 0.99, 11.5, 345, "bottom"),
        OCRBox("V0", (1050, 850, 1110, 930), 0.42, 11.3, 339, "bottom"),
    ]

    payload = build_ocr_refinement_payload(cues, boxes, model="lite")
    content = payload["messages"][1]["content"]

    assert '"text": "똑똑똑", "frames": 3' in content
    assert '"text": "V0", "frames": 1' in content


def test_refine_ocr_source_with_llm_writes_refined_srt(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.machine.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "source.refined.srt"
    write_srt(
        [
            SubtitleCue(index=1, start=1.0, end=1.5, text="안녕"),
            SubtitleCue(index=2, start=1.5, end=2.0, text="하세요"),
        ],
        source,
    )
    boxes_path.write_text(
        json.dumps(
            [
                OCRBox("안녕하세요", (500, 880, 1200, 940), 0.96, 1.1, 33, "bottom").to_dict(),
                OCRBox("로고", (20, 20, 120, 70), 0.99, 1.1, 33, "full_top").to_dict(),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(llm_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(llm_refine, "load_llm_task_config", lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"))
    monkeypatch.setattr(
        llm_refine,
        "_request_translation",
        lambda endpoint, key, payload: json.dumps(
            {
                "actions": [
                    {
                        "ids": [1, 2],
                        "classification": "subtitle",
                        "action": "merge",
                        "text": "안녕하세요",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    progress: list[str] = []
    result = refine_ocr_source_with_llm(
        source,
        boxes_path,
        out,
        config=OCRRefinementConfig(batch_size=4),
        progress_callback=progress.append,
    )

    cues = read_srt(out)
    assert result["refined_srt"] == out
    assert len(cues) == 1
    assert cues[0].text == "안녕하세요"
    assert cues[0].start == 1.0
    assert cues[0].end == 2.0
    assert progress[0] == "ocr_refine_model: lite"
    assert progress[1] == "ocr_refine: 2 cues in 1 batches"


def test_apply_ocr_refinement_actions_drops_unmerged_single_sample() -> None:
    cues = [SubtitleCue(index=1, start=24.858, end=24.985, text="이선빈")]
    boxes = [OCRBox("이선빈", (800, 850, 1040, 930), 0.99, 24.9, 747, "bottom")]
    actions = [{"id": 1, "classification": "program_caption", "action": "keep"}]

    assert apply_ocr_refinement_actions(cues, boxes, actions) == []


def test_refinement_merges_adjacent_duplicate_flicker(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    boxes_path = tmp_path / "ocr_boxes.json"
    out = tmp_path / "refined.srt"
    write_srt(
        [
            SubtitleCue(index=1, start=58.559, end=58.852, text="저 문어인가 봐요!"),
            SubtitleCue(index=2, start=58.892, end=59.019, text="저 문어인가 봐요!"),
        ],
        source,
    )
    boxes_path.write_text(
        json.dumps(
            [
                OCRBox("저 문어인가 봐요!", (500, 850, 1400, 940), 0.99, 58.6, 1758, "bottom").to_dict(),
                OCRBox("저 문어인가 봐요!", (500, 850, 1400, 940), 0.99, 58.8, 1764, "bottom").to_dict(),
                OCRBox("저 문어인가 봐요!", (500, 850, 1400, 940), 0.99, 58.95, 1769, "bottom").to_dict(),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(llm_refine, "load_llm_task_config", lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"))
    monkeypatch.setattr(
        llm_refine,
        "_request_translation",
        lambda endpoint, key, payload: json.dumps(
            {
                "actions": [
                    {"id": 1, "classification": "subtitle", "action": "keep"},
                    {"id": 2, "classification": "subtitle", "action": "keep"},
                ]
            },
            ensure_ascii=False,
        ),
    )

    refine_ocr_source_with_llm(source, boxes_path, out, config=OCRRefinementConfig(batch_size=4))

    cues = read_srt(out)
    assert len(cues) == 1
    assert cues[0].start == 58.559
    assert cues[0].end == 59.019
    assert cues[0].text == "저 문어인가 봐요!"


def test_cleanup_ocr_source_with_llm_drops_contextual_noise(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    out = tmp_path / "source.cleaned.srt"
    write_srt(
        [
            SubtitleCue(index=1, start=332.999, end=335.295, text="총이 있지만\n총쏠생각을못 하는"),
            SubtitleCue(index=2, start=335.335, end=336.035, text="SISNEpt"),
            SubtitleCue(index=3, start=335.335, end=337.964, text="(더각성이 필요해!!!)"),
        ],
        source,
    )

    monkeypatch.setattr(llm_refine, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(llm_refine, "load_llm_task_config", lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://llm", api_key="key"))
    monkeypatch.setattr(
        llm_refine,
        "_request_translation",
        lambda endpoint, key, payload: json.dumps(
            {
                "actions": [
                    {"id": 1, "action": "keep"},
                    {"id": 2, "action": "drop", "reason": "watermark/OCR noise"},
                    {"id": 3, "action": "keep"},
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = cleanup_ocr_source_with_llm(source, out, config=SourceCleanupConfig(batch_size=8, overlap=1))

    cues = read_srt(out)
    assert result["cleaned_srt"] == out
    assert [cue.text for cue in cues] == ["총이 있지만 총쏠생각을못 하는", "(더각성이 필요해!!!)"]
    assert all("SISNEpt" not in cue.text for cue in cues)


def test_run_config_applies_source_cleanup_after_ocr(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    input_video = tmp_path / "demo.mp4"
    input_video.write_bytes(b"video")
    config_path = config_dir / "run.yaml"
    config_path.write_text(
        "\n".join(
            [
                "mode: extract",
                f"input_video: {input_video}",
                "output_dir: outputs/job",
                "source_language: korean",
                "source_cleanup:",
                "  mode: llm_context",
                "  batch_size: 8",
                "  overlap: 1",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs" / "job"
    calls: dict[str, object] = {}

    def fake_extract(*args, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        source = output_dir / "source.srt"
        write_srt(
            [
                SubtitleCue(index=1, start=1.0, end=2.0, text="정상 자막"),
                SubtitleCue(index=2, start=2.1, end=2.7, text="SISNEpt"),
            ],
            source,
        )
        boxes = output_dir / "ocr_boxes.json"
        boxes.write_text("[]", encoding="utf-8")
        return {"source_srt": source, "ocr_boxes": boxes}

    def fake_cleanup(source_srt, out_srt, *, config, **kwargs):
        calls["source_srt"] = source_srt
        calls["config"] = config
        write_srt([SubtitleCue(index=1, start=1.0, end=2.0, text="정상 자막")], out_srt)
        return {"cleaned_srt": out_srt}

    monkeypatch.setattr(run_config_mod, "extract_subtitles_from_video", fake_extract)
    monkeypatch.setattr(run_config_mod, "cleanup_ocr_source_with_llm", fake_cleanup)

    run_config_mod.run_config(config_path)

    source = output_dir / "source.srt"
    assert (output_dir / "source.before_cleanup.srt").exists()
    assert calls["source_srt"] == output_dir / "source.before_cleanup.srt"
    assert calls["config"].batch_size == 8
    assert calls["config"].overlap == 1
    assert [cue.text for cue in read_srt(source)] == ["정상 자막"]
def test_run_config_preserves_raw_source_when_requested(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    input_video = tmp_path / "demo.mp4"
    input_video.write_bytes(b"video")
    config_path = config_dir / "run.yaml"
    config_path.write_text(
        "\n".join(
            [
                "mode: extract",
                f"input_video: {input_video}",
                "output_dir: outputs/job",
                "source_language: korean",
                "source_cleanup:",
                "  mode: llm_context",
                "  preserve_source: true",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs" / "job"

    def fake_extract(*args, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        source = output_dir / "source.srt"
        write_srt([SubtitleCue(index=1, start=1.0, end=2.0, text="raw OCR")], source)
        boxes = output_dir / "ocr_boxes.json"
        boxes.write_text("[]", encoding="utf-8")
        return {"source_srt": source, "ocr_boxes": boxes}

    def fake_cleanup(source_srt, out_srt, *, config, **kwargs):
        write_srt([SubtitleCue(index=1, start=1.0, end=2.0, text="cleaned OCR")], out_srt)
        return {"cleaned_srt": out_srt}

    monkeypatch.setattr(run_config_mod, "extract_subtitles_from_video", fake_extract)
    monkeypatch.setattr(run_config_mod, "cleanup_ocr_source_with_llm", fake_cleanup)

    run_config_mod.run_config(config_path)

    assert [cue.text for cue in read_srt(output_dir / "source.srt")] == ["raw OCR"]
    assert [cue.text for cue in read_srt(output_dir / "source.cleaned.srt")] == ["cleaned OCR"]
    assert [cue.text for cue in read_srt(output_dir / "source.before_cleanup.srt")] == ["raw OCR"]
