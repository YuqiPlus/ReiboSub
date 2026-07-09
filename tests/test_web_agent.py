from __future__ import annotations

import os
from pathlib import Path
import time

import pytest
import yaml

from video_translate import web_agent


@pytest.fixture(autouse=True)
def isolate_agent_task_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "TASK_DIR", tmp_path / "agent_tasks")


def test_caption_entries_collects_formats():
    raw = {"en": [{"ext": "vtt"}, {"ext": "json3"}], "ko": [{"ext": "srv3"}]}

    entries = web_agent._caption_entries(raw, kind="auto")

    assert entries[0]["lang"] == "en"
    assert entries[0]["kind"] == "auto"
    assert entries[0]["formats"] == ["json3", "vtt"]
    assert entries[1]["label"] == "ko · 自动字幕"


def test_filesystem_safe_title_removes_windows_forbidden_chars():
    safe = web_agent._filesystem_safe_title('A | B: "C"? *D*')

    assert safe == "A ｜ B： ＂C＂？ ＊D＊"
    assert not any(char in safe for char in '<>:"/\\|?*')


def test_probe_video_normalizes_url_and_adds_agent_plan(monkeypatch):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            captured["url"] = url
            return {
                "id": "VIDEO_ID_01",
                "title": "demo",
                "duration": 120,
                "webpage_url": "https://www.youtube.com/watch?v=VIDEO_ID_01&t=63",
                "subtitles": {"ko": [{"ext": "vtt"}]},
                "automatic_captions": {"en": [{"ext": "vtt"}]},
            }

    monkeypatch.setattr(web_agent.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    result = web_agent.probe_video(
        "https://www.youtube.com/watch?v=VIDEO_ID_01&t=63&list=abc",
        proxy=None,
        detected_source_language="ko",
    )

    assert captured["url"] == "https://www.youtube.com/watch?v=VIDEO_ID_01"
    assert result["normalized_url"] == "https://www.youtube.com/watch?v=VIDEO_ID_01"
    assert result["webpage_url"] == "https://www.youtube.com/watch?v=VIDEO_ID_01"
    assert result["agent_plan"]["route"] == "translate_source_subtitle"
    assert result["agent_plan"]["selected_subtitle"]["lang"] == "ko"



def test_start_agent_session_uses_configured_japanese_for_probe(monkeypatch):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    captured = {}

    def fake_probe(url, **kwargs):
        captured.update(kwargs)
        return {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "ocr", "selected_subtitle": None, "confidence": 0.5},
        }

    monkeypatch.setattr(web_agent, "probe_video", fake_probe)

    session = web_agent.start_agent_session({"url": "abc123", "source_language": "japanese", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")

    assert snapshot["payload"]["source_language"] == "japanese"
    assert captured["detected_source_language"] == "ja"


def test_agent_session_japanese_asr_passes_language_to_asr_and_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "asr.ja.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "asr", "selected_subtitle": None, "confidence": 0.65},
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(web_agent, "download_video_job", lambda payload: done_job("video", {"input_video": str(video)}))
    monkeypatch.setattr(
        web_agent,
        "audio_local_video_job",
        lambda payload: calls.append(f"asr:{payload['language']}:{payload.get('source_language')}") or done_job("asr", {"source_srt": str(source), "input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload.get('source_language')}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "no", "source_language": "japanese"})
    _wait_agent_phase(session.id, "diagnose_ocr_asr")

    web_agent.answer_agent_session(session.id, {"action": "run_asr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_kind"] == "asr"
    assert calls == ["asr:japanese:japanese", "glossary:japanese"]


def test_ocr_config_records_japanese_source_language(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        source_language="japanese",
    )

    assert config["source_language"] == "japanese"

def test_agent_session_waits_for_auto_subtitle_confirmation(monkeypatch):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [{"lang": "ko", "kind": "auto", "label": "ko · 自动字幕"}],
            "agent_plan": {
                "route": "translate_auto_subtitle",
                "selected_subtitle": {"lang": "ko", "kind": "auto", "label": "ko · 自动字幕"},
                "requires_translation": True,
                "needs_source_correction": True,
                "confidence": 0.76,
                "recommended_action": "download_correct_translate_subtitle",
                "reasons": ["推荐用韩语自动字幕"],
            },
        },
    )

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_status(session.id, "waiting")

    assert snapshot["phase"] == "confirm_subtitle"
    assert snapshot["question"]["kind"] == "confirm_subtitle"
    assert snapshot["question"]["selected_subtitle"]["lang"] == "ko"
    assert snapshot["question"]["selected_subtitle"]["kind"] == "auto"
    assert snapshot["result"]["probe"]["normalized_url"].endswith("abc123")


def test_agent_session_hybrid_downloads_anchor_video_and_generates_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    anchor = tmp_path / "demo.en.srt"
    anchor.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"demo")
    hybrid = tmp_path / "hybrid.source.srt"
    hybrid.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文OCR：안녕\n英文参考：Hello\n", encoding="utf-8")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [{"lang": "en", "kind": "manual", "label": "en · 人工字幕"}],
            "agent_plan": {
                "route": "hybrid_anchor_ocr",
                "selected_subtitle": {"lang": "en", "kind": "manual", "label": "en · 人工字幕"},
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.82,
                "recommended_action": "download_anchor_subtitle_then_hybrid_ocr",
                "reasons": ["推荐 hybrid"],
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(web_agent, "download_subtitle_job", lambda payload: calls.append(f"subtitle:{payload['lang']}") or done_job("subtitle", {"subtitle_path": str(anchor)}))
    monkeypatch.setattr(web_agent, "download_video_job", lambda payload: calls.append("video") or done_job("video", {"input_video": str(video)}))
    monkeypatch.setattr(web_agent, "hybrid_anchor_ocr_job", lambda payload: calls.append(f"hybrid:{payload['anchor_srt']}:{payload['input_video']}") or done_job("hybrid", {"source_srt": str(hybrid), "debug_json": str(tmp_path / "hybrid.debug.json")}))
    def fake_generate_glossary(payload):
        calls.append(f"glossary:{payload['source_srt']}:{payload.get('out', '')}")
        assert Path(payload["out"]).name == "glossary.draft.yaml"
        assert Path(payload["out"]).parent.parent == web_agent.TASK_DIR
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_generate_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")
    assert snapshot["question"]["options"][0]["action"] == "use_recommended"

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
    snapshot = _wait_agent_phase(session.id, "confirm_hybrid_ocr_settings")
    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "confirm_hybrid_ocr_settings"
    assert snapshot["question"]["options"][0]["action"] == "start_hybrid_anchor_ocr"
    assert snapshot["result"]["anchor_srt"] == str(anchor)
    assert snapshot["result"]["input_video"] == str(video)
    assert calls == ["subtitle:en", "video"]

    web_agent.answer_agent_session(
        session.id,
        {
            "action": "start_hybrid_anchor_ocr",
            "ocr_scope": "smart_full",
            "ocr_crop_top_ratio": 0.25,
            "ocr_crop_bottom_ratio": 0.04,
        },
    )
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_srt"] == str(hybrid)
    assert snapshot["result"]["source_kind"] == "hybrid_anchor_ocr"
    assert calls[:3] == ["subtitle:en", "video", f"hybrid:{anchor}:{video}"]
    assert calls[3].startswith(f"glossary:{hybrid}:")
    assert snapshot["payload"]["ocr_scope"] == "smart_full"
    assert snapshot["payload"]["ocr_crop_top_ratio"] == 0.25
    assert snapshot["payload"]["ocr_crop_bottom_ratio"] == 0.04


def test_agent_session_dual_reference_downloads_source_and_reference_subtitles(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    ko = tmp_path / "demo.ko.srt"
    ko.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    en = tmp_path / "demo.en.srt"
    en.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    dual = tmp_path / "dual.source.srt"
    dual.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文原文：안녕\n英文参考：Hi\n", encoding="utf-8")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [
                {"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"},
                {"lang": "en", "kind": "manual", "label": "en · 人工字幕"},
            ],
            "agent_plan": {
                "route": "dual_subtitle_reference",
                "selected_subtitle": {"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"},
                "reference_subtitle": {"lang": "en", "kind": "manual", "label": "en · 人工字幕"},
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.9,
                "recommended_action": "download_dual_subtitles_then_translate",
                "reasons": ["推荐双字幕参考"],
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    def fake_download(payload):
        calls.append(f"subtitle:{payload['lang']}")
        return done_job("subtitle", {"subtitle_path": str(ko if payload["lang"] == "ko" else en)})

    monkeypatch.setattr(web_agent, "download_subtitle_job", fake_download)
    monkeypatch.setattr(
        web_agent,
        "dual_subtitle_reference_job",
        lambda payload: calls.append(f"dual:{payload['source_srt']}:{payload['reference_srt']}") or done_job(
            "dual",
            {"source_srt": str(dual), "context_srt": str(tmp_path / "dual.context.srt"), "debug_json": str(tmp_path / "dual.debug.json")},
        ),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_kind"] == "dual_subtitle_reference"
    assert snapshot["result"]["source_srt"] == str(dual)
    assert calls == ["subtitle:ko", "subtitle:en", f"dual:{ko}:{en}", f"glossary:{dual}"]




def test_agent_can_download_video_for_ocr_preview_before_route_choice(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "ocr", "selected_subtitle": None, "requires_translation": True, "confidence": 0.7},
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "download_video_job",
        lambda payload: calls.append(f"video:{payload['url']}") or done_job("video", {"input_video": str(video)}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert snapshot["result"].get("input_video") is None
    assert any(option["action"] == "download_video_for_preview" for option in snapshot["question"]["options"])

    web_agent.answer_agent_session(session.id, {"action": "download_video_for_preview"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")

    assert snapshot["status"] == "waiting"
    assert snapshot["result"]["input_video"] == str(video)
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert calls == ["video:https://www.youtube.com/watch?v=abc123"]

def test_agent_session_ocr_extracts_then_generates_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_find_reusable_ocr_result", lambda **kwargs: None)
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {
                "route": "ocr",
                "selected_subtitle": None,
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.7,
                "recommended_action": "ocr_full",
                "reasons": ["没有可用外挂字幕"],
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "ocr_extract_job",
        lambda payload: calls.append(f"ocr:{payload['url']}") or done_job("ocr", {"source_srt": str(source), "input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}:{payload.get('source_language')}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert any(option["action"] == "run_ocr" for option in snapshot["question"]["options"])

    web_agent.answer_agent_session(session.id, {"action": "run_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert "OCR 原文字幕" in snapshot["question"]["message"]
    assert snapshot["result"]["source_kind"] == "ocr"
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == ["ocr:https://www.youtube.com/watch?v=abc123", f"glossary:{snapshot['result']['source_srt']}:korean"]


def test_agent_session_asr_generates_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "asr.srt"
    source.write_text(chr(10).join(["1", "00:00:00,000 --> 00:00:01,000", "안녕", ""]), encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text(chr(10).join(["characters: []", ""]), encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {
                "route": "asr",
                "selected_subtitle": None,
                "requires_translation": True,
                "confidence": 0.65,
                "recommended_action": "run_asr",
                "reasons": ["无外挂字幕且无内嵌字幕"],
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "download_video_job",
        lambda payload: calls.append(f"video:{payload['url']}") or done_job("video", {"input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "audio_local_video_job",
        lambda payload: calls.append(f"asr:{payload['input_video']}:{payload['language']}") or done_job("asr", {"source_srt": str(source), "input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}:{payload.get('source_language')}") or done_job("glossary", {"glossary_path": str(glossary), "content": chr(10).join(["characters: []", ""])}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "no"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert snapshot["question"]["recommended_route"] == "asr"

    web_agent.answer_agent_session(session.id, {"action": "run_asr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert "ASR" in snapshot["question"]["message"]
    assert snapshot["result"]["source_kind"] == "asr"
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == [
        "video:https://www.youtube.com/watch?v=abc123",
        f"asr:{video}:auto",
        f"glossary:{snapshot['result']['source_srt']}:korean",
    ]



def test_agent_session_embedded_full_speech_runs_asr_with_ocr_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    asr_source = tmp_path / "asr.srt"
    asr_source.write_text("1\n00:00:00,000 --> 00:00:01,000\n박봉열 선생님\n", encoding="utf-8")
    ocr_source = tmp_path / "ocr.srt"
    ocr_source.write_text("1\n00:00:00,000 --> 00:00:01,000\n박보영 선생님\n", encoding="utf-8")
    corrected = tmp_path / "corrected.srt"
    corrected.write_text("1\n00:00:00,000 --> 00:00:01,000\n박보영 선생님\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(web_agent, "_find_reusable_ocr_result", lambda **kwargs: None)
    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "ocr", "selected_subtitle": None, "confidence": 0.78},
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(web_agent, "download_video_job", lambda payload: calls.append("video") or done_job("video", {"input_video": str(video)}))
    monkeypatch.setattr(web_agent, "audio_local_video_job", lambda payload: calls.append(f"asr:{payload['input_video']}") or done_job("asr", {"source_srt": str(asr_source), "input_video": str(video)}))
    monkeypatch.setattr(web_agent, "ocr_local_video_job", lambda payload: calls.append(f"ocr_ref:{payload['input_video']}:{payload.get('extract_only')}") or done_job("ocr", {"source_srt": str(ocr_source), "input_video": str(video)}))
    monkeypatch.setattr(web_agent, "correct_asr_subtitle_job", lambda payload: calls.append(f"correct:{payload['reference_srt']}") or done_job("correct", {"source_srt": str(corrected), "corrected_srt": str(corrected)}))
    monkeypatch.setattr(web_agent, "generate_glossary_job", lambda payload: calls.append(f"glossary:{payload['source_srt']}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}))

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes", "embedded_subtitle_goal": "full_speech"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert any(option["action"] == "run_asr_with_ocr" for option in snapshot["question"]["options"])

    web_agent.answer_agent_session(session.id, {"action": "run_asr_with_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_kind"] == "asr_ocr_reference"
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == ["video", f"asr:{video}", f"ocr_ref:{video}:True", f"correct:{ocr_source}", f"glossary:{snapshot['result']['source_srt']}"]

def test_agent_session_chinese_ocr_finishes_without_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_find_reusable_ocr_result", lambda **kwargs: None)
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "ocr", "selected_subtitle": None, "confidence": 0.7},
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "ocr_extract_job",
        lambda payload: calls.append(f"ocr:{payload.get('ocr_language')}:{payload.get('source_language')}") or done_job("ocr", {"source_srt": str(source), "input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append("glossary") or done_job("glossary", {"glossary_path": str(tmp_path / "draft.yaml"), "content": ""}),
    )
    monkeypatch.setattr(web_agent, "_copy_agent_translated_sidecar", lambda session, source_srt, translated_srt: {})

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes", "ocr_language": "chinese"})
    _wait_agent_phase(session.id, "diagnose_ocr_asr")

    web_agent.answer_agent_session(session.id, {"action": "run_ocr"})
    snapshot = _wait_agent_status(session.id, "done")

    assert calls == ["ocr:chinese:auto"]
    assert snapshot["result"]["source_srt"].endswith("source.srt")
    assert snapshot["result"]["translated_srt"].endswith("zh.srt")
    assert "glossary_path" not in snapshot["result"]
    zh_path = Path(snapshot["result"]["translated_srt"])
    assert zh_path.exists()
    assert "你好" in zh_path.read_text(encoding="utf-8")


def test_ocr_full_job_chinese_ocr_uses_extract_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    video = tmp_path / "YoutubeDownloads" / "demo" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    calls: list[list[str]] = []

    monkeypatch.setattr(web_agent, "_snapshot_video_files", lambda root: set())
    monkeypatch.setattr(web_agent, "_downloaded_video_candidates", lambda *args, **kwargs: [video])
    monkeypatch.setattr(web_agent, "_matching_thumbnail_file", lambda input_video: None)
    monkeypatch.setattr(web_agent, "update_youtube_project_manifest", lambda *args, **kwargs: {"project_dir": str(video.parent)})

    def fake_run_command(job_id, args):
        calls.append(args)
        if args and args[0] == "/python":
            out_dir = tmp_path / "outputs" / "agent_jobs" / job_id
            (out_dir / "source.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_full_job({"url": "abc123", "title": "demo", "ocr_language": "chinese"})
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done"
    run_yaml = Path(job.result["output_dir"]) / "run.yaml"
    config = yaml.safe_load(run_yaml.read_text(encoding="utf-8"))
    assert config["mode"] == "extract"
    assert config["source_language"] == "chinese"
    assert config["sidecar"]["copy_translated"] is False
    assert job.result["translated_srt"].endswith("zh.srt")
    assert Path(job.result["translated_srt"]).exists()
    assert (video.parent / "demo.zh.srt").exists()

def test_agent_session_does_not_reuse_empty_task_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    task_dir = web_agent.TASK_DIR / "abc123_demo"
    task_dir.mkdir(parents=True)
    empty_source = task_dir / "source.srt"
    empty_source.write_text("", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "abc123_demo",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "demo",
                "stages": {
                    "ocr": {
                        "status": "done",
                        "source_srt": str(empty_source),
                        "ocr_scope": "bottom",
                        "ocr_refinement_mode": "none",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cached = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_scope="bottom",
        ocr_refinement_mode="none",
    )

    assert cached is None


def test_agent_session_reuses_cached_ocr_before_generating_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path)
    source = tmp_path / "oldjob" / "source.srt"
    source.parent.mkdir(parents=True)
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    video = tmp_path / "downloads" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    (source.parent / "run.yaml").write_text(
        "\n".join(
            [
                "mode: extract",
                f"input_video: {video}",
                f"source_srt: {source}",
                "agent_cache:",
                "  kind: youtube_ocr",
                "  normalized_url: https://www.youtube.com/watch?v=abc123",
                "  ocr_translation_mode: standard_cleanup",
            ]
        ),
        encoding="utf-8",
    )
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {
                "route": "ocr",
                "selected_subtitle": None,
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.7,
                "recommended_action": "ocr_full",
                "reasons": ["没有可用外挂字幕"],
            },
        },
    )
    monkeypatch.setattr(web_agent, "ocr_extract_job", lambda payload: (_ for _ in ()).throw(AssertionError("OCR should be reused")))

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}:{payload.get('source_language')}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"

    web_agent.answer_agent_session(session.id, {"action": "run_ocr"})
    snapshot = _wait_agent_phase(session.id, "confirm_ocr_reuse")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "confirm_ocr_reuse"
    assert snapshot["question"]["reusable_ocr"]["source_srt"] == str(source)

    web_agent.answer_agent_session(session.id, {"action": "use_cached_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["reused_ocr"] is True
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == [f"glossary:{snapshot['result']['source_srt']}:korean"]


def test_agent_task_persists_glossary_review_and_can_continue(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "source.srt"
    glossary = tmp_path / "glossary.draft.yaml"
    translated = tmp_path / "zh.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
    translated.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(web_agent, "_find_reusable_ocr_result", lambda **kwargs: None)
    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [],
            "agent_plan": {"route": "ocr", "selected_subtitle": None, "requires_translation": True, "confidence": 0.7},
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(web_agent, "ocr_extract_job", lambda payload: done_job("ocr", {"source_srt": str(source), "input_video": str(tmp_path / "demo.mp4")}))
    monkeypatch.setattr(web_agent, "generate_glossary_job", lambda payload: done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}))
    monkeypatch.setattr(
        web_agent,
        "translate_subtitle_job",
        lambda payload: calls.append(f"translate:{payload['source_srt']}:{payload['glossary']}") or done_job("translate", {"translated_srt": str(translated)}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"

    web_agent.answer_agent_session(session.id, {"action": "run_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    task_id = snapshot["result"]["task_id"]
    tasks = web_agent.list_agent_tasks()
    task = next(item for item in tasks if item["id"] == task_id)
    assert task["current_stage"] == "glossary_review"
    assert task["stages"]["ocr"]["status"] == "done"
    assert task["stages"]["glossary"]["status"] == "waiting_review"

    continued = web_agent.continue_agent_task(task_id)
    snapshot = _wait_agent_status(continued.id, "done")

    task = web_agent.get_agent_task(task_id)
    assert task["current_stage"] == "done"
    assert task["stages"]["translate"]["status"] == "done"
    assert calls == [f"translate:{task['stages']['ocr']['source_srt']}:{glossary}"]
    assert snapshot["result"]["translated_srt"].endswith("zh.srt")


def test_api_path_segment_decodes_percent_encoded_task_id():
    task_id = "yqmrauhwt3w_금빛_대장정"
    encoded = "yqmrauhwt3w_%EA%B8%88%EB%B9%9B_%EB%8C%80%EC%9E%A5%EC%A0%95"

    assert web_agent._api_path_segment(f"/api/agent-tasks/{encoded}/continue", -2) == task_id
    assert web_agent._api_path_segment(f"/api/agent-tasks/{encoded}", -1) == task_id


def test_legacy_glossary_job_imports_as_agent_task(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    source_dir = web_agent.JOB_DIR / "ocr123"
    glossary_dir = web_agent.JOB_DIR / "gloss123"
    source_dir.mkdir(parents=True)
    glossary_dir.mkdir(parents=True)
    video = tmp_path / "downloads" / "demo.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    source = source_dir / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (source_dir / "run.yaml").write_text(f"mode: extract\ninput_video: {video}\nsource_srt: {source}\n", encoding="utf-8")
    glossary = glossary_dir / "glossary.draft.yaml"
    glossary.write_text(f"# Draft glossary generated from downloaded subtitles.\n# source_srt: {source}\nprogram: {{}}\n", encoding="utf-8")

    tasks = web_agent.list_agent_tasks()

    assert tasks[0]["id"] == "legacy_gloss123"
    assert tasks[0]["title"] == "demo"
    assert tasks[0]["current_stage"] == "glossary_review"
    assert tasks[0]["stages"]["ocr"]["source_srt"] == str(source)
    assert tasks[0]["stages"]["ocr"]["can_rerun"] is False
    assert tasks[0]["stages"]["glossary"]["glossary_path"] == str(glossary)


def test_deleted_legacy_task_is_not_reimported(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    source_dir = web_agent.JOB_DIR / "ocr123"
    glossary_dir = web_agent.JOB_DIR / "gloss123"
    source_dir.mkdir(parents=True)
    glossary_dir.mkdir(parents=True)
    source = source_dir / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (source_dir / "run.yaml").write_text(f"mode: extract\nsource_srt: {source}\n", encoding="utf-8")
    glossary = glossary_dir / "glossary.draft.yaml"
    glossary.write_text(f"# source_srt: {source}\nprogram: {{}}\n", encoding="utf-8")

    tasks = web_agent.list_agent_tasks()
    assert [task["id"] for task in tasks] == ["legacy_gloss123"]

    web_agent.delete_agent_task("legacy_gloss123")
    tasks = web_agent.list_agent_tasks()

    assert tasks == []
    assert "legacy_gloss123" in web_agent._deleted_task_ids()
    assert glossary.exists()


def test_delete_agent_task_removes_task_directory(monkeypatch, tmp_path):
    task_dir = web_agent.TASK_DIR / "task123"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text("id: task123\n", encoding="utf-8")
    (task_dir / "source.srt").write_text("1\n", encoding="utf-8")

    result = web_agent.delete_agent_task("task123")

    assert result["deleted"] is True
    assert not task_dir.exists()


def test_delete_agent_task_rejects_traversal(monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    try:
        web_agent.delete_agent_task("../outside")
    except Exception as exc:
        assert "agent task not found" in str(exc) or "任务目录不在允许范围内" in str(exc)
    else:
        raise AssertionError("delete_agent_task should reject traversal")
    assert outside.exists()


def test_delete_download_project_removes_direct_child(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    project = downloads / "demo"
    project.mkdir(parents=True)
    (project / "demo.mp4").write_text("video", encoding="utf-8")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    result = web_agent.delete_download_project({"path": str(project)})

    assert result["deleted"] is True
    assert not project.exists()


def test_delete_download_project_rejects_root_and_outside(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    outside = tmp_path / "outside"
    downloads.mkdir()
    outside.mkdir()
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    for path in [downloads, outside]:
        try:
            web_agent.delete_download_project({"path": str(path)})
        except Exception as exc:
            assert "只能删除下载目录下的单个视频项目文件夹" in str(exc)
        else:
            raise AssertionError(f"delete_download_project should reject {path}")
    assert downloads.exists()
    assert outside.exists()


def test_agent_session_probes_audio_language_before_choosing_manual_source(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    source = tmp_path / "demo.ko.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    reference = tmp_path / "demo.en.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    dual = tmp_path / "dual.source.srt"
    dual.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文原文：안녕\n英文参考：Hi\n", encoding="utf-8")
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [
                {"lang": "en", "kind": "manual", "label": "en · 人工字幕"},
                {"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"},
            ],
            "agent_plan": {
                "route": "probe_audio_language",
                "selected_subtitle": None,
                "candidate_subtitles": [
                    {"lang": "en", "kind": "manual", "label": "en · 人工字幕"},
                    {"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"},
                ],
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.55,
                "recommended_action": "probe_audio_language",
                "reasons": ["需要先检测原视频音源语言。"],
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(web_agent, "download_video_job", lambda payload: calls.append("video") or done_job("video", {"input_video": str(video)}))
    monkeypatch.setattr(web_agent, "audio_language_probe_job", lambda payload: calls.append(f"lang:{payload['input_video']}") or done_job("lang", {"language": "ko", "language_probability": 0.93}))
    monkeypatch.setattr(web_agent, "download_subtitle_job", lambda payload: calls.append(f"subtitle:{payload['lang']}:{payload['kind']}") or done_job("subtitle", {"subtitle_path": str(source if payload["lang"] == "ko" else reference)}))
    monkeypatch.setattr(web_agent, "dual_subtitle_reference_job", lambda payload: calls.append(f"dual:{payload['source_srt']}:{payload['reference_srt']}") or done_job("dual", {"source_srt": str(dual)}))
    monkeypatch.setattr(web_agent, "generate_glossary_job", lambda payload: calls.append(f"glossary:{payload['source_srt']}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}))

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "unknown"})
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert snapshot["question"]["recommended_route"] == "probe_audio_language"

    web_agent.answer_agent_session(session.id, {"action": "probe_audio_language"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["detected_source_language"] == "ko"
    assert snapshot["result"]["agent_plan"]["route"] == "dual_subtitle_reference"
    assert snapshot["result"]["agent_plan"]["selected_subtitle"]["lang"] == "ko"
    assert snapshot["result"]["agent_plan"]["reference_subtitle"]["lang"] == "en"
    assert calls == ["video", f"lang:{video}", "subtitle:ko:manual", "subtitle:en:manual", f"dual:{source}:{reference}", f"glossary:{dual}"]


def test_cancel_agent_session_cancels_current_child_job(monkeypatch):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_JOBS", {})
    session = web_agent.AgentSession(id="agent1", status="running", phase="ocr_full", result={"current_job_id": "child1"})
    child = web_agent.Job(id="child1", name="OCR", status="running")
    with web_agent._LOCK:
        web_agent._AGENT_SESSIONS[session.id] = session
        web_agent._JOBS[child.id] = child

    cancelled = web_agent.cancel_agent_session("agent1")

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert child.status == "cancelled"
    assert "job_cancel_requested" in child.logs


def test_convert_subtitle_job_writes_target_format(tmp_path: Path, monkeypatch):
    source = tmp_path / "demo.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)

    job = web_agent.convert_subtitle_job({"source": str(source), "format": "vtt"})
    snapshot = _wait_job_status(job.id, "done")

    out = tmp_path / "demo.vtt"
    assert out.exists()
    assert "WEBVTT" in out.read_text(encoding="utf-8")
    assert snapshot["result"]["converted_subtitle"] == str(out)


def test_subtitle_editor_read_and_save_as(tmp_path: Path, monkeypatch):
    downloads = tmp_path / "YoutubeDownloads"
    downloads.mkdir()
    source = downloads / "demo.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,200\n第一行\n第二行\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n要删除\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    loaded = web_agent.read_subtitle_file({"path": str(source)})

    assert loaded["count"] == 2
    assert loaded["cues"][0]["text"] == "第一行\n第二行"
    assert loaded["cues"][0]["start_time"] == "00:00:00,000"

    saved = web_agent.write_subtitle_file(
        {
            "path": str(source),
            "cues": [
                {
                    "start_time": "00:00:00,000",
                    "end_time": "00:00:01,600",
                    "text": "第一行 第二行",
                },
                {
                    "start": 2.0,
                    "end": 3.0,
                    "text": "要删除",
                    "deleted": True,
                },
            ],
        }
    )

    out = downloads / "demo.edited.srt"
    assert saved["path"] == str(out)
    assert saved["count"] == 1
    assert out.exists()
    assert web_agent.read_subtitle_file({"path": str(out)})["cues"][0]["text"] == "第一行 第二行"


def test_subtitle_editor_rejects_non_srt_save(tmp_path: Path, monkeypatch):
    downloads = tmp_path / "YoutubeDownloads"
    downloads.mkdir()
    source = downloads / "demo.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    with pytest.raises(ValueError, match=r"\.srt"):
        web_agent.write_subtitle_file(
            {
                "path": str(source),
                "out": str(downloads / "demo.txt"),
                "cues": [{"start": 0, "end": 1, "text": "你好"}],
            }
        )


def test_agent_session_downloads_generates_glossary_then_waits(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    glossary = tmp_path / "draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    source = tmp_path / "demo.ko.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [{"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"}],
            "agent_plan": {
                "route": "translate_source_subtitle",
                "selected_subtitle": {"lang": "ko", "kind": "manual", "label": "ko · 人工字幕"},
                "requires_translation": True,
                "needs_source_correction": False,
                "confidence": 0.88,
                "recommended_action": "download_then_translate_subtitle",
                "reasons": ["推荐用韩语人工字幕"],
            },
        },
    )

    def done_job(name, result):
        job = web_agent.Job(id=name, name=name, status="done", result=result)
        return job

    def fake_download(payload):
        calls.append(f"download:{payload['lang']}:{payload['kind']}")
        return done_job("download", {"subtitle_path": str(source)})

    def fake_glossary(payload):
        calls.append(f"glossary:{payload['source_srt']}:{payload.get('out', '')}")
        assert Path(payload["out"]).name == "glossary.draft.yaml"
        assert Path(payload["out"]).parent.parent == web_agent.TASK_DIR
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "download_subtitle_job", fake_download)
    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert snapshot["result"]["source_srt"] == str(source)
    assert snapshot["result"]["glossary_path"] == str(glossary)
    assert calls[0] == "download:ko:manual"
    assert calls[1].startswith(f"glossary:{source}:")


def test_retry_failed_agent_regenerates_glossary_from_existing_source(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "demo.ko.srt"
    glossary = tmp_path / "draft.yaml"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls: list[str] = []
    session = web_agent.AgentSession(
        id="agent1",
        status="failed",
        phase="generate_glossary",
        payload={"extra_hint": "节目名参考"},
        result={"source_srt": str(source)},
        error="previous failure",
    )
    with web_agent._LOCK:
        web_agent._AGENT_SESSIONS[session.id] = session

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    def fake_generate_glossary(payload):
        calls.append(f"glossary:{payload['source_srt']}:{payload.get('extra_hint', '')}")
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_generate_glossary)

    retried = web_agent.retry_agent_session(session.id)
    assert retried.status in {"running", "waiting"}
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["error"] == ""
    assert snapshot["question"]["kind"] == "review_glossary"
    assert snapshot["result"]["glossary_path"] == str(glossary)
    assert calls == [f"glossary:{source}:节目名参考"]


def test_agent_translate_after_glossary_exposes_sidecar_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "source.srt"
    glossary = tmp_path / "glossary.yaml"
    translated = tmp_path / "source.zh.srt"
    sidecar = tmp_path / "video.zh.srt"
    session = web_agent.AgentSession(
        id="agent1",
        status="waiting",
        phase="review_glossary",
        payload={},
        result={"source_srt": str(source), "glossary_path": str(glossary)},
    )
    with web_agent._LOCK:
        web_agent._AGENT_SESSIONS[session.id] = session

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "translate_subtitle_job",
        lambda payload: done_job(
            "translate",
            {
                "translated_srt": str(translated),
                "translated_sidecar": str(sidecar),
                "translation_mode": payload["translation_mode"],
            },
        ),
    )

    web_agent._agent_translate_after_glossary(session, use_glossary=True)
    snapshot = web_agent.get_agent_session(session.id).to_dict()

    assert snapshot["status"] == "done"
    assert snapshot["result"]["translated_srt"] == str(translated)
    assert snapshot["result"]["translated_sidecar"] == str(sidecar)
    assert snapshot["result"]["translate_subtitle"]["translated_sidecar"] == str(sidecar)


def test_ocr_scope_settings_drive_generated_run_config(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        translation_mode="translate_only",
        ocr_scope="smart_full",
    )

    assert config["ocr"]["bottom_ratio"] == 0.42
    assert config["ocr"]["scan_full_frame"] is True
    assert web_agent._ocr_scope_settings("expanded") == {"bottom_ratio": 0.62, "scan_full_frame": False}



def test_ocr_config_includes_horizontal_crop_ratios(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        ocr_scope="bottom",
        ocr_crop_top_ratio=0.25,
        ocr_crop_bottom_ratio=0.05,
        ocr_crop_left_ratio=0.08,
        ocr_crop_right_ratio=0.14,
    )

    assert config["ocr"]["crop_top_ratio"] == 0.25
    assert config["ocr"]["crop_bottom_ratio"] == 0.05
    assert config["ocr"]["crop_left_ratio"] == 0.08
    assert config["ocr"]["crop_right_ratio"] == 0.14
    assert config["ocr"]["auto_trim_side_noise"] is True



def test_ocr_config_defaults_crop_top_from_scope(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        ocr_scope="expanded",
    )

    assert config["ocr"]["crop_top_ratio"] == 0.38
    assert config["ocr"]["crop_bottom_ratio"] == 0.0



def test_ocr_crop_preview_rect_uses_scope_default():
    rect = web_agent._ocr_crop_preview_rect(200, 100, ocr_scope="bottom")

    assert rect["left"] == 0
    assert rect["top"] == 58
    assert rect["width"] == 200
    assert rect["height"] == 42
    assert rect["ratios"] == {"top": 0.58, "bottom": 0.0, "left": 0.0, "right": 0.0}


def test_ocr_crop_preview_rect_uses_explicit_edges():
    rect = web_agent._ocr_crop_preview_rect(200, 100, ocr_scope="bottom", crop_top_ratio=0.25, crop_bottom_ratio=0.10, crop_left_ratio=0.15, crop_right_ratio=0.20)

    assert rect["left"] == 30
    assert rect["top"] == 25
    assert rect["width"] == 130
    assert rect["height"] == 65


def test_ocr_config_can_enable_llm_box_refinement(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        translation_mode="standard_cleanup",
        ocr_scope="smart_full",
        ocr_refinement_mode="llm_boxes",
    )

    assert config["ocr_refinement"]["mode"] == "llm_boxes"
    assert config["ocr_refinement"]["batch_size"] == 12


def test_ocr_config_enables_llm_context_source_cleanup(tmp_path: Path):
    config = web_agent._ocr_config(tmp_path / "demo.mp4", tmp_path / "job", extra_hint="", ocr_scope="smart_full")

    assert config["source_cleanup"]["mode"] == "llm_context"
    assert config["source_cleanup"]["batch_size"] == 18
    assert config["source_cleanup"]["overlap"] == 3


def test_matching_media_files_handles_yt_dlp_sanitized_title(tmp_path: Path):
    title = "멜로 눈빛 장착한 두부들이 왔습니다♥ | 🎥라이브 짧게보기"
    video = tmp_path / "멜로 눈빛 장착한 두부들이 왔습니다♥ ｜ 🎥라이브 짧게보기.mp4"
    subtitle = tmp_path / "멜로 눈빛 장착한 두부들이 왔습니다♥ ｜ 🎥라이브 짧게보기.en.srt"
    video.write_bytes(b"video")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    assert web_agent._matching_video_files(tmp_path, title) == [video]
    assert web_agent._matching_subtitle_files(tmp_path, title, "en") == [subtitle]


def test_allowed_paths_include_external_download_dir(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    downloads = tmp_path / "external_downloads"
    jobs = root / "outputs" / "agent_jobs"
    glossaries = root / "configs" / "glossaries"
    root.mkdir()
    downloads.mkdir()
    jobs.mkdir(parents=True)
    glossaries.mkdir(parents=True)
    video = downloads / "demo.mp4"
    video.write_bytes(b"video")
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("secret", encoding="utf-8")

    monkeypatch.setattr(web_agent, "ROOT", root)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", glossaries)

    web_agent._ensure_under_root(video)
    try:
        web_agent._ensure_under_root(outside)
    except ValueError:
        pass
    else:
        raise AssertionError("unconfigured external path should be rejected")


def _wait_agent_status(session_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    snapshot = None
    while time.time() < deadline:
        snapshot = web_agent.get_agent_session(session_id).to_dict()
        if snapshot["status"] == status:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"agent did not reach status {status}: {snapshot}")


def _wait_agent_phase(session_id: str, phase: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    snapshot = None
    while time.time() < deadline:
        snapshot = web_agent.get_agent_session(session_id).to_dict()
        if snapshot["phase"] == phase:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"agent did not reach phase {phase}: {snapshot}")


def _wait_job_status(job_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    snapshot = None
    while time.time() < deadline:
        snapshot = web_agent.get_job(job_id).to_dict()
        if snapshot["status"] == status:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"job did not reach status {status}: {snapshot}")


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
  reviewed: true
- source: DIVE
  zh: DIVE
  suggested_zh: ""
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", glossary_dir)

    read = web_agent.read_glossary_items({"path": str(path), "include_blind_candidates": True})
    assert read["items"][0]["source"] == "박보영"
    assert read["items"][0]["suggested_zh"] == "朴宝英"
    assert read["items"][0]["romanized"] == "bak bo yeong"
    assert read["items"][0]["reviewed"] is False
    assert read["items"][1]["reviewed"] is True
    assert read["items"][2]["reviewed"] is True

    written = web_agent.write_glossary_items(
        {
            "path": str(path),
            "items": [
                {"section": "characters", "index": 0, "zh": "朴宝英", "reviewed": True},
                {"section": "terms", "index": 0, "zh": "", "reviewed": True},
            ],
        }
    )

    assert "朴宝英" in written["content"]
    assert written["items"][0]["zh"] == "朴宝英"
    assert written["items"][0]["reviewed"] is True
    assert written["items"][1]["zh"] == ""
    assert written["items"][1]["reviewed"] is True


def test_glossary_write_allows_agent_job_glossary(tmp_path: Path, monkeypatch):
    job_dir = tmp_path / "outputs" / "agent_jobs" / "job123"
    job_dir.mkdir(parents=True)
    path = job_dir / "glossary.draft.yaml"
    path.write_text(
        """characters:
- source: 보영
  zh: ""
  suggested_zh: 宝英
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", tmp_path / "configs" / "glossaries")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")

    text_result = web_agent.write_text_file({"path": str(path), "content": "characters: []\n"})
    item_result = web_agent.write_glossary_items(
        {
            "path": str(path),
            "items": [{"section": "characters", "index": 0, "zh": "宝英", "reviewed": True}],
        }
    )

    assert text_result["saved"] is True
    assert item_result["saved"] is True


def test_glossary_write_allows_agent_task_glossary(tmp_path: Path, monkeypatch):
    task_dir = tmp_path / "outputs" / "agent_tasks" / "task123"
    task_dir.mkdir(parents=True)
    path = task_dir / "glossary.draft.yaml"
    path.write_text(
        """characters:
- source: 희주
  zh: ""
  suggested_zh: 禧主
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", tmp_path / "configs" / "glossaries")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "TASK_DIR", tmp_path / "outputs" / "agent_tasks")

    text_result = web_agent.write_text_file({"path": str(path), "content": "characters: []\n"})

    assert text_result["saved"] is True


def test_glossary_write_rejects_project_file_outside_allowed_dirs(tmp_path: Path, monkeypatch):
    path = tmp_path / "README.md"
    path.write_text("do not overwrite", encoding="utf-8")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", tmp_path / "configs" / "glossaries")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "TASK_DIR", tmp_path / "outputs" / "agent_tasks")

    try:
        web_agent.write_text_file({"path": str(path), "content": "bad"})
    except ValueError as exc:
        assert "只允许保存" in str(exc)
    else:
        raise AssertionError("write_text_file should reject paths outside glossary/job directories")


def test_glossary_item_keeps_romanized_hint_without_suggestion():
    item = web_agent._glossary_item("characters", 0, {"source": "희주", "suggested_zh": ""})

    assert item["romanized"] == "hui ju"


def test_read_glossary_items_adds_context_and_blind_candidate(tmp_path: Path, monkeypatch):
    glossary_dir = tmp_path / "glossaries"
    glossary_dir.mkdir()
    source_srt = tmp_path / "source.srt"
    source_srt.write_text(
        """1
00:00:00,000 --> 00:00:01,000
안녕하세요

2
00:00:01,000 --> 00:00:02,000
천승 좋아해요
""",
        encoding="utf-8",
    )
    path = glossary_dir / "draft.yaml"
    path.write_text(
        f"""# source_srt: {source_srt}
characters:
- source: 천승
  zh: ""
  suggested_zh: ""
  note: "needs review | evidence_ids: 2 | confidence: 0.30"
- source: 박보영
  zh: ""
  suggested_zh: 朴宝英
  note: "evidence_ids: 1"
""",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_blind_translate(text: str) -> str:
        calls.append(text)
        return "我喜欢天胜"

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", glossary_dir)
    monkeypatch.setattr(web_agent, "_blind_translate_glossary_context", fake_blind_translate)

    read_without_candidates = web_agent.read_glossary_items({"path": str(path)})
    assert "blind_candidate_zh" not in read_without_candidates["items"][0]
    assert calls == []

    read = web_agent.read_glossary_items({"path": str(path), "include_blind_candidates": True})

    assert read["items"][0]["context_text"] == "천승 좋아해요"
    assert read["items"][0]["blind_candidate_zh"] == "我喜欢天胜"
    assert read["items"][1]["context_text"] == "안녕하세요"
    assert "blind_candidate_zh" not in read["items"][1]
    assert calls == ["천승 좋아해요"]

    written = web_agent.write_glossary_items(
        {
            "path": str(path),
            "items": [{"section": "characters", "index": 0, "zh": "天胜", "reviewed": True}],
        }
    )

    assert written["content"].splitlines()[0] == f"# source_srt: {source_srt}"


def test_read_glossary_items_adds_hybrid_english_reference(tmp_path: Path, monkeypatch):
    glossary_dir = tmp_path / "glossaries"
    glossary_dir.mkdir()
    source_srt = tmp_path / "hybrid.source.srt"
    source_srt.write_text(
        """1
00:00:00,000 --> 00:00:01,000
런던에 갑니다
""",
        encoding="utf-8",
    )
    context_srt = tmp_path / "hybrid.context.srt"
    context_srt.write_text(
        """1
00:00:00,000 --> 00:00:01,000
韩文OCR候选：런던에 감니다
英文参考：I'm going to London.
""",
        encoding="utf-8",
    )
    path = glossary_dir / "draft.yaml"
    path.write_text(
        f"""# source_srt: {source_srt}
terms:
- source: 런던
  zh: ""
  suggested_zh: ""
  note: "evidence_ids: 1"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", glossary_dir)

    read = web_agent.read_glossary_items({"path": str(path)})

    assert read["items"][0]["context_text"] == "런던에 갑니다"
    assert read["items"][0]["english_reference_text"] == "I'm going to London."


def test_glossary_item_romanizes_kana_hint_without_suggestion():
    item = web_agent._glossary_item("characters", 0, {"source": "ボヨン", "suggested_zh": ""})

    assert item["romanized"] == "bo yo n"


def test_frontend_asset_resolves_dist_index(tmp_path: Path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    index = dist / "index.html"
    index.write_text("<div id=\"app\"></div>", encoding="utf-8")
    monkeypatch.setattr(web_agent, "FRONTEND_DIST", dist)

    asset = web_agent._frontend_asset_path("/")

    assert asset == index


def test_frontend_asset_resolves_vite_static_file(tmp_path: Path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    asset_file = dist / "assets" / "app.js"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(web_agent, "FRONTEND_DIST", dist)

    asset = web_agent._frontend_asset_path("/assets/app.js")

    assert asset == asset_file
    assert web_agent._content_type_for_path(asset_file) == "text/javascript; charset=utf-8"


def test_frontend_asset_blocks_path_traversal(tmp_path: Path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr(web_agent, "FRONTEND_DIST", dist)

    assert web_agent._frontend_asset_path("/../secret.txt") is None


def test_failed_job_snapshot_contains_terminal_log(monkeypatch):
    monkeypatch.setattr(web_agent, "_JOBS", {})

    def fail(_job_id: str):
        raise RuntimeError("boom")

    job = web_agent.start_job("失败任务", fail)
    deadline = time.time() + 2
    snapshot = None
    while time.time() < deadline:
        snapshot = web_agent.get_job(job.id).to_dict()
        if snapshot["status"] == "failed":
            break
        time.sleep(0.01)

    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "boom"
    assert snapshot["logs"][-1] == "job_failed: boom"


def test_list_jobs_returns_newest_first(monkeypatch):
    monkeypatch.setattr(web_agent, "_JOBS", {})

    older = web_agent.Job(id="older", name="older", created_at=1)
    newer = web_agent.Job(id="newer", name="newer", created_at=2)
    web_agent._JOBS.update({older.id: older, newer.id: newer})

    jobs = web_agent.list_jobs()

    assert [job["id"] for job in jobs] == ["newer", "older"]


def test_download_video_job_builds_video_download_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []
    video_dir = tmp_path / "demo"
    video = video_dir / "demo.h264.mp4"
    thumbnail = video_dir / "demo.h264.jpg"

    def fake_run_command(job_id, args):
        calls.append(args)
        video_dir.mkdir(exist_ok=True)
        if args[:3] == ["/python", "-m", "video_translate.youtube.download_thumbnail"]:
            thumbnail.write_bytes(b"jpg")
        else:
            video.write_text("video", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.download_video_job({"url": "abc123"})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert job.status == "done"
    assert calls[0][:3] == ["/python", "-m", "video_translate.youtube.download_video"]
    assert calls[0][3] == "abc123"
    assert "--output-dir" in calls[0]
    assert calls[0][calls[0].index("--output-dir") + 1] == str(tmp_path)
    assert "--quality" in calls[0]
    assert calls[0][calls[0].index("--quality") + 1] == "1080p"
    assert "--thumbnail-format" in calls[0]
    assert calls[0][calls[0].index("--thumbnail-format") + 1] == "jpg"
    assert job.result["input_video"].endswith("demo.h264.mp4")


def test_download_video_job_passes_requested_quality(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []
    video_dir = tmp_path / "demo"
    video = video_dir / "demo.mp4"

    def fake_run_command(job_id, args):
        calls.append(args)
        video_dir.mkdir(exist_ok=True)
        video.write_text("video", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.download_video_job({"url": "abc123", "quality": "1440p"})
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["status"] == "done"
    assert calls[0][calls[0].index("--quality") + 1] == "1440p"


def test_download_video_job_keeps_primary_manifest_for_archive_quality(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    project = downloads / "Target Video"
    project.mkdir(parents=True)
    primary = project / "Target Video.mp4"
    archive = project / "Target Video.best.av1.mp4"
    primary.write_text("primary", encoding="utf-8")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        if args[:3] == ["/python", "-m", "video_translate.youtube.download_video"]:
            archive.write_text("archive", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.download_video_job({"url": "abc123", "title": "Target Video", "quality": "best"})
    snapshot = _wait_job_status(job.id, "done")

    manifest = yaml.safe_load((project / "project.yaml").read_text(encoding="utf-8"))
    assert snapshot["result"]["input_video"] == str(archive)
    assert manifest["primary_video"] == str(primary.resolve())


def test_download_thumbnail_job_builds_thumbnail_download_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []
    image_dir = tmp_path / "demo"
    image = image_dir / "demo.jpg"

    def fake_run_command(job_id, args):
        calls.append(args)
        image_dir.mkdir()
        image.write_bytes(b"jpg")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.download_thumbnail_job({"url": "abc123", "title": "demo", "format": "png"})
    snapshot = _wait_job_status(job.id, "done")

    assert calls[0][:3] == ["/python", "-m", "video_translate.youtube.download_thumbnail"]
    assert calls[0][3] == "abc123"
    assert "--output-dir" in calls[0]
    assert calls[0][calls[0].index("--output-dir") + 1] == str(tmp_path)
    assert "--format" in calls[0]
    assert calls[0][calls[0].index("--format") + 1] == "png"
    assert snapshot["result"]["thumbnail_path"] == str(image)


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
        translation_mode="translate_only",
    )

    translation = cfg["translation"]
    assert translation["dedupe_translated"] is False
    assert translation["llm_cleanup_translated"] is False
    assert translation["cleanup_residual_fragments"] is False
    assert translation["retime_translated"] is False
    assert "锁定 OCR 时间轴模式" in translation["extra_prompt"]


def test_ocr_config_translation_modes_are_explicit(tmp_path: Path):
    standard = web_agent._ocr_config(tmp_path / "demo.mp4", tmp_path / "standard", extra_hint="", translation_mode="standard_cleanup")
    retime = web_agent._ocr_config(tmp_path / "demo.mp4", tmp_path / "retime", extra_hint="", translation_mode="readability_retime")

    assert standard["translation"]["ocr_translation_mode"] == "standard_cleanup"
    assert standard["translation"]["dedupe_translated"] is True
    assert standard["translation"]["llm_cleanup_translated"] is True
    assert standard["translation"]["cleanup_residual_fragments"] is True
    assert standard["translation"]["retime_translated"] is False

    assert retime["translation"]["ocr_translation_mode"] == "readability_retime"
    assert retime["translation"]["retime_translated"] is True
    assert "强力精修模式" in retime["translation"]["extra_prompt"]


def test_list_local_assets_collects_videos_subtitles_and_ocr_jobs(tmp_path: Path, monkeypatch):
    downloads = tmp_path / "YoutubeDownloads"
    jobs = tmp_path / "outputs" / "agent_jobs"
    job_dir = jobs / "abc123"
    downloads.mkdir(parents=True)
    job_dir.mkdir(parents=True)
    project = downloads / "demo"
    project.mkdir()
    video = project / "demo.mp4"
    subtitle = project / "demo.ko.srt"
    source = job_dir / "source.srt"
    run_yaml = job_dir / "run.yaml"
    video.write_text("video", encoding="utf-8")
    subtitle.write_text("1\n", encoding="utf-8")
    source.write_text("1\n", encoding="utf-8")
    run_yaml.write_text("mode: full\n", encoding="utf-8")
    (downloads / "._demo.mp4").write_text("meta", encoding="utf-8")

    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)

    assets = web_agent.list_local_assets()

    assert [item["name"] for item in assets["videos"]] == ["demo.mp4"]
    assert any(item["path"].endswith("demo.ko.srt") for item in assets["subtitles"])
    assert assets["projects"][0]["name"] == "demo"
    assert assets["projects"][0]["counts"] == {"videos": 1, "subtitles": 1, "images": 0, "others": 0}
    assert assets["projects"][0]["videos"][0]["path"] == str(video)
    assert assets["projects"][0]["subtitles"][0]["path"] == str(subtitle)
    assert assets["ocr_jobs"][0]["source_srt"].endswith("source.srt")



def test_subtitle_pair_issues_report_unbalanced_symbols(tmp_path: Path):
    srt = tmp_path / "bad.zh.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n他说“你好\n\n2\n00:00:01,200 --> 00:00:02,000\n没事\n", encoding="utf-8")

    result = web_agent.subtitle_pair_issues(srt)

    assert result["pair_issue_count"] == 1
    assert result["pair_issues"][0]["missing_symbol"] == "”"
    assert result["pair_issues"][0]["cue_index"] == 1

def test_translate_subtitle_job_passes_translation_mode(monkeypatch, tmp_path: Path):
    source = tmp_path / "video.ko.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n박보영\n", encoding="utf-8")
    out = tmp_path / "video.zh.srt"
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        out.write_text("1\n00:00:00,000 --> 00:00:01,000\n朴宝英\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.translate_subtitle_job({"source_srt": str(source), "out": str(out), "translation_mode": "readability_retime"})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert job.status == "done"
    assert "--translation-mode" in calls[0]
    assert calls[0][calls[0].index("--translation-mode") + 1] == "readability_retime"



def test_translate_subtitle_job_copies_sidecar_for_ocr_source(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    job_dir = tmp_path / "outputs" / "agent_jobs" / "job123"
    downloads.mkdir(parents=True)
    job_dir.mkdir(parents=True)
    video = downloads / "demo.video.mp4"
    source = job_dir / "source.srt"
    out = job_dir / "source.zh.srt"
    video.write_text("video", encoding="utf-8")
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n박보영\n", encoding="utf-8")
    (job_dir / "run.yaml").write_text(
        f"""mode: full
input_video: {video}
source_srt: {source}
sidecar:
  enabled: true
  copy_source: true
  copy_translated: true
  source_suffix: .source
  translated_suffix: .zh
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        out.write_text("1\n00:00:00,000 --> 00:00:01,000\n朴宝英\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.translate_subtitle_job({"source_srt": str(source), "translation_mode": "translate_only"})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    sidecar = downloads / "demo.video.zh.srt"
    assert job.status == "done"
    assert sidecar.read_text(encoding="utf-8").endswith("朴宝英\n")
    assert job.result["translated_sidecar"] == str(sidecar)


def test_download_video_job_uses_existing_file_matching_title(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    downloads.mkdir()
    project = downloads / "Target Video"
    project.mkdir()
    target = project / "Target Video.mp4"
    thumbnail = project / "Target Video.jpg"
    wrong_newer = downloads / "Wrong Newer Video.mp4"
    target.write_text("target", encoding="utf-8")
    thumbnail.write_text("thumb", encoding="utf-8")
    wrong_newer.write_text("wrong", encoding="utf-8")
    now = time.time()
    __import__("os").utime(target, (now - 100, now - 100))
    __import__("os").utime(wrong_newer, (now, now))
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    monkeypatch.setattr(web_agent, "_run_command", lambda job_id, args: None)

    job = web_agent.download_video_job({"url": "abc123", "title": "Target Video"})
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["input_video"] == str(target)
    assert snapshot["result"]["thumbnail_path"] == str(thumbnail)


def test_ocr_extract_job_downloads_ocr_compatible_video(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    web_agent.DOWNLOAD_DIR.mkdir()
    calls = []
    video_dir = web_agent.DOWNLOAD_DIR / "Target Video"
    video = video_dir / "Target Video.mp4"

    def fake_run_command(job_id, args):
        calls.append(args)
        if args[:3] == ["/python", "-m", "video_translate.youtube.download_video"]:
            video_dir.mkdir(exist_ok=True)
            video.write_text("video", encoding="utf-8")
        elif args[:2] == ["/python", str(web_agent.ROOT / "run_from_config.py")]:
            out_dir = web_agent.JOB_DIR / job_id
            (out_dir / "source.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n테스트\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_extract_job({"url": "abc123", "title": "Target Video"})
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["status"] == "done"
    download_call = next(call for call in calls if call[:3] == ["/python", "-m", "video_translate.youtube.download_video"])
    assert download_call[download_call.index("--quality") + 1] == "1080p"


def test_ocr_extract_job_uses_existing_file_matching_title(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    downloads.mkdir()
    target_project = downloads / "Target Video"
    target_project.mkdir()
    target = target_project / "Target Video.mp4"
    wrong_project = downloads / "Wrong Newer Video"
    wrong_project.mkdir()
    wrong = wrong_project / "Wrong Newer Video.mp4"
    target.write_text("target", encoding="utf-8")
    wrong.write_text("wrong", encoding="utf-8")
    now = time.time()
    __import__("os").utime(target, (now - 100, now - 100))
    __import__("os").utime(wrong, (now, now))
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        if args[:2] == ["/python", str(web_agent.ROOT / "run_from_config.py")]:
            (web_agent.JOB_DIR / job_id / "source.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n안녕\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_extract_job({"url": "abc123", "title": "Target Video"})
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["input_video"] == str(target)
    assert snapshot["result"]["project_manifest"] == str(target.parent / "project.yaml")
    run_config = web_agent.JOB_DIR / job.id / "run.yaml"
    config = yaml.safe_load(run_config.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((target.parent / "project.yaml").read_text(encoding="utf-8"))
    assert config["input_video"] == str(target)
    assert manifest["normalized_url"] == "https://www.youtube.com/watch?v=abc123"


def test_video_file_discovery_ignores_macos_appledouble_files(tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    project = downloads / "Target Video"
    project.mkdir(parents=True)
    real_video = project / "Target Video.mp4"
    metadata_video = project / "._Target Video.mp4"
    real_video.write_text("real", encoding="utf-8")
    metadata_video.write_text("metadata", encoding="utf-8")
    now = time.time()
    __import__("os").utime(real_video, (now - 100, now - 100))
    __import__("os").utime(metadata_video, (now, now))

    assert web_agent._newest_video_files(downloads, limit=3) == [real_video]
    assert web_agent._matching_video_files(downloads, "Target Video") == [real_video]


def test_download_subtitle_job_uses_existing_file_matching_title_and_language(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    downloads.mkdir()
    project = downloads / "Target Video"
    project.mkdir()
    target = project / "Target Video.en.srt"
    wrong_newer = downloads / "Wrong Newer Video.en.srt"
    target.write_text("target", encoding="utf-8")
    wrong_newer.write_text("wrong", encoding="utf-8")
    now = time.time()
    __import__("os").utime(target, (now - 100, now - 100))
    __import__("os").utime(wrong_newer, (now, now))
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    monkeypatch.setattr(web_agent, "_run_command", lambda job_id, args: None)

    job = web_agent.download_subtitle_job({"url": "abc123", "lang": "en", "kind": "manual", "title": "Target Video"})
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["subtitle_path"] == str(target)



def test_cancel_job_stops_running_subprocess():
    job = web_agent.start_job(
        "sleepy",
        lambda job_id: web_agent._run_command(
            job_id,
            [web_agent.PYTHON, "-c", "import time; time.sleep(30)"],
        )
        or {},
    )
    deadline = __import__("time").time() + 3
    while job.current_process is None and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    cancelled = web_agent.cancel_job(job.id)

    deadline = __import__("time").time() + 3
    while job.status not in {"cancelled", "failed"} and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert cancelled is job
    assert job.status == "cancelled"
    assert any("job_cancelled" in line for line in job.logs)


def test_cancel_finished_job_is_noop():
    job = web_agent.start_job("quick", lambda job_id: {"ok": True})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    cancelled = web_agent.cancel_job(job.id)

    assert cancelled is job
    assert job.status == "done"



def test_audio_local_video_job_builds_transcription_command(monkeypatch, tmp_path: Path):
    video = tmp_path / "YoutubeDownloads" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_text("video", encoding="utf-8")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        out = tmp_path / "outputs" / "agent_jobs" / job_id / "source.srt"
        out.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕하세요\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.audio_local_video_job({"input_video": str(video), "language": "korean", "model_size": "small"})
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert job.status == "done"
    assert calls[0][:3] == ["/python", "-m", "video_translate.tools.transcribe_audio"]
    assert "--language" in calls[0]
    assert calls[0][calls[0].index("--language") + 1] == "korean"
    assert "--model-size" in calls[0]
    assert calls[0][calls[0].index("--model-size") + 1] == "small"
    assert job.result["subtitle_path"].endswith("source.srt")
    assert (video.parent / "demo.source.srt").exists()




def test_save_uploaded_project_cover_updates_manifest(monkeypatch, tmp_path: Path):
    project = tmp_path / "YoutubeDownloads" / "demo"
    project.mkdir(parents=True)
    video = project / "demo.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    web_agent.register_local_project({"input_video": str(video), "title": "demo"})

    result = web_agent.save_uploaded_project_cover(
        project_path=str(project),
        filename="../cover.png",
        content=b"png-bytes",
    )

    cover = project / "cover.png"
    assert cover.read_bytes() == b"png-bytes"
    assert result["thumbnail_path"] == str(cover)
    assert result["project"]["thumbnail"] == str(cover)
    manifest = yaml.safe_load((project / "project.yaml").read_text(encoding="utf-8"))
    assert manifest["thumbnail"] == str(cover)

def test_save_uploaded_video_creates_local_project(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")

    result = web_agent.save_uploaded_video_file(
        filename="../旅行 vlog.mp4",
        content=b"video-bytes",
        title="手机上传测试",
    )

    saved = Path(result["input_video"])
    assert saved == tmp_path / "YoutubeDownloads" / "手机上传测试" / "旅行 vlog.mp4"
    assert saved.read_bytes() == b"video-bytes"
    assert result["project"]["source_type"] == "local"
    assert result["project"]["name"] == "手机上传测试"
    assert Path(result["project_manifest"]).exists()


def test_mobile_asr_translate_job_runs_asr_then_translation(monkeypatch, tmp_path: Path):
    video = tmp_path / "YoutubeDownloads" / "demo" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        out_dir = tmp_path / "outputs" / "agent_jobs" / job_id
        if "video_translate.tools.transcribe_audio" in args:
            (out_dir / "source.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕하세요\n", encoding="utf-8")
        if "video_translate.tools.translate_subtitles" in args:
            (out_dir / "zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.mobile_asr_translate_job({
        "input_video": str(video),
        "language": "korean",
        "source_language": "korean",
        "model_size": "small",
        "translation_mode": "translate_only",
    })
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done"
    assert calls[0][:3] == ["/python", "-m", "video_translate.tools.transcribe_audio"]
    assert calls[1][:3] == ["/python", "-m", "video_translate.tools.translate_subtitles"]
    assert job.result["source_srt"].endswith("source.srt")
    assert job.result["translated_srt"].endswith("zh.srt")
    assert (video.parent / "demo.source.srt").exists()
    assert (video.parent / "demo.zh.srt").exists()

def test_child_process_env_sets_model_cache_without_proxy(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DEFAULT_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")

    env = web_agent._child_process_env()

    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["VIDEO_TRANSLATE_CACHE_DIR"] == str(tmp_path / "models")
    assert env["HF_HOME"] == str(tmp_path / "models" / "huggingface")
    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env
    assert "http_proxy" not in env
    assert "https_proxy" not in env
    assert "all_proxy" not in env


def test_child_process_env_adds_nvidia_cuda_library_paths(monkeypatch, tmp_path: Path):
    lib_dir = tmp_path / "env" / "lib" / "python3.11" / "site-packages" / "nvidia" / "cublas" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "libcublas.so.12").write_text("", encoding="utf-8")
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setenv("LD_LIBRARY_PATH", str(existing_dir))
    monkeypatch.setattr(web_agent, "cuda_library_dirs", lambda: [lib_dir])

    env = web_agent._child_process_env()

    paths = env["LD_LIBRARY_PATH"].split(os.pathsep)
    assert paths[0] == str(lib_dir)
    assert str(existing_dir) in paths


def test_correct_asr_subtitle_job_builds_correction_command(monkeypatch, tmp_path: Path):
    source = tmp_path / "outputs" / "agent_jobs" / "abc" / "source.srt"
    source.parent.mkdir(parents=True)
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n릴 짱\n", encoding="utf-8")
    glossary = tmp_path / "configs" / "glossaries" / "draft.yaml"
    glossary.parent.mkdir(parents=True)
    glossary.write_text("characters:\n- source: 렐짱\n  zh: 怜酱\n", encoding="utf-8")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        out = source.with_name("source.corrected.srt")
        out.write_text("1\n00:00:00,000 --> 00:00:01,000\n렐짱\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.correct_asr_subtitle_job(
        {
            "source_srt": str(source),
            "glossary": str(glossary),
            "source_language": "korean",
            "extra_hint": "아이브 레이 브이로그",
        }
    )
    deadline = __import__("time").time() + 2
    while job.status == "running" and __import__("time").time() < deadline:
        __import__("time").sleep(0.01)

    assert job.status == "done"
    assert calls[0][:3] == ["/python", "-m", "video_translate.tools.correct_asr"]
    assert "--glossary" in calls[0]
    assert calls[0][calls[0].index("--glossary") + 1] == str(glossary)
    assert "--extra-prompt" in calls[0]
    assert calls[0][calls[0].index("--extra-prompt") + 1] == "아이브 레이 브이로그"
    assert job.result["corrected_srt"].endswith("source.corrected.srt")
    assert job.result["subtitle_path"].endswith("source.corrected.srt")


def test_download_video_job_writes_project_manifest(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    downloads.mkdir()
    project = downloads / 'Target Video'
    project.mkdir()
    target = project / 'Target Video.mp4'
    thumbnail = project / 'Target Video.jpg'
    target.write_text('target', encoding='utf-8')
    thumbnail.write_text('thumb', encoding='utf-8')
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)
    monkeypatch.setattr(web_agent, 'PYTHON', '/python')
    monkeypatch.setattr(web_agent, '_run_command', lambda job_id, args: None)

    job = web_agent.download_video_job({'url': 'https://www.youtube.com/watch?v=abc123&t=99s', 'title': 'Target Video'})
    snapshot = _wait_job_status(job.id, 'done')

    manifest = yaml.safe_load((project / 'project.yaml').read_text(encoding='utf-8'))
    assert snapshot['result']['project_dir'] == str(project)
    assert snapshot['result']['project_manifest'] == str(project / 'project.yaml')
    assert manifest['source_type'] == 'youtube'
    assert manifest['normalized_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert manifest['primary_video'] == str(target)
    assert manifest['thumbnail'] == str(thumbnail)


def test_register_local_project_exposes_manifest_in_assets(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    uploads = tmp_path / 'uploads'
    downloads.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(web_agent, 'ROOT', tmp_path)
    video = uploads / 'my upload.mp4'
    video.write_bytes(b'video')
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)

    result = web_agent.register_local_project({'input_video': str(video), 'title': 'my upload'})
    assets = web_agent.list_local_assets()

    assert result['project']['manifest']['source_type'] == 'local'
    assert result['project']['manifest']['primary_video'] == str(video)
    project = next(item for item in assets['projects'] if item['manifest']['primary_video'] == str(video))
    assert project['name'] == 'my upload'
    assert project['primary_video'] == str(video)


def test_asset_scan_backfills_project_manifest_from_agent_task(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    project = downloads / 'Old Video'
    project.mkdir(parents=True)
    video = project / 'Old Video.mp4'
    video.write_bytes(b'video')
    tasks = tmp_path / 'agent_tasks'
    task_dir = tasks / 'abc123_old_video'
    task_dir.mkdir(parents=True)
    (task_dir / 'task.yaml').write_text(
        yaml.safe_dump(
            {
                'id': 'abc123_old_video',
                'url': 'https://www.youtube.com/watch?v=abc123&t=20s',
                'title': 'Old Video',
                'stages': {'ocr': {'input_video': str(video), 'source_srt': str(project / 'Old Video.source.srt')}},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)
    monkeypatch.setattr(web_agent, 'TASK_DIR', tasks)

    assets = web_agent.list_local_assets()

    found = next(item for item in assets['projects'] if item['path'] == str(project))
    assert found['source_type'] == 'youtube'
    assert found['normalized_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert (project / 'project.yaml').exists()


def test_probe_video_binds_existing_project_by_title(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    project = downloads / 'Target Video'
    project.mkdir(parents=True)
    video = project / 'Target Video.mp4'
    video.write_bytes(b'video')
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)

    class FakeYoutubeDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {
                'id': 'abc123',
                'title': 'Target Video',
                'duration': 100,
                'subtitles': {},
                'automatic_captions': {},
            }

    monkeypatch.setattr(web_agent.yt_dlp, 'YoutubeDL', FakeYoutubeDL)

    result = web_agent.probe_video('https://www.youtube.com/watch?v=abc123&t=99s')

    manifest = yaml.safe_load((project / 'project.yaml').read_text(encoding='utf-8'))
    assert result['existing_project']['path'] == str(project)
    assert result['existing_project']['normalized_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert manifest['source_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert manifest['primary_video'] == str(video)


def test_download_video_job_fetches_missing_thumbnail_for_existing_video(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    project = downloads / 'Target Video'
    project.mkdir(parents=True)
    target = project / 'Target Video.mp4'
    thumbnail = project / 'Target Video.jpg'
    target.write_text('target', encoding='utf-8')
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)
    monkeypatch.setattr(web_agent, 'PYTHON', '/python')
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        if args[:3] == ['/python', '-m', 'video_translate.youtube.download_thumbnail']:
            thumbnail.write_bytes(b'jpg')

    monkeypatch.setattr(web_agent, '_run_command', fake_run_command)

    job = web_agent.download_video_job({'url': 'https://www.youtube.com/watch?v=abc123', 'title': 'Target Video'})
    snapshot = _wait_job_status(job.id, 'done')

    assert [call[:3] for call in calls] == [
        ['/python', '-m', 'video_translate.youtube.download_video'],
        ['/python', '-m', 'video_translate.youtube.download_thumbnail'],
    ]
    assert snapshot['result']['thumbnail_path'] == str(thumbnail)
    manifest = yaml.safe_load((project / 'project.yaml').read_text(encoding='utf-8'))
    assert manifest['thumbnail'] == str(thumbnail)


def test_continue_after_glossary_path_reruns_completed_translation(monkeypatch, tmp_path: Path):
    tasks = tmp_path / 'agent_tasks'
    task_dir = tasks / 'task_done'
    task_dir.mkdir(parents=True)
    source = tmp_path / 'source.srt'
    glossary = task_dir / 'glossary.draft.yaml'
    previous = task_dir / 'zh.srt'
    fresh = tmp_path / 'fresh.zh.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n안녕\n', encoding='utf-8')
    glossary.write_text('characters: []\n', encoding='utf-8')
    previous.write_text('old', encoding='utf-8')
    fresh.write_text('new', encoding='utf-8')
    (task_dir / 'task.yaml').write_text(
        yaml.safe_dump(
            {
                'id': 'task_done',
                'title': 'Demo',
                'task_dir': str(task_dir),
                'current_stage': 'done',
                'workflow_status': 'completed',
                'completed_at': 123.0,
                'stages': {
                    'ocr': {'status': 'done', 'source_srt': str(source)},
                    'glossary': {'status': 'done', 'source_srt': str(source), 'glossary_path': str(glossary)},
                    'translate': {'status': 'done', 'source_srt': str(source), 'glossary_path': str(glossary), 'translated_srt': str(previous)},
                },
            },
            allow_unicode=True,
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(web_agent, 'TASK_DIR', tasks)
    monkeypatch.setattr(web_agent, '_AGENT_SESSIONS', {})
    calls = []

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status='done', result=result)

    def fake_translate(payload):
        calls.append(payload)
        return done_job('translate', {'translated_srt': str(fresh)})

    monkeypatch.setattr(web_agent, 'translate_subtitle_job', fake_translate)

    session = web_agent.continue_agent_after_glossary_review(str(glossary))
    snapshot = _wait_agent_status(session.id, 'done')
    task = web_agent.get_agent_task('task_done')

    assert calls and calls[0]['glossary'] == str(glossary)
    assert task['current_stage'] == 'done'
    assert task['workflow_status'] == 'completed'
    assert task['stages']['translate']['translated_srt'] == str(task_dir / 'zh.srt')
    assert snapshot['result']['translated_srt'] == str(task_dir / 'zh.srt')


def test_completed_glossary_review_task_continues_as_active(monkeypatch, tmp_path: Path):
    tasks = tmp_path / 'agent_tasks'
    task_dir = tasks / 'task1'
    task_dir.mkdir(parents=True)
    source = tmp_path / 'source.srt'
    glossary = tmp_path / 'glossary.draft.yaml'
    translated = tmp_path / 'zh.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\n안녕\n', encoding='utf-8')
    glossary.write_text('characters: []\n', encoding='utf-8')
    translated.write_text('1\n00:00:00,000 --> 00:00:01,000\n你好\n', encoding='utf-8')
    (task_dir / 'task.yaml').write_text(
        yaml.safe_dump(
            {
                'id': 'task1',
                'title': 'Demo',
                'task_dir': str(task_dir),
                'current_stage': 'glossary_review',
                'workflow_status': 'completed',
                'completed_at': 123.0,
                'stages': {
                    'ocr': {'status': 'done', 'source_srt': str(source)},
                    'glossary': {'status': 'waiting_review', 'source_srt': str(source), 'glossary_path': str(glossary)},
                },
            },
            allow_unicode=True,
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(web_agent, 'TASK_DIR', tasks)
    monkeypatch.setattr(web_agent, '_AGENT_SESSIONS', {})

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status='done', result=result)

    monkeypatch.setattr(
        web_agent,
        'translate_subtitle_job',
        lambda payload: done_job('translate', {'translated_srt': str(translated)}),
    )

    session = web_agent.continue_agent_task('task1')
    snapshot = _wait_agent_status(session.id, 'done')
    task = web_agent.get_agent_task('task1')

    assert task['workflow_status'] == 'completed'
    assert task['current_stage'] == 'done'
    assert task['stages']['translate']['status'] == 'done'
    assert snapshot['result']['translated_srt'].endswith('zh.srt')


def test_agent_task_completion_state_can_be_toggled(monkeypatch, tmp_path: Path):
    tasks = tmp_path / 'agent_tasks'
    task_dir = tasks / 'task1'
    task_dir.mkdir(parents=True)
    (task_dir / 'task.yaml').write_text(
        yaml.safe_dump({'id': 'task1', 'title': 'Demo', 'current_stage': 'glossary_review', 'stages': {}}, allow_unicode=True),
        encoding='utf-8',
    )
    monkeypatch.setattr(web_agent, 'TASK_DIR', tasks)

    before = web_agent.get_agent_task('task1')
    assert before['workflow_status'] == 'active'
    assert before['is_completed'] is False

    completed = web_agent.complete_agent_task('task1')
    task = web_agent.get_agent_task('task1')
    assert completed['completed'] is True
    assert task['workflow_status'] == 'completed'
    assert task['is_completed'] is True
    assert task['completed_at']

    reopened = web_agent.reopen_agent_task('task1')
    task = web_agent.get_agent_task('task1')
    assert reopened['reopened'] is True
    assert task['workflow_status'] == 'active'
    assert task['is_completed'] is False
    assert 'completed_at' not in task


def test_done_agent_task_is_listed_as_completed(monkeypatch, tmp_path: Path):
    tasks = tmp_path / 'agent_tasks'
    task_dir = tasks / 'task_done'
    task_dir.mkdir(parents=True)
    (task_dir / 'task.yaml').write_text(
        yaml.safe_dump({'id': 'task_done', 'title': 'Done Demo', 'current_stage': 'done', 'stages': {}}, allow_unicode=True),
        encoding='utf-8',
    )
    monkeypatch.setattr(web_agent, 'TASK_DIR', tasks)

    task = next(item for item in web_agent.list_agent_tasks() if item['id'] == 'task_done')

    assert task['workflow_status'] == 'completed'
    assert task['is_completed'] is True


def test_probe_video_downloads_thumbnail_for_new_project(monkeypatch, tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    downloads.mkdir()
    monkeypatch.setattr(web_agent, 'DOWNLOAD_DIR', downloads)

    class FakeYoutubeDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {
                'id': 'abc123',
                'title': 'Target Video',
                'duration': 100,
                'thumbnail': 'https://img.example/thumb.webp',
                'subtitles': {},
                'automatic_captions': {},
            }

    class FakeResponse:
        headers = {'Content-Type': 'image/jpeg'}
        content = b'jpg-bytes'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(web_agent.yt_dlp, 'YoutubeDL', FakeYoutubeDL)
    monkeypatch.setattr(web_agent.requests, 'get', lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(web_agent, 'convert_thumbnail_bytes', lambda content, image_format='jpg': content)

    result = web_agent.probe_video('https://www.youtube.com/watch?v=abc123&t=99s')

    project = downloads / 'Target Video'
    thumbnail = project / 'Target Video.jpg'
    manifest = yaml.safe_load((project / 'project.yaml').read_text(encoding='utf-8'))
    assert thumbnail.read_bytes() == b'jpg-bytes'
    assert result['existing_project']['path'] == str(project)
    assert result['existing_project']['thumbnail'] == str(thumbnail)
    assert result['thumbnail_path'] == str(thumbnail)
    assert manifest['normalized_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert manifest['thumbnail'] == str(thumbnail)
