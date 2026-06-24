from __future__ import annotations

import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import yaml
import yt_dlp

from video_translate.agent_planner import build_agent_plan
from video_translate.cache import cuda_library_dirs, prepend_library_path
from video_translate.env import load_dotenv
from video_translate.llm_config import load_llm_task_config
from video_translate.subtitle.srt import read_srt
from video_translate.subtitle.sidecar import SidecarConfig, copy_sidecar_subtitles
from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _parse_json_content,
    _request_translation,
)
from video_translate.youtube_url import normalize_youtube_url

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT)


def _rooted_dir(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


DOWNLOAD_DIR = _rooted_dir("VIDEO_TRANSLATE_DOWNLOAD_DIR", ROOT / "YoutubeDownloads")
GLOSSARY_DIR = _rooted_dir("VIDEO_TRANSLATE_GLOSSARY_DIR", ROOT / "configs" / "glossaries")
JOB_DIR = _rooted_dir("VIDEO_TRANSLATE_JOB_DIR", ROOT / "outputs" / "agent_jobs")
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "").strip()
DEFAULT_HOST = os.environ.get("VIDEO_TRANSLATE_HOST", "0.0.0.0").strip() or "0.0.0.0"
DEFAULT_PORT = int(os.environ.get("VIDEO_TRANSLATE_PORT", "7860"))
PYTHON = sys.executable
_HYBRID_TRANSLATION_PROMPT = """本次源字幕是 hybrid 格式：时间轴来自作者上传的英文人工字幕，文本中可能同时包含“韩文OCR”和“英文参考”。
翻译时必须优先依据“韩文OCR”的韩文原文，英文参考只用于理解上下文和兜底。
如果某条只有“英文参考”没有“韩文OCR”，才允许按英文参考翻译。
OCR 里的说话人姓名、屏幕姓名牌、频道水印或固定画面标签，默认不是台词内容；不要把它们用逗号接进句子。
如果确实需要保留说话人，请使用“姓名：台词”格式；不要使用“姓名，台词”格式。
输出时不要保留“韩文OCR：”“英文参考：”这些标签。
"""


def _module_command(module: str, *args: object) -> list[str]:
    return [PYTHON, "-m", module, *[str(arg) for arg in args]]


@dataclass
class Job:
    id: str
    name: str
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    current_process: subprocess.Popen[str] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "logs": self.logs[-500:],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancellable": self.status in {"running", "cancel_requested"},
        }



class JobCancelled(RuntimeError):
    pass


@dataclass
class AgentSession:
    id: str
    status: str = "running"
    phase: str = "created"
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    question: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "payload": self.payload,
            "result": self.result,
            "question": self.question,
            "logs": self.logs[-500:],
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancellable": self.status in {"running", "waiting"},
        }


_JOBS: dict[str, Job] = {}
_AGENT_SESSIONS: dict[str, AgentSession] = {}
_LOCK = threading.Lock()


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"Video Translate Agent UI: http://{host}:{port}", flush=True)
    server.serve_forever()


def probe_video(
    url: str,
    *,
    proxy: str | None = DEFAULT_PROXY,
    target_language: str = "zh",
    detected_source_language: str = "",
    embedded_subtitle_hint: str = "unknown",
) -> dict[str, Any]:
    normalized_url = normalize_youtube_url(url)
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if proxy:
        opts["proxy"] = proxy
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(normalized_url, download=False)

    manual = _caption_entries(info.get("subtitles") or {}, kind="manual")
    auto = _caption_entries(info.get("automatic_captions") or {}, kind="auto")
    subtitles = manual + auto
    recommendation = "ocr"
    if manual:
        recommendation = "manual"
    elif auto:
        recommendation = "auto"
    agent_plan = build_agent_plan(
        subtitles,
        target_language=target_language,
        detected_source_language=detected_source_language,
        embedded_subtitle_hint=embedded_subtitle_hint,
    )
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "duration": info.get("duration"),
        "webpage_url": normalized_url,
        "normalized_url": normalized_url,
        "subtitles": subtitles,
        "recommendation": recommendation,
        "agent_plan": agent_plan,
    }


def translate_title_text(title: str, *, model: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("标题为空")
    _load_dotenv(ROOT)
    task_llm = load_llm_task_config("title_translation", explicit_model=model, explicit_base_url=base_url)
    key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 LLM_MODEL 或 title_translation 任务专用模型配置。")
    content = _request_translation(endpoint, key, build_title_translation_payload(title, selected_model))
    zh = _parse_title_translation(content)
    return {"title": title, "zh_title": zh}


def build_title_translation_payload(title: str, model: str) -> dict[str, Any]:
    user = {
        "title": title,
        "task": "把视频标题盲翻成自然简体中文，用于给字幕翻译任务提示提供参考。保留必要的人名、节目名、地名信息，不要解释。",
        "output_schema": {"zh_title": "中文标题"},
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是视频标题翻译助手。只输出 JSON 对象，不要 Markdown，不要解释。"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }


def _parse_title_translation(content: str) -> str:
    text = content.strip()
    try:
        parsed = _parse_json_content(text)
        if isinstance(parsed, dict):
            value = parsed.get("zh_title") or parsed.get("title") or parsed.get("zh")
            if value:
                return str(value).strip()
    except Exception:
        pass
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return text.strip('"“”')


def _caption_entries(raw: dict[str, Any], *, kind: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for lang in sorted(raw):
        formats = raw.get(lang) or []
        exts = sorted({str(item.get("ext") or "") for item in formats if isinstance(item, dict) and item.get("ext")})
        entries.append({"lang": lang, "kind": kind, "label": _caption_label(lang, kind), "formats": exts})
    return entries


def _caption_label(lang: str, kind: str) -> str:
    kind_label = "人工字幕" if kind == "manual" else "自动字幕"
    return f"{lang} · {kind_label}"


def start_job(name: str, target: Callable[[str], dict[str, Any] | None]) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], name=name)
    with _LOCK:
        _JOBS[job.id] = job

    def runner() -> None:
        try:
            _append_log(job.id, f"job_start: {name}")
            result = target(job.id) or {}
            with _LOCK:
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.current_process = None
                    job.logs.append("job_cancelled")
                    job.updated_at = time.time()
                    return
                job.result = result
                job.status = "done"
                job.current_process = None
                job.logs.append("job_done")
                job.updated_at = time.time()
        except JobCancelled:
            with _LOCK:
                job.status = "cancelled"
                job.current_process = None
                job.logs.append("job_cancelled")
                job.updated_at = time.time()
        except Exception as exc:
            with _LOCK:
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.current_process = None
                    job.logs.append("job_cancelled")
                    job.updated_at = time.time()
                else:
                    job.status = "failed"
                    job.error = str(exc)
                    job.current_process = None
                    job.logs.append(f"job_failed: {exc}")
                    job.updated_at = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return job


def cancel_job(job_id: str) -> Job | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.status not in {"running", "cancel_requested"}:
            return job
        job.status = "cancel_requested"
        job.updated_at = time.time()
        process = job.current_process
    _append_log(job_id, "job_cancel_requested")
    if process and process.poll() is None:
        _terminate_process_tree(process)
    with _LOCK:
        if job.status == "cancel_requested" and (process is None or process.poll() is not None):
            job.status = "cancelled"
            job.current_process = None
            job.updated_at = time.time()
    return job


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass

def get_job(job_id: str) -> Job | None:
    with _LOCK:
        return _JOBS.get(job_id)


def list_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: job.created_at, reverse=True)
        return [job.to_dict() for job in jobs]


def start_agent_session(payload: dict[str, Any]) -> AgentSession:
    session = AgentSession(id=uuid.uuid4().hex[:12], payload=dict(payload))
    with _LOCK:
        _AGENT_SESSIONS[session.id] = session
    _run_agent_async(session.id, _agent_start)
    return session


def get_agent_session(session_id: str) -> AgentSession | None:
    with _LOCK:
        return _AGENT_SESSIONS.get(session_id)


def list_agent_sessions() -> list[dict[str, Any]]:
    with _LOCK:
        sessions = sorted(_AGENT_SESSIONS.values(), key=lambda item: item.created_at, reverse=True)
        return [session.to_dict() for session in sessions]


