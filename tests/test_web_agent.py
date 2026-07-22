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


def _stub_agent_project_video(monkeypatch, video: Path) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    if not video.exists():
        video.write_bytes(b"video")
    monkeypatch.setattr(
        web_agent,
        "download_video_job",
        lambda payload: web_agent.Job(
            id="project-video",
            name="project-video",
            status="done",
            result={"input_video": str(video)},
        ),
    )


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



def test_start_agent_session_uses_configured_japanese_for_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    captured = {}
    _stub_agent_project_video(monkeypatch, tmp_path / "demo.mp4")

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

def test_agent_session_waits_for_auto_subtitle_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    _stub_agent_project_video(monkeypatch, tmp_path / "demo.mp4")
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
        assert web_agent.TASK_DIR in Path(payload["out"]).parents
        assert ".work" in Path(payload["out"]).parts
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_generate_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")
    assert snapshot["question"]["options"][0]["action"] == "use_recommended"
    assert calls == []

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
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
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
            "existing_project": {"path": str(tmp_path), "primary_video": str(video)},
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
    def fake_dual(payload):
        assert payload["input_video"] == str(video)
        calls.append(f"dual:{payload['source_srt']}:{payload['reference_srt']}")
        return done_job(
            "dual",
            {"source_srt": str(dual), "context_srt": str(tmp_path / "dual.context.srt"), "debug_json": str(tmp_path / "dual.debug.json")},
        )

    monkeypatch.setattr(web_agent, "dual_subtitle_reference_job", fake_dual)
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")

    assert calls == []

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_kind"] == "dual_subtitle_reference"
    assert snapshot["result"]["source_srt"] == str(dual)
    assert calls == ["subtitle:ko", "subtitle:en", f"dual:{ko}:{en}", f"glossary:{dual}"]




def test_agent_waits_for_route_choice_before_downloading_project_video(monkeypatch, tmp_path):
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

    assert snapshot["status"] == "waiting"
    assert "input_video" not in snapshot["result"]
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert calls == []

    web_agent.answer_agent_session(session.id, {"action": "manual_mode"})
    snapshot = _wait_agent_status(session.id, "done")
    task = web_agent.get_agent_task(snapshot["result"]["task_id"])

    assert snapshot["result"]["input_video"] == str(video)
    assert snapshot["result"]["next_view"] == "new-task"
    assert task["stages"]["probe"]["input_video"] == str(video)
    assert calls == ["video:https://www.youtube.com/watch?v=abc123"]


def test_start_agent_session_maps_explicit_v2_as_one_coherent_pipeline(monkeypatch):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_run_agent_async", lambda session_id, target: None)

    session = web_agent.start_agent_session(
        {
            "url": "abc123",
            "ocr_pipeline_version": "v2",
            "ocr_extraction_mode": "auto",
            "ocr_refinement_mode": "none",
            "ocr_translation_mode": "standard_cleanup",
            "ocr_shape_mode": "horizontal_strict",
        }
    )

    assert session.payload["ocr_pipeline_version"] == "v2"
    assert session.payload["ocr_extraction_mode"] == "region"
    assert session.payload["ocr_refinement_mode"] == "llm_boxes"
    assert session.payload["ocr_translation_mode"] == "translate_only"
    assert session.payload["ocr_shape_mode"] == "unrestricted"


