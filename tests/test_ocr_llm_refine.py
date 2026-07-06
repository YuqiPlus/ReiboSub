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
    build_ocr_refinement_payload,
    cleanup_ocr_source_with_llm,
    refine_ocr_source_with_llm,
)
from video_translate.subtitle.srt import read_srt, write_srt


def test_build_ocr_refinement_payload_contains_machine_cues_and_raw_boxes() -> None:
    cues = [SubtitleCue(index=1, start=1.0, end=2.0, text="안녕\n하세요")]
    boxes = [OCRBox("안녕하세요", (500, 880, 1200, 940), 0.96, 1.2, 36, "bottom")]

    payload = build_ocr_refinement_payload(cues, boxes, model="lite", config=OCRRefinementConfig())
    content = payload["messages"][1]["content"]

    assert "machine_cues" in content
    assert "raw_frames" in content
    assert "안녕하세요" in content
    assert "bottom" in content


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
            [{"start": "00:00:01,000", "end": "00:00:02,000", "text": "안녕하세요"}],
            ensure_ascii=False,
        ),
    )

    result = refine_ocr_source_with_llm(source, boxes_path, out, config=OCRRefinementConfig(batch_size=4))

    cues = read_srt(out)
    assert result["refined_srt"] == out
    assert len(cues) == 1
    assert cues[0].text == "안녕하세요"
    assert cues[0].start == 1.0
    assert cues[0].end == 2.0


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
