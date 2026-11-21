from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from video_translate import subtitle_toolbox as toolbox, web_agent
from video_translate.subtitle.convert import read_subtitle_file, write_subtitle_file
from video_translate.models import SubtitleCue

SRT = "1\n00:00:01,000 --> 00:00:03,000\n數據標註\n\n2\n00:00:04,000 --> 00:00:06,000\n美學很重要。\n"


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass", "ssa", "bcc", "json", "lrc", "txt"])
def test_supported_uploads_and_format_conversion_are_separate_and_immutable(tmp_path, fmt):
    original = tmp_path / f"input.{fmt}"
    write_subtitle_file([SubtitleCue(index=1, start=1, end=3, text="數據標註")], original, fmt)
    content = original.read_bytes()
    info = toolbox.save_upload(tmp_path / "uploads", filename=f"../../字幕.{fmt}", content=content)
    _, directory = toolbox.load_upload(tmp_path / "uploads", info["upload_id"])
    assert info["cue_count"] == 1
    for out_fmt in ["srt", "vtt", "ass", "ssa", "bcc", "json", "lrc", "txt"]:
        result = toolbox.run_mechanical(info, directory, tmp_path / "results" / out_fmt, operation="convert", output_format=out_fmt)
        assert result["format"] == out_fmt
        assert result["cue_count"] == 1
        assert Path(result["output_path"]).is_file()
    assert (directory / f"original.{fmt}").read_bytes() == content
    assert original.read_bytes() == content


def test_encoding_limits_validation_and_unique_ids(tmp_path):
    gb = SRT.encode("gb18030")
    with pytest.raises(ValueError, match="解码失败"):
        toolbox.save_upload(tmp_path, filename="old.srt", content=gb)
    a = toolbox.save_upload(tmp_path, filename="old.srt", content=gb, encoding="gb18030")
    b = toolbox.save_upload(tmp_path, filename="old.srt", content=gb, encoding="gb18030")
    assert a["upload_id"] != b["upload_id"]
    assert a["preview"][0]["text"] == "數據標註"
    for content in [b"", b"x" * (toolbox.MAX_UPLOAD_BYTES + 1)]:
        with pytest.raises(ValueError, match="10 MB"):
            toolbox.save_upload(tmp_path, filename="a.srt", content=content)
    for filename, content in [("a.py", b"hi"), ("a.srt", b"not a subtitle"), ("a.srt", b"1\n00:00:05,000 --> 00:00:01,000\na")]:
        with pytest.raises(ValueError):
            toolbox.save_upload(tmp_path, filename=filename, content=content)
    assert len(list(tmp_path.iterdir())) == 2  # Failed uploads leave no partial uploads.
    for invalid in ["../x", "", "0" * 31, "../" + a["upload_id"]]:
        with pytest.raises(ValueError):
            toolbox.load_upload(tmp_path, invalid)


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass", "ssa", "bcc", "json", "lrc", "txt"])
def test_script_conversion_preserves_times_and_originals(tmp_path, fmt):
    pytest.importorskip("opencc")
    path = tmp_path / f"a.{fmt}"
    write_subtitle_file([SubtitleCue(index=1, start=1, end=3, text="數據與美學。")], path, fmt)
    info = toolbox.save_upload(tmp_path / "uploads", filename=path.name, content=path.read_bytes())
    _, directory = toolbox.load_upload(tmp_path / "uploads", info["upload_id"])
    before = read_subtitle_file(directory / f"source.{fmt}")
    result = toolbox.run_mechanical(info, directory, tmp_path / "out", operation="script", script="simplified")
    after = read_subtitle_file(Path(result["output_path"]))
    assert "数据与美学。" in after[0].text
    assert [(cue.start, cue.end) for cue in before] == [(cue.start, cue.end) for cue in after]
    assert (directory / f"original.{fmt}").read_bytes() == path.read_bytes()


