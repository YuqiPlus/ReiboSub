from __future__ import annotations

from pathlib import Path

from video_translate import web_agent


def test_caption_entries_collects_formats():
    raw = {"en": [{"ext": "vtt"}, {"ext": "json3"}], "ko": [{"ext": "srv3"}]}

    entries = web_agent._caption_entries(raw, kind="auto")

    assert entries[0]["lang"] == "en"
    assert entries[0]["kind"] == "auto"
    assert entries[0]["formats"] == ["json3", "vtt"]
    assert entries[1]["label"] == "ko · 自动字幕"


def test_safe_slug_keeps_readable_text():
    assert web_agent._safe_slug("(SUB)[BHIND] Gold Land.en.srt") == "sub_bhind_gold_land_en"


def test_ocr_config_uses_full_mode(tmp_path: Path):
    cfg = web_agent._ocr_config(tmp_path / "demo.mp4", tmp_path / "out", extra_hint="朴宝英")

    assert cfg["mode"] == "full"
    assert cfg["input_video"].endswith("demo.mp4")
    assert "朴宝英" in cfg["translation"]["extra_prompt"]


def test_glossary_items_and_update_roundtrip(tmp_path: Path, monkeypatch):
    glossary_dir = tmp_path / "glossaries"
    glossary_dir.mkdir()
    path = glossary_dir / "draft.yaml"
    path.write_text(
        '''characters:
- source: 박보영
  zh: ""
  suggested_zh: 朴宝英
  aliases:
  - 보영
  type: person
  always: true
terms:
- source: Gold Land
  zh: ""
  suggested_zh: 黄金乐园
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", glossary_dir)

    read = web_agent.read_glossary_items({"path": str(path)})
    assert read["items"][0]["source"] == "박보영"
    assert read["items"][0]["suggested_zh"] == "朴宝英"

    written = web_agent.write_glossary_items(
        {
            "path": str(path),
            "items": [
                {"section": "characters", "index": 0, "zh": "朴宝英"},
                {"section": "terms", "index": 0, "zh": "黄金乐园"},
            ],
        }
    )

    assert "朴宝英" in written["content"]
    assert written["items"][0]["zh"] == "朴宝英"
    assert written["items"][1]["zh"] == "黄金乐园"


def test_download_video_job_builds_video_download_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []
    video = tmp_path / "demo.h264.mp4"

    def fake_run_command(job_id, args):
        calls.append(args)
        video.write_text("video", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.download_video_job({"url": "abc123"})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert job.status == "done"
    assert calls[0][1].endswith("download_youtube_video.py")
    assert calls[0][-1] == "abc123"
    assert job.result["input_video"].endswith("demo.h264.mp4")


def test_title_translation_payload_requests_json():
    payload = web_agent.build_title_translation_payload("박보영 홍콩 디즈니랜드 브이로그", "model-id")

    assert payload["model"] == "model-id"
    assert payload["temperature"] == 0.2
    assert "zh_title" in payload["messages"][1]["content"]


def test_parse_title_translation_accepts_json_and_plain_text():
    assert web_agent._parse_title_translation('{"zh_title": "朴宝英香港迪士尼乐园 Vlog"}') == "朴宝英香港迪士尼乐园 Vlog"
    assert web_agent._parse_title_translation('```json\n{"zh_title":"标题"}\n```') == "标题"
    assert web_agent._parse_title_translation('朴宝英香港旅行') == "朴宝英香港旅行"


def test_ocr_config_can_preserve_translation_timing(tmp_path: Path):
    cfg = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "out",
        extra_hint="朴宝英",
        preserve_timing=True,
    )

    translation = cfg["translation"]
    assert translation["dedupe_translated"] is False
    assert translation["llm_cleanup_translated"] is False
    assert translation["cleanup_residual_fragments"] is False
    assert translation["retime_translated"] is False
    assert "保持时间轴模式" in translation["extra_prompt"]

