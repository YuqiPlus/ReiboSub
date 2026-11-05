import json
from types import SimpleNamespace

import pytest

from scripts.asr3_benchmark import inference_windows, vad_inference_windows


def test_aligned_report_prioritizes_engine_disagreement_not_timing_only(tmp_path):
    from scripts.asr3_benchmark import report, save_json
    sample = {"id": "clip", "label": "test", "start": 0, "duration": 10,
              "review_points": [{"start": 1, "end": 2, "label": "轻声候选"}]}
    for engine, suffix, text in [("whisper", "asr2", "다른 말"),
                                 ("qwen_vad", "qwen3", "안녕하세요"),
                                 ("qwen_vad_aligned", "qwen3", "안녕하세요")]:
        folder = tmp_path / "clip" / engine
        save_json(folder / f"cues.{suffix}.json", {
            "cues": [{"start": 1, "end": 2, "text": text}]})
        save_json(folder / "benchmark.json", {})
    save_json(tmp_path / "clip/vad.json", {})
    save_json(tmp_path / "clip/qwen_vad_aligned/alignment_audit.json", [])
    report({"samples": [sample]}, tmp_path, SimpleNamespace(qwen_dir="qwen_vad_aligned"))
    result = json.loads((tmp_path / "comparison-aligned.json").read_text())
    assert result["windows"][0]["disagreement"] == 1
    assert result["samples"][0]["review_points"] == sample["review_points"]


def test_vad_keeps_original_offsets_across_a_long_silent_gap():
    # Removing the 3-second gap must not move the second utterance to 1 second.
    assert inference_windows(96000, 16000, 30, [
        {"start": 16000, "end": 32000},
        {"start": 80000, "end": 96000},
    ]) == [(16000, 32000), (80000, 96000)]


def test_vad_empty_speech_does_not_fall_back_to_transcribing_silence():
    assert inference_windows(160000, 16000, 30, []) == []
    assert vad_inference_windows(160000, 16000, 30, []) == []


def test_gate_preserves_context_and_absolute_offsets_in_active_windows():
    assert vad_inference_windows(90 * 16000, 16000, 30, [
        {"start": 16000, "end": 20000},
        {"start": 70 * 16000, "end": 71 * 16000},
    ]) == [(0, 30 * 16000), (60 * 16000, 90 * 16000)]


def test_speech_ending_at_boundary_does_not_open_the_next_silent_window():
    assert vad_inference_windows(60 * 16000, 16000, 30, [
        {"start": 0, "end": 30 * 16000},
    ]) == [(0, 30 * 16000)]


def test_long_speech_is_bounded_without_overlapping_or_losing_frames():
    assert inference_windows(1_000_000, 16000, 30, [
        {"start": 100, "end": 999_999},
    ]) == [(100, 480100), (480100, 960100), (960100, 999999)]


@pytest.mark.parametrize("regions", [
    [{"start": -1, "end": 10}],
    [{"start": 1, "end": 1}],
    [{"start": 0, "end": 1001}],
    [{"start": 0, "end": 600}, {"start": 500, "end": 800}],
])
def test_invalid_vad_offsets_cannot_silently_shift_subtitle_timing(regions):
    with pytest.raises(ValueError, match="Speech regions"):
        inference_windows(1000, 16000, 30, regions)