def answer_agent_session(session_id: str, answer: dict[str, Any]) -> AgentSession:
    session = get_agent_session(session_id)
    if not session:
        raise KeyError("agent session not found")
    with _LOCK:
        if session.status != "waiting":
            raise RuntimeError("agent session is not waiting for input")
        session.status = "running"
        session.question = {}
        session.updated_at = time.time()
    _run_agent_async(session_id, lambda item: _agent_continue(item, answer))
    return session


def cancel_agent_session(session_id: str) -> AgentSession | None:
    session = get_agent_session(session_id)
    if not session:
        return None
    child_job_id = ""
    with _LOCK:
        if session.status in {"done", "failed", "cancelled"}:
            return session
        child_job_id = str(session.result.get("current_job_id") or "")
        session.status = "cancelled"
        session.phase = "cancelled"
        session.logs.append("agent_cancelled")
        session.updated_at = time.time()
    if child_job_id:
        cancel_job(child_job_id)
    return session


def _run_agent_async(session_id: str, target: Callable[[AgentSession], None]) -> None:
    def runner() -> None:
        session = get_agent_session(session_id)
        if not session:
            return
        try:
            target(session)
        except Exception as exc:
            _agent_fail(session_id, exc)

    threading.Thread(target=runner, daemon=True).start()


def _agent_start(session: AgentSession) -> None:
    payload = session.payload
    url = _required_str(payload, "url")
    _agent_log(session.id, "agent_start")
    _agent_set_phase(session.id, "probe")
    probe = probe_video(
        url,
        target_language=str(payload.get("target_language") or "zh"),
        detected_source_language=str(payload.get("detected_source_language") or ""),
        embedded_subtitle_hint=str(payload.get("embedded_subtitle_hint") or "unknown"),
    )
    _agent_update_result(session.id, {"probe": probe, "normalized_url": probe.get("normalized_url")})
    title = str(probe.get("title") or "")
    if title and bool(payload.get("translate_title", False)):
        try:
            translated = translate_title_text(title)
            _agent_update_result(session.id, {"zh_title": translated.get("zh_title", "")})
        except Exception as exc:
            _agent_log(session.id, f"title_translation_skipped: {exc}")
    plan = probe.get("agent_plan") or {}
    _agent_update_result(session.id, {"agent_plan": plan})
    selected = plan.get("selected_subtitle") if isinstance(plan, dict) else None
    if selected:
        route = str(plan.get("route") or "")
        confidence = float(plan.get("confidence") or 0)
        if route in {"download_target_subtitle", "translate_source_subtitle"} and confidence >= 0.85:
            _agent_log(session.id, "agent_auto_use_recommended_subtitle")
            _agent_use_recommended_subtitle(session)
            return
        _agent_wait(
            session.id,
            "confirm_subtitle",
            {
                "kind": "confirm_subtitle",
                "title": "确认字幕源",
                "message": _agent_subtitle_question_message(plan),
                "selected_subtitle": selected,
                "options": _agent_confirm_options(plan),
            },
        )
        return
    _agent_continue_route_without_subtitle(session.id, plan)


def _agent_continue(session: AgentSession, answer: dict[str, Any]) -> None:
    action = str(answer.get("action") or "")
    if action == "manual_mode":
        _agent_done(session.id, {"next_view": "new-task"})
        return
    if action == "run_ocr":
        _agent_run_ocr(session)
        return
    if action == "run_asr":
        _agent_run_asr(session)
        return
    if session.phase == "confirm_subtitle" and action == "use_recommended":
        plan = session.result.get("agent_plan") or {}
        if str(plan.get("route") or "") == "hybrid_anchor_ocr":
            _agent_run_hybrid_anchor_ocr(session)
            return
        _agent_use_recommended_subtitle(session)
        return
    if session.phase == "review_glossary" and action in {"continue_after_glossary", "skip_glossary"}:
        _agent_translate_after_glossary(session, use_glossary=action != "skip_glossary")
        return
    raise RuntimeError(f"未知 Agent 回答: {action}")


def _agent_use_recommended_subtitle(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    selected = plan.get("selected_subtitle") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")
    _agent_set_phase(session.id, "download_subtitle")
    subtitle_job = download_subtitle_job(
        {"url": url, "lang": selected.get("lang"), "kind": selected.get("kind"), "title": probe.get("title") or ""}
    )
    subtitle_result = _wait_for_job(subtitle_job, session_id=session.id)
    source_srt = str(subtitle_result.get("subtitle_path") or "")
    _agent_update_result(session.id, {"source_srt": source_srt, "download_subtitle": subtitle_result})
    if not plan.get("requires_translation", True):
        _agent_done(session.id, {"subtitle_path": source_srt, "message": "已下载目标语言字幕。"})
        return
    if plan.get("needs_source_correction"):
        _agent_log(session.id, "source_correction_suggested")
    _agent_set_phase(session.id, "generate_glossary")
    glossary_job = generate_glossary_job(
        {
            "source_srt": source_srt,
            "extra_hint": str(session.payload.get("extra_hint") or ""),
            "out": str(_agent_glossary_path(session)),
        }
    )
    glossary_result = _wait_for_job(glossary_job, session_id=session.id)
    glossary_path = str(glossary_result.get("glossary_path") or "")
    _agent_update_result(session.id, {"glossary_path": glossary_path, "generate_glossary": glossary_result})
    _agent_wait(
        session.id,
        "review_glossary",
        {
            "kind": "review_glossary",
            "title": "请审核 Glossary",
            "message": "Glossary 草稿已生成。审核人名、昵称和专有词后继续翻译。",
            "glossary_path": glossary_path,
            "options": [
                {"action": "continue_after_glossary", "label": "我已审核，继续翻译"},
                {"action": "skip_glossary", "label": "跳过 glossary 直接翻译"},
            ],
        },
    )


def _agent_translate_after_glossary(session: AgentSession, *, use_glossary: bool) -> None:
    source_srt = str(session.result.get("source_srt") or "")
    glossary_path = str(session.result.get("glossary_path") or "") if use_glossary else ""
    extra_prompt = ""
    if session.result.get("source_kind") == "hybrid_anchor_ocr":
        extra_prompt = _HYBRID_TRANSLATION_PROMPT
    _agent_set_phase(session.id, "translate")
    job = translate_subtitle_job(
        {
            "source_srt": source_srt,
            "glossary": glossary_path,
            "translation_mode": "translate_only",
            "extra_prompt": extra_prompt,
        }
    )
    translated = _wait_for_job(job, session_id=session.id)
    done_result = {"translate_subtitle": translated, "translated_srt": translated.get("translated_srt")}
    for key in ("translated_sidecar", "source_sidecar"):
        if translated.get(key):
            done_result[key] = translated.get(key)
    _agent_done(session.id, done_result)


def _agent_continue_route_without_subtitle(session_id: str, plan: dict[str, Any]) -> None:
    route = str((plan or {}).get("route") or "")
    if route == "ocr":
        session = get_agent_session(session_id)
        if session:
            _agent_run_ocr(session)
        return
    if route == "asr":
        session = get_agent_session(session_id)
        if session:
            _agent_run_asr(session)
        return
    _agent_wait(
        session_id,
        "diagnose_ocr_asr",
        {
            "kind": "diagnose_ocr_asr",
            "title": "需要选择 OCR 或 ASR",
            "message": "没有可用字幕且不确定是否有内嵌字幕。第一版 Agent 先暂停，请选择路线。",
            "options": [
                {"action": "run_ocr", "label": "使用 OCR"},
                {"action": "run_asr", "label": "使用 ASR"},
                {"action": "manual_mode", "label": "转到手动模式"},
            ],
        },
    )


def _agent_run_ocr(session: AgentSession) -> None:
    _agent_set_phase(session.id, "ocr_full")
    url = str(session.result.get("normalized_url") or session.payload.get("url") or "")
    job = ocr_full_job(
        {
            "url": url,
            "title": (session.result.get("probe") or {}).get("title") or "",
            "extra_hint": str(session.payload.get("extra_hint") or ""),
            "translation_mode": str(session.payload.get("ocr_translation_mode") or "standard_cleanup"),
        }
    )
    result = _wait_for_job(job, session_id=session.id)
    _agent_done(session.id, {"ocr": result, "source_srt": result.get("source_srt"), "translated_srt": result.get("translated_srt")})


def _agent_run_hybrid_anchor_ocr(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    selected = plan.get("selected_subtitle") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")
    extra_hint = str(session.payload.get("extra_hint") or "")

    _agent_set_phase(session.id, "download_anchor_subtitle")
    subtitle_result = _wait_for_job(
        download_subtitle_job({"url": url, "lang": selected.get("lang"), "kind": selected.get("kind"), "title": probe.get("title") or ""}),
        session_id=session.id,
    )
    anchor_srt = str(subtitle_result.get("subtitle_path") or "")
    _agent_update_result(session.id, {"anchor_srt": anchor_srt, "download_subtitle": subtitle_result})

    _agent_set_phase(session.id, "download_video_for_hybrid")
    video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
    input_video = str(video_result.get("input_video") or "")
    _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})

    _agent_set_phase(session.id, "hybrid_anchor_ocr")
    hybrid_result = _wait_for_job(
        hybrid_anchor_ocr_job(
            {
                "input_video": input_video,
                "anchor_srt": anchor_srt,
                "title": probe.get("title") or "",
            }
        ),
        session_id=session.id,
    )
    source_srt = str(hybrid_result.get("source_srt") or "")
    _agent_update_result(
        session.id,
        {
            "source_srt": source_srt,
            "source_kind": "hybrid_anchor_ocr",
            "hybrid_anchor_ocr": hybrid_result,
        },
    )

    _agent_set_phase(session.id, "generate_glossary")
    glossary_job = generate_glossary_job(
        {
            "source_srt": source_srt,
            "extra_hint": extra_hint,
            "source_language": "korean",
            "out": str(_agent_glossary_path(session)),
        }
    )
    glossary_result = _wait_for_job(glossary_job, session_id=session.id)
    glossary_path = str(glossary_result.get("glossary_path") or "")
    _agent_update_result(session.id, {"glossary_path": glossary_path, "generate_glossary": glossary_result})
    _agent_wait(
        session.id,
        "review_glossary",
        {
            "kind": "review_glossary",
            "title": "请审核 Glossary",
            "message": "Hybrid 源字幕已生成：时间轴来自英文人工字幕，原文优先使用韩文 OCR。审核 glossary 后继续翻译。",
            "glossary_path": glossary_path,
            "options": [
                {"action": "continue_after_glossary", "label": "我已审核，继续翻译"},
                {"action": "skip_glossary", "label": "跳过 glossary 直接翻译"},
            ],
        },
    )