def test_historical_unversioned_region_task_resumes_as_legacy_not_v2(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    task = {
        "id": "legacy-region",
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "legacy",
        "task_dir": str(tmp_path),
        "payload": {
            "ocr_extraction_mode": "region",
            "ocr_refinement_mode": "none",
            "ocr_translation_mode": "standard_cleanup",
        },
        "stages": {
            "ocr": {
                "status": "done",
                "source_srt": str(source),
                "ocr_extraction_mode": "region",
                "ocr_refinement_mode": "none",
            }
        },
    }

    session = web_agent._agent_session_from_task(task)

    assert session.payload["ocr_pipeline_version"] == "v1"
    assert session.payload["ocr_extraction_mode"] == "auto"
    assert session.payload["ocr_refinement_mode"] == "none"
    assert session.payload["ocr_translation_mode"] == "standard_cleanup"


def test_agent_session_from_task_preserves_run_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    task = {
        "id": "generation-task",
        "task_dir": str(tmp_path),
        "url": "https://www.youtube.com/watch?v=abc123",
        "run_generation": 7,
        "payload": {},
        "stages": {},
    }

    session = web_agent._agent_session_from_task(task)

    assert session.result["run_generation"] == 7


def test_agent_answer_switches_to_v2_and_persists_pipeline_in_task(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_find_reusable_ocr_result", lambda **kwargs: None)
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    glossary = tmp_path / "glossary.draft.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    captured: dict[str, object] = {}

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
                "confidence": 0.7,
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    _stub_agent_project_video(monkeypatch, video)

    def fake_ocr(payload):
        captured.update(payload)
        return done_job(
            "ocr",
            {"source_srt": str(source), "input_video": str(video), "output_dir": str(tmp_path)},
        )

    monkeypatch.setattr(web_agent, "ocr_extract_job", fake_ocr)
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: done_job(
            "glossary",
            {"glossary_path": str(glossary), "content": "characters: []\n"},
        ),
    )

    session = web_agent.start_agent_session(
        {"url": "abc123", "embedded_subtitle_hint": "yes", "ocr_pipeline_version": "v1"}
    )
    _wait_agent_phase(session.id, "diagnose_ocr_asr")

    web_agent.answer_agent_session(
        session.id,
        {
            "action": "run_ocr",
            "ocr_pipeline_version": "v2",
            "ocr_extraction_mode": "auto",
            "ocr_refinement_mode": "none",
            "ocr_translation_mode": "standard_cleanup",
            "ocr_shape_mode": "horizontal_strict",
        },
    )
    snapshot = _wait_agent_phase(session.id, "review_glossary")
    task = web_agent.get_agent_task(snapshot["result"]["task_id"])

    expected_payload = {
        "ocr_pipeline_version": "v2",
        "ocr_extraction_mode": "region",
        "ocr_refinement_mode": "llm_boxes",
        "ocr_translation_mode": "translate_only",
        "ocr_shape_mode": "unrestricted",
    }
    for key, value in expected_payload.items():
        assert snapshot["payload"][key] == value
        assert task["payload"][key] == value
        assert captured[key if key != "ocr_translation_mode" else "translation_mode"] == value
    assert captured["input_video"] == str(video)
    assert task["stages"]["ocr"]["ocr_pipeline_version"] == "v2"
    assert task["stages"]["ocr"]["ocr_extraction_mode"] == "region"
    assert task["stages"]["ocr"]["ocr_refinement_mode"] == "llm_boxes"
    assert task["stages"]["ocr"]["ocr_source_cleanup_mode"] == "none"
    assert task["stages"]["ocr"]["ocr_translation_mode"] == "translate_only"
    assert task["stages"]["ocr"]["ocr_shape_mode"] == "unrestricted"


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
        "download_video_job",
        lambda payload: calls.append("video") or done_job("video", {"input_video": str(video)}),
    )

    monkeypatch.setattr(
        web_agent,
        "ocr_extract_job",
        lambda payload: calls.append(f"ocr:{payload['input_video']}:{payload['ocr_extraction_mode']}:{payload['ocr_shape_mode']}") or done_job("ocr", {"source_srt": str(source), "input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: calls.append(f"glossary:{payload['source_srt']}:{payload.get('source_language')}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}),
    )

    session = web_agent.start_agent_session(
        {
            "url": "abc123",
            "embedded_subtitle_hint": "yes",
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "diagnose_ocr_asr"
    assert any(option["action"] == "run_ocr" for option in snapshot["question"]["options"])
    assert calls == []

    web_agent.answer_agent_session(session.id, {"action": "run_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert "OCR 原文字幕" in snapshot["question"]["message"]
    assert snapshot["result"]["source_kind"] == "ocr"
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == ["video", f"ocr:{video}:region_v3:horizontal_strict", f"glossary:{snapshot['result']['source_srt']}:korean"]


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

    _stub_agent_project_video(monkeypatch, video)

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
    assert calls == []

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
    monkeypatch.setattr(web_agent, "ocr_local_video_job", lambda payload: calls.append(f"ocr_ref:{payload['input_video']}:{payload.get('extract_only')}:{payload['ocr_extraction_mode']}:{payload['ocr_shape_mode']}") or done_job("ocr", {"source_srt": str(ocr_source), "input_video": str(video)}))
    monkeypatch.setattr(web_agent, "correct_asr_subtitle_job", lambda payload: calls.append(f"correct:{payload['reference_srt']}") or done_job("correct", {"source_srt": str(corrected), "corrected_srt": str(corrected)}))
    monkeypatch.setattr(web_agent, "generate_glossary_job", lambda payload: calls.append(f"glossary:{payload['source_srt']}") or done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"}))

    session = web_agent.start_agent_session(
        {
            "url": "abc123",
            "embedded_subtitle_hint": "yes",
            "embedded_subtitle_goal": "full_speech",
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    snapshot = _wait_agent_phase(session.id, "diagnose_ocr_asr")
    assert any(option["action"] == "run_asr_with_ocr" for option in snapshot["question"]["options"])
    assert calls == []

    web_agent.answer_agent_session(session.id, {"action": "run_asr_with_ocr"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_kind"] == "asr_ocr_reference"
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == ["video", f"asr:{video}", f"ocr_ref:{video}:True:region_v3:horizontal_strict", f"correct:{ocr_source}", f"glossary:{snapshot['result']['source_srt']}"]

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

    _stub_agent_project_video(monkeypatch, video)

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

    job = web_agent.ocr_full_job(
        {
            "url": "abc123",
            "title": "demo",
            "ocr_language": "chinese",
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done"
    run_yaml = Path(job.result["output_dir"]) / "run.yaml"
    config = yaml.safe_load(run_yaml.read_text(encoding="utf-8"))
    assert config["mode"] == "extract"
    assert config["source_language"] == "chinese"
    assert config["ocr"]["extraction_mode"] == "region_v3"
    assert config["ocr"]["shape_mode"] == "horizontal_strict"
    assert config["agent_cache"]["ocr_shape_mode"] == "horizontal_strict"
    assert job.result["ocr_shape_mode"] == "horizontal_strict"
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


def _write_cached_ocr_job(
    jobs: Path,
    *,
    name: str,
    input_video: Path,
    cache: dict[str, object],
) -> Path:
    job_dir = jobs / name
    job_dir.mkdir(parents=True)
    source = job_dir / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (job_dir / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "mode": "extract",
                "input_video": str(input_video),
                "source_srt": str(source),
                "agent_cache": cache,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize("matched_by", ["url", "title"])
@pytest.mark.parametrize("legacy_refinement", ["none", "llm_boxes"])
def test_v2_cache_rejects_unversioned_region_jobs_for_url_and_title_matches(
    monkeypatch,
    tmp_path: Path,
    matched_by: str,
    legacy_refinement: str,
):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)
    video = tmp_path / "Target Demo.mp4"
    video.write_bytes(b"video")
    cached_url = (
        "https://www.youtube.com/watch?v=abc123"
        if matched_by == "url"
        else "https://www.youtube.com/watch?v=other123"
    )
    _write_cached_ocr_job(
        jobs,
        name=f"legacy-{matched_by}-{legacy_refinement}",
        input_video=video,
        cache={
            "normalized_url": cached_url,
            "ocr_translation_mode": "translate_only",
            "ocr_scope": "bottom",
            "ocr_extraction_mode": "region",
            "ocr_refinement_mode": legacy_refinement,
        },
    )

    cached = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="Target Demo",
        translation_mode="standard_cleanup",
        ocr_pipeline_version="v2",
        ocr_scope="bottom",
        ocr_extraction_mode="auto",
        ocr_refinement_mode="none",
    )

    assert cached is None


@pytest.mark.parametrize("matched_by", ["url", "title"])
def test_v2_cache_reuses_only_versioned_v2_jobs(monkeypatch, tmp_path: Path, matched_by: str):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)
    video = tmp_path / "Target Demo.mp4"
    video.write_bytes(b"video")
    cached_url = (
        "https://www.youtube.com/watch?v=abc123"
        if matched_by == "url"
        else "https://www.youtube.com/watch?v=other123"
    )
    source = _write_cached_ocr_job(
        jobs,
        name=f"v2-{matched_by}",
        input_video=video,
        cache={
            "normalized_url": cached_url,
            "ocr_pipeline_version": "v2",
            "ocr_translation_mode": "translate_only",
            "ocr_source_cleanup_mode": "none",
            "ocr_scope": "bottom",
            "ocr_extraction_mode": "region",
            "ocr_refinement_mode": "llm_boxes",
        },
    )

    cached = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="Target Demo",
        translation_mode="standard_cleanup",
        ocr_pipeline_version="v2",
        ocr_scope="bottom",
        ocr_extraction_mode="auto",
        ocr_refinement_mode="none",
    )

    assert cached is not None
    assert cached["source_srt"] == str(source)
    assert cached["matched_by"] == matched_by
    assert cached["ocr_pipeline_version"] == "v2"
    assert cached["ocr_source_cleanup_mode"] == "none"
    assert cached["ocr_extraction_mode"] == "region"
    assert cached["ocr_refinement_mode"] == "llm_boxes"
    assert cached["ocr_translation_mode"] == "translate_only"


def test_v1_cache_keeps_unversioned_legacy_auto_job_compatible(monkeypatch, tmp_path: Path):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)
    video = tmp_path / "Legacy Demo.mp4"
    video.write_bytes(b"video")
    source = _write_cached_ocr_job(
        jobs,
        name="legacy-auto",
        input_video=video,
        cache={
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "ocr_scope": "bottom",
        },
    )

    cached = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="Legacy Demo",
        translation_mode="translate_only",
        ocr_pipeline_version="v1",
        ocr_extraction_mode="region",
        ocr_refinement_mode="llm_boxes",
    )

    assert cached is not None
    assert cached["source_srt"] == str(source)
    assert cached["ocr_pipeline_version"] == "v1"
    assert cached["ocr_extraction_mode"] == "auto"
    assert cached["ocr_refinement_mode"] == "none"
    assert cached["ocr_translation_mode"] == "standard_cleanup"


def test_v2_task_cache_requires_pipeline_version_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "missing-jobs")
    task_dir = web_agent.TASK_DIR / "abc123_demo"
    task_dir.mkdir(parents=True)
    source = task_dir / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    task_path = task_dir / "task.yaml"
    task_data = {
        "id": "abc123_demo",
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "demo",
        "stages": {
            "ocr": {
                "status": "done",
                "source_srt": str(source),
                "ocr_scope": "bottom",
                "ocr_extraction_mode": "region",
                "ocr_refinement_mode": "llm_boxes",
            }
        },
    }
    task_path.write_text(
        yaml.safe_dump(task_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    query = {
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "demo",
        "translation_mode": "standard_cleanup",
        "ocr_pipeline_version": "v2",
    }

    assert web_agent._find_reusable_ocr_result(**query) is None

    task_data["stages"]["ocr"]["ocr_pipeline_version"] = "v2"
    task_data["stages"]["ocr"]["ocr_source_cleanup_mode"] = "none"
    task_path.write_text(
        yaml.safe_dump(task_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    cached = web_agent._find_reusable_ocr_result(**query)

    assert cached is not None
    assert cached["source_srt"] == str(source)
    assert cached["ocr_pipeline_version"] == "v2"


def test_reusable_ocr_job_cache_isolated_by_v3_shape_mode_and_keeps_old_region_compatible(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(web_agent, "JOB_DIR", jobs)
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")

    v3_dir = jobs / "v3"
    v3_dir.mkdir(parents=True)
    v3_source = v3_dir / "source.srt"
    v3_source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (v3_dir / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "mode": "extract",
                "input_video": str(video),
                "source_srt": str(v3_source),
                "agent_cache": {
                    "normalized_url": "https://www.youtube.com/watch?v=abc123",
                    "ocr_scope": "bottom",
                    "ocr_extraction_mode": "region_v3",
                    "ocr_shape_mode": "horizontal_preferred",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_extraction_mode="region_v3",
        ocr_shape_mode="horizontal_strict",
    ) is None
    cached_v3 = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_extraction_mode="region_v3",
        ocr_shape_mode="horizontal_preferred",
    )
    assert cached_v3 is not None
    assert cached_v3["ocr_shape_mode"] == "horizontal_preferred"

    old_dir = jobs / "old-region"
    old_dir.mkdir()
    old_source = old_dir / "source.srt"
    old_source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (old_dir / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "mode": "extract",
                "input_video": str(video),
                "source_srt": str(old_source),
                "agent_cache": {
                    "normalized_url": "https://www.youtube.com/watch?v=abc123",
                    "ocr_scope": "bottom",
                    "ocr_extraction_mode": "region",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cached_region = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_extraction_mode="region",
        ocr_shape_mode="horizontal_strict",
    )
    assert cached_region is not None
    assert cached_region["ocr_shape_mode"] == "unrestricted"


def test_reusable_ocr_task_cache_isolated_by_v3_shape_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "missing-jobs")
    task_dir = web_agent.TASK_DIR / "abc123_demo"
    task_dir.mkdir(parents=True)
    source = task_dir / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "abc123_demo",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "demo",
                "stages": {
                    "ocr": {
                        "status": "done",
                        "source_srt": str(source),
                        "ocr_scope": "bottom",
                        "ocr_extraction_mode": "region_v3",
                        "ocr_shape_mode": "horizontal_preferred",
                        "ocr_refinement_mode": "none",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_extraction_mode="region_v3",
        ocr_shape_mode="horizontal_strict",
    ) is None
    cached = web_agent._find_reusable_ocr_result(
        url="https://www.youtube.com/watch?v=abc123",
        title="demo",
        translation_mode="standard_cleanup",
        ocr_extraction_mode="region_v3",
        ocr_shape_mode="horizontal_preferred",
    )
    assert cached is not None
    assert cached["ocr_shape_mode"] == "horizontal_preferred"


def test_agent_session_reuses_cached_ocr_before_generating_glossary(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path)
    source = tmp_path / "oldjob" / "source.srt"
    source.parent.mkdir(parents=True)
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    cached_video = tmp_path / "old-downloads" / "demo.mp4"
    cached_video.parent.mkdir(parents=True)
    cached_video.write_bytes(b"old-video")
    project_video = tmp_path / "downloads" / "demo.mp4"
    project_video.parent.mkdir(parents=True)
    project_video.write_bytes(b"current-video")
    (source.parent / "run.yaml").write_text(
        "\n".join(
            [
                "mode: extract",
                f"input_video: {cached_video}",
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

    _stub_agent_project_video(monkeypatch, project_video)

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
    assert snapshot["result"]["input_video"] == str(project_video)
    assert Path(snapshot["result"]["source_srt"]).parts[-3:] == ("agent_tasks", "abc123_demo", "source.srt")
    assert calls == [f"glossary:{snapshot['result']['source_srt']}:korean"]
    task = web_agent.get_agent_task(snapshot["result"]["task_id"])
    assert task["stages"]["ocr"]["input_video"] == str(project_video)

    assert (
        web_agent._find_reusable_ocr_result(
            url="https://www.youtube.com/watch?v=abc123",
            title="demo",
            translation_mode="standard_cleanup",
            ocr_scope="bottom",
            ocr_extraction_mode="region",
            source_language="korean",
        )
        is None
    )


def test_agent_task_persists_glossary_review_and_can_continue(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    source = tmp_path / "source.srt"
    glossary = tmp_path / "glossary.draft.yaml"
    translated = tmp_path / "zh.srt"
    video = tmp_path / "demo.mp4"
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

    _stub_agent_project_video(monkeypatch, video)
    monkeypatch.setattr(web_agent, "ocr_extract_job", lambda payload: done_job("ocr", {"source_srt": str(source), "input_video": str(video)}))
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

    restored = web_agent.continue_agent_task(task_id)
    assert restored.status == "waiting"
    assert restored.phase == "review_glossary"
    reviewed_glossary = snapshot["result"]["glossary_path"]
    continued = web_agent.continue_agent_after_glossary_review(reviewed_glossary)
    snapshot = _wait_agent_status(continued.id, "done")

    task = web_agent.get_agent_task(task_id)
    assert task["current_stage"] == "done"
    assert task["stages"]["translate"]["status"] == "done"
    assert len(calls) == 1
    assert calls[0].startswith(f"translate:{task['stages']['ocr']['source_srt']}:")
    assert Path(calls[0].rsplit(":", 1)[1]).read_text(encoding="utf-8") == Path(reviewed_glossary).read_text(encoding="utf-8")
    assert snapshot["result"]["translated_srt"].endswith("zh.srt")


def test_same_video_new_agent_run_clears_stale_downstream_stages(tmp_path):
    url = "https://www.youtube.com/watch?v=abc123"
    first = web_agent._ensure_agent_task(normalized_url=url, title="demo", payload={"url": url})
    stale_zh = Path(first["task_dir"]) / "zh.srt"
    old_source = Path(first["task_dir"]) / "source.srt"
    old_source.write_text("old OCR source", encoding="utf-8")
    stale_zh.write_text("old translation", encoding="utf-8")
    web_agent._update_task_stage(first["id"], "ocr", "done", source_srt=str(old_source), ocr_pipeline_version="v2")
    web_agent._update_task_stage(first["id"], "glossary", "waiting_review", glossary_path=str(Path(first["task_dir"]) / "glossary.draft.yaml"))
    web_agent._update_task_stage(first["id"], "translate", "done", current_stage="done", translated_srt=str(stale_zh))

    restarted = web_agent._ensure_agent_task(normalized_url=url, title="demo", payload={"url": url})

    assert restarted["id"] == first["id"]
    assert restarted["run_generation"] == 2
    assert restarted["current_stage"] == "created"
    assert restarted["workflow_status"] == "active"
    assert restarted["stages"] == {}
    assert restarted["ocr_cache"][0]["source_srt"] != str(old_source)
    assert Path(restarted["ocr_cache"][0]["source_srt"]).read_text(encoding="utf-8") == "old OCR source"
    old_source.write_text("new OCR source", encoding="utf-8")
    assert Path(restarted["ocr_cache"][0]["source_srt"]).read_text(encoding="utf-8") == "old OCR source"
    assert "completed_at" not in restarted


def test_old_generation_stage_update_does_not_mutate_new_task(tmp_path):
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    task_yaml = task_dir / "task.yaml"
    task_yaml.write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "run_generation": 2,
                "current_stage": "translate",
                "stages": {"translate": {"status": "running", "marker": "new generation"}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    changed = web_agent._update_task_stage(
        "task1",
        "translate",
        "failed",
        current_stage="translate_failed",
        expected_generation=1,
        error="stale worker failed",
    )

    persisted = web_agent.get_agent_task("task1")
    assert changed is False
    assert persisted["run_generation"] == 2
    assert persisted["current_stage"] == "translate"
    assert persisted["stages"]["translate"] == {"status": "running", "marker": "new generation"}


def test_old_generation_cannot_bind_after_newer_agent_start(monkeypatch):
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    task_yaml = task_dir / "task.yaml"
    task_yaml.write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "run_generation": 2,
                "current_stage": "probe_done",
                "stages": {},
            }
        ),
        encoding="utf-8",
    )
    old = web_agent.AgentSession(id="old", result={"task_id": "task1", "run_generation": 1})
    new = web_agent.AgentSession(id="new", result={"task_id": "task1", "run_generation": 2})
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {old.id: old, new.id: new})

    with pytest.raises(RuntimeError, match="更新的一轮"):
        web_agent._bind_session_to_task_run(
            old.id,
            {"id": "task1", "task_dir": str(task_dir), "run_generation": 1},
        )

    assert old.status == "cancelled"
    assert new.status == "running"
    assert new.result["run_generation"] == 2


def test_old_generation_materialize_does_not_overwrite_new_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "run_generation": 2,
                "current_stage": "translate",
                "stages": {"translate": {"status": "running"}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    destination = task_dir / "zh.srt"
    destination.write_text("new generation translation", encoding="utf-8")
    stale_source = tmp_path / "stale-translation.srt"
    stale_source.write_text("stale generation translation", encoding="utf-8")
    session = web_agent.AgentSession(
        id="stale-session",
        phase="translate",
        result={"task_id": "task1", "task_dir": str(task_dir), "run_generation": 1},
    )

    try:
        web_agent._materialize_task_artifact(session, str(stale_source), "zh.srt")
    except RuntimeError:
        # Rejecting the stale worker explicitly is also a valid implementation.
        pass

    assert destination.read_text(encoding="utf-8") == "new generation translation"


def test_old_generation_failure_does_not_mark_new_task_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "run_generation": 2,
                "current_stage": "translate",
                "stages": {"translate": {"status": "running", "marker": "new generation"}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    stale_session = web_agent.AgentSession(
        id="stale-session",
        phase="translate",
        result={"task_id": "task1", "task_dir": str(task_dir), "run_generation": 1},
    )
    web_agent._AGENT_SESSIONS[stale_session.id] = stale_session

    web_agent._agent_fail(stale_session.id, RuntimeError("stale worker failed"))

    persisted = web_agent.get_agent_task("task1")
    assert persisted["run_generation"] == 2
    assert persisted["current_stage"] == "translate"
    assert persisted["stages"]["translate"] == {"status": "running", "marker": "new generation"}


def test_atomic_glossary_save_rejects_pending_review_without_overwrite_or_translation(monkeypatch):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    source = task_dir / "source.srt"
    glossary = task_dir / "glossary.draft.yaml"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    original = "characters:\n- source: 박보영\n  zh: ''\n  reviewed: false\n"
    glossary.write_text(original, encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "run_generation": 1,
                "current_stage": "glossary_review",
                "stages": {
                    "glossary": {
                        "status": "waiting_review",
                        "source_srt": str(source),
                        "glossary_path": str(glossary),
                    }
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    translate_calls = []
    monkeypatch.setattr(
        web_agent,
        "translate_subtitle_job",
        lambda payload: translate_calls.append(payload),
    )

    with pytest.raises(ValueError, match="还有 1 条未审核"):
        web_agent.save_glossary_review_and_continue(
            {
                "path": str(glossary),
                "items": [{"section": "characters", "index": 0, "zh": "朴宝英", "reviewed": False}],
            }
        )

    assert glossary.read_text(encoding="utf-8") == original
    assert translate_calls == []
    persisted = web_agent.get_agent_task("task1")
    assert persisted["current_stage"] == "glossary_review"
    assert persisted["stages"]["glossary"]["status"] == "waiting_review"
    assert "translate" not in persisted["stages"]


def test_atomic_glossary_save_and_continue_is_idempotent_while_translation_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    source = task_dir / "dual.source.srt"
    glossary = task_dir / "glossary.draft.yaml"
    translated = tmp_path / "translated.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文原文：안녕\n英文参考：Hi\n", encoding="utf-8")
    glossary.write_text("characters:\n- source: 박보영\n  zh: ''\n  reviewed: false\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "current_stage": "glossary_review",
                "stages": {
                    "glossary": {
                        "status": "waiting_review",
                        "source_srt": str(source),
                        "source_kind": "dual_subtitle_reference",
                        "glossary_path": str(glossary),
                    }
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    child = web_agent.Job(id="translate1", name="translate", status="running")
    calls = []

    def fake_translate(payload):
        calls.append(payload)
        return child

    monkeypatch.setattr(web_agent, "translate_subtitle_job", fake_translate)
    payload = {
        "path": str(glossary),
        "items": [{"section": "characters", "index": 0, "zh": "朴宝英", "reviewed": True}],
    }

    waiting = web_agent.continue_agent_task("task1")
    assert waiting.status == "waiting"
    assert waiting.phase == "review_glossary"
    first = web_agent.save_glossary_review_and_continue(payload)
    deadline = time.time() + 2
    while len(calls) < 1 and time.time() < deadline:
        time.sleep(0.01)
    second = web_agent.save_glossary_review_and_continue(payload)

    assert first["saved"] is True
    assert first["review_summary"]["all_reviewed"] is True
    assert first["session"]["id"] == waiting.id
    assert first["session"]["id"] == second["session"]["id"]
    assert len(calls) == 1
    assert not any(
        session.status == "waiting" and session.phase == "review_glossary"
        for session in web_agent._AGENT_SESSIONS.values()
    )
    persisted = web_agent.get_agent_task("task1")
    assert persisted["stages"]["glossary"]["status"] == "reviewed"
    assert persisted["current_stage"] in {"translate_pending", "translate_running"}

    translated.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    child.result = {"translated_srt": str(translated)}
    child.status = "done"
    _wait_agent_status(first["session"]["id"], "done")
    completed_retry = web_agent.save_glossary_review_and_continue(payload)
    assert completed_retry["session"]["id"] == first["session"]["id"]
    assert completed_retry["session"]["status"] == "done"
    assert len(calls) == 1


def test_restart_restores_dual_source_kind_and_copies_translated_sidecar(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    task_dir = web_agent.TASK_DIR / "task1"
    task_dir.mkdir(parents=True)
    project_dir = tmp_path / "YoutubeDownloads" / "demo"
    project_dir.mkdir(parents=True)
    video = project_dir / "demo.mp4"
    source = task_dir / "dual.source.srt"
    glossary = task_dir / "glossary.draft.yaml"
    translated = tmp_path / "dual.source.zh.srt"
    video.write_bytes(b"video")
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文原文：안녕\n英文参考：Hi\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
    translated.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "task_dir": str(task_dir),
                "current_stage": "translate_pending",
                "stages": {
                    "glossary": {
                        "status": "reviewed",
                        "source_srt": str(source),
                        "source_kind": "dual_subtitle_reference",
                        "glossary_path": str(glossary),
                        "input_video": str(video),
                        "project_dir": str(project_dir),
                    },
                    "translate": {"status": "queued", "source_srt": str(source), "glossary_path": str(glossary)},
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    captured = {}

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    def fake_translate(payload):
        captured.update(payload)
        return done_job("translate", {"translated_srt": str(translated)})

    monkeypatch.setattr(web_agent, "translate_subtitle_job", fake_translate)

    session = web_agent.continue_agent_task("task1")
    snapshot = _wait_agent_status(session.id, "done")

    assert snapshot["result"]["source_kind"] == "dual_subtitle_reference"
    assert "dual reference" in captured["extra_prompt"]
    assert Path(snapshot["result"]["translated_sidecar"]) == project_dir / "demo.zh.srt"
    assert (project_dir / "demo.zh.srt").exists()


def test_restart_recovers_youtube_project_for_legacy_task_and_copies_translated_sidecar(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    monkeypatch.setattr(web_agent, "_ensure_under_root", lambda path: None)
    downloads = tmp_path / "YoutubeDownloads"
    project_dir = downloads / "Legacy Demo"
    task_dir = web_agent.TASK_DIR / "task1"
    project_dir.mkdir(parents=True)
    task_dir.mkdir(parents=True)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    video = project_dir / "Legacy Demo.mp4"
    source = task_dir / "dual.source.srt"
    glossary = task_dir / "glossary.draft.yaml"
    translated = tmp_path / "translated.srt"
    video.write_bytes(b"video")
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n韩文原文：안녕\n英文参考：Hi\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
    translated.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    web_agent.update_youtube_project_manifest(
        video,
        source_url="https://www.youtube.com/watch?v=legacy123",
        title="Legacy Demo",
    )
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "task1",
                "url": "https://www.youtube.com/watch?v=legacy123",
                "title": "Legacy Demo",
                "task_dir": str(task_dir),
                "current_stage": "translate_pending",
                "stages": {
                    "glossary": {
                        "status": "reviewed",
                        "source_srt": str(source),
                        "source_kind": "dual_subtitle_reference",
                        "glossary_path": str(glossary),
                    },
                    "translate": {
                        "status": "queued",
                        "source_srt": str(source),
                        "glossary_path": str(glossary),
                    },
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        web_agent,
        "translate_subtitle_job",
        lambda payload: web_agent.Job(
            id="translate",
            name="translate",
            status="done",
            result={"translated_srt": str(translated)},
        ),
    )

    session = web_agent.continue_agent_task("task1")
    snapshot = _wait_agent_status(session.id, "done")

    expected_sidecar = project_dir / "Legacy Demo.zh.srt"
    assert expected_sidecar.read_text(encoding="utf-8").endswith("你好\n")
    assert snapshot["result"]["input_video"] == str(video)
    assert snapshot["result"]["project_dir"] == str(project_dir)
    assert snapshot["result"]["translated_sidecar"] == str(expected_sidecar)
    persisted = web_agent.get_agent_task("task1")
    assert persisted["stages"]["translate"]["input_video"] == str(video)
    assert persisted["stages"]["translate"]["project_dir"] == str(project_dir)
    assert persisted["stages"]["translate"]["translated_sidecar"] == str(expected_sidecar)


def test_legacy_source_run_metadata_recovers_project_video(tmp_path):
    project_dir = tmp_path / "YoutubeDownloads" / "demo"
    job_dir = tmp_path / "agent_jobs" / "job1"
    project_dir.mkdir(parents=True)
    job_dir.mkdir(parents=True)
    video = project_dir / "demo.mp4"
    source_subtitle = project_dir / "demo.ko.srt"
    generated_source = job_dir / "dual.source.srt"
    video.write_bytes(b"video")
    source_subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    generated_source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    (job_dir / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "mode": "dual_subtitle_reference",
                "source_subtitle": str(source_subtitle),
                "source_srt": str(generated_source),
            }
        ),
        encoding="utf-8",
    )
    task = {
        "id": "legacy",
        "stages": {"glossary": {"source_srt": str(generated_source)}},
    }
    session = web_agent.AgentSession(
        id="legacy-session",
        result={"source_srt": str(generated_source)},
    )

    assert web_agent._agent_input_video_from_source_metadata(session, task) == video


def test_find_or_bind_youtube_project_ignores_debug_video(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    debug_dir = downloads / "debug"
    debug_dir.mkdir(parents=True)
    debug_video = debug_dir / "Target Video.mp4"
    debug_video.write_bytes(b"debug video")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    project = web_agent._find_or_bind_youtube_project(
        "https://www.youtube.com/watch?v=target123",
        "Target Video",
    )

    assert project == {}
    assert not (debug_dir / "project.yaml").exists()


def test_find_or_bind_youtube_project_rejects_ambiguous_title_matches(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    first = downloads / "first"
    second = downloads / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "Target Video.mp4").write_bytes(b"first")
    (second / "Target Video.mp4").write_bytes(b"second")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    project = web_agent._find_or_bind_youtube_project(
        "https://www.youtube.com/watch?v=target123",
        "Target Video",
    )

    assert project == {}
    assert not (first / "project.yaml").exists()
    assert not (second / "project.yaml").exists()


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
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")
    assert calls == ["video", f"lang:{video}"]

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
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
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
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

    def fake_video_download(payload):
        calls.append(f"video:{payload['url']}")
        return done_job("video", {"input_video": str(video)})

    def fake_glossary(payload):
        calls.append(f"glossary:{payload['source_srt']}:{payload.get('out', '')}")
        assert Path(payload["out"]).name == "glossary.draft.yaml"
        assert web_agent.TASK_DIR in Path(payload["out"]).parents
        assert ".work" in Path(payload["out"]).parts
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "download_video_job", fake_video_download)
    monkeypatch.setattr(web_agent, "download_subtitle_job", fake_download)
    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")

    assert snapshot["question"]["kind"] == "confirm_subtitle"
    assert calls == []

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert snapshot["result"]["source_srt"] == str(source)
    assert Path(snapshot["result"]["glossary_path"]).name == "glossary.draft.yaml"
    assert Path(snapshot["result"]["glossary_path"]).parent.parent == web_agent.TASK_DIR
    assert Path(snapshot["result"]["glossary_path"]).read_text(encoding="utf-8") == glossary.read_text(encoding="utf-8")
    assert snapshot["result"]["input_video"] == str(video)
    assert calls[0] == "video:https://www.youtube.com/watch?v=abc123"
    assert calls[1] == "download:ko:manual"
    assert calls[2].startswith(f"glossary:{source}:")


def test_target_subtitle_route_downloads_video_only_after_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    subtitle = tmp_path / "demo.zh.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        web_agent,
        "probe_video",
        lambda url, **kwargs: {
            "title": "demo",
            "normalized_url": "https://www.youtube.com/watch?v=abc123",
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
            "subtitles": [{"lang": "zh-CN", "kind": "manual", "label": "zh-CN · 人工字幕"}],
            "agent_plan": {
                "route": "download_target_subtitle",
                "selected_subtitle": {"lang": "zh-CN", "kind": "manual", "label": "zh-CN · 人工字幕"},
                "requires_translation": False,
                "confidence": 0.95,
            },
        },
    )

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status="done", result=result)

    monkeypatch.setattr(
        web_agent,
        "download_video_job",
        lambda payload: calls.append("video") or done_job("video", {"input_video": str(video)}),
    )
    monkeypatch.setattr(
        web_agent,
        "download_subtitle_job",
        lambda payload: calls.append("subtitle") or done_job("subtitle", {"subtitle_path": str(subtitle)}),
    )
    monkeypatch.setattr(
        web_agent,
        "generate_glossary_job",
        lambda payload: (_ for _ in ()).throw(AssertionError("目标语言字幕不应生成 Glossary")),
    )

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")

    assert calls == []
    assert "input_video" not in snapshot["result"]

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
    snapshot = _wait_agent_status(session.id, "done")

    assert calls == ["video", "subtitle"]
    assert snapshot["result"]["input_video"] == str(video)
    assert snapshot["result"]["subtitle_path"] == str(subtitle)
    assert "glossary_path" not in snapshot["result"]
    task = web_agent.get_agent_task(snapshot["result"]["task_id"])
    assert task["current_stage"] == "done"
    assert task["workflow_status"] == "completed"
    assert task["stages"]["translate"]["translated_srt"] == str(subtitle)


def test_failed_translation_restart_keeps_skip_glossary_choice(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(web_agent, "_AGENT_SESSIONS", {})
    source = tmp_path / "source.srt"
    glossary = tmp_path / "glossary.yaml"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
    task_dir = web_agent.TASK_DIR / "legacy_demo"
    task_dir.mkdir(parents=True)
    web_agent._write_task_file(
        task_dir / "task.yaml",
        {
            "id": "legacy_demo",
            "task_dir": str(task_dir),
            "url": "",
            "title": "demo",
            "payload": {},
            "run_generation": 1,
            "current_stage": "translate_failed",
            "workflow_status": "active",
            "stages": {
                "glossary": {
                    "status": "reviewed",
                    "source_srt": str(source),
                    "glossary_path": str(glossary),
                },
                "translate": {
                    "status": "failed",
                    "source_srt": str(source),
                    "use_glossary": False,
                },
            },
        },
    )
    scheduled: list[str] = []
    monkeypatch.setattr(web_agent, "_run_agent_async", lambda session_id, target: scheduled.append(session_id))

    session = web_agent._start_agent_translation(web_agent._read_task("legacy_demo"))

    assert session.result["translation_use_glossary"] is False
    assert session.result["translation_glossary_path"] == ""
    assert scheduled == [session.id]
    task = web_agent.get_agent_task("legacy_demo")
    assert task["stages"]["translate"]["use_glossary"] is False
    assert "glossary_path" not in task["stages"]["translate"]


def test_retry_ocr_download_preserves_explicit_rerun_choice(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        web_agent,
        "_agent_run_ocr",
        lambda session, force=False: calls.append(force),
    )
    session = web_agent.AgentSession(
        id="retry-ocr",
        status="failed",
        phase="download_video_for_ocr",
        result={"ocr_force_requested": True},
    )

    web_agent._agent_retry_current_phase(session)

    assert calls == [True]


def test_explicit_youtube_url_rejects_local_paths_and_bare_ids():
    assert web_agent._explicit_youtube_url("/data/video.mp4") == ""
    assert web_agent._explicit_youtube_url("abc123") == ""
    assert web_agent._explicit_youtube_url("https://example.com/watch?v=abc123") == ""
    assert web_agent._explicit_youtube_url("https://youtu.be/abc123?t=3") == "https://www.youtube.com/watch?v=abc123"


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
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    glossary.write_text("characters: []\n", encoding="utf-8")
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
    assert config["ocr"]["extraction_mode"] == "auto"
    assert config["ocr"]["sample_fps"] == 3.0
    assert web_agent._ocr_scope_settings("expanded") == {"bottom_ratio": 0.62, "scan_full_frame": False}


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (
            "v1",
            {
                "version": "v1",
                "extraction_mode": "auto",
                "refinement_mode": "none",
                "source_cleanup_mode": "llm_context",
                "translation_mode": "standard_cleanup",
            },
        ),
        (
            "v2",
            {
                "version": "v2",
                "extraction_mode": "region",
                "refinement_mode": "llm_boxes",
                "source_cleanup_mode": "none",
                "translation_mode": "translate_only",
            },
        ),
        (
            "v3",
            {
                "version": "v3",
                "extraction_mode": "region_v3",
                "refinement_mode": "llm_geometry",
                "source_cleanup_mode": "none",
                "translation_mode": "translate_only",
            },
        ),
    ],
)
def test_explicit_ocr_pipeline_version_overrides_conflicting_advanced_settings(
    tmp_path: Path,
    version: str,
    expected: dict[str, str],
):
    resolved = web_agent._resolve_ocr_pipeline(
        version,
        extraction_mode="region_v3",
        refinement_mode="llm_boxes" if version == "v1" else "none",
        translation_mode="readability_retime",
        preserve_timing=version == "v1",
    )
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / version,
        extra_hint="",
        ocr_pipeline_version=version,
        ocr_extraction_mode="region_v3",
        ocr_refinement_mode="llm_boxes" if version == "v1" else "none",
        translation_mode="readability_retime",
        preserve_timing=version == "v1",
    )

    assert {key: resolved[key] for key in expected} == expected
    assert {key: config["ocr_pipeline"][key] for key in expected} == expected
    assert config["ocr"]["extraction_mode"] == expected["extraction_mode"]
    assert config["ocr_refinement"]["mode"] == expected["refinement_mode"]
    assert config["source_cleanup"]["mode"] == expected["source_cleanup_mode"]
    assert config["translation"]["ocr_translation_mode"] == expected["translation_mode"]


def test_unversioned_ocr_config_keeps_manual_advanced_settings_independent(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "custom",
        extra_hint="",
        ocr_extraction_mode="region",
        ocr_refinement_mode="llm_boxes",
        translation_mode="readability_retime",
    )

    expected = {
        "version": "custom",
        "label": "自定义 OCR 流程",
        "extraction_mode": "region",
        "refinement_mode": "llm_boxes",
        "source_cleanup_mode": "llm_context",
        "translation_mode": "readability_retime",
    }
    assert {key: config["ocr_pipeline"][key] for key in expected} == expected


def test_ocr_config_region_extraction_mode_keeps_old_mode_separate(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        ocr_scope="smart_full",
        ocr_extraction_mode="region",
    )

    assert config["ocr"]["extraction_mode"] == "region"
    assert config["ocr"]["shape_mode"] == "unrestricted"
    assert config["ocr"]["sample_fps"] == 6.0
    assert config["ocr"]["scan_full_frame"] is False
    assert config["ocr"]["auto_trim_side_noise"] is False
    assert config["subtitle"]["snapshot_min_confidence"] == 0.35
    assert config["subtitle"]["min_duration_seconds"] == 0.35


def test_ocr_config_region_v3_defaults_to_horizontal_preferred(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        ocr_scope="smart_full",
        ocr_extraction_mode="region_v3",
    )

    assert config["ocr"]["extraction_mode"] == "region_v3"
    assert config["ocr"]["shape_mode"] == "horizontal_preferred"
    assert config["ocr"]["sample_fps"] == 6.0
    assert config["ocr"]["scan_full_frame"] is False
    assert config["ocr"]["auto_trim_side_noise"] is False
    assert config["subtitle"]["snapshot_min_confidence"] == 0.35


def test_ocr_shape_mode_is_isolated_from_region_v2(tmp_path: Path):
    v2 = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "v2",
        extra_hint="",
        ocr_extraction_mode="region",
        ocr_shape_mode="horizontal_strict",
    )
    v3 = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "v3",
        extra_hint="",
        ocr_extraction_mode="region_v3",
        ocr_shape_mode="horizontal_strict",
    )

    assert v2["ocr"]["shape_mode"] == "unrestricted"
    assert v3["ocr"]["shape_mode"] == "horizontal_strict"
    with pytest.raises(ValueError, match="未知 OCR 文字形态方式"):
        web_agent._normalize_ocr_shape_mode("diagonal", "region_v3")



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


def test_ocr_config_includes_logo_exclude_region(tmp_path: Path):
    config = web_agent._ocr_config(
        tmp_path / "demo.mp4",
        tmp_path / "job",
        extra_hint="",
        ocr_exclude_enabled=True,
        ocr_exclude_top_ratio=0.03,
        ocr_exclude_bottom_ratio=0.80,
        ocr_exclude_left_ratio=0.72,
        ocr_exclude_right_ratio=0.04,
    )

    assert config["ocr"]["exclude_enabled"] is True
    assert config["ocr"]["exclude_top_ratio"] == 0.03
    assert config["ocr"]["exclude_bottom_ratio"] == 0.80
    assert config["ocr"]["exclude_left_ratio"] == 0.72
    assert config["ocr"]["exclude_right_ratio"] == 0.04


def test_ocr_development_job_runs_and_materializes_the_complete_v2_pipeline(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        config = yaml.safe_load(Path(args[-1]).read_text(encoding="utf-8"))
        captured["config"] = config
        output_dir = Path(config["output_dir"])
        for name in ["source.srt", "source.machine.srt", "source.refined.srt", "ocr_boxes.json", "ocr_sample_frames.json", "tracks.json"]:
            (output_dir / name).write_text("[]", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_development_job(
        {
            "input_video": str(video),
            "source_language": "korean",
            "sample_fps": 8,
            "min_confidence": 30,
            "refine_timing_boundaries": True,
            "flicker_smoothing_max_duration_seconds": 0.8,
            "llm_cleanup": True,
            "ocr_exclude_enabled": True,
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["ocr_sample_frames"].endswith("ocr_sample_frames.json")
    assert Path(snapshot["result"]["debug_dir"]) == tmp_path / "YoutubeDownloads" / "debug" / "demo"
    assert Path(snapshot["result"]["debug_dir"]).is_dir()
    assert Path(snapshot["result"]["debug_video"]).exists()
    assert Path(snapshot["result"]["debug_source_srt"]).name == "demo.srt"
    assert Path(snapshot["result"]["debug_source_srt"]).read_text(encoding="utf-8") == "[]"
    assert Path(snapshot["result"]["debug_machine_source_srt"]).name == "source.machine.srt"
    assert Path(snapshot["result"]["debug_track_refined_srt"]).name == "source.track_refined.srt"
    assert Path(snapshot["result"]["debug_track_refined_srt"]).read_text(encoding="utf-8") == "[]"
    assert captured["config"]["mode"] == "extract"
    assert captured["config"]["ocr"]["extraction_mode"] == "region"
    assert captured["config"]["ocr"]["shape_mode"] == "unrestricted"
    assert captured["config"]["ocr"]["sample_fps"] == 8
    assert captured["config"]["ocr"]["min_confidence"] == 0.3
    assert captured["config"]["ocr"]["refine_timing_boundaries"] is True
    assert captured["config"]["subtitle"]["flicker_smoothing_max_duration_seconds"] == 0.8
    assert captured["config"]["ocr"]["auto_trim_side_noise"] is False
    assert captured["config"]["ocr_refinement"]["mode"] == "llm_boxes"
    assert snapshot["result"]["ocr_refinement_mode"] == "llm_boxes"
    assert snapshot["result"]["refined_srt"].endswith("source.refined.srt")
    assert captured["config"]["source_cleanup"] == {
        "mode": "none",
        "batch_size": 18,
        "overlap": 3,
        "preserve_source": True,
    }
    assert captured["config"]["filters"] == {"ignored_texts": [], "ignored_contains": [], "ignored_patterns": []}


def test_ocr_development_job_region_v3_enables_geometry_refinement_and_materializes_artifacts(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        config = yaml.safe_load(Path(args[-1]).read_text(encoding="utf-8"))
        captured["config"] = config
        output_dir = Path(config["output_dir"])
        artifacts = {
            "source.srt": "v3 layered",
            "source.machine.srt": "machine",
            "source.geometry_refined.srt": "geometry refined",
            "source.v3.refined.srt": "v3 text refined",
            "source.v3.layered.srt": "v3 layered",
            "ocr_geometry.json": '{"tracks": []}',
            "ocr_v3_layers.json": '{"layers": []}',
            "ocr_boxes.json": "[]",
            "ocr_rejected_boxes.json": '{"boxes": []}',
            "ocr_sample_frames.json": '{"frames": []}',
            "tracks.json": "[]",
        }
        for name, content in artifacts.items():
            (output_dir / name).write_text(content, encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_development_job(
        {
            "input_video": str(video),
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_preferred",
            "llm_cleanup": True,
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    config = captured["config"]
    assert config["ocr"]["extraction_mode"] == "region_v3"
    assert config["ocr"]["shape_mode"] == "horizontal_preferred"
    assert config["ocr_refinement"] == {
        "mode": "llm_geometry",
        "batch_size": 8,
        "context_overlap": 2,
        "text_batch_size": 12,
        "window_padding_seconds": 0.5,
        "max_boxes_per_frame": 16,
        "layered_batch_size": 8,
        "layered_context_overlap": 1,
    }
    assert config["source_cleanup"]["mode"] == "none"
    assert snapshot["result"]["ocr_refinement_mode"] == "llm_geometry"
    assert snapshot["result"]["geometry_srt"].endswith("source.geometry_refined.srt")
    assert snapshot["result"]["ocr_geometry"].endswith("ocr_geometry.json")
    assert snapshot["result"]["v3_refined_srt"].endswith("source.v3.refined.srt")
    assert snapshot["result"]["v3_layered_srt"].endswith("source.v3.layered.srt")
    assert snapshot["result"]["ocr_v3_layers"].endswith("ocr_v3_layers.json")
    assert snapshot["result"]["source_srt"].endswith("source.srt")
    assert Path(snapshot["result"]["source_srt"]).read_text(encoding="utf-8") == "v3 layered"
    assert Path(snapshot["result"]["debug_geometry_srt"]).read_text(encoding="utf-8") == "geometry refined"
    assert Path(snapshot["result"]["debug_ocr_geometry"]).read_text(encoding="utf-8") == '{"tracks": []}'
    assert Path(snapshot["result"]["debug_machine_source_srt"]).read_text(encoding="utf-8") == "machine"
    assert Path(snapshot["result"]["debug_v3_refined_srt"]).read_text(encoding="utf-8") == "v3 text refined"
    assert Path(snapshot["result"]["debug_v3_layered_srt"]).read_text(encoding="utf-8") == "v3 layered"
    assert Path(snapshot["result"]["debug_ocr_v3_layers"]).read_text(encoding="utf-8") == '{"layers": []}'


def test_ocr_development_job_region_v3_without_cleanup_skips_geometry_refinement(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")

    def fake_run_command(job_id, args):
        config = yaml.safe_load(Path(args[-1]).read_text(encoding="utf-8"))
        captured["config"] = config
        output_dir = Path(config["output_dir"])
        for name in ["source.srt", "ocr_boxes.json", "ocr_rejected_boxes.json", "ocr_sample_frames.json", "tracks.json"]:
            (output_dir / name).write_text("[]", encoding="utf-8")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_development_job(
        {
            "input_video": str(video),
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
            "llm_cleanup": False,
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    assert captured["config"]["ocr"]["extraction_mode"] == "region_v3"
    assert captured["config"]["ocr"]["shape_mode"] == "horizontal_strict"
    assert captured["config"]["ocr_refinement"]["mode"] == "none"
    assert captured["config"]["source_cleanup"]["mode"] == "none"
    assert snapshot["result"]["ocr_extraction_mode"] == "region_v3"
    assert snapshot["result"]["ocr_shape_mode"] == "horizontal_strict"
    assert snapshot["result"]["ocr_refinement_mode"] == "none"
    assert snapshot["result"]["geometry_srt"] == ""
    assert snapshot["result"]["ocr_geometry"] == ""
    assert Path(snapshot["result"]["debug_ocr_rejected_boxes"]).exists()


def test_region_v2_debug_bundle_removes_stale_v3_geometry_artifacts(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    (output_dir / "source.srt").write_text("", encoding="utf-8")
    debug_dir = downloads / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    stale_artifacts = [
        debug_dir / "source.machine.srt",
        debug_dir / "source.track_refined.srt",
        debug_dir / "source.rebuilt.srt",
        debug_dir / "source.layered.srt",
        debug_dir / "ocr_layers.json",
        debug_dir / "source.geometry_refined.srt",
        debug_dir / "ocr_geometry.json",
        debug_dir / "ocr_rejected_boxes.json",
    ]
    for stale in stale_artifacts:
        stale.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    result = web_agent._materialize_ocr_debug_bundle(video, output_dir)

    assert all(not stale.exists() for stale in stale_artifacts)
    assert "debug_machine_source_srt" not in result
    assert "debug_geometry_srt" not in result
    assert "debug_ocr_geometry" not in result
    assert "debug_ocr_rejected_boxes" not in result


def test_ocr3_debug_bundle_uses_a_separate_variant_folder_and_preserves_v2(monkeypatch, tmp_path):
    downloads = tmp_path / "YoutubeDownloads"
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    v2_output = tmp_path / "v2"
    v3_output = tmp_path / "v3"
    v2_output.mkdir()
    v3_output.mkdir()
    (v2_output / "source.srt").write_text("v2", encoding="utf-8")
    (v3_output / "source.srt").write_text("v3", encoding="utf-8")
    (v3_output / "source.geometry_refined.srt").write_text("v3", encoding="utf-8")
    (v3_output / "ocr_geometry.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)

    v2 = web_agent._materialize_ocr_debug_bundle(video, v2_output)
    v3 = web_agent._materialize_ocr_debug_bundle(
        video,
        v3_output,
        debug_variant="ocr3_horizontal_preferred",
    )

    assert Path(v2["debug_dir"]) == downloads / "debug" / "demo"
    assert Path(v3["debug_dir"]) == downloads / "debug" / "demo__ocr3_horizontal_preferred"
    assert Path(v2["debug_source_srt"]).read_text(encoding="utf-8") == "v2"
    assert Path(v3["debug_source_srt"]).read_text(encoding="utf-8") == "v3"



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


def test_ocr_exclude_preview_rect_uses_explicit_edges():
    rect = web_agent._ocr_exclude_preview_rect(200, 100, exclude_enabled=True, exclude_top_ratio=0.04, exclude_bottom_ratio=0.82, exclude_left_ratio=0.76, exclude_right_ratio=0.02)

    assert rect["enabled"] is True
    assert rect["left"] == 152
    assert rect["top"] == 4
    assert rect["width"] == 44
    assert rect["height"] == 14


def test_ocr_v3_preferred_preview_keeps_tilted_text_as_soft_candidate(monkeypatch):
    import numpy as np

    class FakeOCR:
        def predict(self, image, **kwargs):
            return [
                {
                    "rec_texts": ["정상 자막", "기울어진 글자"],
                    "rec_scores": [0.96, 0.94],
                    "rec_polys": [
                        [(20, 20), (150, 20), (150, 40), (20, 40)],
                        [(20, 20), (140, 65), (135, 80), (15, 35)],
                    ],
                }
            ]

    monkeypatch.setattr(web_agent, "_ocr_preview_model", lambda language, device: FakeOCR())
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    result = web_agent._ocr_preview_analysis(
        frame,
        {
            "analyze_ocr": True,
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_preferred",
            "ocr_crop_top_ratio": 0,
            "ocr_crop_bottom_ratio": 0,
            "ocr_crop_left_ratio": 0,
            "ocr_crop_right_ratio": 0,
            "ocr_min_confidence": 30,
            "source_language": "korean",
        },
        time_seconds=1.25,
        frame_index=30,
    )

    assert result is not None
    assert result["shape_mode"] == "horizontal_preferred"
    assert result["min_confidence"] == 0.3
    assert [item["text"] for item in result["accepted"]] == ["정상 자막", "기울어진 글자"]
    assert result["accepted"][0]["angle_degrees"] == 0.0
    assert result["accepted"][0]["shape_hint"] == "horizontal_candidate"
    assert result["accepted"][1]["shape_hint"] == "tilted_soft_candidate"
    assert result["accepted"][1]["shape_limit_degrees"] == 15.0
    assert result["rejected"] == []


def test_ocr_v3_strict_preview_still_rejects_tilted_text(monkeypatch):
    import numpy as np

    class FakeOCR:
        def predict(self, image, **kwargs):
            return [
                {
                    "rec_texts": ["정상 자막", "기울어진 글자"],
                    "rec_scores": [0.96, 0.94],
                    "rec_polys": [
                        [(20, 20), (150, 20), (150, 40), (20, 40)],
                        [(20, 20), (140, 65), (135, 80), (15, 35)],
                    ],
                }
            ]

    monkeypatch.setattr(web_agent, "_ocr_preview_model", lambda language, device: FakeOCR())
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    result = web_agent._ocr_preview_analysis(
        frame,
        {
            "analyze_ocr": True,
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
            "ocr_crop_top_ratio": 0,
            "ocr_crop_bottom_ratio": 0,
            "ocr_crop_left_ratio": 0,
            "ocr_crop_right_ratio": 0,
            "ocr_min_confidence": 30,
            "source_language": "korean",
        },
        time_seconds=1.25,
        frame_index=30,
    )

    assert result is not None
    assert result["shape_mode"] == "horizontal_strict"
    assert [item["text"] for item in result["accepted"]] == ["정상 자막"]
    assert result["accepted"][0]["shape_hint"] == "horizontal_candidate"
    assert [item["text"] for item in result["rejected"]] == ["기울어진 글자"]
    assert result["rejected"][0]["reason"] == "shape_angle_exceeds_horizontal_strict"
    assert result["rejected"][0]["shape_hint"] == "tilted_hard_reject"


def test_ocr_v2_preview_does_not_load_ocr_model(monkeypatch):
    monkeypatch.setattr(
        web_agent,
        "_ocr_preview_model",
        lambda language, device: (_ for _ in ()).throw(AssertionError("OCR model should not load for 2.0 preview")),
    )

    result = web_agent._ocr_preview_analysis(
        object(),
        {"analyze_ocr": True, "ocr_extraction_mode": "region"},
        time_seconds=0,
        frame_index=0,
    )

    assert result is None


def test_ocr_v3_preview_is_blocked_while_full_ocr_uses_gpu(monkeypatch):
    monkeypatch.setattr(web_agent, "_OCR_ACTIVE_COMMANDS", 1)
    monkeypatch.setattr(
        web_agent,
        "_ocr_preview_model",
        lambda language, device: (_ for _ in ()).throw(AssertionError("preview model should remain unloaded")),
    )

    with pytest.raises(RuntimeError, match="完整 OCR 任务正在使用 GPU"):
        web_agent._ocr_preview_analysis(
            object(),
            {
                "analyze_ocr": True,
                "ocr_extraction_mode": "region_v3",
                "ocr_shape_mode": "horizontal_preferred",
            },
            time_seconds=0,
            frame_index=0,
        )


def test_ocr_gpu_command_detection_covers_full_and_hybrid_runs():
    assert web_agent._command_uses_ocr_gpu(["python", "/repo/run_from_config.py", "run.yaml"])
    assert web_agent._command_uses_ocr_gpu(["python", "-m", "video_translate.tools.hybrid_anchor_ocr"])
    assert not web_agent._command_uses_ocr_gpu(["python", "-m", "video_translate.tools.translate_subtitles"])


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
    debug_dir = downloads / "debug" / "demo-debug"
    project.mkdir()
    debug_dir.mkdir(parents=True)
    video = project / "demo.mp4"
    subtitle = project / "demo.ko.srt"
    source = job_dir / "source.srt"
    run_yaml = job_dir / "run.yaml"
    video.write_text("video", encoding="utf-8")
    subtitle.write_text("1\n", encoding="utf-8")
    source.write_text("1\n", encoding="utf-8")
    run_yaml.write_text("mode: full\n", encoding="utf-8")
    (debug_dir / "demo-debug.srt").write_text("1\n", encoding="utf-8")
    (debug_dir / "demo-debug.cleaned.srt").write_text("1\n", encoding="utf-8")
    (debug_dir / "source.layered.srt").write_text("1\n", encoding="utf-8")
    (debug_dir / "source.machine.srt").write_text("machine\n", encoding="utf-8")
    (debug_dir / "source.geometry_refined.srt").write_text("1\n", encoding="utf-8")
    (debug_dir / "source.v3.refined.srt").write_text("v3 refined\n", encoding="utf-8")
    (debug_dir / "source.v3.layered.srt").write_text("v3 layered\n", encoding="utf-8")
    (debug_dir / "ocr_boxes.json").write_text("[]", encoding="utf-8")
    (debug_dir / "ocr_geometry.json").write_text("{}", encoding="utf-8")
    (debug_dir / "ocr_v3_layers.json").write_text("{}", encoding="utf-8")
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
    assert assets["ocr_debug_folders"][0]["source_srt"].endswith("source.v3.layered.srt")
    assert assets["ocr_debug_folders"][0]["cleaned_srt"].endswith("demo-debug.cleaned.srt")
    assert assets["ocr_debug_folders"][0]["layered_srt"].endswith("source.layered.srt")
    assert assets["ocr_debug_folders"][0]["geometry_srt"].endswith("source.geometry_refined.srt")
    assert assets["ocr_debug_folders"][0]["v3_refined_srt"].endswith("source.v3.refined.srt")
    assert assets["ocr_debug_folders"][0]["v3_layered_srt"].endswith("source.v3.layered.srt")
    assert assets["ocr_debug_folders"][0]["ocr_geometry"].endswith("ocr_geometry.json")
    assert assets["ocr_debug_folders"][0]["ocr_v3_layers"].endswith("ocr_v3_layers.json")
    assert assets["ocr_debug_folders"][0]["ocr_lab_version"] == "v3"
    assert assets["ocr_debug_folders"][0]["ocr_version_label"] == "OCR 3.0"
    assert assets["ocr_debug_folders"][0]["has_ocr_boxes"] is True
    assert assets["ocr_debug_folders"][0]["has_machine_source"] is True



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

    job = web_agent.ocr_extract_job(
        {
            "url": "abc123",
            "title": "Target Video",
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["status"] == "done"
    download_call = next(call for call in calls if call[:3] == ["/python", "-m", "video_translate.youtube.download_video"])
    assert download_call[download_call.index("--quality") + 1] == "1080p"


def test_ocr_extract_job_reuses_prebound_project_video(monkeypatch, tmp_path: Path):
    downloads = tmp_path / "YoutubeDownloads"
    project = downloads / "Target Video"
    project.mkdir(parents=True)
    video = project / "Target Video.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")
    monkeypatch.setattr(web_agent, "PYTHON", "/python")
    calls = []

    def fake_run_command(job_id, args):
        calls.append(args)
        if args[:2] == ["/python", str(web_agent.ROOT / "run_from_config.py")]:
            (web_agent.JOB_DIR / job_id / "source.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n안녕\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.ocr_extract_job(
        {
            "url": "abc123",
            "title": "Target Video",
            "input_video": str(video),
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["input_video"] == str(video)
    assert not any(call[:3] == ["/python", "-m", "video_translate.youtube.download_video"] for call in calls)
    manifest = yaml.safe_load((project / "project.yaml").read_text(encoding="utf-8"))
    assert manifest["source_type"] == "youtube"
    assert manifest["normalized_url"] == "https://www.youtube.com/watch?v=abc123"


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

    job = web_agent.ocr_extract_job(
        {
            "url": "abc123",
            "title": "Target Video",
            "ocr_extraction_mode": "region_v3",
            "ocr_shape_mode": "horizontal_strict",
        }
    )
    snapshot = _wait_job_status(job.id, "done")

    assert snapshot["result"]["input_video"] == str(target)
    assert snapshot["result"]["project_manifest"] == str(target.parent / "project.yaml")
    run_config = web_agent.JOB_DIR / job.id / "run.yaml"
    config = yaml.safe_load(run_config.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((target.parent / "project.yaml").read_text(encoding="utf-8"))
    assert config["input_video"] == str(target)
    assert config["ocr"]["extraction_mode"] == "region_v3"
    assert config["ocr"]["shape_mode"] == "horizontal_strict"
    assert config["agent_cache"]["ocr_shape_mode"] == "horizontal_strict"
    assert snapshot["result"]["ocr_shape_mode"] == "horizontal_strict"
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

    assert calls
    assert calls[0]['glossary'] != str(glossary)
    assert Path(calls[0]['glossary']).read_text(encoding='utf-8') == glossary.read_text(encoding='utf-8')
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
    monkeypatch.setattr(web_agent, '_ensure_under_root', lambda path: None)

    def done_job(name, result):
        return web_agent.Job(id=name, name=name, status='done', result=result)

    monkeypatch.setattr(
        web_agent,
        'translate_subtitle_job',
        lambda payload: done_job('translate', {'translated_srt': str(translated)}),
    )

    restored = web_agent.continue_agent_task('task1')
    assert restored.status == 'waiting'
    assert restored.phase == 'review_glossary'
    session = web_agent.continue_agent_after_glossary_review(str(glossary))
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
def test_cleanup_existing_ocr_source_writes_sibling_file(monkeypatch, tmp_path):
    source_srt = tmp_path / "source.srt"
    source_srt.write_text("raw", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)

    def fake_cleanup(source, output, *, config, progress_callback):
        captured["source"] = source
        captured["output"] = output
        captured["config"] = config
        progress_callback("source_cleanup: 24 cues in 2 batches")
        progress_callback("source_cleanup_batch: 1/2 cues 1-18")
        output.write_text("cleaned", encoding="utf-8")
        return {"cleaned_srt": output}

    monkeypatch.setattr(web_agent, "cleanup_ocr_source_with_llm", fake_cleanup)

    job = web_agent.cleanup_existing_ocr_source_job({"source_srt": str(source_srt)})
    snapshot = _wait_job_status(job.id, "done")

    cleaned_srt = tmp_path / "source.cleaned.srt"
    assert captured["source"] == source_srt
    assert captured["output"] == cleaned_srt
    assert captured["config"].batch_size == 18
    assert cleaned_srt.read_text(encoding="utf-8") == "cleaned"
    assert "source_cleanup: 24 cues in 2 batches" in snapshot["logs"]
    assert "source_cleanup_batch: 1/2 cues 1-18" in snapshot["logs"]
    assert snapshot["result"] == {"source_srt": str(source_srt), "cleaned_srt": str(cleaned_srt)}


def test_rebuild_ocr_debug_with_llm_uses_existing_json(monkeypatch, tmp_path):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    (debug_dir / "tracks.json").write_text('[{"id": 1, "text": "caption", "start": 1.0, "end": 2.0, "kind": "main_subtitle", "boxes": []}]', encoding="utf-8")
    (debug_dir / "ocr_boxes.json").write_text("[]", encoding="utf-8")
    (debug_dir / "run.yaml").write_text("ocr:\n  sample_fps: 6\nsubtitle:\n  min_duration_seconds: 0.35\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    def fake_write_outputs(tracks, out_dir, *, cue_timing):
        captured["tracks"] = tracks
        captured["timing"] = cue_timing
        source = out_dir / "source.srt"
        source.write_text("rebuilt", encoding="utf-8")
        return {"source_srt": source}

    def fake_refine(source, boxes, output, *, config, progress_callback):
        captured["source"] = source
        captured["boxes"] = boxes
        captured["config"] = config
        progress_callback("ocr_refine: 1 cues in 1 batches")
        output.write_text("refined", encoding="utf-8")
        return {"refined_srt": output}

    monkeypatch.setattr(web_agent, "write_extraction_outputs", fake_write_outputs)
    monkeypatch.setattr(web_agent, "refine_ocr_source_with_llm", fake_refine)

    job = web_agent.rebuild_ocr_debug_with_llm_job({"debug_dir": str(debug_dir)})
    snapshot = _wait_job_status(job.id, "done")

    assert captured["timing"].sample_interval_seconds == pytest.approx(1 / 6)
    assert captured["boxes"] == debug_dir / "ocr_boxes.json"
    assert captured["config"].batch_size == 12
    assert (debug_dir / "source.rebuilt.srt").read_text(encoding="utf-8") == "rebuilt"
    assert (debug_dir / "source.track_refined.srt").read_text(encoding="utf-8") == "refined"
    assert any("video decoding is skipped" in line for line in snapshot["logs"])
    assert "ocr_refine: 1 cues in 1 batches" in snapshot["logs"]


def test_refine_ocr_debug_layers_uses_ocr2_refined_source_and_materializes_outputs(monkeypatch, tmp_path):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    raw_source = debug_dir / "source.machine.srt"
    raw_source.write_text("machine", encoding="utf-8")
    refined_source = debug_dir / "source.track_refined.srt"
    refined_source.write_text("ocr2 refined", encoding="utf-8")
    (debug_dir / "source.rebuilt.srt").write_text("rebuilt", encoding="utf-8")
    boxes = debug_dir / "ocr_boxes.json"
    boxes.write_text("[]", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    def fake_refine(source, ocr_boxes, output, debug_json, *, recovery_srt, config, progress_callback):
        captured.update(
            {
                "source": source,
                "boxes": ocr_boxes,
                "output": output,
                "debug_json": debug_json,
                "recovery_srt": recovery_srt,
                "config": config,
            }
        )
        progress_callback("layered_refine: 1 cues in 1 batches")
        output.write_text("layered", encoding="utf-8")
        debug_json.write_text("{}", encoding="utf-8")
        return {"layered_srt": output, "layers_json": debug_json}

    monkeypatch.setattr(web_agent, "refine_ocr_layers_with_llm", fake_refine)

    job = web_agent.refine_ocr_debug_layers_job({"debug_dir": str(debug_dir)})
    snapshot = _wait_job_status(job.id, "done")

    assert captured["source"] == refined_source
    assert captured["recovery_srt"] == raw_source
    assert captured["boxes"] == boxes
    assert isinstance(captured["config"], web_agent.LayeredOCRRefinementConfig)
    assert (debug_dir / "source.layered.srt").read_text(encoding="utf-8") == "layered"
    assert (debug_dir / "ocr_layers.json").read_text(encoding="utf-8") == "{}"
    assert snapshot["result"]["source_layered_srt"] == str(debug_dir / "source.layered.srt")
    assert snapshot["result"]["ocr_layers"] == str(debug_dir / "ocr_layers.json")
    assert any("video decoding is skipped" in line for line in snapshot["logs"])
    assert "layered_refine: 1 cues in 1 batches" in snapshot["logs"]


def test_refine_ocr_debug_layers_reuses_v3_text_result_without_rerunning_earlier_stages(
    monkeypatch,
    tmp_path,
):
    debug_dir = (
        tmp_path
        / "YoutubeDownloads"
        / "debug"
        / "demo__ocr3_horizontal_preferred"
    )
    debug_dir.mkdir(parents=True)
    (debug_dir / "run.yaml").write_text(
        "ocr:\n  extraction_mode: region_v3\n  shape_mode: horizontal_preferred\n",
        encoding="utf-8",
    )
    machine_source = debug_dir / "source.machine.srt"
    machine_source.write_text("machine", encoding="utf-8")
    refined_source = debug_dir / "source.v3.refined.srt"
    refined_source.write_text("v3 refined", encoding="utf-8")
    old_source = debug_dir / "source.srt"
    old_source.write_text("old source stays", encoding="utf-8")
    boxes = debug_dir / "ocr_boxes.json"
    boxes.write_text("[]", encoding="utf-8")
    geometry = debug_dir / "ocr_geometry.json"
    geometry.write_text("{}", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    def fake_refine(
        source,
        ocr_boxes,
        output,
        debug_json,
        *,
        recovery_srt,
        geometry_json,
        config,
        progress_callback,
    ):
        captured.update(
            {
                "source": source,
                "boxes": ocr_boxes,
                "recovery_srt": recovery_srt,
                "geometry_json": geometry_json,
                "config": config,
            }
        )
        progress_callback("layered_refine: 1 cues in 1 batches")
        output.write_text("v3 layered", encoding="utf-8")
        debug_json.write_text("{}", encoding="utf-8")
        return {"layered_srt": output, "layers_json": debug_json}

    monkeypatch.setattr(web_agent, "refine_ocr_layers_with_llm", fake_refine)

    job = web_agent.refine_ocr_debug_layers_job({"debug_dir": str(debug_dir)})
    snapshot = _wait_job_status(job.id, "done")

    assert captured["source"] == refined_source
    assert captured["boxes"] == boxes
    assert captured["recovery_srt"] == machine_source
    assert captured["geometry_json"] == geometry
    assert captured["config"].pipeline_version == "v3"
    assert old_source.read_text(encoding="utf-8") == "old source stays"
    assert (debug_dir / "source.v3.layered.srt").read_text(encoding="utf-8") == "v3 layered"
    assert (debug_dir / "ocr_v3_layers.json").read_text(encoding="utf-8") == "{}"
    assert snapshot["result"]["source_v3_layered_srt"] == str(debug_dir / "source.v3.layered.srt")
    assert snapshot["result"]["ocr_v3_layers"] == str(debug_dir / "ocr_v3_layers.json")
    assert snapshot["result"]["v3_layered_only"] is True
    assert any("text refinement is skipped" in line for line in snapshot["logs"])


def test_refine_ocr_debug_geometry_uses_saved_polygon_json_without_video_decode(monkeypatch, tmp_path):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    tracks = debug_dir / "tracks.json"
    tracks.write_text("[]", encoding="utf-8")
    boxes = debug_dir / "ocr_boxes.json"
    boxes.write_text(
        '[{"text":"기울어진 글자","bbox":[20,20,140,80],"confidence":0.94,'
        '"time":1.25,"frame_index":30,"region":"bottom",'
        '"polygon":[[20,20],[140,65],[135,80],[15,35]],"angle_degrees":20.5,'
        '"shape_hint":"tilted_soft_candidate"}]',
        encoding="utf-8",
    )
    (debug_dir / "run.yaml").write_text(
        "ocr:\n  sample_fps: 8\nsubtitle:\n  min_duration_seconds: 0.35\n",
        encoding="utf-8",
    )
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    def fake_refine(tracks_path, boxes_path, output, debug_json, *, cue_timing, config, progress_callback):
        captured.update(
            {
                "tracks": tracks_path,
                "boxes": boxes_path,
                "output": output,
                "debug_json": debug_json,
                "timing": cue_timing,
                "config": config,
            }
        )
        progress_callback("ocr3_geometry_refine: 1 tracks in 1 batches")
        output.write_text("geometry refined", encoding="utf-8")
        debug_json.write_text('{"tracks": []}', encoding="utf-8")
        return {"geometry_srt": output, "geometry_json": debug_json}

    monkeypatch.setattr(web_agent, "refine_ocr_geometry_with_llm", fake_refine)

    job = web_agent.refine_ocr_debug_geometry_job({"debug_dir": str(debug_dir)})
    snapshot = _wait_job_status(job.id, "done")

    assert captured["tracks"] == tracks
    assert captured["boxes"] == boxes
    assert captured["timing"].sample_interval_seconds == pytest.approx(1 / 8)
    assert isinstance(captured["config"], web_agent.GeometryRefinementConfig)
    assert captured["config"].batch_size == 8
    assert captured["config"].max_observations_per_track == 10
    assert not any(path.suffix.lower() in {".mp4", ".mkv", ".webm"} for path in debug_dir.iterdir())
    assert (debug_dir / "source.geometry_refined.srt").read_text(encoding="utf-8") == "geometry refined"
    assert (debug_dir / "ocr_geometry.json").read_text(encoding="utf-8") == '{"tracks": []}'
    assert snapshot["result"]["source_geometry_refined_srt"] == str(debug_dir / "source.geometry_refined.srt")
    assert snapshot["result"]["ocr_geometry"] == str(debug_dir / "ocr_geometry.json")
    assert any("video decoding is skipped" in line for line in snapshot["logs"])
    assert "ocr3_geometry_refine: 1 tracks in 1 batches" in snapshot["logs"]


def test_refine_ocr_debug_geometry_rejects_legacy_boxes_without_geometry(monkeypatch, tmp_path):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    (debug_dir / "tracks.json").write_text("[]", encoding="utf-8")
    (debug_dir / "ocr_boxes.json").write_text(
        '[{"text":"일반 자막","bbox":[20,20,140,40],"confidence":0.95,'
        '"time":1.25,"frame_index":30,"region":"bottom"}]',
        encoding="utf-8",
    )

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    with pytest.raises(ValueError, match="没有 OCR 3.0 几何信息"):
        web_agent.refine_ocr_debug_geometry_job({"debug_dir": str(debug_dir)})


@pytest.mark.parametrize("with_geometry", [True, False])
def test_refine_ocr_debug_v3_reuses_saved_machine_boxes_and_writes_new_artifacts(
    monkeypatch,
    tmp_path,
    with_geometry,
):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo__ocr3_horizontal_preferred"
    debug_dir.mkdir(parents=True)
    original_source = debug_dir / "source.srt"
    original_source.write_text("old main source", encoding="utf-8")
    machine = debug_dir / "source.machine.srt"
    machine.write_text("machine baseline", encoding="utf-8")
    boxes = debug_dir / "ocr_boxes.json"
    boxes.write_text("[]", encoding="utf-8")
    geometry = debug_dir / "ocr_geometry.json"
    if with_geometry:
        geometry.write_text('{"tracks": [{"id": 1}]}', encoding="utf-8")
    (debug_dir / "run.yaml").write_text(
        "ocr:\n  extraction_mode: region_v3\n  shape_mode: horizontal_preferred\n",
        encoding="utf-8",
    )
    captured = {}

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "agent_jobs")

    def fake_text_refine(source, ocr_boxes, output, *, config, progress_callback):
        captured.update(
            {
                "text_source": source,
                "text_boxes": ocr_boxes,
                "text_config": config,
            }
        )
        progress_callback("ocr_refine: v3 text")
        output.write_text("v3 text refined", encoding="utf-8")
        return {"refined_srt": output}

    def fake_layered_refine(
        source,
        ocr_boxes,
        output,
        debug_json,
        *,
        recovery_srt,
        geometry_json,
        config,
        progress_callback,
    ):
        captured.update(
            {
                "layered_source": source,
                "layered_boxes": ocr_boxes,
                "recovery_srt": recovery_srt,
                "geometry_json": geometry_json,
                "layered_config": config,
            }
        )
        progress_callback("ocr_layered_refine: v3 final")
        output.write_text("v3 layered final", encoding="utf-8")
        debug_json.write_text('{"layers": []}', encoding="utf-8")
        return {"layered_srt": output, "layers_json": debug_json}

    monkeypatch.setattr(web_agent, "refine_ocr_source_with_llm", fake_text_refine)
    monkeypatch.setattr(web_agent, "refine_ocr_layers_with_llm", fake_layered_refine)

    job = web_agent.refine_ocr_debug_v3_job({"debug_dir": str(debug_dir)})
    snapshot = _wait_job_status(job.id, "done")

    assert captured["text_source"] == machine
    assert captured["text_boxes"] == boxes
    assert isinstance(captured["text_config"], web_agent.OCRRefinementConfig)
    assert captured["layered_source"].name == "source.v3.refined.srt"
    assert captured["layered_boxes"] == boxes
    assert captured["recovery_srt"] == machine
    assert captured["geometry_json"] == (geometry if with_geometry else None)
    assert isinstance(captured["layered_config"], web_agent.LayeredOCRRefinementConfig)
    assert captured["layered_config"].pipeline_version == "v3"
    assert (debug_dir / "source.v3.refined.srt").read_text(encoding="utf-8") == "v3 text refined"
    assert (debug_dir / "source.v3.layered.srt").read_text(encoding="utf-8") == "v3 layered final"
    assert (debug_dir / "ocr_v3_layers.json").read_text(encoding="utf-8") == '{"layers": []}'
    assert original_source.read_text(encoding="utf-8") == "old main source"
    assert snapshot["result"]["source_srt"] == str(debug_dir / "source.v3.layered.srt")
    assert snapshot["result"]["v3_refined_srt"] == str(debug_dir / "source.v3.refined.srt")
    assert snapshot["result"]["v3_layered_srt"] == str(debug_dir / "source.v3.layered.srt")
    assert snapshot["result"]["ocr_v3_layers"] == str(debug_dir / "ocr_v3_layers.json")
    assert snapshot["result"]["ocr_geometry"] == (str(geometry) if with_geometry else "")
    assert any("video decoding is skipped" in line for line in snapshot["logs"])


def test_refine_ocr_debug_v3_rejects_v2_directory(monkeypatch, tmp_path):
    debug_dir = tmp_path / "YoutubeDownloads" / "debug" / "demo"
    debug_dir.mkdir(parents=True)
    (debug_dir / "source.machine.srt").write_text("machine", encoding="utf-8")
    (debug_dir / "ocr_boxes.json").write_text("[]", encoding="utf-8")
    (debug_dir / "run.yaml").write_text("ocr:\n  extraction_mode: region\n", encoding="utf-8")

    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")

    with pytest.raises(ValueError, match="只能用于 OCR 3.0"):
        web_agent.refine_ocr_debug_v3_job({"debug_dir": str(debug_dir)})
