from __future__ import annotations

import json
from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.subtitle.dual_reference import build_dual_reference_cues, write_dual_reference_outputs
from video_translate.subtitle.srt import read_srt


def test_build_dual_reference_cues_keeps_source_timing_and_adds_english_reference():
    source = [
        SubtitleCue(index=1, start=1.0, end=3.0, text="안녕하세요"),
        SubtitleCue(index=2, start=4.0, end=5.0, text="잘 부탁드립니다"),
    ]
    reference = [
        SubtitleCue(index=1, start=0.9, end=2.9, text="Hello."),
        SubtitleCue(index=2, start=8.0, end=9.0, text="No overlap"),
    ]

    cues, debug = build_dual_reference_cues(source, reference)

    assert cues[0].start == 1.0
    assert cues[0].end == 3.0
    assert cues[0].text == "韩文原文：안녕하세요\n英文参考：Hello."
    assert cues[1].text == "韩文原文：잘 부탁드립니다"
    assert debug[0]["reference_text"] == "Hello."
    assert debug[0]["overlap_seconds"] > 1.0
    assert debug[1]["reference_text"] == ""


def test_write_dual_reference_outputs_writes_source_context_and_debug(tmp_path: Path):
    source = [SubtitleCue(index=1, start=0.0, end=1.0, text="안녕")]
    reference = [SubtitleCue(index=1, start=0.0, end=1.0, text="Hi")]

    result = write_dual_reference_outputs(source, reference, tmp_path)

    source_cues = read_srt(result["source_srt"])
    context_cues = read_srt(result["context_srt"])
    debug = json.loads(result["debug_json"].read_text(encoding="utf-8"))

    assert source_cues[0].text == "韩文原文：안녕\n英文参考：Hi"
    assert context_cues[0].text == source_cues[0].text
    assert debug[0]["source_text"] == "안녕"
    assert debug[0]["reference_text"] == "Hi"
