from __future__ import annotations

import json

from video_translate.subtitle.convert import convert_subtitle_file, read_subtitle_file, write_subtitle_file
from video_translate.subtitle.srt import read_srt


SRT_TEXT = """1
00:00:01,000 --> 00:00:03,500
你好
世界

2
00:00:04,000 --> 00:00:05,000
第二句
"""


def test_convert_srt_to_vtt_and_read_back(tmp_path):
    source = tmp_path / "demo.srt"
    source.write_text(SRT_TEXT, encoding="utf-8")
    out = tmp_path / "demo.vtt"

    result = convert_subtitle_file(source, out)

    assert result == out
    text = out.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:03.500" in text
    cues = read_subtitle_file(out)
    assert cues[0].text == "你好\n世界"
    assert cues[0].start == 1.0


def test_convert_srt_to_bilibili_bcc(tmp_path):
    source = tmp_path / "demo.srt"
    source.write_text(SRT_TEXT, encoding="utf-8")
    out = tmp_path / "demo.bcc"

    convert_subtitle_file(source, out, output_format="bcc")

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["font_size"] == 0.4
    assert data["body"][0]["from"] == 1.0
    assert data["body"][0]["to"] == 3.5
    assert data["body"][0]["content"] == "你好\n世界"


def test_read_bcc_and_write_srt(tmp_path):
    source = tmp_path / "demo.bcc"
    source.write_text(
        json.dumps({"body": [{"from": 2.0, "to": 4.0, "content": "你好"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "demo.srt"

    convert_subtitle_file(source, out)

    cues = read_srt(out)
    assert cues[0].start == 2.0
    assert cues[0].end == 4.0
    assert cues[0].text == "你好"


def test_write_ass_contains_dialogue(tmp_path):
    source = tmp_path / "demo.srt"
    source.write_text(SRT_TEXT, encoding="utf-8")
    out = tmp_path / "demo.ass"

    convert_subtitle_file(source, out)

    text = out.read_text(encoding="utf-8")
    assert "[Events]" in text
    assert "Dialogue: 0,0:00:01.00,0:00:03.50" in text
    assert "你好\\N世界" in text


def test_write_json_roundtrip(tmp_path):
    out = tmp_path / "demo.json"
    source = tmp_path / "demo.srt"
    source.write_text(SRT_TEXT, encoding="utf-8")

    write_subtitle_file(read_subtitle_file(source), out, "json")

    cues = read_subtitle_file(out)
    assert len(cues) == 2
    assert cues[1].text == "第二句"
