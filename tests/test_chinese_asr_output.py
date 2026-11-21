from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from video_translate import web_agent
from video_translate.asr_v2 import AsrWord, write_asr_v2_outputs
from video_translate.chinese_script import (
    configure_chinese_output,
    convert_chinese_text,
    normalize_chinese_script,
    output_chinese_script,
)
from video_translate.subtitle.srt import read_srt

pytest.importorskip("opencc", reason="Chinese ASR conversion is installed with the asr extra")


@pytest.mark.parametrize("script,source,expected", [
    ("simplified", "數據標註與美學，AI 对吧。", "数据标注与美学，AI 对吧。"),
    ("traditional", "数据标注与美学，AI 对吧。", "數據標註與美學，AI 對吧。"),
    ("original", "數據与数据", "數據与数据"),
])
def test_script_conversion_preserves_content_and_punctuation(script, source, expected):
    assert convert_chinese_text(source, script) == expected


def test_script_policy_defaults_and_rejects_unknown_values(tmp_path):
    assert normalize_chinese_script(None) == "simplified"
    assert output_chinese_script(tmp_path) == "original"
    with pytest.raises(ValueError, match="中文输出"):
        normalize_chinese_script("unknown")
    assert configure_chinese_output(tmp_path, "traditional", "ja") == "original"
    assert output_chinese_script(tmp_path) == "original"


@pytest.mark.parametrize("script,expected", [("simplified", "数据标注与美学。"), ("traditional", "數據標註與美學。"), ("original", "數據标注與美学。")])
def test_v2_outputs_use_same_script_without_touching_words_or_times(tmp_path, script, expected):
    words = [AsrWord(index=1, start=1.2, end=2.8, text="數據标注與美学。", probability=.9, segment_id=0)]
    original = write_asr_v2_outputs(tmp_path, words)
    original_cues = read_srt(original["source_srt"])
    configure_chinese_output(tmp_path, script, "zh")
    output = write_asr_v2_outputs(tmp_path, words)
    cues = read_srt(output["source_srt"])
    assert [cue.text for cue in cues] == [expected]
    assert [(cue.index, cue.start, cue.end) for cue in cues] == [(cue.index, cue.start, cue.end) for cue in original_cues]
    assert output["transcript_text"] == output["plain_transcript_text"] == expected + "\n"
    assert words[0].text == "數據标注與美学。"
    assert output["words"][0].text == words[0].text
    assert json.loads(output["cues_path"].read_text())["cues"][0]["text"] == expected
    # Subsequent rebuilds (including gap review) retain the saved presentation policy.
    assert write_asr_v2_outputs(tmp_path, words)["transcript_text"] == expected + "\n"


@pytest.mark.parametrize("version", ["1.0", "2.0"])
@pytest.mark.parametrize("script,expected", [("simplified", "数据标注与美学。"), ("traditional", "數據標註與美學。"), ("original", "數據标注與美学。")])
def test_lab_script_applies_to_text_srt_sidecar_but_raw_evidence_stays_intact(monkeypatch, tmp_path, version, script, expected):
    audio = tmp_path / "YoutubeDownloads" / "demo" / "speech.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"synthetic")
    for name, value in {"ROOT": tmp_path, "DOWNLOAD_DIR": tmp_path / "YoutubeDownloads", "JOB_DIR": tmp_path / "outputs" / "agent_jobs"}.items():
        monkeypatch.setattr(web_agent, name, value)
    raw_text = "數據标注與美学。"
    raw_srt = f"1\n00:00:01,200 --> 00:00:02,800\n{raw_text}\n"

    def fake_command(job_id, args):
        out_dir = web_agent.JOB_DIR / job_id
        if version == "2.0":
            (out_dir / "source.raw.srt").write_text(raw_srt, encoding="utf-8")
            (out_dir / "words.json").write_text(json.dumps({"version": "2.2", "info": {"language": "zh"}, "words": [{"index": 1, "start": 1.2, "end": 2.8, "text": raw_text, "probability": .9, "segment_id": 0}]}, ensure_ascii=False), encoding="utf-8")
            (out_dir / "quality.json").write_text("{}", encoding="utf-8")
        else:
            (out_dir / "source.srt").write_text(raw_srt, encoding="utf-8")
            web_agent._append_log(job_id, "detected_language: zh")

    monkeypatch.setattr(web_agent, "_run_command", fake_command)
    job = web_agent.asr_lab_job({"input_video": str(audio), "source_language": "auto", "asr_version": version, "chinese_script": script})
    deadline = time.monotonic() + 5
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status == "done", job.error
    assert job.result["chinese_script"] == script
    assert job.result["transcript_text"] == expected + "\n"
    assert read_srt(Path(job.result["source_srt"]))[0].text == expected
    assert read_srt(Path(job.result["source_sidecar"]))[0].text == expected
    if version == "2.0" or script != "original":
        assert Path(job.result["raw_source_srt"]).read_text(encoding="utf-8") == raw_srt
    if version == "2.0":
        path = Path(job.result["words_path"])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        reviewed = path.parent / "source.reviewed.srt"
        result = web_agent._write_asr_reviewed_outputs(Path(job.result["source_srt"]), reviewed, path, [])
        assert result["chinese_script"] == script
        assert read_srt(reviewed)[0].text == expected
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_non_chinese_output_is_not_simplified(tmp_path):
    configure_chinese_output(tmp_path, "simplified", "ja")
    words = [AsrWord(index=1, start=0, end=1, text="東京の學校", probability=.9, segment_id=0)]
    assert write_asr_v2_outputs(tmp_path, words)["transcript_text"] == "東京の學校\n"


def test_gap_review_converts_newly_accepted_text_using_saved_policy(tmp_path):
    configure_chinese_output(tmp_path, "simplified", "zh")
    words_path = tmp_path / "words.json"
    words_path.write_text(json.dumps({"words": [{"index": 1, "start": 0, "end": 1, "text": "數據。", "probability": .9, "segment_id": 0}]}, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "source.asr2.srt"
    reviewed = tmp_path / "reviewed.srt"
    result = web_agent._write_asr_reviewed_outputs(source, reviewed, words_path, [{"action": "accept", "candidate": {"start": 3, "end": 4, "text": "標註。", "probability": .8}}])
    assert result["transcript_text"] == "数据。\n标注。\n"
    assert [(cue.start, cue.end) for cue in read_srt(reviewed)] == [(0, 1), (3, 4)]