def _agent_run_asr(session: AgentSession) -> None:
    _agent_set_phase(session.id, "download_video_for_asr")
    url = str(session.result.get("normalized_url") or session.payload.get("url") or "")
    probe = session.result.get("probe") or {}
    video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
    input_video = str(video_result.get("input_video") or "")
    _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})
    _agent_set_phase(session.id, "audio_asr")
    asr_result = _wait_for_job(
        audio_local_video_job({"input_video": input_video, "language": "auto", "model_size": "large-v3"}),
        session_id=session.id,
    )
    _agent_done(session.id, {"asr": asr_result, "source_srt": asr_result.get("source_srt"), "input_video": input_video})


def _wait_for_job(job: Job, timeout: float | None = None, *, session_id: str = "") -> dict[str, Any]:
    if session_id:
        _agent_update_result(
            session_id,
            {
                "current_job_id": job.id,
                "current_job_name": job.name,
                "current_job_status": job.status,
            },
        )
    deadline = time.time() + timeout if timeout else None
    while True:
        if job.status == "done":
            if session_id:
                _agent_update_result(session_id, {"current_job_status": job.status})
            return job.result
        if job.status in {"failed", "cancelled"}:
            if session_id:
                _agent_update_result(session_id, {"current_job_status": job.status})
            raise RuntimeError(job.error or f"任务失败: {job.name}")
        if deadline and time.time() > deadline:
            raise TimeoutError(f"等待任务超时: {job.name}")
        if session_id:
            _agent_update_result(
                session_id,
                {
                    "current_job_status": job.status,
                    "current_job_logs": job.logs[-40:],
                },
            )
        time.sleep(0.2)


def _agent_subtitle_question_message(plan: dict[str, Any]) -> str:
    route = str(plan.get("route") or "")
    if route == "download_target_subtitle":
        return "检测到目标语言字幕，建议直接下载。"
    if route == "hybrid_anchor_ocr":
        return "检测到英文人工字幕，且你确认画面有内嵌字幕。建议使用英文人工字幕定轴，再用韩文 OCR 补足原文精度。"
    if route == "translate_auto_subtitle":
        return "检测到原声自动字幕，建议下载后先纠错再翻译。"
    return "检测到原声作者字幕，建议下载后生成 glossary 并翻译。"


def _agent_confirm_options(plan: dict[str, Any]) -> list[dict[str, str]]:
    route = str(plan.get("route") or "")
    if route == "hybrid_anchor_ocr":
        return [
            {"action": "use_recommended", "label": "英文定轴 + 韩文 OCR（推荐，较慢但更准）"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "整片 OCR（慢）"},
            {"action": "run_asr", "label": "音频 ASR"},
        ]
    if route == "translate_fallback_subtitle":
        return [
            {"action": "use_recommended", "label": "使用中转字幕翻译（快）"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "改用整片 OCR（慢）"},
            {"action": "run_asr", "label": "改用 ASR"},
        ]
    return [
        {"action": "use_recommended", "label": "使用推荐字幕"},
        {"action": "manual_mode", "label": "转到手动模式"},
        {"action": "run_ocr", "label": "改用 OCR"},
        {"action": "run_asr", "label": "改用 ASR"},
    ]


def _agent_set_phase(session_id: str, phase: str) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session or session.status == "cancelled":
            raise RuntimeError("agent session cancelled")
        session.phase = phase
        session.status = "running"
        session.updated_at = time.time()
        session.logs.append(f"agent_phase: {phase}")


def _agent_workspace(session: AgentSession) -> Path:
    path = JOB_DIR / session.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _agent_glossary_path(session: AgentSession) -> Path:
    return _agent_workspace(session) / "glossary.draft.yaml"


def _agent_update_result(session_id: str, values: dict[str, Any]) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        session.result.update(values)
        session.updated_at = time.time()


def _agent_log(session_id: str, line: str) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        session.logs.append(line.rstrip())
        session.updated_at = time.time()


def _agent_wait(session_id: str, phase: str, question: dict[str, Any]) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        session.phase = phase
        session.status = "waiting"
        session.question = question
        session.logs.append(f"agent_wait: {phase}")
        session.updated_at = time.time()


def _agent_done(session_id: str, values: dict[str, Any]) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        session.result.update(values)
        session.status = "done"
        session.phase = "done"
        session.question = {}
        session.logs.append("agent_done")
        session.updated_at = time.time()


def _agent_fail(session_id: str, exc: Exception) -> None:
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        session.status = "failed"
        session.error = str(exc)
        session.question = {}
        session.logs.append(f"agent_failed: {exc}")
        session.updated_at = time.time()


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.logs.append(line.rstrip())
        job.updated_at = time.time()


def download_subtitle_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    lang = _required_str(payload, "lang")
    kind = str(payload.get("kind") or "manual")
    title = str(payload.get("title") or "").strip()
    before = _snapshot_files(DOWNLOAD_DIR, "*.srt")

    def target(job_id: str) -> dict[str, Any]:
        args = _module_command("video_translate.youtube.download_subtitles", url, "--output-dir", DOWNLOAD_DIR, "--sub-langs", lang)
        if kind == "manual":
            args.append("--no-auto")
        elif kind == "auto":
            args.append("--auto-only")
        _run_command(job_id, args)
        changed = _changed_files(DOWNLOAD_DIR, "*.srt", before)
        if not changed:
            changed = _matching_subtitle_files(DOWNLOAD_DIR, title, lang)
        if not changed and not title:
            changed = _newest_files(DOWNLOAD_DIR, "*.srt", limit=3)
        if not changed:
            raise RuntimeError(f"字幕下载完成后没有找到匹配文件: title={title or '<unknown>'}, lang={lang}")
        return {"subtitle_paths": [str(path) for path in changed], "subtitle_path": str(changed[0]) if changed else ""}

    return start_job(f"下载字幕 {lang} {kind}", target)