def test_native_ass_and_vtt_metadata_are_not_converted():
    pytest.importorskip("opencc")
    ass = "[V4+ Styles]\nStyle: 學校,字體,42\n[Events]\nDialogue: 0,0:00:01.00,0:00:03.00,學校,張三,0,0,0,,{\\fn字體}數據\\N美學\n"
    output = toolbox.convert_script_document(ass, "ass", "simplified")
    assert "Style: 學校,字體,42" in output
    assert "學校,張三,0,0,0,,{\\fn字體}数据\\N美学" in output
    vtt = "WEBVTT\n\nNOTE 學校\n備註\n\ncue-name\n00:01.000 --> 00:03.000 align:start\n<v 張三><b>數據</b>與美學\n"
    output = toolbox.convert_script_document(vtt, "vtt", "simplified")
    assert "NOTE 學校\n備註" in output
    assert '<v 張三><b>数据</b>与美学' in output
    assert "00:01.000 --> 00:03.000 align:start" in output
    bcc = {"font_color": "#FFF", "label": "學校", "body": [{"from": 1, "to": 2, "location": 2, "content": "數據"}]}
    output = json.loads(toolbox.convert_script_document(json.dumps(bcc), "bcc", "simplified"))
    assert output["label"] == "學校" and output["body"][0] == {"from": 1, "to": 2, "location": 2, "content": "数据"}


@pytest.fixture
def tool_server(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_agent.AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address
    server.shutdown(); server.server_close(); thread.join(timeout=5)


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection(*server, timeout=5)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def upload_http(server):
    body = b'--test\r\nContent-Disposition: form-data; name="file"; filename="test.srt"\r\nContent-Type: text/plain\r\n\r\n' + SRT.encode() + b'\r\n--test--\r\n'
    status, info = request(server, "POST", "/api/toolbox/upload-subtitle", body, {"Content-Type": "multipart/form-data; boundary=test"})
    assert status == 200, info
    return info


def test_http_upload_conversion_restoration_and_cross_origin_guard(tool_server):
    info = upload_http(tool_server)
    status, restored = request(tool_server, "GET", f"/api/toolbox/subtitles/uploads/{info['upload_id']}")
    assert status == 200 and restored == info
    payload = {"upload_id": info["upload_id"], "operation": "convert", "format": "vtt"}
    status, job = request(tool_server, "POST", "/api/toolbox/subtitles", json.dumps(payload), {"Content-Type": "application/json"})
    assert status == 200
    deadline = time.monotonic() + 5
    while job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.01)
        _, job = request(tool_server, "GET", f"/api/jobs/{job['id']}")
    assert job["status"] == "done", job
    assert Path(job["result"]["output_path"]).read_text().startswith("WEBVTT")
    assert job["result"]["cue_count"] == 2
    status, _ = request(tool_server, "POST", "/api/toolbox/subtitles", json.dumps(payload), {"Content-Type": "application/json", "Origin": "https://untrusted.invalid"})
    assert status == 403
    status, _ = request(tool_server, "POST", "/api/toolbox/upload-subtitle", b"file", {"Content-Type": "multipart/form-data; boundary=test", "Sec-Fetch-Site": "cross-site"})
    assert status == 403
    status, _ = request(tool_server, "POST", "/api/toolbox/subtitles", json.dumps(payload), {"Content-Type": "text/plain"})
    assert status == 400


def test_translation_reuses_existing_tool_and_creates_unique_output_without_sidecars(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path)
    info = toolbox.save_upload(tmp_path / "subtitle_uploads", filename="字幕.vtt", content=b"WEBVTT\n\n00:01.000 --> 00:03.000\nHello\n")
    calls = []
    monkeypatch.setattr(web_agent, "translate_subtitle_job", lambda payload: calls.append(payload) or payload)
    payload = {"upload_id": info["upload_id"], "operation": "translate", "target_language": "en", "source_language": "ko", "extra_prompt": "Fixed names"}
    web_agent.subtitle_toolbox_job(payload); web_agent.subtitle_toolbox_job(payload)
    assert len(calls) == 2 and calls[0]["out"] != calls[1]["out"]
    assert calls[0]["source_srt"].endswith("normalized.srt")
    assert calls[0]["translation_mode"] == "translate_only"
    assert calls[0]["target_language"] == "en"
    assert calls[0]["copy_sidecar"] is False
    assert "韩语" in calls[0]["extra_prompt"] and "Fixed names" in calls[0]["extra_prompt"]
    assert calls[0]["out"].endswith("字幕.en.srt")
