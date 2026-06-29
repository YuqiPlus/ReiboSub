from __future__ import annotations

from pathlib import Path
import time

from video_translate import web_agent


def test_caption_entries_collects_formats():
    raw = {"en": [{"ext": "vtt"}, {"ext": "json3"}], "ko": [{"ext": "srv3"}]}

    entries = web_agent._caption_entries(raw, kind="auto")

    assert entries[0]["lang"] == "en"
    assert entries[0]["kind"] == "auto"
    assert entries[0]["formats"] == ["json3", "vtt"]
    assert entries[1]["label"] == "ko · 自动字幕"


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
        assert Path(payload["out"]).parts[-3:] == ("agent_jobs", session.id, "glossary.draft.yaml")
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_generate_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "embedded_subtitle_hint": "yes"})
    snapshot = _wait_agent_phase(session.id, "confirm_subtitle")
    assert snapshot["question"]["options"][0]["action"] == "use_recommended"

    web_agent.answer_agent_session(session.id, {"action": "use_recommended"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["result"]["source_srt"] == str(hybrid)
    assert snapshot["result"]["source_kind"] == "hybrid_anchor_ocr"
    assert calls == ["subtitle:en", "video", f"hybrid:{anchor}:{video}", f"glossary:{hybrid}:{web_agent.JOB_DIR / session.id / 'glossary.draft.yaml'}"]


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
        assert Path(payload["out"]).parts[-3:] == ("agent_jobs", session.id, "glossary.draft.yaml")
        return done_job("glossary", {"glossary_path": str(glossary), "content": "characters: []\n"})

    monkeypatch.setattr(web_agent, "download_subtitle_job", fake_download)
    monkeypatch.setattr(web_agent, "generate_glossary_job", fake_glossary)

    session = web_agent.start_agent_session({"url": "abc123", "detected_source_language": "ko"})
    snapshot = _wait_agent_phase(session.id, "review_glossary")

    assert snapshot["status"] == "waiting"
    assert snapshot["question"]["kind"] == "review_glossary"
    assert snapshot["result"]["source_srt"] == str(source)
    assert snapshot["result"]["glossary_path"] == str(glossary)
    assert calls == [f"download:ko:manual", f"glossary:{source}:{web_agent.JOB_DIR / session.id / 'glossary.draft.yaml'}"]


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


def test_glossary_write_rejects_project_file_outside_allowed_dirs(tmp_path: Path, monkeypatch):
    path = tmp_path / "README.md"
    path.write_text("do not overwrite", encoding="utf-8")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "GLOSSARY_DIR", tmp_path / "configs" / "glossaries")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")

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

    def fake_run_command(job_id, args):
        calls.append(args)
        video_dir.mkdir()
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
    assert "--thumbnail-format" in calls[0]
    assert calls[0][calls[0].index("--thumbnail-format") + 1] == "jpg"
    assert job.result["input_video"].endswith("demo.h264.mp4")


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

    paths = env["LD_LIBRARY_PATH"].split(":")
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