def generate_glossary_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    source_language = str(payload.get("source_language") or "auto")
    if source_language == "auto":
        source_language = _guess_language_from_path(source_srt)
    extra_hint = str(payload.get("extra_hint") or "")
    out = _resolve_project_path(payload.get("out") or str(GLOSSARY_DIR / f"{_safe_slug(source_srt.stem)}.draft.yaml"))
    _ensure_under_root(out)

    def target(job_id: str) -> dict[str, Any]:
        out.parent.mkdir(parents=True, exist_ok=True)
        args = _module_command("video_translate.tools.generate_glossary", source_srt, "--out", out, "--source-language", source_language)
        if extra_hint.strip():
            args.extend(["--extra-hint", extra_hint.strip()])
        _run_command(job_id, args)
        return {"glossary_path": str(out), "content": out.read_text(encoding="utf-8") if out.exists() else ""}

    return start_job("生成 glossary 草稿", target)


def translate_subtitle_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    glossary_value = str(payload.get("glossary") or "").strip()
    glossary = _resolve_project_path(glossary_value) if glossary_value else None
    translation_mode = _normalize_subtitle_translation_mode(payload.get("translation_mode"))
    extra_prompt = str(payload.get("extra_prompt") or "")
    out = _resolve_project_path(payload.get("out") or str(source_srt.with_name(source_srt.stem + ".zh.srt")))
    _ensure_under_root(out)

    def target(job_id: str) -> dict[str, Any]:
        args = [
            *_module_command(
                "video_translate.tools.translate_subtitles",
                source_srt,
                "--out",
                out,
                "--translation-mode",
                translation_mode,
            ),
        ]
        if glossary:
            args.extend(["--glossary", str(glossary)])
        if extra_prompt.strip():
            args.extend(["--extra-prompt", extra_prompt.strip()])
        _run_command(job_id, args)
        result = {"translated_srt": str(out), "translation_mode": translation_mode}
        result.update({name: str(path) for name, path in _copy_translated_sidecar_for_source(source_srt, out).items()})
        return result

    return start_job("翻译外挂字幕", target)


def correct_asr_subtitle_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    glossary_value = str(payload.get("glossary") or "").strip()
    glossary = _resolve_project_path(glossary_value) if glossary_value else None
    source_language = str(payload.get("source_language") or "auto").strip()
    extra_hint = str(payload.get("extra_hint") or "")
    out = _resolve_project_path(payload.get("out") or str(source_srt.with_name(source_srt.stem + ".corrected.srt")))
    _ensure_under_root(out)

    def target(job_id: str) -> dict[str, Any]:
        args = [
            *_module_command(
                "video_translate.tools.correct_asr",
                source_srt,
                "--out",
                out,
                "--source-language",
                source_language,
            ),
        ]
        if glossary:
            args.extend(["--glossary", str(glossary)])
        if extra_hint.strip():
            args.extend(["--extra-prompt", extra_hint.strip()])
        _run_command(job_id, args)
        result = {"corrected_srt": str(out), "source_srt": str(out), "subtitle_path": str(out)}
        result.update({name: str(path) for name, path in _copy_corrected_source_sidecar_for_source(source_srt, out).items()})
        return result

    return start_job("ASR 原文纠错", target)


def convert_subtitle_job(payload: dict[str, Any]) -> Job:
    source = _resolve_project_path(_required_str(payload, "source"))
    _ensure_under_root(source)
    if not source.exists():
        raise FileNotFoundError(f"字幕文件不存在: {source}")
    output_format = str(payload.get("format") or payload.get("output_format") or "srt").strip()
    out_value = str(payload.get("out") or "").strip()
    out = _resolve_project_path(out_value) if out_value else source.with_suffix(f".{output_format.lower().lstrip('.')}")
    _ensure_under_root(out)

    def target(job_id: str) -> dict[str, Any]:
        args = [
            *_module_command(
                "video_translate.tools.convert_subtitle",
                source,
                "--format",
                output_format,
                "--out",
                out,
            ),
        ]
        _run_command(job_id, args)
        return {"converted_subtitle": str(out), "subtitle_path": str(out), "format": output_format}

    return start_job(f"字幕格式转换 {source.name} -> {output_format}", target)



