from __future__ import annotations

import json

from video_translate.llm_config import LLMTaskConfig
from video_translate.models import OCRBox, SubtitleCue
from video_translate.subtitle import hybrid_ocr
from video_translate.subtitle.hybrid_ocr import build_hybrid_source_cues, reconstruct_korean_cues_with_llm, write_hybrid_outputs
from video_translate.subtitle.srt import read_srt


def test_build_hybrid_source_preserves_anchor_timing_and_builds_ocr_context():
    anchors = [
        SubtitleCue(index=1, start=1.0, end=3.0, text="A London morning"),
        SubtitleCue(index=2, start=4.0, end=5.5, text="Fallback English"),
    ]
    boxes = [
        OCRBox(text="런던의 아침", bbox=(10, 800, 500, 850), confidence=0.96, time=1.5, frame_index=45),
        OCRBox(text="1234", bbox=(10, 100, 100, 140), confidence=0.99, time=1.5, frame_index=45),
    ]

    cues, debug = build_hybrid_source_cues(anchors, boxes)

    assert [(cue.start, cue.end) for cue in cues] == [(1.0, 3.0), (4.0, 5.5)]
    assert "韩文OCR候选：런던의 아침" in cues[0].text
    assert "英文参考：A London morning" in cues[0].text
    assert cues[1].text == "英文参考：Fallback English"
    assert debug[0]["mode"] == "ocr_context_with_english_reference"
    assert debug[1]["mode"] == "english_reference_fallback"


def test_write_hybrid_outputs_writes_reconstructed_korean_source(tmp_path):
    anchors = [SubtitleCue(index=1, start=0.0, end=1.0, text="Hello")]
    boxes = [OCRBox(text="안녕", bbox=(0, 0, 10, 10), confidence=0.93, time=0.4, frame_index=12)]

    result = write_hybrid_outputs(
        anchors,
        boxes,
        tmp_path,
        reconstruct_korean=True,
        reconstruct_fn=lambda cues, **kwargs: {1: "안녕"},
    )

    cues = read_srt(result["source_srt"])
    context_cues = read_srt(result["context_srt"])
    debug = json.loads(result["debug_json"].read_text(encoding="utf-8"))
    assert cues[0].start == 0.0
    assert cues[0].end == 1.0
    assert cues[0].text == "안녕"
    assert "英文参考：Hello" in context_cues[0].text
    assert debug[0]["anchor_text"] == "Hello"
    assert debug[0]["reconstructed_korean"] == "안녕"


def test_write_hybrid_outputs_falls_back_to_context_without_reconstruction(tmp_path):
    anchors = [SubtitleCue(index=1, start=0.0, end=1.0, text="Hello")]
    boxes = [OCRBox(text="안녕", bbox=(0, 0, 10, 10), confidence=0.93, time=0.4, frame_index=12)]

    result = write_hybrid_outputs(anchors, boxes, tmp_path)

    cues = read_srt(result["source_srt"])
    assert "韩文OCR候选：안녕" in cues[0].text


def test_reconstruct_korean_cues_splits_batch_when_model_returns_bad_json(monkeypatch):
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.0, text="英文参考：Hello"),
        SubtitleCue(index=2, start=1.0, end=2.0, text="英文参考：Thanks"),
    ]
    calls: list[list[int]] = []

    def fake_request(endpoint, key, payload):
        ids = [item["id"] for item in json.loads(payload["messages"][1]["content"])["items"]]
        calls.append(ids)
        if ids == [1, 2]:
            return '[{"id": 1, "ko": "안녕"} {"id": 2, "ko": "고마워"}]'
        return json.dumps([{"id": ids[0], "ko": "안녕" if ids[0] == 1 else "고마워"}], ensure_ascii=False)

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(hybrid_ocr, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(hybrid_ocr, "load_llm_task_config", lambda *args, **kwargs: LLMTaskConfig(model="lite", base_url="http://ark"))
    monkeypatch.setattr(hybrid_ocr, "_request_translation", fake_request)

    mapping = reconstruct_korean_cues_with_llm(cues, batch_size=2)

    assert mapping == {1: "안녕", 2: "고마워"}
    assert calls == [[1, 2], [1], [2]]