def _copy_translated_sidecar_for_source(source_srt: Path, translated_srt: Path) -> dict[str, Path]:
    run_config = source_srt.parent / "run.yaml"
    if not run_config.exists() or not translated_srt.exists():
        return {}
    data = yaml.safe_load(run_config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("input_video"):
        return {}
    input_video = _resolve_project_path(data["input_video"])
    _ensure_under_root(input_video)
    if not input_video.exists():
        return {}
    raw_sidecar = data.get("sidecar") if isinstance(data.get("sidecar"), dict) else {}
    config = SidecarConfig(
        enabled=bool(raw_sidecar.get("enabled", True)),
        copy_source=False,
        copy_translated=bool(raw_sidecar.get("copy_translated", True)),
        source_suffix=str(raw_sidecar.get("source_suffix", ".source")),
        translated_suffix=str(raw_sidecar.get("translated_suffix", ".zh")),
    )
    return copy_sidecar_subtitles(input_video, translated_srt=translated_srt, config=config)


def _copy_corrected_source_sidecar_for_source(source_srt: Path, corrected_srt: Path) -> dict[str, Path]:
    run_config = source_srt.parent / "run.yaml"
    if not run_config.exists() or not corrected_srt.exists():
        return {}
    data = yaml.safe_load(run_config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("input_video"):
        return {}
    input_video = _resolve_project_path(data["input_video"])
    _ensure_under_root(input_video)
    if not input_video.exists():
        return {}
    raw_sidecar = data.get("sidecar") if isinstance(data.get("sidecar"), dict) else {}
    config = SidecarConfig(
        enabled=bool(raw_sidecar.get("enabled", True)),
        copy_source=bool(raw_sidecar.get("copy_source", True)),
        copy_translated=False,
        source_suffix=str(raw_sidecar.get("source_suffix", ".source")),
        translated_suffix=str(raw_sidecar.get("translated_suffix", ".zh")),
    )
    return copy_sidecar_subtitles(input_video, source_srt=corrected_srt, config=config)


def _copy_source_sidecar_for_run_config(run_config: Path, source_srt: Path) -> dict[str, Path]:
    if not run_config.exists() or not source_srt.exists():
        return {}
    data = yaml.safe_load(run_config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("input_video"):
        return {}
    input_video = _resolve_project_path(data["input_video"])
    _ensure_under_root(input_video)
    if not input_video.exists():
        return {}
    raw_sidecar = data.get("sidecar") if isinstance(data.get("sidecar"), dict) else {}
    config = SidecarConfig(
        enabled=bool(raw_sidecar.get("enabled", True)),
        copy_source=bool(raw_sidecar.get("copy_source", True)),
        copy_translated=False,
        source_suffix=str(raw_sidecar.get("source_suffix", ".source")),
        translated_suffix=str(raw_sidecar.get("translated_suffix", ".zh")),
    )
    return copy_sidecar_subtitles(input_video, source_srt=source_srt, config=config)


def download_video_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    title = str(payload.get("title") or "").strip()
    before = _snapshot_video_files(DOWNLOAD_DIR)

    def target(job_id: str) -> dict[str, Any]:
        _run_command(job_id, _module_command("video_translate.youtube.download_video", url))
        videos = _changed_video_files(DOWNLOAD_DIR, before)
        if not videos:
            videos = _matching_video_files(DOWNLOAD_DIR, title)
        if not videos and not title:
            videos = _newest_video_files(DOWNLOAD_DIR, limit=3)
        if not videos:
            raise RuntimeError(f"视频下载完成后没有找到匹配文件: title={title or '<unknown>'}")
        return {"video_paths": [str(path) for path in videos], "input_video": str(videos[0]) if videos else ""}

    return start_job("下载视频", target)


def ocr_full_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    extra_hint = str(payload.get("extra_hint") or "")
    translation_mode = _normalize_ocr_translation_mode(payload.get("translation_mode"), bool(payload.get("preserve_timing", False)))
    job_slug = _safe_slug(payload.get("title") or "ocr_task")[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        before_videos = _snapshot_video_files(DOWNLOAD_DIR)
        _append_log(job_id, "download_video_start")
        _run_command(job_id, _module_command("video_translate.youtube.download_video", url))
        videos = _changed_video_files(DOWNLOAD_DIR, before_videos)
        if not videos:
            videos = _newest_video_files(DOWNLOAD_DIR, limit=1)
        if not videos:
            raise RuntimeError("视频下载完成后没有找到 mp4/mkv/webm 文件")
        input_video = videos[0]
        _append_log(job_id, f"input_video: {input_video}")
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint, translation_mode=translation_mode)
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        return {"input_video": str(input_video), "output_dir": str(out_dir), "source_srt": str(out_dir / "source.srt"), "translated_srt": str(out_dir / "zh.srt")}

    return start_job(f"OCR 全流程 {job_slug}", target)


def ocr_local_video_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    extra_hint = str(payload.get("extra_hint") or "")
    translation_mode = _normalize_ocr_translation_mode(payload.get("translation_mode"), bool(payload.get("preserve_timing", False)))
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint, translation_mode=translation_mode)
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        return {"input_video": str(input_video), "output_dir": str(out_dir), "source_srt": str(out_dir / "source.srt"), "translated_srt": str(out_dir / "zh.srt")}

    return start_job(f"本地视频 OCR {job_slug}", target)


def hybrid_anchor_ocr_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    anchor_srt = _resolve_project_path(_required_str(payload, "anchor_srt"))
    _ensure_under_root(input_video)
    _ensure_under_root(anchor_srt)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    if not anchor_srt.exists():
        raise FileNotFoundError(f"字幕文件不存在: {anchor_srt}")
    lang = str(payload.get("lang") or "korean").strip()
    sample_fps = str(payload.get("sample_fps") or "2.0")
    bottom_ratio = str(payload.get("bottom_ratio") or "0.42")
    device = str(payload.get("device") or "auto")
    job_slug = _safe_slug(payload.get("title") or input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        config_path = out_dir / "run.yaml"
        config = {
            "mode": "hybrid_anchor_ocr",
            "input_video": str(input_video),
            "anchor_srt": str(anchor_srt),
            "source_srt": str(out_dir / "hybrid.source.srt"),
            "output_dir": str(out_dir),
            "hybrid": {
                "lang": lang,
                "sample_fps": sample_fps,
                "bottom_ratio": bottom_ratio,
                "device": device,
            },
            "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"anchor_srt: {anchor_srt}")
        _append_log(job_id, f"config: {config_path}")
        _run_command(
            job_id,
            [
                *_module_command(
                    "video_translate.tools.hybrid_anchor_ocr",
                    input_video,
                    anchor_srt,
                ),
                "--out-dir",
                str(out_dir),
                "--lang",
                lang,
                "--sample-fps",
                sample_fps,
                "--bottom-ratio",
                bottom_ratio,
                "--device",
                device,
                "--ocr-window-seconds",
                str(payload.get("ocr_window_seconds") or "1.20"),
                "--reconstruct-korean",
            ],
        )
        source_srt = out_dir / "hybrid.source.srt"
        result = {
            "input_video": str(input_video),
            "anchor_srt": str(anchor_srt),
            "output_dir": str(out_dir),
            "source_srt": str(source_srt),
            "context_srt": str(out_dir / "hybrid.context.srt"),
            "debug_json": str(out_dir / "hybrid.debug.json"),
            "ocr_boxes": str(out_dir / "hybrid.ocr_boxes.json"),
        }
        result.update({name: str(path) for name, path in _copy_source_sidecar_for_run_config(config_path, source_srt).items()})
        return result

    return start_job(f"英文定轴 + 韩文 OCR {job_slug}", target)


def audio_local_video_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    language = str(payload.get("language") or "auto").strip()
    model_size = str(payload.get("model_size") or "large-v3").strip()
    device = str(payload.get("device") or "cuda").strip()
    compute_type = str(payload.get("compute_type") or "float16").strip()
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        source_srt = out_dir / "source.srt"
        config_path = out_dir / "run.yaml"
        config = {
            "mode": "audio",
            "input_video": str(input_video),
            "source_srt": str(source_srt),
            "output_dir": str(out_dir),
            "audio": {
                "provider": "faster-whisper",
                "model_size": model_size,
                "language": language,
                "device": device,
                "compute_type": compute_type,
            },
            "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"config: {config_path}")
        _run_command(
            job_id,
            [
                *_module_command(
                    "video_translate.tools.transcribe_audio",
                    input_video,
                ),
                "--out",
                str(source_srt),
                "--model-size",
                model_size,
                "--language",
                language,
                "--device",
                device,
                "--compute-type",
                compute_type,
            ],
        )
        copied = copy_sidecar_subtitles(
            input_video,
            source_srt=source_srt,
            config=SidecarConfig(enabled=True, copy_source=True, copy_translated=False, source_suffix=".source", translated_suffix=".zh"),
        )
        result = {"input_video": str(input_video), "output_dir": str(out_dir), "source_srt": str(source_srt), "subtitle_path": str(source_srt)}
        result.update({name: str(path) for name, path in copied.items()})
        return result

    return start_job(f"音频识别字幕 {job_slug}", target)


def _ocr_config(
    input_video: Path,
    output_dir: Path,
    *,
    extra_hint: str,
    translation_mode: str = "standard_cleanup",
    preserve_timing: bool = False,
) -> dict[str, Any]:
    translation_mode = _normalize_ocr_translation_mode(translation_mode, preserve_timing)
    prompt = """
严格遵守 glossary 中的人名、角色名、节目名和固定术语。
字幕要自然、简洁、口语化，适合 1-2 行外挂字幕显示。
如果相邻两条字幕明显是同一句话的 OCR 变体，请保持译文一致。
""".strip()
    if extra_hint.strip():
        prompt += "\n任务提示：" + extra_hint.strip()
    mode_prompt, translation = _ocr_translation_mode_config(translation_mode, prompt)
    prompt = mode_prompt
    return {
        "mode": "full",
        "input_video": str(input_video),
        "source_srt": str(output_dir / "source.srt"),
        "output_dir": str(output_dir),
        "source_language": "korean",
        "target_language": "简体中文",
        "glossary": "",
        "ocr": {"device": "auto", "sample_fps": 3.0, "bottom_ratio": 0.42, "scan_full_frame": False},
        "filters": {"ignored_texts": ["Disney+", "디즈니+"], "ignored_contains": [], "ignored_patterns": ["disn[e3][yp]?\\+?"]},
        "subtitle": {"merge_gap_seconds": 0.85, "same_text_similarity": 0.88, "merge_same_start_seconds": 0.16, "merge_short_fragment_gap_seconds": 0.50, "short_fragment_max_chars": 14, "short_fragment_similarity": 0.55, "snapshot_similarity": 0.72, "snapshot_max_gap_seconds": None, "snapshot_min_confidence": 0.50, "end_padding_seconds": 0.35, "sample_end_extension_ratio": 0.75, "min_duration_seconds": 0.60, "max_next_overlap_seconds": 0.04, "enforce_no_overlap": True},
        "translation": translation,
        "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
    }


OCR_TRANSLATION_MODES = {
    "translate_only": {
        "label": "锁定 OCR 时间轴，只翻译文本",
        "prompt": "本次使用锁定 OCR 时间轴模式：必须逐条翻译，不合并、不拆分、不删除字幕条目，不调整字幕时间。",
        "settings": {
            "llm_cleanup_translated": False,
            "cleanup_residual_fragments": False,
            "dedupe_translated": False,
            "retime_translated": False,
        },
    },
    "standard_cleanup": {
        "label": "标准清理，去重复和残片",
        "prompt": "本次使用标准清理模式：可以清理明显重复、残缺或噪声字幕，但不要为了阅读速度改动时间轴。",
        "settings": {
            "llm_cleanup_translated": True,
            "cleanup_residual_fragments": True,
            "dedupe_translated": True,
            "retime_translated": False,
        },
    },
    "readability_retime": {
        "label": "强力精修，优化阅读时长",
        "prompt": "本次使用强力精修模式：可以清理重复和残片，并在不和下一条字幕重叠的前提下优化中文字幕显示时长。",
        "settings": {
            "llm_cleanup_translated": True,
            "cleanup_residual_fragments": True,
            "dedupe_translated": True,
            "retime_translated": True,
        },
    },
}


def _normalize_subtitle_translation_mode(value: Any) -> str:
    mode = str(value or "translate_only").strip()
    if mode not in OCR_TRANSLATION_MODES:
        raise ValueError(f"未知字幕翻译处理模式: {mode}")
    return mode


def _normalize_ocr_translation_mode(value: Any, preserve_timing: bool = False) -> str:
    if preserve_timing:
        return "translate_only"
    mode = str(value or "standard_cleanup").strip()
    if mode not in OCR_TRANSLATION_MODES:
        raise ValueError(f"未知 OCR 翻译处理模式: {mode}")
    return mode


def _ocr_translation_mode_config(mode: str, prompt: str) -> tuple[str, dict[str, Any]]:
    mode = _normalize_ocr_translation_mode(mode)
    mode_config = OCR_TRANSLATION_MODES[mode]
    prompt = prompt + "\n" + str(mode_config["prompt"])
    translation = {
        "provider": "volcengine",
        "batch_size": 20,
        "model": None,
        "base_url": None,
        "extra_prompt": prompt,
        "llm_cleanup_translated": True,
        "llm_cleanup_max_gap_seconds": 3.0,
        "llm_cleanup_max_window_size": 8,
        "cleanup_residual_fragments": True,
        "residual_max_gap_seconds": 3.0,
        "residual_short_text_chars": 6,
        "dedupe_translated": True,
        "dedupe_similarity": 0.88,
        "dedupe_max_gap_seconds": 1.2,
        "retime_translated": False,
    }
    translation.update(mode_config["settings"])
    translation["ocr_translation_mode"] = mode
    return prompt, translation


def read_text_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


def write_text_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    content = str(payload.get("content") or "")
    _ensure_under_root(path)
    _ensure_writable_glossary_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "saved": True}


def read_glossary_items(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    text = path.read_text(encoding="utf-8")
    data = _load_yaml_text(text, path)
    source_srt = _source_srt_from_glossary_text(text, path)
    cue_texts = _cue_texts_by_id(source_srt)
    english_reference_texts = _hybrid_english_references_by_id(source_srt)
    return {
        "path": str(path),
        "items": _glossary_items(
            data,
            cue_texts=cue_texts,
            english_reference_texts=english_reference_texts,
            include_blind_candidates=bool(payload.get("include_blind_candidates", False)),
        ),
    }


def write_glossary_items(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    _ensure_writable_glossary_path(path)
    original_text = path.read_text(encoding="utf-8")
    source_srt = _source_srt_from_glossary_text(original_text, path)
    data = _load_yaml_text(original_text, path)
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "")
        index = int(item.get("index", -1))
        zh = str(item.get("zh") or "").strip()
        reviewed = bool(item.get("reviewed", False))
        if section == "program" and isinstance(data.get("program"), dict):
            data["program"]["zh"] = zh
            data["program"]["reviewed"] = reviewed
        elif section in {"characters", "terms"} and isinstance(data.get(section), list) and 0 <= index < len(data[section]):
            if isinstance(data[section][index], dict):
                data[section][index]["zh"] = zh
                data[section][index]["reviewed"] = reviewed
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    if source_srt is not None:
        text = f"# source_srt: {source_srt}\n{text}"
    path.write_text(text, encoding="utf-8")
    return {"path": str(path), "saved": True, "content": text, "items": _glossary_items(data)}


def _ensure_writable_glossary_path(path: Path) -> None:
    if _is_relative_to(path, GLOSSARY_DIR) or _is_relative_to(path, JOB_DIR):
        return
    raise ValueError("UI 只允许保存 configs/glossaries 或 outputs/agent_jobs 下的 glossary 文件")


def _load_yaml_file(path: Path) -> dict[str, Any]:
    return _load_yaml_text(path.read_text(encoding="utf-8"), path)


def _load_yaml_text(text: str, path: Path) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 内容必须是对象: {path}")
    return data


def _source_srt_from_glossary_text(text: str, glossary_path: Path) -> Path | None:
    for line in text.splitlines()[:20]:
        match = re.match(r"\s*#\s*source_srt:\s*(.+?)\s*$", line)
        if not match:
            continue
        raw = match.group(1).strip().strip("'\"")
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = glossary_path.parent / path
        return path
    return None


def _cue_texts_by_id(path: Path | None) -> dict[int, str]:
    if path is None or not path.exists():
        return {}
    try:
        return {cue.index: cue.text.strip() for cue in read_srt(path) if cue.text.strip()}
    except Exception:
        return {}


def _hybrid_english_references_by_id(source_srt: Path | None) -> dict[int, str]:
    if source_srt is None:
        return {}
    context_srt = source_srt.with_name("hybrid.context.srt")
    if not context_srt.exists():
        return {}
    result: dict[int, str] = {}
    try:
        for cue in read_srt(context_srt):
            text = _extract_hybrid_english_reference(cue.text)
            if text:
                result[cue.index] = text
    except Exception:
        return {}
    return result


def _extract_hybrid_english_reference(text: str) -> str:
    marker = "英文参考："
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].strip()


def _evidence_ids_from_item(item: dict[str, Any]) -> list[int]:
    raw_ids = item.get("evidence_ids")
    values: list[Any]
    if isinstance(raw_ids, list):
        values = raw_ids
    else:
        note = str(item.get("note") or "")
        match = re.search(r"evidence_ids\s*:\s*([^|]+)", note)
        values = re.findall(r"\d+", match.group(1)) if match else []
    ids: list[int] = []
    for value in values:
        try:
            cue_id = int(value)
        except (TypeError, ValueError):
            continue
        if cue_id not in ids:
            ids.append(cue_id)
    return ids


def _glossary_context_text(item: dict[str, Any], cue_texts: dict[int, str]) -> str:
    lines: list[str] = []
    for cue_id in _evidence_ids_from_item(item):
        text = cue_texts.get(cue_id, "").strip()
        if text and text not in lines:
            lines.append(text)
        if len(lines) >= 3:
            break
    return "\n".join(lines)


def _glossary_reference_text(item: dict[str, Any], cue_texts: dict[int, str]) -> str:
    lines: list[str] = []
    for cue_id in _evidence_ids_from_item(item):
        text = cue_texts.get(cue_id, "").strip()
        if text and text not in lines:
            lines.append(text)
        if len(lines) >= 3:
            break
    return "\n".join(lines)


def _blind_translate_glossary_context(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    _load_dotenv(ROOT)
    task_llm = load_llm_task_config("title_translation")
    key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    if not key:
        return ""
    selected_model = task_llm.model
    if not selected_model:
        return ""
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": "你是字幕句子直译助手。不要使用任何术语表、上下文或推测，只把用户给出的单句翻译成自然简体中文。只输出译文。",
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
    }
    return _request_translation(endpoint, key, payload).strip()


def _glossary_items(
    data: dict[str, Any],
    *,
    cue_texts: dict[int, str] | None = None,
    english_reference_texts: dict[int, str] | None = None,
    include_blind_candidates: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    blind_candidate_cache: dict[str, str] = {}
    program = data.get("program")
    if isinstance(program, dict):
        result.append(
            _glossary_item(
                "program",
                0,
                program,
                cue_texts=cue_texts,
                english_reference_texts=english_reference_texts,
                include_blind_candidates=include_blind_candidates,
                blind_candidate_cache=blind_candidate_cache,
            )
        )
    for section in ["characters", "terms"]:
        values = data.get(section) or []
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if isinstance(item, dict):
                result.append(
                    _glossary_item(
                        section,
                        index,
                        item,
                        cue_texts=cue_texts,
                        english_reference_texts=english_reference_texts,
                        include_blind_candidates=include_blind_candidates,
                        blind_candidate_cache=blind_candidate_cache,
                    )
                )
    return result


def _glossary_item(
    section: str,
    index: int,
    item: dict[str, Any],
    *,
    cue_texts: dict[int, str] | None = None,
    english_reference_texts: dict[int, str] | None = None,
    include_blind_candidates: bool = False,
    blind_candidate_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = str(item.get("source") or "")
    zh = str(item.get("zh") or "")
    suggested_zh = str(item.get("suggested_zh") or "")
    reviewed = bool(item.get("reviewed")) if "reviewed" in item else bool(zh.strip())
    result = {
        "section": section,
        "index": index,
        "source": source,
        "zh": zh,
        "reviewed": reviewed,
        "suggested_zh": suggested_zh,
        "romanized": _romanize_source_text(source),
        "aliases": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
        "type": str(item.get("type") or ""),
        "note": str(item.get("note") or ""),
        "always": bool(item.get("always", False)),
    }
    context_text = _glossary_context_text(item, cue_texts or {})
    if context_text:
        result["context_text"] = context_text
    english_reference_text = _glossary_reference_text(item, english_reference_texts or {})
    if english_reference_text:
        result["english_reference_text"] = english_reference_text
    if include_blind_candidates and context_text and not suggested_zh.strip() and not reviewed:
        cache = blind_candidate_cache if blind_candidate_cache is not None else {}
        try:
            if context_text not in cache:
                cache[context_text] = _blind_translate_glossary_context(context_text)
            if cache[context_text]:
                result["blind_candidate_zh"] = cache[context_text]
        except Exception as exc:
            result["blind_candidate_error"] = str(exc)
    return result


_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3
_HANGUL_INITIALS = [
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s",
    "ss", "", "j", "jj", "ch", "k", "t", "p", "h",
]
_HANGUL_VOWELS = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa",
    "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
]
_HANGUL_FINALS = [
    "", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk",
    "lm", "lb", "ls", "lt", "lp", "lh", "m", "p", "ps", "t",
    "t", "ng", "t", "t", "k", "t", "p", "t",
]
_KANA_ROMAJI = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo",
}
_KANA_COMBOS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
}


def _romanize_source_text(text: str) -> str:
    parts: list[str] = []
    kana_text = _katakana_to_hiragana(text)
    index = 0
    while index < len(text):
        char = text[index]
        kana_char = kana_text[index]
        if index + 1 < len(text):
            combo = kana_char + kana_text[index + 1]
            if combo in _KANA_COMBOS:
                parts.append(_KANA_COMBOS[combo])
                index += 2
                continue
        code = ord(char)
        if _HANGUL_BASE <= code <= _HANGUL_END:
            offset = code - _HANGUL_BASE
            initial = offset // 588
            vowel = (offset % 588) // 28
            final = offset % 28
            parts.append(_HANGUL_INITIALS[initial] + _HANGUL_VOWELS[vowel] + _HANGUL_FINALS[final])
        elif kana_char in _KANA_ROMAJI:
            parts.append(_KANA_ROMAJI[kana_char])
        elif char == "ー" and parts:
            parts[-1] = parts[-1] + parts[-1][-1]
        elif char.isspace() or char in "-_/·・":
            parts.append(" ")
        index += 1
    return " ".join(" ".join(parts).split())


def _katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(char)
    return "".join(chars)


def list_local_assets() -> dict[str, Any]:
    return {
        "videos": _asset_entries(_iter_video_files(DOWNLOAD_DIR), kind="video"),
        "subtitles": _asset_entries(_iter_subtitle_files(), kind="subtitle"),
        "ocr_jobs": _ocr_job_entries(),
    }


def _iter_video_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        files.extend(path for path in directory.glob(pattern) if _is_real_file(path))
    return sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)


def _iter_subtitle_files() -> list[Path]:
    files: list[Path] = []
    for base in [DOWNLOAD_DIR, JOB_DIR]:
        for pattern in ["*.srt", "**/*.srt"]:
            files.extend(path for path in base.glob(pattern) if _is_real_file(path))
    return sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)


def _asset_entries(paths: list[Path], *, kind: str, limit: int = 80) -> list[dict[str, Any]]:
    return [_asset_entry(path, kind=kind) for path in paths[:limit]]


def _asset_entry(path: Path, *, kind: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "kind": kind,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "modified_at": stat.st_mtime,
        "modified_label": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        "role": _subtitle_role(path) if kind == "subtitle" else "video",
    }


def _ocr_job_entries(limit: int = 80) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if not JOB_DIR.exists():
        return jobs
    for job_dir in sorted([path for path in JOB_DIR.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True)[:limit]:
        entry = _asset_entry(job_dir / "run.yaml", kind="ocr_job") if (job_dir / "run.yaml").exists() else {
            "path": str(job_dir),
            "name": job_dir.name,
            "kind": "ocr_job",
            "size_bytes": 0,
            "size_mb": 0,
            "modified_at": job_dir.stat().st_mtime,
            "modified_label": time.strftime("%Y-%m-%d %H:%M", time.localtime(job_dir.stat().st_mtime)),
            "role": "ocr_job",
        }
        entry.update(
            {
                "job_id": job_dir.name,
                "source_srt": str(job_dir / "source.srt") if (job_dir / "source.srt").exists() else "",
                "translated_srt": str(job_dir / "zh.srt") if (job_dir / "zh.srt").exists() else "",
                "run_config": str(job_dir / "run.yaml") if (job_dir / "run.yaml").exists() else "",
            }
        )
        jobs.append(entry)
    return jobs


def _subtitle_role(path: Path) -> str:
    name = path.name.lower()
    if name == "source.srt" or name.endswith(".source.srt"):
        return "source"
    if name == "zh.srt" or ".zh" in name or "zh-hans" in name:
        return "translated"
    return "downloaded"


def _is_real_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith("._") and path.name != ".DS_Store"


def _run_command(job_id: str, args: list[str]) -> None:
    _append_log(job_id, "$ " + " ".join(_quote_arg(arg) for arg in args))
    env = _child_process_env()
    process = subprocess.Popen(
        args,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.current_process = process
            job.updated_at = time.time()
            if job.status == "cancel_requested":
                should_cancel = True
            else:
                should_cancel = False
        else:
            should_cancel = False
    if should_cancel:
        _terminate_process_tree(process)
    assert process.stdout is not None
    for line in process.stdout:
        _append_log(job_id, line.rstrip())
    code = process.wait()
    with _LOCK:
        job = _JOBS.get(job_id)
        cancelled = bool(job and job.status == "cancel_requested")
        if job and job.current_process is process:
            job.current_process = None
            job.updated_at = time.time()
    if cancelled:
        raise JobCancelled()
    if code != 0:
        raise RuntimeError(f"命令失败，退出码 {code}")


def _child_process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cache_root = Path(env.get("VIDEO_TRANSLATE_CACHE_DIR") or ROOT / "models").expanduser()
    if not cache_root.is_absolute():
        cache_root = ROOT / cache_root
    cache_root = cache_root.resolve()
    env["VIDEO_TRANSLATE_CACHE_DIR"] = str(cache_root)
    env.setdefault("HF_HOME", str(cache_root / "huggingface"))
    for proxy_name in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        env.pop(proxy_name, None)
    prepend_library_path(env, cuda_library_dirs())
    return env


def _snapshot_files(directory: Path, pattern: str) -> dict[Path, float]:
    directory.mkdir(parents=True, exist_ok=True)
    return {path: path.stat().st_mtime for path in directory.glob(pattern) if path.is_file()}


def _changed_files(directory: Path, pattern: str, before: dict[Path, float]) -> list[Path]:
    changed: list[Path] = []
    for path in directory.glob(pattern):
        if not path.is_file():
            continue
        mtime = path.stat().st_mtime
        if path not in before or mtime > before[path] + 0.001:
            changed.append(path)
    return sorted(changed, key=lambda p: p.stat().st_mtime, reverse=True)


def _newest_files(directory: Path, pattern: str, *, limit: int) -> list[Path]:
    files = [path for path in directory.glob(pattern) if path.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _snapshot_video_files(directory: Path) -> dict[Path, float]:
    result: dict[Path, float] = {}
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        result.update(_snapshot_files(directory, pattern))
    return result


def _changed_video_files(directory: Path, before: dict[Path, float]) -> list[Path]:
    changed: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        changed.extend(_changed_files(directory, pattern, before))
    return sorted(set(changed), key=lambda p: p.stat().st_mtime, reverse=True)


def _newest_video_files(directory: Path, *, limit: int) -> list[Path]:
    files: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        files.extend(_newest_files(directory, pattern, limit=20))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _matching_video_files(directory: Path, title: str) -> list[Path]:
    return _matching_media_files(directory, ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"], title)


def _matching_subtitle_files(directory: Path, title: str, lang: str) -> list[Path]:
    matches = _matching_media_files(directory, ["*.srt"], title)
    lang_key = str(lang or "").strip()
    if not lang_key:
        return matches
    exact_suffix = f".{lang_key}.srt"
    exact = [path for path in matches if path.name.endswith(exact_suffix)]
    if exact:
        return exact
    return [path for path in matches if f".{lang_key}" in path.name]


def _matching_media_files(directory: Path, patterns: list[str], title: str) -> list[Path]:
    title = str(title or "").strip()
    if not title:
        return []
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in directory.glob(pattern) if path.is_file() and not path.name.startswith("._"))
    if not candidates:
        return []

    def score(path: Path) -> tuple[int, float]:
        stem = path.stem
        if stem == title:
            rank = 0
        elif stem.startswith(title + "."):
            rank = 1
        elif stem.startswith(title):
            rank = 2
        elif title in stem:
            rank = 3
        else:
            rank = 99
        return (rank, -path.stat().st_mtime)

    matches = [path for path in candidates if score(path)[0] < 99]
    return sorted(matches, key=score)


def _required_str(payload: dict[str, Any], name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"缺少参数: {name}")
    return value


def _resolve_project_path(value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _ensure_under_root(path: Path) -> None:
    if not _is_relative_to(path, ROOT):
        raise ValueError(f"路径不在项目目录下: {path}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_slug(value: Any) -> str:
    raw = str(value or "task").strip().lower()
    raw = re.sub(r"\.[a-z0-9]{2,5}$", "", raw)
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff\uac00-\ud7a3]+", "_", raw).strip("_")
    return slug[:120] or "task"


def _guess_language_from_path(path: Path) -> str:
    name = path.name.lower()
    if ".en" in name:
        return "english"
    if ".ja" in name or ".jp" in name:
        return "japanese"
    if ".zh" in name or ".cn" in name:
        return "chinese"
    return "korean"


def _quote_arg(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", value):
        return value
    return repr(value)


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "VideoTranslateAgent/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/agent":
            self._send_json({"sessions": list_agent_sessions()})
            return
        if parsed.path.startswith("/api/agent/"):
            session_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            session = get_agent_session(session_id)
            if not session:
                self._send_json({"error": "agent session not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(session.to_dict())
            return
        if parsed.path == "/api/jobs":
            self._send_json({"jobs": list_jobs()})
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            job = get_job(job_id)
            if not job:
                self._send_json({"error": "job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job.to_dict())
            return
        if parsed.path == "/api/list-files":
            query = parse_qs(parsed.query)
            kind = (query.get("kind") or ["srt"])[0]
            self._send_json({"files": _list_known_files(kind)})
            return
        if parsed.path == "/api/assets":
            self._send_json(list_local_assets())
            return
        asset = _frontend_asset_path(parsed.path)
        if asset:
            self._send_file(asset)
            return
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            if self.path.startswith("/api/jobs/") and self.path.rstrip("/").endswith("/cancel"):
                job_id = self.path.rstrip("/").split("/")[-2]
                job = cancel_job(job_id)
                if not job:
                    self._send_json({"error": "job not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(job.to_dict())
                return
            payload = self._read_json()
            if self.path == "/api/agent/start":
                self._send_json(start_agent_session(payload).to_dict())
            elif self.path.startswith("/api/agent/") and self.path.rstrip("/").endswith("/answer"):
                session_id = self.path.rstrip("/").split("/")[-2]
                self._send_json(answer_agent_session(session_id, payload).to_dict())
            elif self.path.startswith("/api/agent/") and self.path.rstrip("/").endswith("/cancel"):
                session_id = self.path.rstrip("/").split("/")[-2]
                session = cancel_agent_session(session_id)
                if not session:
                    self._send_json({"error": "agent session not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(session.to_dict())
            elif self.path == "/api/probe":
                data = probe_video(
                    _required_str(payload, "url"),
                    proxy=str(payload.get("proxy") or DEFAULT_PROXY) or None,
                    target_language=str(payload.get("target_language") or "zh"),
                    detected_source_language=str(payload.get("detected_source_language") or ""),
                    embedded_subtitle_hint=str(payload.get("embedded_subtitle_hint") or "unknown"),
                )
                self._send_json(data)
            elif self.path == "/api/translate-title":
                self._send_json(translate_title_text(_required_str(payload, "title")))
            elif self.path == "/api/jobs/download-subtitle":
                self._send_json(download_subtitle_job(payload).to_dict())
            elif self.path == "/api/jobs/download-video":
                self._send_json(download_video_job(payload).to_dict())
            elif self.path == "/api/jobs/generate-glossary":
                self._send_json(generate_glossary_job(payload).to_dict())
            elif self.path == "/api/jobs/translate-subtitle":
                self._send_json(translate_subtitle_job(payload).to_dict())
            elif self.path == "/api/jobs/correct-asr-subtitle":
                self._send_json(correct_asr_subtitle_job(payload).to_dict())
            elif self.path == "/api/jobs/convert-subtitle":
                self._send_json(convert_subtitle_job(payload).to_dict())
            elif self.path == "/api/jobs/ocr-full":
                self._send_json(ocr_full_job(payload).to_dict())
            elif self.path == "/api/jobs/ocr-local":
                self._send_json(ocr_local_video_job(payload).to_dict())
            elif self.path == "/api/jobs/hybrid-anchor-ocr":
                self._send_json(hybrid_anchor_ocr_job(payload).to_dict())
            elif self.path == "/api/jobs/audio-local":
                self._send_json(audio_local_video_job(payload).to_dict())
            elif self.path == "/api/read-text":
                self._send_json(read_text_file(payload))
            elif self.path == "/api/write-text":
                self._send_json(write_text_file(payload))
            elif self.path == "/api/read-glossary-items":
                self._send_json(read_glossary_items(payload))
            elif self.path == "/api/write-glossary-items":
                self._send_json(write_glossary_items(payload))
            else:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _send_json(self, data: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _content_type_for_path(path))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _list_known_files(kind: str) -> list[str]:
    patterns = {
        "srt": ["YoutubeDownloads/*.srt", "outputs/**/*.srt"],
        "glossary": ["configs/glossaries/*.yaml", "configs/glossaries/*.yml", "configs/glossaries/*.json"],
    }.get(kind, ["YoutubeDownloads/*.srt"])
    files: list[Path] = []
    for pattern in patterns:
        files.extend(ROOT.glob(pattern))
    return [str(path) for path in sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:80]]


def _frontend_asset_path(request_path: str) -> Path | None:
    if not FRONTEND_DIST.exists():
        return None
    if request_path in {"", "/"}:
        candidate = FRONTEND_DIST / "index.html"
    else:
        relative = unquote(request_path).lstrip("/")
        if not relative or "\x00" in relative:
            return None
        candidate = FRONTEND_DIST / relative
    try:
        resolved = candidate.resolve()
        dist = FRONTEND_DIST.resolve()
        resolved.relative_to(dist)
    except (OSError, ValueError):
        return None
    if resolved.is_file():
        return resolved
    index = FRONTEND_DIST / "index.html"
    return index if index.is_file() and "." not in Path(request_path).name else None


def _content_type_for_path(path: Path) -> str:
    if path.suffix == ".js":
        return "text/javascript; charset=utf-8"
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("text/"):
        return f"{guessed}; charset=utf-8"
    return guessed or "application/octet-stream"

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Video Translate Agent</title></head>
<body>
  <h1>Video Translate Agent</h1>
  <p>前端还没有构建。请在项目根目录运行 <code>cd frontend && npm install && npm run build</code>。</p>
</body>
</html>
"""
