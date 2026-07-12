from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from difflib import SequenceMatcher
from email.parser import BytesParser
from email.policy import default as email_default_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import requests
import yaml
import yt_dlp

from video_translate.agent_planner import build_agent_plan
from video_translate.agent.models import AgentSession
from video_translate.cache import cuda_library_dirs, prepend_library_path
from video_translate.env import load_dotenv
from video_translate.llm_config import load_llm_task_config
from video_translate.languages import (
    asr_language_for_source,
    normalize_source_language,
    ocr_language_for_source,
    youtube_language_for_source,
)
from video_translate.models import SubtitleCue
from video_translate.jobs import Job, JobCancelled, JobService
from video_translate.projects import ProjectPathPolicy
from video_translate.project_manifest import (
    PROJECT_MANIFEST_NAME,
    infer_project_manifest,
    update_local_project_manifest,
    update_youtube_project_manifest,
    update_youtube_project_metadata,
)
from video_translate.subtitle.dual_reference import write_dual_reference_outputs
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.subtitle.sidecar import SidecarConfig, copy_sidecar_subtitles
from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _parse_json_content,
    _request_translation,
)
from video_translate.utils.timecode import format_srt_time, parse_srt_time
from video_translate.youtube.download_video import convert_thumbnail_bytes, thumbnail_extension, thumbnail_url_from_info
from video_translate.youtube.filenames import filesystem_safe_title
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
TASK_DIR = _rooted_dir("VIDEO_TRANSLATE_TASK_DIR", ROOT / "outputs" / "agent_tasks")
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
_DUAL_REFERENCE_TRANSLATION_PROMPT = """本次源字幕是 dual reference 格式：时间轴和主文本来自作者上传的原语言人工字幕，文本中可能同时包含“韩文原文”和“英文参考”。
必须优先依据“韩文原文”的韩文原文翻译，英文参考只用于理解上下文、补足省略、判断专名和语气。
如果韩文原文和英文参考冲突，必须以韩文原文为准。
输出时不要保留“韩文原文：”“英文参考：”这些标签。
"""


def _source_language_label(source_language: str) -> str:
    labels = {"korean": "韩文", "japanese": "日文", "english": "英文", "chinese": "中文", "auto": "原文"}
    return labels.get(normalize_source_language(source_language or "auto"), "原文")


def _hybrid_translation_prompt(source_language: str) -> str:
    label = _source_language_label(source_language)
    return _HYBRID_TRANSLATION_PROMPT.replace("韩文OCR", f"{label}OCR").replace("韩文原文", f"{label}原文")


def _dual_reference_translation_prompt(source_language: str) -> str:
    label = _source_language_label(source_language)
    return _DUAL_REFERENCE_TRANSLATION_PROMPT.replace("韩文原文", f"{label}原文")


def _module_command(module: str, *args: object) -> list[str]:
    return [PYTHON, "-m", module, *[str(arg) for arg in args]]


_JOBS: dict[str, Job] = {}
_AGENT_SESSIONS: dict[str, AgentSession] = {}
_LOCK = threading.Lock()


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"Video Translate Agent UI listening on {host}:{port}", flush=True)
    for url in _browse_urls(host, port):
        print(f"  {url}", flush=True)
    server.serve_forever()


def _browse_urls(host: str, port: int) -> list[str]:
    if host not in {"0.0.0.0", "::"}:
        return [f"http://{_format_url_host(host)}:{port}"]

    hosts = ["127.0.0.1", *_local_ipv4_addresses()]
    urls: list[str] = []
    for item in hosts:
        url = f"http://{item}:{port}"
        if url not in urls:
            urls.append(url)
    return urls


def _local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            address = info[4][0]
            if _is_browsable_ipv4(address):
                addresses.add(address)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
            if _is_browsable_ipv4(address):
                addresses.add(address)
    except OSError:
        pass

    return sorted(addresses, key=_ipv4_sort_key)


def _is_browsable_ipv4(address: str) -> bool:
    return bool(address and not address.startswith(("127.", "169.254.")) and address != "0.0.0.0")


def _ipv4_sort_key(address: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in address.split("."))
    except ValueError:
        return (999, 999, 999, 999)


def _format_url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


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
    planner_source_language = _planner_source_language(detected_source_language)
    agent_plan = build_agent_plan(
        subtitles,
        target_language=target_language,
        detected_source_language=planner_source_language,
        embedded_subtitle_hint=embedded_subtitle_hint,
    )
    title = str(info.get("title") or "")
    existing_project = _find_or_bind_youtube_project(normalized_url, title)
    thumbnail_path = _ensure_probe_thumbnail(normalized_url, title, info, proxy=proxy)
    if thumbnail_path:
        existing_project = _find_or_bind_youtube_project(normalized_url, title)
    return {
        "id": info.get("id"),
        "title": title,
        "duration": info.get("duration"),
        "webpage_url": normalized_url,
        "normalized_url": normalized_url,
        "subtitles": subtitles,
        "recommendation": recommendation,
        "agent_plan": agent_plan,
        "existing_project": existing_project,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else "",
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
    return _job_service().start(name, target)


def cancel_job(job_id: str) -> Job | None:
    return _job_service().cancel(job_id)


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
    return _job_service().get(job_id)


def list_jobs() -> list[dict[str, Any]]:
    return _job_service().list()


def start_agent_session(payload: dict[str, Any]) -> AgentSession:
    normalized_payload = dict(payload)
    normalized_payload["source_language"] = normalize_source_language(normalized_payload.get("source_language") or "auto")
    normalized_payload["ocr_language"] = normalize_source_language(normalized_payload.get("ocr_language") or "auto")
    session = AgentSession(id=uuid.uuid4().hex[:12], payload=normalized_payload)
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


def list_agent_tasks() -> list[dict[str, Any]]:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    _import_legacy_agent_jobs()
    tasks = [_task_to_dict(path) for path in TASK_DIR.glob("*/task.yaml")]
    tasks = [task for task in tasks if task]
    return sorted(tasks, key=lambda item: float(item.get("updated_at") or 0), reverse=True)


def get_agent_task(task_id: str) -> dict[str, Any] | None:
    path = _task_yaml_path(task_id)
    if not path.exists():
        return None
    return _task_to_dict(path)


def continue_agent_task(task_id: str) -> AgentSession:
    task = _read_task(task_id)
    session = _agent_session_from_task(task)
    stage = str(task.get("current_stage") or "")
    if stage in {"glossary_review", "translate_failed"} and _task_stage_path(task, "glossary", "glossary_path"):
        _run_agent_async(session.id, lambda item: _agent_translate_after_glossary(item, use_glossary=True))
    elif _task_stage_path(task, "ocr", "source_srt"):
        _run_agent_async(session.id, lambda item: _agent_generate_glossary_review(item, str(item.result.get("source_srt") or "")))
    else:
        _run_agent_async(session.id, _agent_start)
    return session


def continue_agent_after_glossary_review(glossary_path: str) -> AgentSession:
    path = _resolve_project_path(glossary_path)
    _ensure_under_root(path)
    waiting_session_id = _find_waiting_glossary_session(path)
    if waiting_session_id:
        return answer_agent_session(waiting_session_id, {"action": "continue_after_glossary"})
    task = _find_agent_task_by_glossary_path(path)
    if not task:
        raise KeyError("agent task not found for glossary")
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise KeyError("agent task not found for glossary")
    if _task_stage_path(task, "glossary", "glossary_path"):
        _invalidate_task_after(task_id, "translate")
        task = _read_task(task_id)
        session = _agent_session_from_task(task)
        _run_agent_async(session.id, lambda item: _agent_translate_after_glossary(item, use_glossary=True))
        return session
    return continue_agent_task(task_id)


def _find_waiting_glossary_session(glossary_path: Path) -> str:
    target = glossary_path.resolve()
    with _LOCK:
        sessions = sorted(_AGENT_SESSIONS.values(), key=lambda item: item.updated_at, reverse=True)
        for session in sessions:
            if session.status != "waiting" or session.phase != "review_glossary":
                continue
            for value in (
                session.result.get("glossary_path"),
                session.question.get("glossary_path") if isinstance(session.question, dict) else "",
            ):
                if _same_existing_path(value, target):
                    return session.id
    return ""


def _find_agent_task_by_glossary_path(glossary_path: Path) -> dict[str, Any] | None:
    target = glossary_path.resolve()
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    for task_yaml in sorted(TASK_DIR.glob("*/task.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        task = _task_to_dict(task_yaml)
        if not task:
            continue
        for stage in ("glossary", "translate"):
            value = _task_stage_value(task, stage, "glossary_path")
            if _same_existing_path(value, target):
                return task
    return None


def _same_existing_path(value: Any, target: Path) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        return Path(raw).expanduser().resolve() == target
    except OSError:
        return False


def rerun_agent_task_stage(task_id: str, stage: str) -> AgentSession:
    task = _read_task(task_id)
    stage = str(stage or "").strip()
    session = _agent_session_from_task(task)
    if stage == "ocr":
        _invalidate_task_after(task_id, "ocr")
        _run_agent_async(session.id, lambda item: _agent_run_ocr(item, force=True))
    elif stage == "glossary":
        source_srt = str(session.result.get("source_srt") or "")
        if not source_srt:
            raise RuntimeError("没有可用于重新生成 glossary 的 OCR 原文")
        _invalidate_task_after(task_id, "glossary")
        _run_agent_async(session.id, lambda item: _agent_generate_glossary_review(item, source_srt))
    elif stage == "translate":
        if not session.result.get("glossary_path"):
            raise RuntimeError("没有 glossary，不能重新翻译")
        _invalidate_task_after(task_id, "translate")
        _run_agent_async(session.id, lambda item: _agent_translate_after_glossary(item, use_glossary=True))
    else:
        raise ValueError(f"未知可重跑阶段: {stage}")
    return session


def delete_agent_task(task_id: str) -> dict[str, Any]:
    safe_task_id = Path(task_id).name
    task_dir = _task_yaml_path(safe_task_id).parent
    _ensure_task_dir(task_dir)
    if not task_dir.exists():
        raise KeyError("agent task not found")
    _mark_task_deleted(safe_task_id)
    shutil.rmtree(task_dir)
    with _LOCK:
        for session in _AGENT_SESSIONS.values():
            if str(session.result.get("task_id") or "") == safe_task_id:
                session.result["task_deleted"] = True
                session.updated_at = time.time()
    return {"deleted": True, "task_id": safe_task_id, "path": str(task_dir)}


def complete_agent_task(task_id: str) -> dict[str, Any]:
    data = _read_task(task_id)
    data["workflow_status"] = "completed"
    data["completed_at"] = time.time()
    _write_task_file(_task_yaml_path(task_id), data)
    return {"completed": True, "task_id": Path(str(task_id)).name, "workflow_status": "completed"}


def reopen_agent_task(task_id: str) -> dict[str, Any]:
    data = _read_task(task_id)
    data["workflow_status"] = "active"
    data.pop("completed_at", None)
    _write_task_file(_task_yaml_path(task_id), data)
    return {"reopened": True, "task_id": Path(str(task_id)).name, "workflow_status": "active"}


def delete_download_project(payload: dict[str, Any]) -> dict[str, Any]:
    project_dir = _resolve_project_path(_required_str(payload, "path"))
    _ensure_download_project_dir(project_dir)
    name = project_dir.name
    shutil.rmtree(project_dir)
    return {"deleted": True, "name": name, "path": str(project_dir)}


def register_local_project(payload: dict[str, Any]) -> dict[str, Any]:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists() or not input_video.is_file():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    title = str(payload.get("title") or input_video.stem).strip()
    manifest = update_local_project_manifest(input_video, download_dir=DOWNLOAD_DIR, title=title)
    project = _download_project_entry(Path(str(manifest["project_dir"])))
    return {"project": project, "manifest": manifest, "project_dir": manifest["project_dir"]}


VIDEO_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".ts", ".m2ts"}
COVER_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def save_uploaded_video_file(*, filename: str, content: bytes, title: str = "") -> dict[str, Any]:
    original_name = Path(str(filename or "uploaded_video.mp4")).name.strip()
    if not original_name or original_name in {".", ".."}:
        original_name = "uploaded_video.mp4"
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_UPLOAD_EXTENSIONS))
        raise ValueError(f"不支持的视频格式: {suffix or '<none>'}。支持: {allowed}")
    safe_name = filesystem_safe_title(Path(original_name).stem).strip() + suffix
    safe_title = filesystem_safe_title(str(title or Path(original_name).stem)).strip() or Path(safe_name).stem
    project_dir = (DOWNLOAD_DIR / safe_title).resolve()
    _ensure_under_root(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    input_video = (project_dir / safe_name).resolve()
    _ensure_under_root(input_video)
    input_video.write_bytes(content)
    manifest = update_local_project_manifest(input_video, download_dir=DOWNLOAD_DIR, title=safe_title)
    project = _download_project_entry(Path(str(manifest["project_dir"])))
    return {
        "input_video": str(input_video),
        "project_dir": manifest["project_dir"],
        "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
        "manifest": manifest,
        "project": project,
    }


def save_uploaded_project_cover(*, project_path: str, filename: str, content: bytes) -> dict[str, Any]:
    project_dir = _resolve_project_path(project_path)
    _ensure_download_project_dir(project_dir)
    original_name = Path(str(filename or "cover.jpg")).name.strip()
    if not original_name or original_name in {".", ".."}:
        original_name = "cover.jpg"
    suffix = Path(original_name).suffix.lower()
    if suffix not in COVER_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(COVER_UPLOAD_EXTENSIONS))
        raise ValueError(f"不支持的封面格式: {suffix or '<none>'}。支持: {allowed}")
    safe_name = filesystem_safe_title(Path(original_name).stem).strip() + suffix
    if not safe_name or safe_name == suffix:
        safe_name = "cover" + suffix
    cover_path = (project_dir / safe_name).resolve()
    _ensure_under_root(cover_path)
    cover_path.write_bytes(content)
    manifest = infer_project_manifest(project_dir)
    source_type = str(manifest.get("source_type") or "")
    title = str(manifest.get("title") or project_dir.name)
    if source_type == "youtube":
        manifest = update_youtube_project_metadata(
            project_dir,
            source_url=str(manifest.get("source_url") or ""),
            title=title,
            primary_video=Path(str(manifest["primary_video"])) if manifest.get("primary_video") else None,
            thumbnail_path=cover_path,
        )
    else:
        primary_video = Path(str(manifest.get("primary_video") or "")).expanduser()
        if not str(primary_video) or not primary_video.exists():
            videos = [path for path in project_dir.iterdir() if _is_real_file(path) and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
            primary_video = sorted(videos, key=lambda path: path.stat().st_mtime, reverse=True)[0] if videos else project_dir / "uploaded.mp4"
        manifest = update_local_project_manifest(primary_video, download_dir=DOWNLOAD_DIR, title=title)
        manifest["thumbnail"] = str(cover_path)
        from video_translate.project_manifest import save_project_manifest
        manifest = save_project_manifest(project_dir, manifest)
    project = _download_project_entry(project_dir)
    return {
        "thumbnail_path": str(cover_path),
        "project_dir": str(project_dir),
        "project_manifest": str(project_dir / PROJECT_MANIFEST_NAME),
        "manifest": manifest,
        "project": project,
    }


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


def retry_agent_session(session_id: str) -> AgentSession:
    session = get_agent_session(session_id)
    if not session:
        raise KeyError("agent session not found")
    with _LOCK:
        if session.status != "failed":
            raise RuntimeError("agent session is not failed")
        session.status = "running"
        session.error = ""
        session.question = {}
        session.logs.append(f"agent_retry: {session.phase}")
        session.updated_at = time.time()
    _run_agent_async(session_id, _agent_retry_current_phase)
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
    configured_source_language = _session_source_language(session)
    detected_source_language = str(payload.get("detected_source_language") or "")
    if configured_source_language != "auto" and not detected_source_language:
        detected_source_language = youtube_language_for_source(configured_source_language)
    probe = probe_video(
        url,
        target_language=str(payload.get("target_language") or "zh"),
        detected_source_language=detected_source_language,
        embedded_subtitle_hint=str(payload.get("embedded_subtitle_hint") or "unknown"),
    )
    _agent_update_result(session.id, {"probe": probe, "normalized_url": probe.get("normalized_url")})
    title = str(probe.get("title") or "")
    task = _ensure_agent_task(
        normalized_url=str(probe.get("normalized_url") or ""),
        title=title,
        payload=payload,
    )
    _agent_update_result(session.id, {"task_id": task["id"], "task_dir": task["task_dir"]})
    _update_task_stage(
        task["id"],
        "probe",
        "done",
        current_stage="probe_done",
        title=title,
        normalized_url=probe.get("normalized_url"),
        webpage_url=probe.get("webpage_url"),
        subtitles=probe.get("subtitles") or [],
        agent_plan=probe.get("agent_plan") or {},
    )
    if title and bool(payload.get("translate_title", False)):
        try:
            translated = translate_title_text(title)
            _agent_update_result(session.id, {"zh_title": translated.get("zh_title", "")})
            _update_task_fields(task["id"], {"zh_title": translated.get("zh_title", "")})
        except Exception as exc:
            _agent_log(session.id, f"title_translation_skipped: {exc}")
    plan = probe.get("agent_plan") or {}
    _agent_update_result(session.id, {"agent_plan": plan})
    _agent_handle_plan(session, plan)


def _agent_continue(session: AgentSession, answer: dict[str, Any]) -> None:
    _agent_update_ocr_settings_from_answer(session, answer)
    action = str(answer.get("action") or "")
    if action == "manual_mode":
        _agent_done(session.id, {"next_view": "new-task"})
        return
    if action == "use_cached_ocr":
        cached = session.result.get("reusable_ocr") if isinstance(session.result.get("reusable_ocr"), dict) else {}
        if not cached:
            raise RuntimeError("没有可复用 OCR 结果")
        _agent_use_cached_ocr(session, cached)
        return
    if action == "rerun_ocr":
        _agent_run_ocr(session, force=True)
        return
    if action == "run_ocr":
        _agent_run_ocr(session)
        return
    if action == "download_video_for_preview":
        _agent_download_video_for_preview(session)
        return
    if action == "run_asr":
        _agent_run_asr(session)
        return
    if action == "run_asr_with_ocr":
        _agent_run_asr_with_ocr_reference(session)
        return
    if action == "probe_audio_language":
        _agent_probe_audio_language(session)
        return
    if session.phase == "confirm_subtitle" and action == "use_recommended":
        plan = session.result.get("agent_plan") or {}
        if str(plan.get("route") or "") == "hybrid_anchor_ocr":
            _agent_prepare_hybrid_ocr_settings(session)
            return
        _agent_use_recommended_subtitle(session)
        return
    if session.phase == "confirm_hybrid_ocr_settings" and action == "start_hybrid_anchor_ocr":
        _agent_run_hybrid_anchor_ocr(session)
        return
    if session.phase == "review_glossary" and action in {"continue_after_glossary", "skip_glossary"}:
        _agent_translate_after_glossary(session, use_glossary=action != "skip_glossary")
        return
    raise RuntimeError(f"未知 Agent 回答: {action}")


def _session_source_language(session: AgentSession) -> str:
    configured = normalize_source_language(session.payload.get("source_language") or "auto")
    if configured != "auto":
        return configured
    for value in (
        session.result.get("detected_source_language"),
        session.payload.get("detected_source_language"),
    ):
        if not value:
            continue
        try:
            detected = normalize_source_language(value)
        except ValueError:
            detected = normalize_source_language(_planner_source_language(value))
        if detected != "auto":
            return detected
    return "auto"



def _session_ocr_language(session: AgentSession) -> str:
    configured = normalize_source_language(session.payload.get("ocr_language") or "auto")
    if configured != "auto":
        return configured
    return _session_source_language(session)


EMBEDDED_SUBTITLE_GOALS = {"screen_subtitle", "full_speech"}


def _normalize_embedded_subtitle_goal(value: Any) -> str:
    goal = str(value or "screen_subtitle").strip()
    if goal not in EMBEDDED_SUBTITLE_GOALS:
        raise ValueError(f"未知内嵌字幕目标: {goal}")
    return goal


def _session_embedded_subtitle_goal(session: AgentSession) -> str:
    return _normalize_embedded_subtitle_goal(session.payload.get("embedded_subtitle_goal"))


def _planner_source_language(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return youtube_language_for_source(raw)
    except ValueError:
        return raw.lower()


def _agent_update_ocr_settings_from_answer(session: AgentSession, answer: dict[str, Any]) -> None:
    updates: dict[str, Any] = {}
    if "ocr_scope" in answer:
        updates["ocr_scope"] = _normalize_ocr_scope(answer.get("ocr_scope"))
    if "ocr_extraction_mode" in answer:
        updates["ocr_extraction_mode"] = _normalize_ocr_extraction_mode(answer.get("ocr_extraction_mode"))
    scope = str(updates.get("ocr_scope") or session.payload.get("ocr_scope") or "bottom")
    if "ocr_crop_top_ratio" in answer:
        updates["ocr_crop_top_ratio"] = _normalize_ocr_crop_top_ratio(answer.get("ocr_crop_top_ratio"), scope)
    if "ocr_crop_bottom_ratio" in answer:
        updates["ocr_crop_bottom_ratio"] = _normalize_ocr_vertical_crop_ratio(answer.get("ocr_crop_bottom_ratio"))
    if "ocr_crop_left_ratio" in answer:
        updates["ocr_crop_left_ratio"] = _normalize_ocr_crop_ratio(answer.get("ocr_crop_left_ratio"))
    if "ocr_crop_right_ratio" in answer:
        updates["ocr_crop_right_ratio"] = _normalize_ocr_crop_ratio(answer.get("ocr_crop_right_ratio"))
    if "ocr_exclude_enabled" in answer:
        updates["ocr_exclude_enabled"] = bool(answer.get("ocr_exclude_enabled"))
    if "ocr_exclude_top_ratio" in answer:
        updates["ocr_exclude_top_ratio"] = _normalize_ocr_exclude_ratio(answer.get("ocr_exclude_top_ratio"))
    if "ocr_exclude_bottom_ratio" in answer:
        updates["ocr_exclude_bottom_ratio"] = _normalize_ocr_exclude_ratio(answer.get("ocr_exclude_bottom_ratio"))
    if "ocr_exclude_left_ratio" in answer:
        updates["ocr_exclude_left_ratio"] = _normalize_ocr_exclude_ratio(answer.get("ocr_exclude_left_ratio"))
    if "ocr_exclude_right_ratio" in answer:
        updates["ocr_exclude_right_ratio"] = _normalize_ocr_exclude_ratio(answer.get("ocr_exclude_right_ratio"))
    if "source_language" in answer:
        updates["source_language"] = normalize_source_language(answer.get("source_language") or "auto")
    if "ocr_language" in answer:
        updates["ocr_language"] = normalize_source_language(answer.get("ocr_language") or "auto")
    if "embedded_subtitle_goal" in answer:
        updates["embedded_subtitle_goal"] = _normalize_embedded_subtitle_goal(answer.get("embedded_subtitle_goal"))
    if not updates:
        return
    with _LOCK:
        current = _AGENT_SESSIONS.get(session.id)
        if current:
            current.payload.update(updates)
            current.updated_at = time.time()
            session.payload.update(updates)


def _agent_prepare_hybrid_ocr_settings(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    selected = plan.get("selected_subtitle") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")

    anchor_srt = str(result.get("anchor_srt") or "")
    if not anchor_srt or not Path(anchor_srt).exists():
        _agent_set_phase(session.id, "download_anchor_subtitle")
        subtitle_result = _wait_for_job(
            download_subtitle_job({"url": url, "lang": selected.get("lang"), "kind": selected.get("kind"), "title": probe.get("title") or ""}),
            session_id=session.id,
        )
        anchor_srt = str(subtitle_result.get("subtitle_path") or "")
        _agent_update_result(session.id, {"anchor_srt": anchor_srt, "download_subtitle": subtitle_result})

    input_video = str(result.get("input_video") or "")
    if not input_video or not Path(input_video).exists():
        _agent_set_phase(session.id, "download_video_for_hybrid")
        video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
        input_video = str(video_result.get("input_video") or "")
        _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})

    _agent_confirm_hybrid_ocr_settings(get_agent_session(session.id) or session)


def _agent_confirm_hybrid_ocr_settings(session: AgentSession) -> None:
    scope = _normalize_ocr_scope(session.payload.get("ocr_scope") or "bottom")
    _agent_wait(
        session.id,
        "confirm_hybrid_ocr_settings",
        {
            "kind": "confirm_hybrid_ocr_settings",
            "title": "确认原声 OCR 范围",
            "message": "英文人工字幕只负责时间轴。开始原声 OCR 前，请先用上方 OCR 模式、裁剪预设和抽帧预览确认绿色区域；调好后再点开始。",
            "ocr_settings": {
                "ocr_scope": scope,
                "ocr_crop_top_ratio": _normalize_ocr_crop_top_ratio(session.payload.get("ocr_crop_top_ratio"), scope),
                "ocr_crop_bottom_ratio": _normalize_ocr_vertical_crop_ratio(session.payload.get("ocr_crop_bottom_ratio")),
                "ocr_crop_left_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_left_ratio")),
                "ocr_crop_right_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_right_ratio")),
            },
            "options": [
                {"action": "start_hybrid_anchor_ocr", "label": "开始英文定轴 + 原声 OCR"},
                {"action": "manual_mode", "label": "转到手动模式"},
            ],
        },
    )


def _agent_retry_current_phase(session: AgentSession) -> None:
    phase = session.phase
    if phase in {"created", "probe"}:
        _agent_start(session)
        return
    if phase in {"confirm_subtitle", "download_subtitle"}:
        _agent_use_recommended_subtitle(session)
        return
    if phase in {"download_reference_subtitle", "dual_subtitle_reference"}:
        _agent_run_dual_subtitle_reference(session)
        return
    if phase == "confirm_hybrid_ocr_settings":
        _agent_confirm_hybrid_ocr_settings(session)
        return
    if phase in {"download_anchor_subtitle", "download_video_for_hybrid", "hybrid_anchor_ocr"}:
        _agent_run_hybrid_anchor_ocr(session)
        return
    if phase == "generate_glossary":
        source_srt = str(session.result.get("source_srt") or "")
        if not source_srt:
            _agent_use_recommended_subtitle(session)
            return
        _agent_generate_glossary_review(session, source_srt)
        return
    if phase == "translate":
        _agent_translate_after_glossary(session, use_glossary=bool(session.result.get("glossary_path")))
        return
    if phase == "ocr_full":
        _agent_run_ocr(session)
        return
    if phase in {"download_video_for_asr", "audio_asr"}:
        _agent_run_asr(session)
        return
    if phase in {"probe_audio_language", "download_video_for_audio_probe"}:
        _agent_probe_audio_language(session)
        return
    if phase == "diagnose_ocr_asr":
        plan = session.result.get("agent_plan") or {}
        _agent_continue_route_without_subtitle(session.id, plan)
        return
    raise RuntimeError(f"当前阶段不支持重试: {phase}")


def _agent_handle_plan(session: AgentSession, plan: dict[str, Any]) -> None:
    selected = plan.get("selected_subtitle") if isinstance(plan, dict) else None
    if selected:
        route = str(plan.get("route") or "")
        confidence = float(plan.get("confidence") or 0)
        if route in {"download_target_subtitle", "translate_source_subtitle", "dual_subtitle_reference"} and confidence >= 0.85:
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
                "candidate_subtitles": plan.get("candidate_subtitles") or [],
                "options": _agent_confirm_options(plan),
            },
        )
        return
    _agent_continue_route_without_subtitle(session.id, plan)


def _agent_use_recommended_subtitle(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    if str(plan.get("route") or "") == "dual_subtitle_reference":
        _agent_run_dual_subtitle_reference(session)
        return
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
    _agent_generate_glossary_review(session, source_srt)


def _agent_generate_glossary_review(session: AgentSession, source_srt: str) -> None:
    _agent_set_phase(session.id, "generate_glossary")
    is_hybrid = session.result.get("source_kind") == "hybrid_anchor_ocr"
    is_dual_reference = session.result.get("source_kind") == "dual_subtitle_reference"
    is_ocr = session.result.get("source_kind") == "ocr"
    is_asr = session.result.get("source_kind") in {"asr", "asr_ocr_reference"}
    glossary_job = generate_glossary_job(
        {
            "source_srt": source_srt,
            "extra_hint": str(session.payload.get("extra_hint") or ""),
            "source_language": _agent_source_language_for_glossary(session, is_hybrid or is_dual_reference or is_ocr or is_asr),
            "out": str(_agent_glossary_path(session)),
        }
    )
    glossary_result = _wait_for_job(glossary_job, session_id=session.id)
    glossary_path = str(glossary_result.get("glossary_path") or "")
    _agent_update_result(session.id, {"glossary_path": glossary_path, "generate_glossary": glossary_result})
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "glossary",
            "waiting_review",
            current_stage="glossary_review",
            glossary_path=glossary_path,
            source_srt=source_srt,
            job_result=glossary_result,
        )
    message = "Glossary 草稿已生成。审核人名、昵称和专有词后继续翻译。"
    if is_hybrid:
        message = "Hybrid 源字幕已生成：时间轴来自英文人工字幕，原文优先使用原声 OCR。审核 glossary 后继续翻译。"
    if is_dual_reference:
        message = "双字幕参考源已生成：原声人工字幕为主，英文人工字幕只作参考。审核 glossary 后继续翻译。"
    if is_ocr:
        message = "OCR 原文字幕已生成。请审核 glossary，尤其是人名、昵称和音译词，然后继续翻译。"
    if is_asr:
        message = "ASR 原文字幕已生成。请审核 glossary，尤其是人名、昵称和同音误识别词，然后继续翻译。"
    if session.result.get("source_kind") == "asr_ocr_reference":
        message = "完整听译源字幕已生成：ASR 时间轴为主，并参考内嵌字幕 OCR 做了原文纠错。请审核 glossary 后继续翻译。"
    _agent_wait(
        session.id,
        "review_glossary",
        {
            "kind": "review_glossary",
            "title": "请审核 Glossary",
            "message": message,
            "glossary_path": glossary_path,
            "options": [
                {"action": "continue_after_glossary", "label": "我已审核，继续翻译"},
                {"action": "skip_glossary", "label": "跳过 glossary 直接翻译"},
            ],
        },
    )


def _agent_source_language_for_glossary(session: AgentSession, prefer_source: bool) -> str:
    ocr_language = _session_ocr_language(session)
    if ocr_language != "auto":
        return ocr_language
    source_language = _session_source_language(session)
    if source_language != "auto":
        return source_language
    return "korean" if prefer_source else ""


def _agent_translate_after_glossary(session: AgentSession, *, use_glossary: bool) -> None:
    source_srt = str(session.result.get("source_srt") or "")
    glossary_path = str(session.result.get("glossary_path") or "") if use_glossary else ""
    extra_prompt = ""
    if session.result.get("source_kind") == "hybrid_anchor_ocr":
        extra_prompt = _hybrid_translation_prompt(_session_source_language(session))
    if session.result.get("source_kind") == "dual_subtitle_reference":
        extra_prompt = _dual_reference_translation_prompt(_session_source_language(session))
    if session.result.get("source_kind") == "asr_ocr_reference":
        extra_prompt = "源字幕来自完整听译路线：ASR 提供时间轴和主要台词，OCR 内嵌字幕只参与过原文纠错。翻译时不要额外增加画面说明或姓名牌内容。"
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
    if translated.get("translated_srt"):
        materialized = _materialize_task_artifact(session, str(translated.get("translated_srt")), "zh.srt")
        if materialized:
            translated["translated_srt"] = materialized
    translated.update(
        {name: str(path) for name, path in _copy_agent_translated_sidecar(session, source_srt, str(translated.get("translated_srt") or "")).items()}
    )
    done_result = {"translate_subtitle": translated, "translated_srt": translated.get("translated_srt")}
    for key in ("translated_sidecar", "source_sidecar"):
        if translated.get(key):
            done_result[key] = translated.get(key)
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "translate",
            "done",
            current_stage="done",
            translated_srt=translated.get("translated_srt"),
            translated_sidecar=translated.get("translated_sidecar"),
            glossary_path=glossary_path,
            source_srt=source_srt,
            job_result=translated,
        )
    _agent_done(session.id, done_result)


def _agent_continue_route_without_subtitle(session_id: str, plan: dict[str, Any]) -> None:
    route = str((plan or {}).get("route") or "")
    if route == "ocr":
        message = "Agent 判断这个视频更适合 OCR，但会先暂停。请确认是复用/重新 OCR，还是改用 ASR 或手动模式。"
    elif route == "asr":
        message = "Agent 判断这个视频更适合 ASR，但会先暂停。请确认使用 ASR，还是改用 OCR 或手动模式。"
    elif route == "probe_audio_language":
        message = "还不确定原视频音源语言。可以先检测音源，也可以直接选择 OCR 或 ASR。"
    else:
        message = "没有可用字幕且不确定是否有内嵌字幕。请先选择处理路线。"
    _agent_wait(
        session_id,
        "diagnose_ocr_asr",
        {
            "kind": "diagnose_ocr_asr",
            "title": "选择处理方式",
            "message": message,
            "candidate_subtitles": (plan or {}).get("candidate_subtitles") or [],
            "recommended_route": route,
            "options": _agent_ocr_asr_options(route, _session_embedded_subtitle_goal(_AGENT_SESSIONS.get(session_id)) if _AGENT_SESSIONS.get(session_id) else "screen_subtitle"),
        },
    )


def _agent_ocr_asr_options(route: str, embedded_goal: str = "screen_subtitle") -> list[dict[str, str]]:
    if route == "asr":
        return [
            {"action": "download_video_for_preview", "label": "下载视频并抽帧预览"},
            {"action": "run_asr", "label": "使用 ASR（推荐）"},
            {"action": "run_asr_with_ocr", "label": "ASR 主导 + OCR 参考纠错"},
            {"action": "run_ocr", "label": "改用 OCR 复刻画面字幕"},
            {"action": "probe_audio_language", "label": "先检测音源语言"},
            {"action": "manual_mode", "label": "转到手动模式"},
        ]
    if route == "probe_audio_language":
        return [
            {"action": "download_video_for_preview", "label": "下载视频并抽帧预览"},
            {"action": "probe_audio_language", "label": "先检测音源语言（推荐）"},
            {"action": "run_ocr", "label": "使用 OCR"},
            {"action": "run_asr", "label": "使用 ASR"},
            {"action": "manual_mode", "label": "转到手动模式"},
        ]
    ocr_option = {"action": "run_ocr", "label": "复刻画面字幕：OCR 主导（推荐）"}
    asr_ocr_option = {"action": "run_asr_with_ocr", "label": "完整听译字幕：ASR 主导 + OCR 参考"}
    ordered = [asr_ocr_option, ocr_option] if embedded_goal == "full_speech" else [ocr_option, asr_ocr_option]
    return [
        {"action": "download_video_for_preview", "label": "下载视频并抽帧预览"},
        *ordered,
        {"action": "run_asr", "label": "纯 ASR 听译"},
        {"action": "probe_audio_language", "label": "先检测音源语言"},
        {"action": "manual_mode", "label": "转到手动模式"},
    ]



def _agent_download_video_for_preview(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")
    input_video = str(result.get("input_video") or "")
    if not input_video:
        _agent_set_phase(session.id, "download_video_for_preview")
        video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
        input_video = str(video_result.get("input_video") or "")
        _agent_update_result(session.id, {"input_video": input_video, "download_video_for_preview": video_result})
    _agent_continue_route_without_subtitle(session.id, plan)

def _agent_probe_audio_language(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")
    input_video = str(result.get("input_video") or "")
    if not input_video:
        _agent_set_phase(session.id, "download_video_for_audio_probe")
        video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
        input_video = str(video_result.get("input_video") or "")
        _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})

    _agent_set_phase(session.id, "probe_audio_language")
    language_result = _wait_for_job(audio_language_probe_job({"input_video": input_video}), session_id=session.id)
    detected = str(language_result.get("language") or "")
    probability = float(language_result.get("language_probability") or 0)
    _agent_update_result(
        session.id,
        {
            "audio_language_probe": language_result,
            "detected_source_language": detected,
            "detected_source_language_confidence": probability,
        },
    )
    _agent_log(session.id, f"agent_tool_result: audio_language={detected or 'unknown'} confidence={probability:.2f}")
    plan = build_agent_plan(
        list(probe.get("subtitles") or []),
        target_language=str(session.payload.get("target_language") or "zh"),
        detected_source_language=detected,
        embedded_subtitle_hint=str(session.payload.get("embedded_subtitle_hint") or "unknown"),
    )
    _agent_update_result(session.id, {"agent_plan": plan})
    _agent_handle_plan(session, plan)


def _agent_run_ocr(session: AgentSession, *, force: bool = False) -> None:
    _agent_set_phase(session.id, "ocr_full")
    url = str(session.result.get("normalized_url") or session.payload.get("url") or "")
    title = str((session.result.get("probe") or {}).get("title") or "")
    translation_mode = str(session.payload.get("ocr_translation_mode") or "standard_cleanup")
    ocr_scope = _normalize_ocr_scope(session.payload.get("ocr_scope"))
    ocr_extraction_mode = _normalize_ocr_extraction_mode(session.payload.get("ocr_extraction_mode"))
    ocr_refinement_mode = _normalize_ocr_refinement_mode(session.payload.get("ocr_refinement_mode"))
    ocr_crop_top_ratio = _normalize_ocr_crop_top_ratio(session.payload.get("ocr_crop_top_ratio"), ocr_scope)
    ocr_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(session.payload.get("ocr_crop_bottom_ratio"))
    ocr_crop_left_ratio = _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_left_ratio"))
    ocr_crop_right_ratio = _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_right_ratio"))
    ocr_exclude_enabled = bool(session.payload.get("ocr_exclude_enabled", False))
    ocr_exclude_top_ratio = _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_top_ratio", 0.04))
    ocr_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_bottom_ratio", 0.82))
    ocr_exclude_left_ratio = _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_left_ratio", 0.76))
    ocr_exclude_right_ratio = _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_right_ratio", 0.02))
    source_language = _session_source_language(session)
    ocr_language = _session_ocr_language(session)
    cache_language = ocr_language if ocr_language != "auto" else source_language
    if not force:
        cached = _find_reusable_ocr_result(
            url=url,
            title=title,
            translation_mode=translation_mode,
            ocr_scope=ocr_scope,
            ocr_extraction_mode=ocr_extraction_mode,
            ocr_refinement_mode=ocr_refinement_mode,
            ocr_crop_top_ratio=ocr_crop_top_ratio,
            ocr_crop_bottom_ratio=ocr_crop_bottom_ratio,
            ocr_crop_left_ratio=ocr_crop_left_ratio,
            ocr_crop_right_ratio=ocr_crop_right_ratio,
            ocr_exclude_enabled=ocr_exclude_enabled,
            ocr_exclude_top_ratio=ocr_exclude_top_ratio,
            ocr_exclude_bottom_ratio=ocr_exclude_bottom_ratio,
            ocr_exclude_left_ratio=ocr_exclude_left_ratio,
            ocr_exclude_right_ratio=ocr_exclude_right_ratio,
            source_language=cache_language,
            exclude_session_id=session.id,
        )
        if cached:
            _agent_update_result(session.id, {"reusable_ocr": cached})
            _agent_wait(
                session.id,
                "confirm_ocr_reuse",
                {
                    "kind": "confirm_ocr_reuse",
                    "title": "检测到已有 OCR 原文",
                    "message": "这个视频之前已经成功生成过 OCR 原文字幕，可以直接从 glossary 继续，避免重新跑 OCR。",
                    "reusable_ocr": cached,
                    "options": [
                        {"action": "use_cached_ocr", "label": "复用 OCR，继续生成 glossary"},
                        {"action": "rerun_ocr", "label": "重新 OCR"},
                    ],
                },
            )
            return
    job = ocr_extract_job(
        {
            "url": url,
            "title": title,
            "extra_hint": str(session.payload.get("extra_hint") or ""),
            "translation_mode": translation_mode,
            "ocr_scope": ocr_scope,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_refinement_mode": ocr_refinement_mode,
            "ocr_crop_top_ratio": ocr_crop_top_ratio,
            "ocr_crop_bottom_ratio": ocr_crop_bottom_ratio,
            "ocr_crop_left_ratio": ocr_crop_left_ratio,
            "ocr_crop_right_ratio": ocr_crop_right_ratio,
            "ocr_exclude_enabled": ocr_exclude_enabled,
            "ocr_exclude_top_ratio": ocr_exclude_top_ratio,
            "ocr_exclude_bottom_ratio": ocr_exclude_bottom_ratio,
            "ocr_exclude_left_ratio": ocr_exclude_left_ratio,
            "ocr_exclude_right_ratio": ocr_exclude_right_ratio,
            "source_language": source_language,
            "ocr_language": ocr_language,
        }
    )
    result = _wait_for_job(job, session_id=session.id)
    source_srt = str(result.get("source_srt") or "")
    source_srt = _materialize_task_artifact(session, source_srt, "source.srt") or source_srt
    _agent_update_result(
        session.id,
        {
            "ocr": result,
            "source_srt": source_srt,
            "source_kind": "ocr",
            "input_video": result.get("input_video"),
        },
    )
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "ocr",
            "done",
            current_stage="ocr_done",
            source_srt=source_srt,
            input_video=result.get("input_video"),
            output_dir=result.get("output_dir"),
            ocr_scope=ocr_scope,
            ocr_extraction_mode=ocr_extraction_mode,
            ocr_refinement_mode=ocr_refinement_mode,
            ocr_crop_top_ratio=ocr_crop_top_ratio,
            ocr_crop_bottom_ratio=ocr_crop_bottom_ratio,
            ocr_crop_left_ratio=ocr_crop_left_ratio,
            ocr_crop_right_ratio=ocr_crop_right_ratio,
            ocr_exclude_enabled=ocr_exclude_enabled,
            ocr_exclude_top_ratio=ocr_exclude_top_ratio,
            ocr_exclude_bottom_ratio=ocr_exclude_bottom_ratio,
            ocr_exclude_left_ratio=ocr_exclude_left_ratio,
            ocr_exclude_right_ratio=ocr_exclude_right_ratio,
            source_language=source_language,
            ocr_language=ocr_language,
            job_result=result,
            reused=False,
        )
    if _agent_should_finish_ocr_without_translation(session):
        _agent_finish_ocr_without_translation(session, source_srt)
        return
    _agent_generate_glossary_review(session, source_srt)


def _agent_use_cached_ocr(session: AgentSession, cached: dict[str, Any]) -> None:
    source_srt = str(cached.get("source_srt") or "")
    if not source_srt or not Path(source_srt).exists():
        raise RuntimeError(f"可复用 OCR 原文不存在: {source_srt or '<empty>'}")
    source_srt = _materialize_task_artifact(session, source_srt, "source.srt") or source_srt
    _agent_log(session.id, f"agent_reuse_ocr: {source_srt}")
    _agent_update_result(
        session.id,
        {
            "ocr": cached,
            "source_srt": source_srt,
            "source_kind": "ocr",
            "input_video": cached.get("input_video"),
            "reused_ocr": True,
        },
    )
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "ocr",
            "done",
            current_stage="ocr_done",
            source_srt=source_srt,
            input_video=cached.get("input_video"),
            output_dir=cached.get("output_dir"),
            ocr_scope=cached.get("ocr_scope"),
            ocr_extraction_mode=cached.get("ocr_extraction_mode"),
            ocr_refinement_mode=cached.get("ocr_refinement_mode"),
            ocr_crop_top_ratio=cached.get("ocr_crop_top_ratio"),
            ocr_crop_bottom_ratio=cached.get("ocr_crop_bottom_ratio"),
            ocr_crop_left_ratio=cached.get("ocr_crop_left_ratio"),
            ocr_crop_right_ratio=cached.get("ocr_crop_right_ratio"),
            ocr_exclude_enabled=cached.get("ocr_exclude_enabled"),
            ocr_exclude_top_ratio=cached.get("ocr_exclude_top_ratio"),
            ocr_exclude_bottom_ratio=cached.get("ocr_exclude_bottom_ratio"),
            ocr_exclude_left_ratio=cached.get("ocr_exclude_left_ratio"),
            ocr_exclude_right_ratio=cached.get("ocr_exclude_right_ratio"),
            source_language=cached.get("source_language") or _session_source_language(session),
            job_result=cached,
            reused=True,
        )
    if _agent_should_finish_ocr_without_translation(session):
        _agent_finish_ocr_without_translation(session, source_srt)
        return
    _agent_generate_glossary_review(session, source_srt)



def _agent_should_finish_ocr_without_translation(session: AgentSession) -> bool:
    return _session_ocr_language(session) == "chinese"


def _agent_finish_ocr_without_translation(session: AgentSession, source_srt: str) -> None:
    zh_srt = _materialize_task_artifact(session, source_srt, "zh.srt") or source_srt
    copied = _copy_agent_translated_sidecar(session, source_srt, zh_srt)
    done_result: dict[str, Any] = {
        "translated_srt": zh_srt,
        "subtitle_path": zh_srt,
        "message": "中文内嵌字幕已 OCR 提取完成，未进入 glossary/翻译。",
    }
    for key in ("translated_sidecar", "source_sidecar"):
        if copied.get(key):
            done_result[key] = str(copied[key])
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "translate",
            "done",
            current_stage="done",
            translated_srt=zh_srt,
            translated_sidecar=done_result.get("translated_sidecar"),
            source_srt=source_srt,
            job_result={"mode": "ocr_extract_only", **done_result},
        )
    _agent_done(session.id, done_result)


def _agent_run_hybrid_anchor_ocr(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    selected = plan.get("selected_subtitle") or {}
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")

    anchor_srt = str(result.get("anchor_srt") or "")
    input_video = str(result.get("input_video") or "")
    if not anchor_srt or not Path(anchor_srt).exists() or not input_video or not Path(input_video).exists():
        _agent_prepare_hybrid_ocr_settings(session)
        return

    _agent_set_phase(session.id, "hybrid_anchor_ocr")
    hybrid_result = _wait_for_job(
        hybrid_anchor_ocr_job(
            {
                "input_video": input_video,
                "anchor_srt": anchor_srt,
                "title": probe.get("title") or "",
                "ocr_scope": str(session.payload.get("ocr_scope") or "bottom"),
                "ocr_crop_top_ratio": _normalize_ocr_crop_top_ratio(session.payload.get("ocr_crop_top_ratio"), str(session.payload.get("ocr_scope") or "bottom")),
                "ocr_crop_bottom_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_bottom_ratio")),
                "ocr_crop_left_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_left_ratio")),
                "ocr_crop_right_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_right_ratio")),
                "source_language": _session_source_language(session),
                "ocr_language": _session_ocr_language(session),
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

    _agent_generate_glossary_review(session, source_srt)


def _agent_run_dual_subtitle_reference(session: AgentSession) -> None:
    result = session.result
    probe = result.get("probe") or {}
    plan = result.get("agent_plan") or {}
    selected = plan.get("selected_subtitle") or {}
    reference = plan.get("reference_subtitle") or {}
    if not reference:
        _agent_use_recommended_subtitle(session)
        return
    url = str(probe.get("normalized_url") or result.get("normalized_url") or session.payload.get("url") or "")

    _agent_set_phase(session.id, "download_subtitle")
    source_result = _wait_for_job(
        download_subtitle_job({"url": url, "lang": selected.get("lang"), "kind": selected.get("kind"), "title": probe.get("title") or ""}),
        session_id=session.id,
    )
    source_srt = str(source_result.get("subtitle_path") or "")
    _agent_update_result(session.id, {"primary_subtitle_srt": source_srt, "download_subtitle": source_result})

    _agent_set_phase(session.id, "download_reference_subtitle")
    reference_result = _wait_for_job(
        download_subtitle_job({"url": url, "lang": reference.get("lang"), "kind": reference.get("kind"), "title": probe.get("title") or ""}),
        session_id=session.id,
    )
    reference_srt = str(reference_result.get("subtitle_path") or "")
    _agent_update_result(session.id, {"reference_subtitle_srt": reference_srt, "download_reference_subtitle": reference_result})

    _agent_set_phase(session.id, "dual_subtitle_reference")
    dual_result = _wait_for_job(
        dual_subtitle_reference_job(
            {
                "source_srt": source_srt,
                "reference_srt": reference_srt,
                "title": probe.get("title") or "",
                "source_language": _session_source_language(session),
            }
        ),
        session_id=session.id,
    )
    dual_source = str(dual_result.get("source_srt") or "")
    _agent_update_result(
        session.id,
        {
            "source_srt": dual_source,
            "source_kind": "dual_subtitle_reference",
            "dual_subtitle_reference": dual_result,
        },
    )
    _agent_generate_glossary_review(session, dual_source)


def _agent_run_asr(session: AgentSession) -> None:
    _agent_set_phase(session.id, "download_video_for_asr")
    url = str(session.result.get("normalized_url") or session.payload.get("url") or "")
    probe = session.result.get("probe") or {}
    video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
    input_video = str(video_result.get("input_video") or "")
    _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})
    _agent_set_phase(session.id, "audio_asr")
    asr_result = _wait_for_job(
        audio_local_video_job({"input_video": input_video, "source_language": _session_source_language(session), "language": asr_language_for_source(_session_source_language(session)), "model_size": "large-v3"}),
        session_id=session.id,
    )
    source_srt = str(asr_result.get("source_srt") or "")
    source_srt = _materialize_task_artifact(session, source_srt, "source.srt") or source_srt
    _agent_update_result(
        session.id,
        {
            "asr": asr_result,
            "source_srt": source_srt,
            "source_kind": "asr",
            "input_video": input_video,
        },
    )
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "asr",
            "done",
            current_stage="asr_done",
            source_srt=source_srt,
            input_video=input_video,
            output_dir=asr_result.get("output_dir"),
            job_result=asr_result,
        )
    _agent_generate_glossary_review(session, source_srt)


def _agent_run_asr_with_ocr_reference(session: AgentSession) -> None:
    _agent_set_phase(session.id, "download_video_for_asr")
    url = str(session.result.get("normalized_url") or session.payload.get("url") or "")
    probe = session.result.get("probe") or {}
    input_video = str(session.result.get("input_video") or "")
    if not input_video or not Path(input_video).exists():
        video_result = _wait_for_job(download_video_job({"url": url, "title": probe.get("title") or ""}), session_id=session.id)
        input_video = str(video_result.get("input_video") or "")
        _agent_update_result(session.id, {"input_video": input_video, "download_video": video_result})

    _agent_set_phase(session.id, "audio_asr")
    asr_result = _wait_for_job(
        audio_local_video_job({"input_video": input_video, "source_language": _session_source_language(session), "language": asr_language_for_source(_session_source_language(session)), "model_size": "large-v3"}),
        session_id=session.id,
    )
    asr_srt = str(asr_result.get("source_srt") or "")

    _agent_set_phase(session.id, "ocr_reference")
    ocr_result = _wait_for_job(
        ocr_local_video_job(
            {
                "input_video": input_video,
                "extra_hint": str(session.payload.get("extra_hint") or ""),
                "translation_mode": "translate_only",
                "ocr_scope": _normalize_ocr_scope(session.payload.get("ocr_scope")),
                "ocr_extraction_mode": _normalize_ocr_extraction_mode(session.payload.get("ocr_extraction_mode")),
                "ocr_refinement_mode": _normalize_ocr_refinement_mode(session.payload.get("ocr_refinement_mode")),
                "ocr_crop_top_ratio": _normalize_ocr_crop_top_ratio(session.payload.get("ocr_crop_top_ratio"), _normalize_ocr_scope(session.payload.get("ocr_scope"))),
                "ocr_crop_bottom_ratio": _normalize_ocr_vertical_crop_ratio(session.payload.get("ocr_crop_bottom_ratio")),
                "ocr_crop_left_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_left_ratio")),
                "ocr_crop_right_ratio": _normalize_ocr_crop_ratio(session.payload.get("ocr_crop_right_ratio")),
                "ocr_exclude_enabled": bool(session.payload.get("ocr_exclude_enabled", False)),
                "ocr_exclude_top_ratio": _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_top_ratio", 0.04)),
                "ocr_exclude_bottom_ratio": _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_bottom_ratio", 0.82)),
                "ocr_exclude_left_ratio": _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_left_ratio", 0.76)),
                "ocr_exclude_right_ratio": _normalize_ocr_exclude_ratio(session.payload.get("ocr_exclude_right_ratio", 0.02)),
                "source_language": _session_source_language(session),
                "ocr_language": _session_ocr_language(session),
                "extract_only": True,
            }
        ),
        session_id=session.id,
    )
    ocr_srt = str(ocr_result.get("source_srt") or "")

    _agent_set_phase(session.id, "asr_ocr_refine")
    corrected_out = _agent_workspace(session) / "source.corrected.srt"
    corrected_result = _wait_for_job(
        correct_asr_subtitle_job(
            {
                "source_srt": asr_srt,
                "reference_srt": ocr_srt,
                "out": str(corrected_out),
                "source_language": _session_source_language(session),
                "extra_hint": (
                    "本任务是完整听译字幕：ASR 时间轴和完整台词为主，OCR 内嵌字幕只作为同时间段人名、术语、短语纠错参考。"
                    + ("\n" + str(session.payload.get("extra_hint") or "") if str(session.payload.get("extra_hint") or "").strip() else "")
                ),
            }
        ),
        session_id=session.id,
    )
    source_srt = str(corrected_result.get("source_srt") or corrected_out)
    source_srt = _materialize_task_artifact(session, source_srt, "source.srt") or source_srt
    reference_srt = _materialize_task_artifact(session, ocr_srt, "source.ocr_reference.srt") or ocr_srt
    _agent_update_result(
        session.id,
        {
            "asr": asr_result,
            "ocr_reference": ocr_result,
            "asr_ocr_correction": corrected_result,
            "source_srt": source_srt,
            "reference_srt": reference_srt,
            "source_kind": "asr_ocr_reference",
            "input_video": input_video,
        },
    )
    task_id = str(session.result.get("task_id") or "")
    if task_id:
        _update_task_stage(
            task_id,
            "asr",
            "done",
            current_stage="asr_ocr_done",
            source_srt=source_srt,
            reference_srt=reference_srt,
            input_video=input_video,
            output_dir=asr_result.get("output_dir"),
            job_result={"asr": asr_result, "ocr_reference": ocr_result, "correction": corrected_result},
        )
    _agent_generate_glossary_review(session, source_srt)


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
        return "检测到英文人工字幕，且你确认画面有内嵌字幕。建议使用英文人工字幕定轴，再用原声 OCR 补足原文精度。"
    if route == "dual_subtitle_reference":
        return "检测到原声人工字幕和英文人工字幕。建议以原声字幕为主，英文字幕只作为 glossary 和翻译参考。"
    if route == "translate_auto_subtitle":
        return "检测到原声自动字幕，建议下载后先纠错再翻译。"
    if route == "probe_audio_language":
        return "检测到作者上传字幕，但还不知道原视频音源语言。建议先用音频样本检测原声语言，再选择字幕源。"
    return "检测到原声作者字幕，建议下载后生成 glossary 并翻译。"


def _agent_confirm_options(plan: dict[str, Any]) -> list[dict[str, str]]:
    route = str(plan.get("route") or "")
    if route == "hybrid_anchor_ocr":
        return [
            {"action": "use_recommended", "label": "英文定轴 + 原声 OCR（推荐，较慢但更准）"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "整片 OCR（慢）"},
            {"action": "run_asr", "label": "音频 ASR"},
        ]
    if route == "dual_subtitle_reference":
        return [
            {"action": "use_recommended", "label": "原声主字幕 + 英文参考（推荐）"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "改用 OCR"},
            {"action": "run_asr", "label": "改用 ASR"},
        ]
    if route == "translate_fallback_subtitle":
        return [
            {"action": "use_recommended", "label": "使用中转字幕翻译（快）"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "改用整片 OCR（慢）"},
            {"action": "run_asr", "label": "改用 ASR"},
        ]
    if route == "probe_audio_language":
        return [
            {"action": "probe_audio_language", "label": "先检测音源语言"},
            {"action": "manual_mode", "label": "转到手动模式"},
            {"action": "run_ocr", "label": "改用 OCR"},
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
    task_dir = str(session.result.get("task_dir") or "")
    if task_dir:
        path = Path(task_dir).expanduser().resolve()
        _ensure_under_root(path)
        path.mkdir(parents=True, exist_ok=True)
        return path / "glossary.draft.yaml"
    return _agent_workspace(session) / "glossary.draft.yaml"


def _ensure_agent_task(*, normalized_url: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    normalized = normalize_youtube_url(normalized_url)
    video_key = _youtube_task_key(normalized)
    existing = _find_task_dir(video_key)
    task_dir = existing or (TASK_DIR / f"{video_key}_{_safe_slug(title)[:64]}").resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / "task.yaml"
    now = time.time()
    data = _read_task_file(path) if path.exists() else {}
    data.update(
        {
            "id": task_dir.name,
            "video_key": video_key,
            "url": normalized,
            "title": title or data.get("title") or "",
            "task_dir": str(task_dir),
            "payload": {**(data.get("payload") if isinstance(data.get("payload"), dict) else {}), **dict(payload)},
            "created_at": data.get("created_at") or now,
            "updated_at": now,
        }
    )
    data.setdefault("current_stage", "created")
    data.setdefault("stages", {})
    _write_task_file(path, data)
    return data


def _import_legacy_agent_jobs() -> None:
    if not JOB_DIR.exists():
        return
    deleted_task_ids = _deleted_task_ids()
    existing_glossaries = {
        str(_task_stage_value(_read_task_file(path), "glossary", "glossary_path") or "")
        for path in TASK_DIR.glob("*/task.yaml")
    }
    for glossary in sorted(JOB_DIR.glob("*/glossary.draft.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        legacy_task_id = f"legacy_{glossary.parent.name}"
        if legacy_task_id in deleted_task_ids:
            continue
        if str(glossary) in existing_glossaries:
            continue
        text_head = "\n".join(glossary.read_text(encoding="utf-8", errors="ignore").splitlines()[:8])
        match = re.search(r"^#\s*source_srt:\s*(.+)$", text_head, re.MULTILINE)
        source_srt = Path(match.group(1).strip()).expanduser().resolve() if match else None
        if not source_srt or not source_srt.exists():
            continue
        source_run = source_srt.parent / "run.yaml"
        input_video = ""
        title = source_srt.parent.name
        if source_run.exists():
            try:
                run_config = yaml.safe_load(source_run.read_text(encoding="utf-8")) or {}
            except Exception:
                run_config = {}
            if isinstance(run_config, dict):
                input_video = str(run_config.get("input_video") or "")
                if input_video:
                    title = Path(input_video).stem
        task_dir = TASK_DIR / legacy_task_id
        if (task_dir / "task.yaml").exists():
            continue
        now = time.time()
        data = {
            "id": task_dir.name,
            "video_key": task_dir.name,
            "url": "",
            "title": title,
            "task_dir": str(task_dir),
            "payload": {},
            "current_stage": "glossary_review",
            "created_at": min(source_srt.stat().st_mtime, glossary.stat().st_mtime),
            "updated_at": now,
            "stages": {
                "ocr": {
                    "status": "done",
                    "source_srt": str(source_srt),
                    "input_video": input_video,
                    "can_rerun": False,
                    "updated_at": source_srt.stat().st_mtime,
                },
                "glossary": {
                    "status": "waiting_review",
                    "source_srt": str(source_srt),
                    "glossary_path": str(glossary),
                    "updated_at": glossary.stat().st_mtime,
                },
            },
        }
        _write_task_file(task_dir / "task.yaml", data)


def _agent_session_from_task(task: dict[str, Any]) -> AgentSession:
    payload = dict(task.get("payload") if isinstance(task.get("payload"), dict) else {})
    payload["url"] = task.get("url") or payload.get("url") or ""
    session = AgentSession(id=uuid.uuid4().hex[:12], payload=payload)
    result = {
        "task_id": task.get("id"),
        "task_dir": task.get("task_dir"),
        "normalized_url": task.get("url"),
        "probe": {
            "title": task.get("title") or "",
            "normalized_url": task.get("url") or "",
            "webpage_url": task.get("url") or "",
            "subtitles": _task_stage_value(task, "probe", "subtitles") or [],
        },
        "agent_plan": _task_stage_value(task, "probe", "agent_plan") or {},
    }
    source_srt = _task_stage_path(task, "ocr", "source_srt") or _task_stage_path(task, "glossary", "source_srt")
    input_video = _task_stage_path(task, "ocr", "input_video")
    glossary_path = _task_stage_path(task, "glossary", "glossary_path")
    translated_srt = _task_stage_path(task, "translate", "translated_srt")
    translated_sidecar = _task_stage_path(task, "translate", "translated_sidecar")
    if source_srt:
        result.update({"source_srt": source_srt, "source_kind": "ocr"})
    if input_video:
        result["input_video"] = input_video
    if glossary_path:
        result["glossary_path"] = glossary_path
    if translated_srt:
        result["translated_srt"] = translated_srt
    if translated_sidecar:
        result["translated_sidecar"] = translated_sidecar
    with _LOCK:
        session.result.update(result)
        _AGENT_SESSIONS[session.id] = session
    return session


def _read_task(task_id: str) -> dict[str, Any]:
    path = _task_yaml_path(task_id)
    if not path.exists():
        raise KeyError("agent task not found")
    return _read_task_file(path)


def _task_yaml_path(task_id: str) -> Path:
    safe = Path(str(task_id)).name
    return (TASK_DIR / safe / "task.yaml").resolve()


def _deleted_tasks_path() -> Path:
    return (TASK_DIR / ".deleted_task_ids.yaml").resolve()


def _deleted_task_ids() -> set[str]:
    path = _deleted_tasks_path()
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except Exception:
        return set()
    if isinstance(data, list):
        return {str(item) for item in data if str(item).strip()}
    return set()


def _mark_task_deleted(task_id: str) -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    deleted = _deleted_task_ids()
    deleted.add(Path(str(task_id)).name)
    _deleted_tasks_path().write_text(yaml.safe_dump(sorted(deleted), allow_unicode=True), encoding="utf-8")


def _ensure_task_dir(path: Path) -> None:
    resolved = path.resolve()
    if not _is_relative_to(resolved, TASK_DIR) or resolved == TASK_DIR.resolve() or resolved.parent != TASK_DIR.resolve():
        raise ValueError(f"任务目录不在允许范围内: {path}")


def _ensure_download_project_dir(path: Path) -> None:
    resolved = path.resolve()
    download_root = DOWNLOAD_DIR.resolve()
    if resolved == download_root or resolved.parent != download_root or not _is_relative_to(resolved, download_root):
        raise ValueError(f"只能删除下载目录下的单个视频项目文件夹: {path}")
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"视频项目目录不存在: {path}")
    if resolved.is_symlink():
        raise ValueError(f"不允许删除软链接目录: {path}")


def _task_to_dict(path: Path) -> dict[str, Any]:
    data = _read_task_file(path)
    data["id"] = data.get("id") or path.parent.name
    data["task_dir"] = data.get("task_dir") or str(path.parent)
    workflow_status = str(data.get("workflow_status") or "").strip()
    if not workflow_status:
        workflow_status = "completed" if str(data.get("current_stage") or "") == "done" else "active"
    data["workflow_status"] = workflow_status
    data["is_completed"] = workflow_status == "completed"
    data["stage_items"] = _task_stage_items(data)
    return data


def _read_task_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_task_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _update_task_fields(task_id: str, values: dict[str, Any]) -> None:
    if not task_id:
        return
    path = _task_yaml_path(task_id)
    if not path.exists():
        return
    data = _read_task_file(path)
    data.update(values)
    _write_task_file(path, data)


def _update_task_stage(task_id: str, stage: str, status: str, *, current_stage: str | None = None, **values: Any) -> None:
    if not task_id:
        return
    path = _task_yaml_path(task_id)
    if not path.exists():
        return
    data = _read_task_file(path)
    stages = data.setdefault("stages", {})
    if not isinstance(stages, dict):
        stages = {}
        data["stages"] = stages
    item = stages.setdefault(stage, {})
    if not isinstance(item, dict):
        item = {}
        stages[stage] = item
    item.update({key: _task_serializable(value) for key, value in values.items() if value is not None and value != ""})
    item["status"] = status
    item["updated_at"] = time.time()
    if current_stage:
        data["current_stage"] = current_stage
        if current_stage == "done":
            data["workflow_status"] = "completed"
            data.setdefault("completed_at", time.time())
        elif data.get("workflow_status") == "completed":
            data["workflow_status"] = "active"
            data.pop("completed_at", None)
    _write_task_file(path, data)


def _invalidate_task_after(task_id: str, stage: str) -> None:
    order = ["ocr", "glossary", "translate"]
    if stage not in order:
        return
    path = _task_yaml_path(task_id)
    if not path.exists():
        return
    data = _read_task_file(path)
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    for name in order[order.index(stage):]:
        item = stages.get(name)
        if isinstance(item, dict):
            item["status"] = "invalidated" if name != stage else "rerunning"
            item["updated_at"] = time.time()
    data["current_stage"] = f"{stage}_rerun"
    data["workflow_status"] = "active"
    data.pop("completed_at", None)
    _write_task_file(path, data)


def _materialize_task_artifact(session: AgentSession, source: str, filename: str) -> str:
    task_dir = str(session.result.get("task_dir") or "")
    if not task_dir or not source:
        return ""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return ""
    dst_dir = Path(task_dir).expanduser().resolve()
    _ensure_under_root(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / filename
    if src != dst:
        shutil.copy2(src, dst)
    return str(dst)


def _copy_agent_translated_sidecar(session: AgentSession, source_srt: str, translated_srt: str) -> dict[str, Path]:
    translated = Path(str(translated_srt or "")).expanduser()
    if not translated.exists():
        return {}
    input_video = _agent_input_video_path(session)
    if not input_video:
        return {}
    source = Path(str(source_srt or "")).expanduser()
    copied = copy_sidecar_subtitles(
        input_video,
        source_srt=source if source.exists() else None,
        translated_srt=translated,
        config=SidecarConfig(enabled=True, copy_source=False, copy_translated=True, source_suffix=".source", translated_suffix=".zh"),
    )
    return copied


def _agent_input_video_path(session: AgentSession) -> Path | None:
    raw = str(session.result.get("input_video") or "").strip()
    if raw:
        path = Path(raw).expanduser().resolve()
        if path.exists():
            return path
    task_id = str(session.result.get("task_id") or "").strip()
    if not task_id:
        return None
    try:
        task = _read_task(task_id)
    except Exception:
        return None
    for stage in ("ocr", "glossary", "translate"):
        raw = str(_task_stage_value(task, stage, "input_video") or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.exists():
            return path
    return None


def _task_stage_value(task: dict[str, Any], stage: str, key: str) -> Any:
    stages = task.get("stages") if isinstance(task.get("stages"), dict) else {}
    item = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    return item.get(key)


def _task_stage_path(task: dict[str, Any], stage: str, key: str) -> str:
    value = str(_task_stage_value(task, stage, key) or "").strip()
    return value if value and Path(value).exists() else ""


def _task_stage_items(task: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {"probe": "检测", "ocr": "OCR 原文", "glossary": "Glossary", "translate": "翻译"}
    stages = task.get("stages") if isinstance(task.get("stages"), dict) else {}
    return [{"id": key, "label": label, **(stages.get(key) if isinstance(stages.get(key), dict) else {"status": "pending"})} for key, label in labels.items()]


def _task_serializable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _task_serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_task_serializable(item) for item in value]
    return value


def _youtube_task_key(normalized_url: str) -> str:
    parsed = urlparse(normalized_url)
    video_id = ""
    if parsed.netloc.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    return _safe_slug(video_id or normalized_url)[:80]


def _find_task_dir(video_key: str) -> Path | None:
    exact = TASK_DIR / video_key
    if exact.exists():
        return exact
    matches = sorted(TASK_DIR.glob(f"{video_key}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _find_reusable_ocr_result(
    *,
    url: str,
    title: str,
    translation_mode: str,
    ocr_scope: str = "bottom",
    ocr_extraction_mode: str = "auto",
    ocr_refinement_mode: str = "none",
    ocr_crop_top_ratio: float | None = None,
    ocr_crop_bottom_ratio: float = 0.0,
    ocr_crop_left_ratio: float = 0.0,
    ocr_crop_right_ratio: float = 0.0,
    ocr_exclude_enabled: bool = False,
    ocr_exclude_top_ratio: float = 0.04,
    ocr_exclude_bottom_ratio: float = 0.82,
    ocr_exclude_left_ratio: float = 0.76,
    ocr_exclude_right_ratio: float = 0.02,
    source_language: str = "auto",
    exclude_session_id: str = "",
) -> dict[str, Any] | None:
    normalized_url = normalize_youtube_url(url) if str(url or "").strip() else ""
    title_key = _filename_match_key(title)
    mode = _normalize_ocr_translation_mode(translation_mode)
    scope = _normalize_ocr_scope(ocr_scope)
    extraction_mode = _normalize_ocr_extraction_mode(ocr_extraction_mode)
    refinement_mode = _normalize_ocr_refinement_mode(ocr_refinement_mode)
    crop_top_ratio = _normalize_ocr_crop_top_ratio(ocr_crop_top_ratio, scope)
    crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(ocr_crop_bottom_ratio)
    crop_left_ratio = _normalize_ocr_crop_ratio(ocr_crop_left_ratio)
    crop_right_ratio = _normalize_ocr_crop_ratio(ocr_crop_right_ratio)
    exclude_enabled = bool(ocr_exclude_enabled)
    exclude_top_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_top_ratio)
    exclude_bottom_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_bottom_ratio)
    exclude_left_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_left_ratio)
    exclude_right_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_right_ratio)
    normalized_source_language = normalize_source_language(source_language or "auto")
    candidates: list[dict[str, Any]] = []
    candidates.extend(_reusable_ocr_from_tasks(normalized_url=normalized_url, title_key=title_key, mode=mode, scope=scope, extraction_mode=extraction_mode, refinement_mode=refinement_mode, crop_top_ratio=crop_top_ratio, crop_bottom_ratio=crop_bottom_ratio, crop_left_ratio=crop_left_ratio, crop_right_ratio=crop_right_ratio, exclude_enabled=exclude_enabled, exclude_top_ratio=exclude_top_ratio, exclude_bottom_ratio=exclude_bottom_ratio, exclude_left_ratio=exclude_left_ratio, exclude_right_ratio=exclude_right_ratio, source_language=normalized_source_language, exclude_session_id=exclude_session_id))
    if not JOB_DIR.exists():
        return sorted(candidates, key=lambda item: float(item.get("created_at") or 0), reverse=True)[0] if candidates else None
    for run_yaml in JOB_DIR.glob("*/run.yaml"):
        job_dir = run_yaml.parent
        if exclude_session_id and job_dir.name == exclude_session_id:
            continue
        try:
            config = yaml.safe_load(run_yaml.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(config, dict):
            continue
        if str(config.get("mode") or "") not in {"extract", "full"}:
            continue
        source_srt = _resolve_cached_source_srt(job_dir, config)
        if not source_srt or not source_srt.exists() or source_srt.stat().st_size <= 0:
            continue
        cache = config.get("agent_cache") if isinstance(config.get("agent_cache"), dict) else {}
        cached_url = str(cache.get("normalized_url") or "").strip()
        cached_mode = str(cache.get("ocr_translation_mode") or "").strip()
        cached_scope = str(cache.get("ocr_scope") or "bottom").strip()
        cached_extraction_mode = str(cache.get("ocr_extraction_mode") or "auto").strip()
        cached_refinement_mode = str(cache.get("ocr_refinement_mode") or "none").strip()
        cached_crop_top_ratio = _normalize_ocr_crop_top_ratio(cache.get("ocr_crop_top_ratio"), cached_scope)
        cached_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(cache.get("ocr_crop_bottom_ratio"))
        cached_crop_left_ratio = _normalize_ocr_crop_ratio(cache.get("ocr_crop_left_ratio"))
        cached_crop_right_ratio = _normalize_ocr_crop_ratio(cache.get("ocr_crop_right_ratio"))
        cached_exclude_enabled = bool(cache.get("ocr_exclude_enabled", False))
        cached_exclude_top_ratio = _normalize_ocr_exclude_ratio(cache.get("ocr_exclude_top_ratio", 0.04))
        cached_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(cache.get("ocr_exclude_bottom_ratio", 0.82))
        cached_exclude_left_ratio = _normalize_ocr_exclude_ratio(cache.get("ocr_exclude_left_ratio", 0.76))
        cached_exclude_right_ratio = _normalize_ocr_exclude_ratio(cache.get("ocr_exclude_right_ratio", 0.02))
        cached_source_language = normalize_source_language(cache.get("source_language") or config.get("source_language") or "auto")
        if normalized_source_language != "auto" and cached_source_language != normalized_source_language:
            continue
        input_video = Path(str(config.get("input_video") or ""))
        exact_url_match = bool(normalized_url and cached_url == normalized_url)
        title_match = _cached_ocr_title_matches(input_video, title_key)
        if exact_url_match:
            if cached_mode and cached_mode != mode:
                continue
            if _normalize_ocr_scope(cached_scope) != scope:
                continue
            if _normalize_ocr_extraction_mode(cached_extraction_mode) != extraction_mode:
                continue
            if _normalize_ocr_refinement_mode(cached_refinement_mode) != refinement_mode:
                continue
        elif not title_match:
            continue
        if _normalize_ocr_extraction_mode(cached_extraction_mode) != extraction_mode:
            continue
        if (
            cached_crop_top_ratio != crop_top_ratio
            or cached_crop_bottom_ratio != crop_bottom_ratio
            or cached_crop_left_ratio != crop_left_ratio
            or cached_crop_right_ratio != crop_right_ratio
            or cached_exclude_enabled != exclude_enabled
            or (exclude_enabled and (
                cached_exclude_top_ratio != exclude_top_ratio
                or cached_exclude_bottom_ratio != exclude_bottom_ratio
                or cached_exclude_left_ratio != exclude_left_ratio
                or cached_exclude_right_ratio != exclude_right_ratio
            ))
        ):
            continue
        candidates.append(
            {
                "source_srt": str(source_srt),
                "input_video": str(input_video) if str(input_video) else "",
                "output_dir": str(job_dir),
                "job_id": job_dir.name,
                "matched_by": "url" if exact_url_match else "title",
                "created_at": run_yaml.stat().st_mtime,
                "ocr_translation_mode": cached_mode or mode,
                "ocr_scope": _normalize_ocr_scope(cached_scope),
                "ocr_extraction_mode": _normalize_ocr_extraction_mode(cached_extraction_mode),
                "ocr_refinement_mode": _normalize_ocr_refinement_mode(cached_refinement_mode),
                "ocr_crop_top_ratio": cached_crop_top_ratio,
                "ocr_crop_bottom_ratio": cached_crop_bottom_ratio,
                "ocr_crop_left_ratio": cached_crop_left_ratio,
                "ocr_crop_right_ratio": cached_crop_right_ratio,
                "ocr_exclude_enabled": cached_exclude_enabled,
                "ocr_exclude_top_ratio": cached_exclude_top_ratio,
                "ocr_exclude_bottom_ratio": cached_exclude_bottom_ratio,
                "ocr_exclude_left_ratio": cached_exclude_left_ratio,
                "ocr_exclude_right_ratio": cached_exclude_right_ratio,
                "source_language": cached_source_language,
            }
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: float(item.get("created_at") or 0), reverse=True)[0]


def _reusable_ocr_from_tasks(*, normalized_url: str, title_key: str, mode: str, scope: str, extraction_mode: str, refinement_mode: str, crop_top_ratio: float, crop_bottom_ratio: float, crop_left_ratio: float, crop_right_ratio: float, exclude_enabled: bool, exclude_top_ratio: float, exclude_bottom_ratio: float, exclude_left_ratio: float, exclude_right_ratio: float, source_language: str, exclude_session_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not TASK_DIR.exists():
        return results
    for task_yaml in TASK_DIR.glob("*/task.yaml"):
        task = _read_task_file(task_yaml)
        if exclude_session_id and task.get("id") == exclude_session_id:
            continue
        source_srt = _task_stage_path(task, "ocr", "source_srt")
        if not source_srt:
            continue
        source_path = Path(source_srt)
        if not source_path.exists() or source_path.stat().st_size <= 1:
            continue
        task_url = str(task.get("url") or "")
        task_title_key = _filename_match_key(str(task.get("title") or ""))
        exact_url_match = bool(normalized_url and task_url == normalized_url)
        title_match = bool(title_key and task_title_key and (title_key in task_title_key or task_title_key in title_key or SequenceMatcher(None, title_key, task_title_key).ratio() >= 0.86))
        if not exact_url_match and not title_match:
            continue
        cached_scope = _normalize_ocr_scope(_task_stage_value(task, "ocr", "ocr_scope") or "bottom")
        if cached_scope != scope:
            continue
        cached_extraction_mode = _normalize_ocr_extraction_mode(_task_stage_value(task, "ocr", "ocr_extraction_mode") or "auto")
        if cached_extraction_mode != extraction_mode:
            continue
        cached_refinement_mode = _normalize_ocr_refinement_mode(_task_stage_value(task, "ocr", "ocr_refinement_mode") or "none")
        if cached_refinement_mode != refinement_mode:
            continue
        cached_crop_top_ratio = _normalize_ocr_crop_top_ratio(_task_stage_value(task, "ocr", "ocr_crop_top_ratio"), cached_scope)
        cached_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(_task_stage_value(task, "ocr", "ocr_crop_bottom_ratio"))
        cached_crop_left_ratio = _normalize_ocr_crop_ratio(_task_stage_value(task, "ocr", "ocr_crop_left_ratio"))
        cached_crop_right_ratio = _normalize_ocr_crop_ratio(_task_stage_value(task, "ocr", "ocr_crop_right_ratio"))
        cached_exclude_enabled = bool(_task_stage_value(task, "ocr", "ocr_exclude_enabled") or False)
        cached_exclude_top_ratio = _normalize_ocr_exclude_ratio(_task_stage_value(task, "ocr", "ocr_exclude_top_ratio") or 0.04)
        cached_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(_task_stage_value(task, "ocr", "ocr_exclude_bottom_ratio") or 0.82)
        cached_exclude_left_ratio = _normalize_ocr_exclude_ratio(_task_stage_value(task, "ocr", "ocr_exclude_left_ratio") or 0.76)
        cached_exclude_right_ratio = _normalize_ocr_exclude_ratio(_task_stage_value(task, "ocr", "ocr_exclude_right_ratio") or 0.02)
        cached_source_language = normalize_source_language(_task_stage_value(task, "ocr", "source_language") or "auto")
        if source_language != "auto" and cached_source_language != source_language:
            continue
        if (
            cached_crop_top_ratio != crop_top_ratio
            or cached_crop_bottom_ratio != crop_bottom_ratio
            or cached_crop_left_ratio != crop_left_ratio
            or cached_crop_right_ratio != crop_right_ratio
            or cached_exclude_enabled != exclude_enabled
            or (exclude_enabled and (
                cached_exclude_top_ratio != exclude_top_ratio
                or cached_exclude_bottom_ratio != exclude_bottom_ratio
                or cached_exclude_left_ratio != exclude_left_ratio
                or cached_exclude_right_ratio != exclude_right_ratio
            ))
        ):
            continue
        results.append(
            {
                "source_srt": source_srt,
                "input_video": _task_stage_value(task, "ocr", "input_video") or "",
                "output_dir": str(task_yaml.parent),
                "job_id": str(task.get("id") or task_yaml.parent.name),
                "matched_by": "url" if exact_url_match else "title",
                "created_at": float(_task_stage_value(task, "ocr", "updated_at") or task.get("updated_at") or task_yaml.stat().st_mtime),
                "ocr_translation_mode": mode,
                "ocr_scope": cached_scope,
                "ocr_extraction_mode": cached_extraction_mode,
                "ocr_refinement_mode": cached_refinement_mode,
                "ocr_crop_top_ratio": cached_crop_top_ratio,
                "ocr_crop_bottom_ratio": cached_crop_bottom_ratio,
                "ocr_crop_left_ratio": cached_crop_left_ratio,
                "ocr_crop_right_ratio": cached_crop_right_ratio,
                "ocr_exclude_enabled": cached_exclude_enabled,
                "ocr_exclude_top_ratio": cached_exclude_top_ratio,
                "ocr_exclude_bottom_ratio": cached_exclude_bottom_ratio,
                "ocr_exclude_left_ratio": cached_exclude_left_ratio,
                "ocr_exclude_right_ratio": cached_exclude_right_ratio,
                "source_language": cached_source_language,
            }
        )
    return results


def _resolve_cached_source_srt(job_dir: Path, config: dict[str, Any]) -> Path | None:
    raw = str(config.get("source_srt") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        return path
    fallback = job_dir / "source.srt"
    return fallback if fallback.exists() else None


def _cached_ocr_title_matches(input_video: Path, title_key: str) -> bool:
    if not title_key:
        return False
    text = " ".join(part for part in [input_video.stem, input_video.parent.name] if part)
    key = _filename_match_key(text)
    return bool(key and (title_key in key or key in title_key or SequenceMatcher(None, title_key, key).ratio() >= 0.86))


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
    task_id = ""
    phase = ""
    with _LOCK:
        session = _AGENT_SESSIONS.get(session_id)
        if not session:
            return
        task_id = str(session.result.get("task_id") or "")
        phase = session.phase
        session.status = "failed"
        session.error = str(exc)
        session.question = {}
        session.logs.append(f"agent_failed: {exc}")
        session.updated_at = time.time()
    if task_id:
        stage = _task_stage_for_phase(phase)
        if stage:
            _update_task_stage(task_id, stage, "failed", current_stage=f"{stage}_failed", error=str(exc))


def _task_stage_for_phase(phase: str) -> str:
    if phase in {"ocr_full", "confirm_ocr_reuse"}:
        return "ocr"
    if phase in {"generate_glossary", "review_glossary"}:
        return "glossary"
    if phase == "translate":
        return "translate"
    if phase == "probe":
        return "probe"
    return ""


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.logs.append(line.rstrip())
        job.updated_at = time.time()


def _job_service() -> JobService:
    return JobService(
        _JOBS,
        _LOCK,
        append_log=_append_log,
        terminate_process=_terminate_process_tree,
    )


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
        manifest = update_youtube_project_metadata(changed[0].parent, source_url=url, title=title or changed[0].parent.name)
        return {
            "subtitle_paths": [str(path) for path in changed],
            "subtitle_path": str(changed[0]) if changed else "",
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
        }

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
        result.update(subtitle_pair_issues(out))
        return result

    return start_job("翻译外挂字幕", target)


def correct_asr_subtitle_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    glossary_value = str(payload.get("glossary") or "").strip()
    glossary = _resolve_project_path(glossary_value) if glossary_value else None
    reference_value = str(payload.get("reference_srt") or "").strip()
    reference_srt = _resolve_project_path(reference_value) if reference_value else None
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
        if reference_srt:
            args.extend(["--reference-srt", str(reference_srt)])
        if extra_hint.strip():
            args.extend(["--extra-prompt", extra_hint.strip()])
        _run_command(job_id, args)
        result = {"corrected_srt": str(out), "source_srt": str(out), "subtitle_path": str(out)}
        if reference_srt:
            result["reference_srt"] = str(reference_srt)
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
    thumbnail_format = str(payload.get("thumbnail_format") or "jpg").strip().lower()
    quality = str(payload.get("quality") or "1080p").strip() or "1080p"
    archive_quality = quality.strip().lower() in {"best", "highest", "max", "最高", "archive", "best_archive", "best-archive"}
    before = _snapshot_video_files(DOWNLOAD_DIR)

    def target(job_id: str) -> dict[str, Any]:
        _run_command(
            job_id,
            _module_command(
                "video_translate.youtube.download_video",
                url,
                "--output-dir",
                DOWNLOAD_DIR,
                "--quality",
                quality,
                "--thumbnail-format",
                thumbnail_format,
            ),
        )
        videos = _changed_video_files(DOWNLOAD_DIR, before)
        if not videos:
            videos = _matching_video_files(DOWNLOAD_DIR, title)
        if not videos and not title:
            videos = _newest_video_files(DOWNLOAD_DIR, limit=3)
        if not videos:
            raise RuntimeError(f"视频下载完成后没有找到匹配文件: title={title or '<unknown>'}")
        thumbnail = _matching_thumbnail_file(videos[0]) if videos else None
        if not thumbnail:
            before_images = _snapshot_image_files(DOWNLOAD_DIR)
            _run_command(
                job_id,
                _module_command(
                    "video_translate.youtube.download_thumbnail",
                    url,
                    "--output-dir",
                    DOWNLOAD_DIR,
                    "--format",
                    thumbnail_format,
                ),
            )
            images = _changed_image_files(DOWNLOAD_DIR, before_images)
            if not images:
                images = _matching_image_files(DOWNLOAD_DIR, title or videos[0].parent.name)
            thumbnail = images[0] if images else _matching_thumbnail_file(videos[0])
        if archive_quality:
            project_dir = videos[0].parent
            primary_candidates = [
                path for path in _matching_video_files(DOWNLOAD_DIR, title or project_dir.name)
                if path.parent == project_dir and ".best" not in path.stem
            ]
            manifest = update_youtube_project_metadata(
                project_dir,
                source_url=url,
                title=title or project_dir.name,
                primary_video=primary_candidates[0] if primary_candidates else None,
                thumbnail_path=thumbnail,
            )
        else:
            manifest = update_youtube_project_manifest(videos[0], source_url=url, title=title or videos[0].parent.name, thumbnail_path=thumbnail)
        result = {
            "video_paths": [str(path) for path in videos],
            "input_video": str(videos[0]) if videos else "",
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
            "project": _download_project_entry(Path(str(manifest["project_dir"]))),
        }
        if thumbnail:
            result["thumbnail_path"] = str(thumbnail)
        return result

    return start_job("下载视频", target)


def download_thumbnail_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    title = str(payload.get("title") or "").strip()
    image_format = str(payload.get("format") or payload.get("thumbnail_format") or "jpg").strip().lower()
    before = _snapshot_image_files(DOWNLOAD_DIR)

    def target(job_id: str) -> dict[str, Any]:
        _run_command(
            job_id,
            _module_command(
                "video_translate.youtube.download_thumbnail",
                url,
                "--output-dir",
                DOWNLOAD_DIR,
                "--format",
                image_format,
            ),
        )
        images = _changed_image_files(DOWNLOAD_DIR, before)
        if not images:
            images = _matching_image_files(DOWNLOAD_DIR, title)
        if not images and not title:
            images = _newest_image_files(DOWNLOAD_DIR, limit=3)
        if not images:
            raise RuntimeError(f"封面下载完成后没有找到匹配文件: title={title or '<unknown>'}")
        manifest = update_youtube_project_metadata(images[0].parent, source_url=url, title=title or images[0].parent.name, thumbnail_path=images[0])
        return {
            "thumbnail_paths": [str(path) for path in images],
            "thumbnail_path": str(images[0]),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
        }

    return start_job("下载封面", target)



def _materialize_chinese_ocr_output(input_video: Path, out_dir: Path) -> dict[str, str]:
    source_srt = out_dir / "source.srt"
    zh_srt = out_dir / "zh.srt"
    if not source_srt.exists():
        return {"translated_srt": ""}
    if source_srt != zh_srt:
        shutil.copy2(source_srt, zh_srt)
    copied = copy_sidecar_subtitles(
        input_video,
        source_srt=source_srt,
        translated_srt=zh_srt,
        config=SidecarConfig(enabled=True, copy_source=True, copy_translated=True, source_suffix=".source", translated_suffix=".zh"),
    )
    result = {"translated_srt": str(zh_srt), "subtitle_path": str(zh_srt)}
    result.update({name: str(path) for name, path in copied.items()})
    return result


def ocr_full_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    title = str(payload.get("title") or "").strip()
    extra_hint = str(payload.get("extra_hint") or "")
    translation_mode = _normalize_ocr_translation_mode(payload.get("translation_mode"), bool(payload.get("preserve_timing", False)))
    ocr_scope = _normalize_ocr_scope(payload.get("ocr_scope"))
    ocr_extraction_mode = _normalize_ocr_extraction_mode(payload.get("ocr_extraction_mode"))
    ocr_refinement_mode = _normalize_ocr_refinement_mode(payload.get("ocr_refinement_mode"))
    ocr_crop_top_ratio = _normalize_ocr_crop_top_ratio(payload.get("ocr_crop_top_ratio"), ocr_scope)
    ocr_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(payload.get("ocr_crop_bottom_ratio"))
    ocr_crop_left_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_left_ratio"))
    ocr_crop_right_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_right_ratio"))
    ocr_exclude_enabled = bool(payload.get("ocr_exclude_enabled", False))
    ocr_exclude_top_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_top_ratio", 0.04))
    ocr_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_bottom_ratio", 0.82))
    ocr_exclude_left_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_left_ratio", 0.76))
    ocr_exclude_right_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_right_ratio", 0.02))
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    ocr_language = normalize_source_language(payload.get("ocr_language") or "auto")
    config_source_language = ocr_language if ocr_language != "auto" else source_language
    job_slug = _safe_slug(payload.get("title") or "ocr_task")[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        before_videos = _snapshot_video_files(DOWNLOAD_DIR)
        _append_log(job_id, "download_video_start")
        _run_command(job_id, _module_command("video_translate.youtube.download_video", url, "--output-dir", DOWNLOAD_DIR, "--quality", "1080p"))
        videos = _downloaded_video_candidates(DOWNLOAD_DIR, before_videos, title, newest_limit=1)
        if not videos:
            missing_title = title or "<unknown>"
            raise RuntimeError(f"视频下载完成后没有找到匹配文件: title={missing_title}")
        input_video = videos[0]
        thumbnail = _matching_thumbnail_file(input_video)
        manifest = update_youtube_project_manifest(input_video, source_url=url, title=title or input_video.parent.name, thumbnail_path=thumbnail)
        _append_log(job_id, f"input_video: {input_video}")
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint, translation_mode=translation_mode, ocr_scope=ocr_scope, ocr_extraction_mode=ocr_extraction_mode, ocr_refinement_mode=ocr_refinement_mode, ocr_crop_top_ratio=ocr_crop_top_ratio, ocr_crop_bottom_ratio=ocr_crop_bottom_ratio, ocr_crop_left_ratio=ocr_crop_left_ratio, ocr_crop_right_ratio=ocr_crop_right_ratio, ocr_exclude_enabled=ocr_exclude_enabled, ocr_exclude_top_ratio=ocr_exclude_top_ratio, ocr_exclude_bottom_ratio=ocr_exclude_bottom_ratio, ocr_exclude_left_ratio=ocr_exclude_left_ratio, ocr_exclude_right_ratio=ocr_exclude_right_ratio, source_language=config_source_language)
        if config_source_language == "chinese":
            config["mode"] = "extract"
            config["sidecar"]["copy_translated"] = False
        config["agent_cache"] = {
            "kind": "youtube_ocr",
            "normalized_url": normalize_youtube_url(url),
            "ocr_translation_mode": translation_mode,
            "ocr_scope": ocr_scope,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_refinement_mode": ocr_refinement_mode,
            "ocr_crop_top_ratio": ocr_crop_top_ratio,
            "ocr_crop_bottom_ratio": ocr_crop_bottom_ratio,
            "ocr_crop_left_ratio": ocr_crop_left_ratio,
            "ocr_crop_right_ratio": ocr_crop_right_ratio,
            "ocr_exclude_enabled": ocr_exclude_enabled,
            "ocr_exclude_top_ratio": ocr_exclude_top_ratio,
            "ocr_exclude_bottom_ratio": ocr_exclude_bottom_ratio,
            "ocr_exclude_left_ratio": ocr_exclude_left_ratio,
            "ocr_exclude_right_ratio": ocr_exclude_right_ratio,
            "source_language": config_source_language,
            "ocr_language": ocr_language,
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        result = {
            "input_video": str(input_video),
            "output_dir": str(out_dir),
            "source_srt": str(out_dir / "source.srt"),
            "translated_srt": str(out_dir / "zh.srt"),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
            "source_language": config_source_language,
            "ocr_language": ocr_language,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_exclude_enabled": ocr_exclude_enabled,
        }
        if config_source_language == "chinese":
            result.update(_materialize_chinese_ocr_output(input_video, out_dir))
        return result

    return start_job(f"OCR 全流程 {job_slug}", target)


def ocr_extract_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    title = str(payload.get("title") or "").strip()
    extra_hint = str(payload.get("extra_hint") or "")
    translation_mode = _normalize_ocr_translation_mode(payload.get("translation_mode"), bool(payload.get("preserve_timing", False)))
    ocr_scope = _normalize_ocr_scope(payload.get("ocr_scope"))
    ocr_extraction_mode = _normalize_ocr_extraction_mode(payload.get("ocr_extraction_mode"))
    ocr_refinement_mode = _normalize_ocr_refinement_mode(payload.get("ocr_refinement_mode"))
    ocr_crop_top_ratio = _normalize_ocr_crop_top_ratio(payload.get("ocr_crop_top_ratio"), ocr_scope)
    ocr_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(payload.get("ocr_crop_bottom_ratio"))
    ocr_crop_left_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_left_ratio"))
    ocr_crop_right_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_right_ratio"))
    ocr_exclude_enabled = bool(payload.get("ocr_exclude_enabled", False))
    ocr_exclude_top_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_top_ratio", 0.04))
    ocr_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_bottom_ratio", 0.82))
    ocr_exclude_left_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_left_ratio", 0.76))
    ocr_exclude_right_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_right_ratio", 0.02))
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    ocr_language = normalize_source_language(payload.get("ocr_language") or "auto")
    config_source_language = ocr_language if ocr_language != "auto" else source_language
    job_slug = _safe_slug(payload.get("title") or "ocr_task")[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        before_videos = _snapshot_video_files(DOWNLOAD_DIR)
        _append_log(job_id, "download_video_start")
        _run_command(job_id, _module_command("video_translate.youtube.download_video", url, "--output-dir", DOWNLOAD_DIR, "--quality", "1080p"))
        videos = _downloaded_video_candidates(DOWNLOAD_DIR, before_videos, title, newest_limit=1)
        if not videos:
            missing_title = title or "<unknown>"
            raise RuntimeError(f"视频下载完成后没有找到匹配文件: title={missing_title}")
        input_video = videos[0]
        thumbnail = _matching_thumbnail_file(input_video)
        manifest = update_youtube_project_manifest(input_video, source_url=url, title=title or input_video.parent.name, thumbnail_path=thumbnail)
        _append_log(job_id, f"input_video: {input_video}")
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint, translation_mode=translation_mode, ocr_scope=ocr_scope, ocr_extraction_mode=ocr_extraction_mode, ocr_refinement_mode=ocr_refinement_mode, ocr_crop_top_ratio=ocr_crop_top_ratio, ocr_crop_bottom_ratio=ocr_crop_bottom_ratio, ocr_crop_left_ratio=ocr_crop_left_ratio, ocr_crop_right_ratio=ocr_crop_right_ratio, ocr_exclude_enabled=ocr_exclude_enabled, ocr_exclude_top_ratio=ocr_exclude_top_ratio, ocr_exclude_bottom_ratio=ocr_exclude_bottom_ratio, ocr_exclude_left_ratio=ocr_exclude_left_ratio, ocr_exclude_right_ratio=ocr_exclude_right_ratio, source_language=config_source_language)
        config["mode"] = "extract"
        config["sidecar"]["copy_translated"] = False
        config["agent_cache"] = {
            "kind": "youtube_ocr",
            "normalized_url": normalize_youtube_url(url),
            "ocr_translation_mode": translation_mode,
            "ocr_scope": ocr_scope,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_refinement_mode": ocr_refinement_mode,
            "ocr_crop_top_ratio": ocr_crop_top_ratio,
            "ocr_crop_bottom_ratio": ocr_crop_bottom_ratio,
            "ocr_crop_left_ratio": ocr_crop_left_ratio,
            "ocr_crop_right_ratio": ocr_crop_right_ratio,
            "ocr_exclude_enabled": ocr_exclude_enabled,
            "ocr_exclude_top_ratio": ocr_exclude_top_ratio,
            "ocr_exclude_bottom_ratio": ocr_exclude_bottom_ratio,
            "ocr_exclude_left_ratio": ocr_exclude_left_ratio,
            "ocr_exclude_right_ratio": ocr_exclude_right_ratio,
            "source_language": config_source_language,
            "ocr_language": ocr_language,
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        return {
            "input_video": str(input_video),
            "output_dir": str(out_dir),
            "source_srt": str(out_dir / "source.srt"),
            "subtitle_path": str(out_dir / "source.srt"),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
            "source_language": config_source_language,
            "ocr_language": ocr_language,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_exclude_enabled": ocr_exclude_enabled,
        }

    return start_job(f"OCR 提取 {job_slug}", target)


def ocr_local_video_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    extra_hint = str(payload.get("extra_hint") or "")
    translation_mode = _normalize_ocr_translation_mode(payload.get("translation_mode"), bool(payload.get("preserve_timing", False)))
    ocr_scope = _normalize_ocr_scope(payload.get("ocr_scope"))
    ocr_extraction_mode = _normalize_ocr_extraction_mode(payload.get("ocr_extraction_mode"))
    ocr_refinement_mode = _normalize_ocr_refinement_mode(payload.get("ocr_refinement_mode"))
    ocr_crop_top_ratio = _normalize_ocr_crop_top_ratio(payload.get("ocr_crop_top_ratio"), ocr_scope)
    ocr_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(payload.get("ocr_crop_bottom_ratio"))
    ocr_crop_left_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_left_ratio"))
    ocr_crop_right_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_right_ratio"))
    ocr_exclude_enabled = bool(payload.get("ocr_exclude_enabled", False))
    ocr_exclude_top_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_top_ratio", 0.04))
    ocr_exclude_bottom_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_bottom_ratio", 0.82))
    ocr_exclude_left_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_left_ratio", 0.76))
    ocr_exclude_right_ratio = _normalize_ocr_exclude_ratio(payload.get("ocr_exclude_right_ratio", 0.02))
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    ocr_language = normalize_source_language(payload.get("ocr_language") or "auto")
    extract_only = bool(payload.get("extract_only", False))
    config_source_language = ocr_language if ocr_language != "auto" else source_language
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint, translation_mode=translation_mode, ocr_scope=ocr_scope, ocr_extraction_mode=ocr_extraction_mode, ocr_refinement_mode=ocr_refinement_mode, ocr_crop_top_ratio=ocr_crop_top_ratio, ocr_crop_bottom_ratio=ocr_crop_bottom_ratio, ocr_crop_left_ratio=ocr_crop_left_ratio, ocr_crop_right_ratio=ocr_crop_right_ratio, ocr_exclude_enabled=ocr_exclude_enabled, ocr_exclude_top_ratio=ocr_exclude_top_ratio, ocr_exclude_bottom_ratio=ocr_exclude_bottom_ratio, ocr_exclude_left_ratio=ocr_exclude_left_ratio, ocr_exclude_right_ratio=ocr_exclude_right_ratio, source_language=config_source_language)
        if extract_only or config_source_language == "chinese":
            config["mode"] = "extract"
            config["sidecar"]["copy_translated"] = False
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        manifest = update_local_project_manifest(input_video, download_dir=DOWNLOAD_DIR, title=input_video.stem)
        result = {
            "input_video": str(input_video),
            "output_dir": str(out_dir),
            "source_srt": str(out_dir / "source.srt"),
            "translated_srt": str(out_dir / "zh.srt"),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
            "source_language": config_source_language,
            "ocr_language": ocr_language,
            "ocr_extraction_mode": ocr_extraction_mode,
            "ocr_exclude_enabled": ocr_exclude_enabled,
        }
        if config_source_language == "chinese":
            result.update(_materialize_chinese_ocr_output(input_video, out_dir))
        return result

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
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    ocr_language = normalize_source_language(payload.get("ocr_language") or "auto")
    if source_language == "auto":
        source_language = "korean"
    if ocr_language == "auto":
        ocr_language = source_language
    lang = str(payload.get("lang") or ocr_language_for_source(ocr_language)).strip()
    sample_fps = str(payload.get("sample_fps") or "2.0")
    ocr_scope = _normalize_ocr_scope(payload.get("ocr_scope"))
    ocr_settings = _ocr_scope_settings(ocr_scope)
    bottom_ratio = str(payload.get("bottom_ratio") or ocr_settings["bottom_ratio"])
    ocr_crop_top_ratio = _normalize_ocr_crop_top_ratio(payload.get("ocr_crop_top_ratio"), ocr_scope)
    ocr_crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(payload.get("ocr_crop_bottom_ratio"))
    ocr_crop_left_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_left_ratio"))
    ocr_crop_right_ratio = _normalize_ocr_crop_ratio(payload.get("ocr_crop_right_ratio"))
    scan_full_frame = bool(payload.get("scan_full_frame", ocr_settings["scan_full_frame"]))
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
            "source_language": ocr_language,
            "hybrid": {
                "lang": lang,
                "sample_fps": sample_fps,
                "bottom_ratio": bottom_ratio,
                "crop_top_ratio": ocr_crop_top_ratio,
                "crop_bottom_ratio": ocr_crop_bottom_ratio,
                "crop_left_ratio": ocr_crop_left_ratio,
                "crop_right_ratio": ocr_crop_right_ratio,
                "scan_full_frame": scan_full_frame,
                "device": device,
            },
            "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"anchor_srt: {anchor_srt}")
        _append_log(job_id, f"config: {config_path}")
        args = [
                *_module_command(
                    "video_translate.tools.hybrid_anchor_ocr",
                    input_video,
                    anchor_srt,
                ),
                "--out-dir",
                str(out_dir),
                "--lang",
                lang,
                "--source-language",
                ocr_language,
                "--sample-fps",
                sample_fps,
                "--bottom-ratio",
                bottom_ratio,
                "--crop-top-ratio",
                str(ocr_crop_top_ratio),
                "--crop-bottom-ratio",
                str(ocr_crop_bottom_ratio),
                "--crop-left-ratio",
                str(ocr_crop_left_ratio),
                "--crop-right-ratio",
                str(ocr_crop_right_ratio),
                "--device",
                device,
                "--ocr-window-seconds",
                str(payload.get("ocr_window_seconds") or "1.20"),
                "--reconstruct-korean",
        ]
        if scan_full_frame:
            args.append("--scan-full-frame")
        _run_command(job_id, args)
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

    return start_job(f"英文定轴 + 原声 OCR {job_slug}", target)


def dual_subtitle_reference_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    reference_srt = _resolve_project_path(_required_str(payload, "reference_srt"))
    _ensure_under_root(source_srt)
    _ensure_under_root(reference_srt)
    if not source_srt.exists():
        raise FileNotFoundError(f"主字幕文件不存在: {source_srt}")
    if not reference_srt.exists():
        raise FileNotFoundError(f"参考字幕文件不存在: {reference_srt}")
    job_slug = _safe_slug(payload.get("title") or source_srt.stem)[:80]
    min_overlap = float(payload.get("min_overlap_seconds") or 0.10)
    source_language = normalize_source_language(payload.get("source_language") or "korean")
    if source_language == "auto":
        source_language = "korean"

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        config_path = out_dir / "run.yaml"
        config = {
            "mode": "dual_subtitle_reference",
            "source_subtitle": str(source_srt),
            "reference_subtitle": str(reference_srt),
            "source_srt": str(out_dir / "dual.source.srt"),
            "context_srt": str(out_dir / "dual.context.srt"),
            "output_dir": str(out_dir),
            "source_language": source_language,
            "dual_reference": {"min_overlap_seconds": min_overlap},
            "sidecar": {"enabled": True, "copy_source": False, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"source_subtitle: {source_srt}")
        _append_log(job_id, f"reference_subtitle: {reference_srt}")
        _append_log(job_id, f"config: {config_path}")
        result_paths = write_dual_reference_outputs(
            read_srt(source_srt),
            read_srt(reference_srt),
            out_dir,
            min_overlap_seconds=min_overlap,
            source_language=source_language,
        )
        return {name: str(path) for name, path in result_paths.items()}

    return start_job(f"原声主字幕 + 英文参考 {job_slug}", target)



def video_overlay_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    layers = _normalize_overlay_layers(payload.get("layers") or [])
    if not layers:
        raise ValueError("至少启用一层贴图。")
    output_value = str(payload.get("out") or "").strip()
    if output_value:
        output_video = _resolve_project_path(output_value)
        _ensure_under_root(output_video)
    else:
        output_video = _unique_overlay_output_path(input_video)
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        asset_dir = out_dir / "overlay_assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        video_width, video_height = _video_dimensions(input_video)
        prepared_layers = []
        for index, layer in enumerate(layers, start=1):
            image_path = _save_overlay_image(layer, asset_dir, index)
            width_px = max(1, int(round(video_width * float(layer["width"]))))
            x_px = max(0, min(video_width - 1, int(round(video_width * float(layer["x"])))) )
            y_px = max(0, min(video_height - 1, int(round(video_height * float(layer["y"])))) )
            prepared_layers.append({**layer, "image_path": image_path, "width_px": width_px, "x_px": x_px, "y_px": y_px})
        output_video.parent.mkdir(parents=True, exist_ok=True)
        args = _build_video_overlay_command(input_video, output_video, prepared_layers)
        _run_command(job_id, args)
        return {
            "input_video": str(input_video),
            "output_video": str(output_video),
            "layers": [
                {
                    "kind": layer["kind"],
                    "image_path": str(layer["image_path"]),
                    "x": layer["x"],
                    "y": layer["y"],
                    "width": layer["width"],
                    "opacity": layer["opacity"],
                    "remove_background": layer["remove_background"],
                }
                for layer in prepared_layers
            ],
        }

    return start_job(f"视频贴图处理 {job_slug}", target)


def _normalize_overlay_layers(raw_layers: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_layers, list):
        raise ValueError("layers 必须是数组。")
    layers: list[dict[str, Any]] = []
    for raw in raw_layers:
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            continue
        image_data_url = str(raw.get("image_data_url") or raw.get("image") or "").strip()
        if not image_data_url:
            continue
        kind = str(raw.get("kind") or "overlay").strip() or "overlay"
        layers.append(
            {
                "kind": kind,
                "image_data_url": image_data_url,
                "x": _clamp_float(raw.get("x"), 0.0, 0.98, 0.72),
                "y": _clamp_float(raw.get("y"), 0.0, 0.98, 0.08),
                "width": _clamp_float(raw.get("width"), 0.02, 0.90, 0.18),
                "opacity": _clamp_float(raw.get("opacity"), 0.0, 1.0, 1.0),
                "remove_background": bool(raw.get("remove_background", False)),
            }
        )
    return layers


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _unique_overlay_output_path(input_video: Path) -> Path:
    base = input_video.with_name(f"{input_video.stem}.overlay.mp4")
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = input_video.with_name(f"{input_video.stem}.overlay-{index}.mp4")
        if not candidate.exists():
            return candidate
    raise RuntimeError("无法生成不冲突的输出视频文件名。")


def _save_overlay_image(layer: dict[str, Any], asset_dir: Path, index: int) -> Path:
    from PIL import Image
    import io

    raw = str(layer["image_data_url"])
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception as exc:
        raise ValueError(f"贴图 {index} 不是有效的 base64 图片。") from exc
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    if bool(layer.get("remove_background")):
        image = _remove_image_background(image)
    out = asset_dir / f"{index:02d}_{_safe_slug(layer.get('kind'))}.png"
    image.save(out, "PNG")
    return out


def _remove_image_background(image):
    from PIL import ImageChops

    rgba = image.convert("RGBA")
    width, height = rgba.size
    border_pixels = []
    for x in range(width):
        border_pixels.append(rgba.getpixel((x, 0)))
        border_pixels.append(rgba.getpixel((x, height - 1)))
    for y in range(height):
        border_pixels.append(rgba.getpixel((0, y)))
        border_pixels.append(rgba.getpixel((width - 1, y)))
    key = tuple(sorted(channel)[len(channel) // 2] for channel in zip(*border_pixels))[:3]
    pixels = rgba.load()
    threshold = 38
    soft = 18
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            distance = ((r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2) ** 0.5
            if distance <= threshold:
                pixels[x, y] = (r, g, b, 0)
            elif distance <= threshold + soft:
                next_alpha = int(a * ((distance - threshold) / soft))
                pixels[x, y] = (r, g, b, next_alpha)
    return rgba


def _video_dimensions(video_path: Path) -> tuple[int, int]:
    cv2 = _load_cv2_for_preview()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"无法读取视频尺寸: {video_path}")
    return width, height


def _build_video_overlay_command(input_video: Path, output_video: Path, layers: list[dict[str, Any]]) -> list[str]:
    args = ["ffmpeg", "-y", "-i", str(input_video)]
    for layer in layers:
        args.extend(["-i", str(layer["image_path"])])
    filter_parts: list[str] = []
    current = "[0:v]"
    for index, layer in enumerate(layers, start=1):
        overlay_label = f"ov{index}"
        output_label = f"v{index}"
        opacity = float(layer["opacity"])
        width_px = int(layer["width_px"])
        x_px = int(layer["x_px"])
        y_px = int(layer["y_px"])
        filter_parts.append(f"[{index}:v]format=rgba,scale={width_px}:-1,colorchannelmixer=aa={opacity:.4f}[{overlay_label}]")
        filter_parts.append(f"{current}[{overlay_label}]overlay={x_px}:{y_px}[{output_label}]")
        current = f"[{output_label}]"
    filter_complex = ";".join(filter_parts)
    args.extend([
        "-filter_complex",
        filter_complex,
        "-map",
        current,
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_video),
    ])
    return args

def audio_language_probe_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    model_size = str(payload.get("model_size") or os.environ.get("ASR_PROBE_MODEL_SIZE") or os.environ.get("ASR_MODEL_SIZE") or "large-v3").strip()
    device = str(payload.get("device") or os.environ.get("ASR_DEVICE") or "cuda").strip()
    compute_type = str(payload.get("compute_type") or os.environ.get("ASR_COMPUTE_TYPE") or "float16").strip()
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        json_out = out_dir / "audio_language.json"
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"json_out: {json_out}")
        _run_command(
            job_id,
            [
                *_module_command(
                    "video_translate.tools.transcribe_audio",
                    input_video,
                ),
                "--out",
                str(out_dir / "probe.srt"),
                "--model-size",
                model_size,
                "--language",
                "auto",
                "--device",
                device,
                "--compute-type",
                compute_type,
                "--detect-language-only",
                "--json-out",
                str(json_out),
            ],
        )
        data = json.loads(json_out.read_text(encoding="utf-8")) if json_out.exists() else {}
        return {
            "input_video": str(input_video),
            "language": str(data.get("language") or "unknown"),
            "language_probability": float(data.get("language_probability") or 0),
            "json_path": str(json_out),
        }

    return start_job(f"音源语言检测 {job_slug}", target)


def audio_local_video_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    language = str(payload.get("language") or asr_language_for_source(source_language)).strip()
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
            "source_language": source_language,
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
        manifest = update_local_project_manifest(input_video, download_dir=DOWNLOAD_DIR, title=input_video.stem)
        result = {
            "input_video": str(input_video),
            "output_dir": str(out_dir),
            "source_srt": str(source_srt),
            "subtitle_path": str(source_srt),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
        }
        result.update({name: str(path) for name, path in copied.items()})
        return result

    return start_job(f"音频识别字幕 {job_slug}", target)


def mobile_asr_translate_job(payload: dict[str, Any]) -> Job:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    source_language = normalize_source_language(payload.get("source_language") or "auto")
    language = str(payload.get("language") or asr_language_for_source(source_language)).strip()
    model_size = str(payload.get("model_size") or "large-v3").strip()
    device = str(payload.get("device") or "cuda").strip()
    compute_type = str(payload.get("compute_type") or "float16").strip()
    translation_mode = _normalize_subtitle_translation_mode(payload.get("translation_mode") or "standard_cleanup")
    extra_hint = str(payload.get("extra_hint") or "").strip()
    glossary_value = str(payload.get("glossary") or "").strip()
    glossary = _resolve_project_path(glossary_value) if glossary_value else None
    target_language = str(payload.get("target_language") or "简体中文").strip()
    job_slug = _safe_slug(input_video.stem)[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        source_srt = out_dir / "source.srt"
        translated_srt = out_dir / "zh.srt"
        config_path = out_dir / "run.yaml"
        config = {
            "mode": "mobile_audio_translate",
            "input_video": str(input_video),
            "source_srt": str(source_srt),
            "translated_srt": str(translated_srt),
            "output_dir": str(out_dir),
            "source_language": source_language,
            "audio": {
                "provider": "faster-whisper",
                "model_size": model_size,
                "language": language,
                "device": device,
                "compute_type": compute_type,
            },
            "translation": {
                "mode": translation_mode,
                "target_language": target_language,
            },
            "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
        }
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"input_video: {input_video}")
        _append_log(job_id, f"config: {config_path}")
        _run_command(
            job_id,
            [
                *_module_command("video_translate.tools.transcribe_audio", input_video),
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
        translate_args = [
            *_module_command("video_translate.tools.translate_subtitles", source_srt),
            "--out",
            str(translated_srt),
            "--translation-mode",
            translation_mode,
            "--target-language",
            target_language,
        ]
        if glossary:
            translate_args.extend(["--glossary", str(glossary)])
        mobile_prompt = "本次源字幕来自 ASR 音频识别，可能存在同音误识别；请结合上下文翻译，清理明显语音识别噪声，但不要改动时间轴。"
        if extra_hint:
            mobile_prompt += "\n" + extra_hint
        translate_args.extend(["--extra-prompt", mobile_prompt])
        _run_command(job_id, translate_args)
        copied = copy_sidecar_subtitles(
            input_video,
            source_srt=source_srt,
            translated_srt=translated_srt,
            config=SidecarConfig(enabled=True, copy_source=True, copy_translated=True, source_suffix=".source", translated_suffix=".zh"),
        )
        manifest = update_local_project_manifest(input_video, download_dir=DOWNLOAD_DIR, title=input_video.parent.name)
        result = {
            "input_video": str(input_video),
            "output_dir": str(out_dir),
            "source_srt": str(source_srt),
            "translated_srt": str(translated_srt),
            "subtitle_path": str(translated_srt),
            "project_dir": str(Path(str(manifest["project_dir"]))),
            "project_manifest": str(Path(str(manifest["project_dir"])) / PROJECT_MANIFEST_NAME),
            "translation_mode": translation_mode,
        }
        result.update({name: str(path) for name, path in copied.items()})
        result.update(subtitle_pair_issues(translated_srt))
        return result

    return start_job(f"手机 ASR 翻译 {job_slug}", target)


def _ocr_config(
    input_video: Path,
    output_dir: Path,
    *,
    extra_hint: str,
    translation_mode: str = "standard_cleanup",
    preserve_timing: bool = False,
    ocr_scope: str = "bottom",
    ocr_extraction_mode: str = "auto",
    ocr_refinement_mode: str = "none",
    ocr_crop_top_ratio: float | None = None,
    ocr_crop_bottom_ratio: float = 0.0,
    ocr_crop_left_ratio: float = 0.0,
    ocr_crop_right_ratio: float = 0.0,
    ocr_exclude_enabled: bool = False,
    ocr_exclude_top_ratio: float = 0.04,
    ocr_exclude_bottom_ratio: float = 0.82,
    ocr_exclude_left_ratio: float = 0.76,
    ocr_exclude_right_ratio: float = 0.02,
    source_language: str = "korean",
) -> dict[str, Any]:
    translation_mode = _normalize_ocr_translation_mode(translation_mode, preserve_timing)
    ocr_settings = _ocr_scope_settings(ocr_scope)
    ocr_extraction_mode = _normalize_ocr_extraction_mode(ocr_extraction_mode)
    ocr_refinement_mode = _normalize_ocr_refinement_mode(ocr_refinement_mode)
    crop_top_ratio = _normalize_ocr_crop_top_ratio(ocr_crop_top_ratio, ocr_scope)
    crop_bottom_ratio = _normalize_ocr_vertical_crop_ratio(ocr_crop_bottom_ratio)
    crop_left_ratio = _normalize_ocr_crop_ratio(ocr_crop_left_ratio)
    crop_right_ratio = _normalize_ocr_crop_ratio(ocr_crop_right_ratio)
    exclude_enabled = bool(ocr_exclude_enabled)
    exclude_top_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_top_ratio)
    exclude_bottom_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_bottom_ratio)
    exclude_left_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_left_ratio)
    exclude_right_ratio = _normalize_ocr_exclude_ratio(ocr_exclude_right_ratio)
    normalized_source_language = normalize_source_language(source_language or "korean")
    prompt = """
严格遵守 glossary 中的人名、角色名、节目名和固定术语。
字幕要自然、简洁、口语化，适合 1-2 行外挂字幕显示。
如果相邻两条字幕明显是同一句话的 OCR 变体，请保持译文一致。
保留原文语气；源文是疑问、反问或确认提问时，中文应以“？”结尾。
括号、引号、书名号等符号必须成对出现；无法确认另一半时不要输出半边符号。
""".strip()
    if extra_hint.strip():
        prompt += "\n任务提示：" + extra_hint.strip()
    mode_prompt, translation = _ocr_translation_mode_config(translation_mode, prompt)
    prompt = mode_prompt
    ocr_config = {
        "device": "auto",
        "sample_fps": 3.0,
        **ocr_settings,
        "extraction_mode": ocr_extraction_mode,
        "crop_top_ratio": crop_top_ratio,
        "crop_bottom_ratio": crop_bottom_ratio,
        "crop_left_ratio": crop_left_ratio,
        "crop_right_ratio": crop_right_ratio,
        "exclude_enabled": exclude_enabled,
        "exclude_top_ratio": exclude_top_ratio,
        "exclude_bottom_ratio": exclude_bottom_ratio,
        "exclude_left_ratio": exclude_left_ratio,
        "exclude_right_ratio": exclude_right_ratio,
        "auto_trim_side_noise": True,
    }
    subtitle_config = {"merge_gap_seconds": 0.85, "same_text_similarity": 0.88, "merge_same_start_seconds": 0.16, "merge_short_fragment_gap_seconds": 0.50, "short_fragment_max_chars": 14, "short_fragment_similarity": 0.55, "snapshot_similarity": 0.72, "snapshot_max_gap_seconds": None, "snapshot_min_confidence": 0.50, "end_padding_seconds": 0.35, "sample_end_extension_ratio": 0.75, "min_duration_seconds": 0.60, "max_next_overlap_seconds": 0.04, "enforce_no_overlap": True}
    if ocr_extraction_mode == "region":
        ocr_config.update({"sample_fps": 6.0, "scan_full_frame": False, "auto_trim_side_noise": False})
        subtitle_config.update({"same_text_similarity": 0.78, "merge_short_fragment_gap_seconds": 0.75, "short_fragment_similarity": 0.45, "snapshot_min_confidence": 0.35, "min_duration_seconds": 0.35})

    return {
        "mode": "full",
        "input_video": str(input_video),
        "source_srt": str(output_dir / "source.srt"),
        "output_dir": str(output_dir),
        "source_language": normalized_source_language,
        "target_language": "简体中文",
        "glossary": "",
        "ocr": ocr_config,
        "ocr_refinement": {"mode": ocr_refinement_mode, "batch_size": 12, "window_padding_seconds": 0.50, "max_boxes_per_frame": 16},
        "source_cleanup": {"mode": "llm_context", "batch_size": 18, "overlap": 3},
        "filters": {"ignored_texts": ["Disney+", "디즈니+"], "ignored_contains": [], "ignored_patterns": ["disn[e3][yp]?\\+?"]},
        "subtitle": subtitle_config,
        "translation": translation,
        "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
    }


OCR_SCOPE_SETTINGS = {
    "bottom": {"bottom_ratio": 0.42, "scan_full_frame": False},
    "expanded": {"bottom_ratio": 0.62, "scan_full_frame": False},
    "smart_full": {"bottom_ratio": 0.42, "scan_full_frame": True},
}

OCR_EXTRACTION_MODES = {"auto", "region"}


def _normalize_ocr_scope(value: Any) -> str:
    scope = str(value or "bottom").strip()
    if scope not in OCR_SCOPE_SETTINGS:
        raise ValueError(f"未知 OCR 扫描范围: {scope}")
    return scope


def _ocr_scope_settings(scope: Any) -> dict[str, Any]:
    normalized = _normalize_ocr_scope(scope)
    return dict(OCR_SCOPE_SETTINGS[normalized])


def _normalize_ocr_extraction_mode(value: Any) -> str:
    mode = str(value or "auto").strip()
    if mode not in OCR_EXTRACTION_MODES:
        raise ValueError(f"未知 OCR 提取方式: {mode}")
    return mode




def _normalize_ocr_crop_top_ratio(value: Any, scope: Any = "bottom") -> float:
    if value is None or value == "":
        settings = _ocr_scope_settings(scope)
        return round(max(0.0, min(0.95, 1 - float(settings.get("bottom_ratio", 0.42)))), 4)
    return _normalize_ocr_vertical_crop_ratio(value)

def _normalize_ocr_vertical_crop_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(0.95, ratio)), 4)

def _normalize_ocr_crop_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(0.45, ratio)), 4)


def _normalize_ocr_exclude_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(0.98, ratio)), 4)


OCR_REFINEMENT_MODES = {"none", "llm_boxes"}


def _normalize_ocr_refinement_mode(value: Any) -> str:
    mode = str(value or "none").strip()
    if mode not in OCR_REFINEMENT_MODES:
        raise ValueError(f"未知 OCR 原文精修模式: {mode}")
    return mode


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


PAIR_SYMBOLS = [
    {"name": "中文双引号", "open": "“", "close": "”"},
    {"name": "中文单引号", "open": "‘", "close": "’"},
    {"name": "中文圆括号", "open": "（", "close": "）"},
    {"name": "英文圆括号", "open": "(", "close": ")"},
    {"name": "方括号", "open": "[", "close": "]"},
    {"name": "中文方括号", "open": "【", "close": "】"},
    {"name": "书名号", "open": "《", "close": "》"},
    {"name": "直角引号", "open": "「", "close": "」"},
    {"name": "双直角引号", "open": "『", "close": "』"},
]


def subtitle_pair_issues(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"pair_issue_count": 0, "pair_issues": []}
    open_map = {item["open"]: item for item in PAIR_SYMBOLS}
    close_map = {item["close"]: item for item in PAIR_SYMBOLS}
    stack: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for cue in read_srt(path):
        for char in cue.text or "":
            if char in open_map:
                stack.append({"pair": open_map[char], "cue": cue})
                continue
            pair = close_map.get(char)
            if not pair:
                continue
            match_index = _find_pair_stack_index(stack, pair)
            if match_index >= 0:
                stack.pop(match_index)
            else:
                issues.append(_build_subtitle_pair_issue(cue, pair, "missing_open"))
    for item in stack:
        issues.append(_build_subtitle_pair_issue(item["cue"], item["pair"], "missing_close"))
    issues.sort(key=lambda item: (item["cue_index"], item["type"]))
    return {"pair_issue_count": len(issues), "pair_issues": issues}


def _find_pair_stack_index(stack: list[dict[str, Any]], pair: dict[str, str]) -> int:
    for index in range(len(stack) - 1, -1, -1):
        item_pair = stack[index]["pair"]
        if item_pair["open"] == pair["open"] and item_pair["close"] == pair["close"]:
            return index
    return -1


def _build_subtitle_pair_issue(cue: SubtitleCue, pair: dict[str, str], issue_type: str) -> dict[str, Any]:
    return {
        "cue_index": cue.index,
        "start": cue.start,
        "end": cue.end,
        "text": cue.text,
        "symbol_name": pair["name"],
        "missing_symbol": pair["open"] if issue_type == "missing_open" else pair["close"],
        "type": issue_type,
    }


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


def read_subtitle_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_readable_subtitle_path(path)
    cues = read_srt(path)
    return {
        "path": str(path),
        "count": len(cues),
        "cues": [_subtitle_cue_to_editor_dict(cue) for cue in cues],
    }


def write_subtitle_file(payload: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_project_path(_required_str(payload, "path"))
    _ensure_readable_subtitle_path(source)
    output_value = str(payload.get("out") or "").strip()
    if output_value:
        output = _resolve_project_path(output_value)
    elif bool(payload.get("overwrite", False)):
        output = source
    else:
        output = source.with_name(f"{source.stem}.edited.srt")
    _ensure_writable_subtitle_path(output)

    raw_cues = payload.get("cues")
    if not isinstance(raw_cues, list):
        raise ValueError("缺少字幕条目: cues")
    cues: list[SubtitleCue] = []
    for item in raw_cues:
        if not isinstance(item, dict) or item.get("deleted"):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = _subtitle_time_value(item.get("start_time", item.get("start")))
        end = _subtitle_time_value(item.get("end_time", item.get("end")))
        if end <= start:
            raise ValueError(f"字幕结束时间必须大于开始时间: {text[:30]}")
        cues.append(SubtitleCue(index=len(cues) + 1, start=start, end=end, text=text))

    write_srt(cues, output)
    return {
        "path": str(output),
        "saved": True,
        "count": len(cues),
        "cues": [_subtitle_cue_to_editor_dict(cue) for cue in cues],
    }


def _subtitle_cue_to_editor_dict(cue: SubtitleCue) -> dict[str, Any]:
    return {
        "index": cue.index,
        "start": cue.start,
        "end": cue.end,
        "start_time": format_srt_time(cue.start),
        "end_time": format_srt_time(cue.end),
        "text": cue.text,
    }


def _subtitle_time_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        raise ValueError("字幕时间不能为空")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    return parse_srt_time(text)


def _ensure_readable_subtitle_path(path: Path) -> None:
    _ensure_under_root(path)
    if path.suffix.lower() != ".srt":
        raise ValueError("字幕编辑器只支持读取 .srt 文件")
    if not path.is_file():
        raise FileNotFoundError(f"字幕文件不存在: {path}")


def _ensure_writable_subtitle_path(path: Path) -> None:
    _ensure_under_root(path)
    if path.suffix.lower() != ".srt":
        raise ValueError("字幕编辑器只允许保存 .srt 文件")
    path.parent.mkdir(parents=True, exist_ok=True)


def read_glossary_items(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    text = path.read_text(encoding="utf-8")
    data = _load_yaml_text(text, path)
    source_srt = _source_srt_from_glossary_text(text, path)
    cue_texts = _cue_texts_by_id(source_srt)
    english_reference_texts = _english_references_by_id(source_srt)
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
    if _is_relative_to(path, GLOSSARY_DIR) or _is_relative_to(path, JOB_DIR) or _is_relative_to(path, TASK_DIR):
        return
    raise ValueError("UI 只允许保存 configs/glossaries、outputs/agent_jobs 或 outputs/agent_tasks 下的 glossary 文件")


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


def _english_references_by_id(source_srt: Path | None) -> dict[int, str]:
    if source_srt is None:
        return {}
    context_srt = _reference_context_srt(source_srt)
    if not context_srt.exists():
        return {}
    result: dict[int, str] = {}
    try:
        for cue in read_srt(context_srt):
            text = _extract_english_reference(cue.text)
            if text:
                result[cue.index] = text
    except Exception:
        return {}
    return result


def _reference_context_srt(source_srt: Path) -> Path:
    if source_srt.name.startswith("dual."):
        return source_srt.with_name("dual.context.srt")
    return source_srt.with_name("hybrid.context.srt")


def _extract_english_reference(text: str) -> str:
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
    videos = _asset_entries(_iter_video_files(DOWNLOAD_DIR), kind="video")
    subtitles = _asset_entries(_iter_subtitle_files(), kind="subtitle")
    return {
        "videos": videos,
        "subtitles": subtitles,
        "projects": _download_project_entries(DOWNLOAD_DIR),
        "ocr_jobs": _ocr_job_entries(),
    }


def _iter_video_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        files.extend(path for path in directory.rglob(pattern) if _is_real_file(path))
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


def _download_project_entries(directory: Path, limit: int = 80) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    projects = [_download_project_entry(path) for path in directory.iterdir() if path.is_dir()]
    projects = [project for project in projects if project]
    return sorted(projects, key=lambda item: item["modified_at"], reverse=True)[:limit]


def _download_project_entry(project_dir: Path) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    _backfill_project_manifest_from_tasks(project_dir)
    manifest = infer_project_manifest(project_dir)
    files = [path for path in project_dir.iterdir() if _is_real_file(path) and path.name != PROJECT_MANIFEST_NAME] if project_dir.exists() else []
    primary_video = Path(str(manifest.get("primary_video") or "")).expanduser()
    if str(primary_video) and primary_video.exists() and primary_video.is_file() and primary_video not in files:
        files.insert(0, primary_video.resolve())
    thumbnail = Path(str(manifest.get("thumbnail") or "")).expanduser()
    if str(thumbnail) and thumbnail.exists() and thumbnail.is_file() and thumbnail not in files:
        files.append(thumbnail.resolve())
    if not files and not manifest:
        return {}
    videos = _asset_entries([path for path in files if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}], kind="video", limit=50)
    subtitles = _asset_entries([path for path in files if path.suffix.lower() in {".srt", ".vtt", ".ass", ".ssa", ".bcc"}], kind="subtitle", limit=80)
    images = _asset_entries([path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}], kind="image", limit=20)
    others = _asset_entries([path for path in files if path.suffix.lower() not in {
        ".mp4", ".mkv", ".webm", ".mov", ".m4v",
        ".srt", ".vtt", ".ass", ".ssa", ".bcc",
        ".jpg", ".jpeg", ".png", ".webp",
    }], kind="file", limit=20)
    newest = max((path.stat().st_mtime for path in files if path.exists()), default=project_dir.stat().st_mtime if project_dir.exists() else time.time())
    manifest_updated = float(manifest.get("updated_at") or 0)
    newest = max(newest, manifest_updated)
    return {
        "name": str(manifest.get("title") or project_dir.name),
        "path": str(project_dir),
        "project_id": str(manifest.get("project_id") or project_dir.name),
        "source_type": str(manifest.get("source_type") or "unknown"),
        "source_url": str(manifest.get("source_url") or ""),
        "normalized_url": str(manifest.get("normalized_url") or ""),
        "video_id": str(manifest.get("video_id") or ""),
        "primary_video": str(manifest.get("primary_video") or (videos[0]["path"] if videos else "")),
        "thumbnail": str(manifest.get("thumbnail") or (images[0]["path"] if images else "")),
        "manifest_path": str(project_dir / PROJECT_MANIFEST_NAME),
        "manifest": manifest,
        "modified_at": newest,
        "modified_label": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)),
        "videos": videos,
        "subtitles": subtitles,
        "images": images,
        "others": others,
        "counts": {
            "videos": len(videos),
            "subtitles": len(subtitles),
            "images": len(images),
            "others": len(others),
        },
    }


def _ensure_probe_thumbnail(normalized_url: str, title: str, info: dict[str, Any], *, proxy: str | None = DEFAULT_PROXY) -> Path | None:
    title = title or str(info.get("title") or "") or "youtube_video"
    project_dir = _youtube_project_dir_for_title(title)
    project_dir.mkdir(parents=True, exist_ok=True)
    existing = _matching_project_thumbnail(project_dir, title)
    if existing:
        update_youtube_project_metadata(project_dir, source_url=normalized_url, title=title, thumbnail_path=existing)
        return existing
    thumbnail_url = thumbnail_url_from_info(info)
    if not thumbnail_url:
        update_youtube_project_metadata(project_dir, source_url=normalized_url, title=title)
        return None
    try:
        response = requests.get(thumbnail_url, timeout=30, proxies={"http": proxy, "https": proxy} if proxy else None)
        response.raise_for_status()
    except Exception as exc:
        print(f"thumbnail_probe_skip: {type(exc).__name__}: {exc}", flush=True)
        update_youtube_project_metadata(project_dir, source_url=normalized_url, title=title)
        return None
    extension = thumbnail_extension(thumbnail_url, response.headers.get("Content-Type", ""), image_format="jpg")
    thumbnail_path = project_dir / f"{_filesystem_safe_title(title)}{extension}"
    thumbnail_path.write_bytes(convert_thumbnail_bytes(response.content, image_format="jpg"))
    update_youtube_project_metadata(project_dir, source_url=normalized_url, title=title, thumbnail_path=thumbnail_path)
    return thumbnail_path


def _youtube_project_dir_for_title(title: str) -> Path:
    matches = _matching_media_files(DOWNLOAD_DIR, ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v", "*.jpg", "*.jpeg", "*.png", "*.webp", "*.srt"], title)
    if matches:
        return matches[0].parent
    return DOWNLOAD_DIR / _filesystem_safe_title(title)


def _matching_project_thumbnail(project_dir: Path, title: str) -> Path | None:
    if not project_dir.exists():
        return None
    image_files = [path for path in project_dir.iterdir() if _is_real_file(path) and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    if not image_files:
        return None
    exact = [path for path in image_files if _filename_match_key(path.stem) == _filename_match_key(title)]
    return sorted(exact or image_files, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _filesystem_safe_title(title: str) -> str:
    return filesystem_safe_title(title)


def _find_or_bind_youtube_project(normalized_url: str, title: str) -> dict[str, Any]:
    if not DOWNLOAD_DIR.exists():
        return {}
    normalized_url = normalize_youtube_url(normalized_url) if normalized_url else ""
    for project_dir in sorted([path for path in DOWNLOAD_DIR.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True):
        manifest = infer_project_manifest(project_dir)
        if normalized_url and str(manifest.get("normalized_url") or "") == normalized_url:
            return _download_project_entry(project_dir)
    matches = _matching_video_files(DOWNLOAD_DIR, title)
    if matches:
        video = matches[0]
        update_youtube_project_manifest(
            video,
            source_url=normalized_url,
            title=title or video.parent.name,
            thumbnail_path=_matching_thumbnail_file(video),
        )
        return _download_project_entry(video.parent)
    return {}


def _backfill_project_manifest_from_tasks(project_dir: Path) -> None:
    if (project_dir / PROJECT_MANIFEST_NAME).exists() or not TASK_DIR.exists():
        return
    for task_yaml in sorted(TASK_DIR.glob("*/task.yaml"), key=lambda path: path.stat().st_mtime, reverse=True):
        task = _read_task_file(task_yaml)
        url = str(task.get("url") or "").strip()
        if not url:
            continue
        input_video_raw = str(_task_stage_value(task, "ocr", "input_video") or "").strip()
        if not input_video_raw:
            continue
        input_video = Path(input_video_raw).expanduser()
        if not input_video.exists() or not _is_relative_to(input_video.resolve(), project_dir):
            continue
        update_youtube_project_manifest(
            input_video,
            source_url=url,
            title=str(task.get("title") or project_dir.name),
            thumbnail_path=_matching_thumbnail_file(input_video),
        )
        return


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
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
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
    return {path: path.stat().st_mtime for path in _iter_pattern_files(directory, pattern) if _is_real_file(path)}


def _changed_files(directory: Path, pattern: str, before: dict[Path, float]) -> list[Path]:
    changed: list[Path] = []
    for path in _iter_pattern_files(directory, pattern):
        if not _is_real_file(path):
            continue
        mtime = path.stat().st_mtime
        if path not in before or mtime > before[path] + 0.001:
            changed.append(path)
    return sorted(changed, key=lambda p: p.stat().st_mtime, reverse=True)


def _newest_files(directory: Path, pattern: str, *, limit: int) -> list[Path]:
    files = [path for path in _iter_pattern_files(directory, pattern) if _is_real_file(path)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _iter_pattern_files(directory: Path, pattern: str) -> list[Path]:
    if pattern.startswith("**/") or "/" in pattern:
        return list(directory.glob(pattern))
    return list(directory.rglob(pattern))


def _snapshot_video_files(directory: Path) -> dict[Path, float]:
    result: dict[Path, float] = {}
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        result.update(_snapshot_files(directory, pattern))
    return result


def _snapshot_image_files(directory: Path) -> dict[Path, float]:
    result: dict[Path, float] = {}
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.webp"]:
        result.update(_snapshot_files(directory, pattern))
    return result


def _downloaded_video_candidates(directory: Path, before: dict[Path, float], title: str, *, newest_limit: int) -> list[Path]:
    videos = _matching_video_files(directory, title) if str(title or "").strip() else []
    if videos:
        return videos
    videos = _changed_video_files(directory, before)
    if videos:
        return videos
    return _newest_video_files(directory, limit=newest_limit)


def _changed_video_files(directory: Path, before: dict[Path, float]) -> list[Path]:
    changed: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        changed.extend(_changed_files(directory, pattern, before))
    return sorted(set(changed), key=lambda p: p.stat().st_mtime, reverse=True)


def _changed_image_files(directory: Path, before: dict[Path, float]) -> list[Path]:
    changed: list[Path] = []
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.webp"]:
        changed.extend(_changed_files(directory, pattern, before))
    return sorted(set(changed), key=lambda p: p.stat().st_mtime, reverse=True)


def _newest_video_files(directory: Path, *, limit: int) -> list[Path]:
    files: list[Path] = []
    for pattern in ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]:
        files.extend(_newest_files(directory, pattern, limit=20))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _newest_image_files(directory: Path, *, limit: int) -> list[Path]:
    files: list[Path] = []
    for pattern in ["*.jpg", "*.jpeg", "*.png", "*.webp"]:
        files.extend(_newest_files(directory, pattern, limit=20))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _matching_video_files(directory: Path, title: str) -> list[Path]:
    return _matching_media_files(directory, ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"], title)


def _matching_image_files(directory: Path, title: str) -> list[Path]:
    return _matching_media_files(directory, ["*.jpg", "*.jpeg", "*.png", "*.webp"], title)


def _matching_thumbnail_file(video_path: Path) -> Path | None:
    for suffix in [".jpg", ".jpeg", ".png", ".webp"]:
        candidate = video_path.with_suffix(suffix)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


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
    title_key = _filename_match_key(title)
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in directory.rglob(pattern) if path.is_file() and not path.name.startswith("._"))
    if not candidates:
        return []

    def score(path: Path) -> tuple[int, float]:
        stem = path.stem
        stem_key = _filename_match_key(stem)
        if stem == title:
            rank = 0
        elif stem.startswith(title + "."):
            rank = 1
        elif stem.startswith(title):
            rank = 2
        elif title in stem:
            rank = 3
        elif stem_key == title_key:
            rank = 4
        elif stem_key.startswith(title_key):
            rank = 5
        elif title_key and title_key in stem_key:
            rank = 6
        elif title_key and SequenceMatcher(None, title_key, stem_key).ratio() >= 0.86:
            rank = 7
        else:
            rank = 99
        return (rank, -path.stat().st_mtime)

    matches = [path for path in candidates if score(path)[0] < 99]
    return sorted(matches, key=score)


def _filename_match_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in normalized if char.isalnum())



def ocr_preview_frame(payload: dict[str, Any]) -> dict[str, Any]:
    input_video = _resolve_project_path(_required_str(payload, "input_video"))
    _ensure_under_root(input_video)
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    time_seconds = _optional_float_value(payload.get("time_seconds"))
    cv2 = _load_cv2_for_preview()
    capture = cv2.VideoCapture(str(input_video))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {input_video}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if frame_count else None
        if time_seconds is None:
            time_seconds = duration / 2 if duration else 0.0
        frame_index = max(0, int(time_seconds * fps))
        if frame_count:
            frame_index = min(frame_index, max(0, frame_count - 1))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok and frame_index != 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
            frame_index = 0
            time_seconds = 0.0
        if not ok:
            raise RuntimeError(f"无法读取视频帧: {input_video}")
    finally:
        capture.release()
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    if not ok:
        raise RuntimeError("视频帧编码失败")
    height, width = frame.shape[:2]
    rect = _ocr_crop_preview_rect(
        width,
        height,
        ocr_scope=str(payload.get("ocr_scope") or "bottom"),
        crop_top_ratio=payload.get("ocr_crop_top_ratio"),
        crop_bottom_ratio=payload.get("ocr_crop_bottom_ratio"),
        crop_left_ratio=payload.get("ocr_crop_left_ratio"),
        crop_right_ratio=payload.get("ocr_crop_right_ratio"),
    )
    exclude_rect = _ocr_exclude_preview_rect(
        width,
        height,
        exclude_enabled=bool(payload.get("ocr_exclude_enabled", False)),
        exclude_top_ratio=payload.get("ocr_exclude_top_ratio", 0.04),
        exclude_bottom_ratio=payload.get("ocr_exclude_bottom_ratio", 0.82),
        exclude_left_ratio=payload.get("ocr_exclude_left_ratio", 0.76),
        exclude_right_ratio=payload.get("ocr_exclude_right_ratio", 0.02),
    )
    image_base64 = base64.b64encode(encoded.tobytes()).decode("ascii")
    return {
        "input_video": str(input_video),
        "time_seconds": frame_index / fps if fps else float(time_seconds or 0),
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "crop_rect": rect,
        "exclude_rect": exclude_rect,
        "image_data_url": f"data:image/jpeg;base64,{image_base64}",
    }


def _load_cv2_for_preview():
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 opencv-python，无法抽帧预览。") from exc
    return cv2


def _optional_float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _ocr_crop_preview_rect(
    width: int,
    height: int,
    *,
    ocr_scope: str = "bottom",
    crop_top_ratio: Any = None,
    crop_bottom_ratio: Any = 0.0,
    crop_left_ratio: Any = 0.0,
    crop_right_ratio: Any = 0.0,
) -> dict[str, Any]:
    top_ratio = _normalize_ocr_crop_top_ratio(crop_top_ratio, ocr_scope)
    bottom_ratio = _normalize_ocr_vertical_crop_ratio(crop_bottom_ratio)
    left_ratio = _normalize_ocr_crop_ratio(crop_left_ratio)
    right_ratio = _normalize_ocr_crop_ratio(crop_right_ratio)
    left = round(width * left_ratio)
    top = round(height * top_ratio)
    right = round(width * (1 - right_ratio))
    bottom = round(height * (1 - bottom_ratio))
    if right <= left:
        left, right = 0, width
        left_ratio, right_ratio = 0.0, 0.0
    if bottom <= top:
        top_ratio = _normalize_ocr_crop_top_ratio(None, ocr_scope)
        bottom_ratio = 0.0
        top = round(height * top_ratio)
        bottom = height
    return {
        "left": left,
        "top": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
        "ratios": {"top": top_ratio, "bottom": bottom_ratio, "left": left_ratio, "right": right_ratio},
    }


def _ocr_exclude_preview_rect(
    width: int,
    height: int,
    *,
    exclude_enabled: bool = False,
    exclude_top_ratio: Any = 0.04,
    exclude_bottom_ratio: Any = 0.82,
    exclude_left_ratio: Any = 0.76,
    exclude_right_ratio: Any = 0.02,
) -> dict[str, Any]:
    top_ratio = _normalize_ocr_exclude_ratio(exclude_top_ratio)
    bottom_ratio = _normalize_ocr_exclude_ratio(exclude_bottom_ratio)
    left_ratio = _normalize_ocr_exclude_ratio(exclude_left_ratio)
    right_ratio = _normalize_ocr_exclude_ratio(exclude_right_ratio)
    left = round(width * left_ratio)
    top = round(height * top_ratio)
    right = round(width * (1 - right_ratio))
    bottom = round(height * (1 - bottom_ratio))
    enabled = bool(exclude_enabled and right > left and bottom > top)
    return {
        "enabled": enabled,
        "left": left if enabled else 0,
        "top": top if enabled else 0,
        "width": max(0, right - left) if enabled else 0,
        "height": max(0, bottom - top) if enabled else 0,
        "ratios": {"top": top_ratio, "bottom": bottom_ratio, "left": left_ratio, "right": right_ratio},
    }

def _required_str(payload: dict[str, Any], name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"缺少参数: {name}")
    return value


def _resolve_project_path(value: Any) -> Path:
    return _project_path_policy().resolve(str(value))


def _ensure_under_root(path: Path) -> None:
    try:
        _project_path_policy().ensure_allowed(path)
    except ValueError:
        allowed_text = "、".join(str(root) for root in _allowed_path_roots())
        raise ValueError(f"路径不在允许的工作目录下: {path}。允许目录: {allowed_text}")


def _allowed_path_roots() -> list[Path]:
    roots: list[Path] = []
    for path in [ROOT, DOWNLOAD_DIR, JOB_DIR, TASK_DIR, GLOSSARY_DIR]:
        resolved = path.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _is_relative_to(path: Path, parent: Path) -> bool:
    return ProjectPathPolicy.is_relative_to(path, parent)


def _project_path_policy() -> ProjectPathPolicy:
    return ProjectPathPolicy(ROOT, _allowed_path_roots())


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


def _api_path_segment(path: str, index: int) -> str:
    parts = urlparse(path).path.rstrip("/").split("/")
    return unquote(parts[index])


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "VideoTranslateAgent/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/agent":
            self._send_json({"sessions": list_agent_sessions()})
            return
        if parsed.path == "/api/agent-tasks":
            self._send_json({"tasks": list_agent_tasks()})
            return
        if parsed.path.startswith("/api/agent-tasks/"):
            task_id = _api_path_segment(parsed.path, -1)
            task = get_agent_task(task_id)
            if not task:
                self._send_json({"error": "agent task not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(task)
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
        if parsed.path == "/api/file":
            query = parse_qs(parsed.query)
            raw_path = (query.get("path") or [""])[0]
            file_path = _resolve_project_path(raw_path)
            _ensure_under_root(file_path)
            if not file_path.is_file():
                self._send_json({"error": "file not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path)
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
            if self.path == "/api/upload-video":
                self._send_json(self._read_video_upload())
                return
            if self.path == "/api/upload-project-cover":
                self._send_json(self._read_project_cover_upload())
                return
            payload = self._read_json()
            if self.path == "/api/agent/start":
                self._send_json(start_agent_session(payload).to_dict())
            elif self.path == "/api/agent/continue-glossary":
                self._send_json(continue_agent_after_glossary_review(_required_str(payload, "glossary_path")).to_dict())
            elif self.path.startswith("/api/agent-tasks/") and self.path.rstrip("/").endswith("/delete"):
                task_id = _api_path_segment(self.path, -2)
                self._send_json(delete_agent_task(task_id))
            elif self.path.startswith("/api/agent-tasks/") and self.path.rstrip("/").endswith("/complete"):
                task_id = _api_path_segment(self.path, -2)
                self._send_json(complete_agent_task(task_id))
            elif self.path.startswith("/api/agent-tasks/") and self.path.rstrip("/").endswith("/reopen"):
                task_id = _api_path_segment(self.path, -2)
                self._send_json(reopen_agent_task(task_id))
            elif self.path.startswith("/api/agent-tasks/") and self.path.rstrip("/").endswith("/continue"):
                task_id = _api_path_segment(self.path, -2)
                self._send_json(continue_agent_task(task_id).to_dict())
            elif self.path.startswith("/api/agent-tasks/") and self.path.rstrip("/").endswith("/rerun"):
                task_id = _api_path_segment(self.path, -2)
                self._send_json(rerun_agent_task_stage(task_id, str(payload.get("stage") or "")).to_dict())
            elif self.path.startswith("/api/agent/") and self.path.rstrip("/").endswith("/answer"):
                session_id = self.path.rstrip("/").split("/")[-2]
                self._send_json(answer_agent_session(session_id, payload).to_dict())
            elif self.path.startswith("/api/agent/") and self.path.rstrip("/").endswith("/retry"):
                session_id = self.path.rstrip("/").split("/")[-2]
                self._send_json(retry_agent_session(session_id).to_dict())
            elif self.path.startswith("/api/agent/") and self.path.rstrip("/").endswith("/cancel"):
                session_id = self.path.rstrip("/").split("/")[-2]
                session = cancel_agent_session(session_id)
                if not session:
                    self._send_json({"error": "agent session not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(session.to_dict())
            elif self.path == "/api/probe":
                source_language = normalize_source_language(payload.get("source_language") or "auto")
                detected_source_language = str(payload.get("detected_source_language") or "")
                if source_language != "auto" and not detected_source_language:
                    detected_source_language = youtube_language_for_source(source_language)
                data = probe_video(
                    _required_str(payload, "url"),
                    proxy=str(payload.get("proxy") or DEFAULT_PROXY) or None,
                    target_language=str(payload.get("target_language") or "zh"),
                    detected_source_language=detected_source_language,
                    embedded_subtitle_hint=str(payload.get("embedded_subtitle_hint") or "unknown"),
                )
                self._send_json(data)
            elif self.path == "/api/translate-title":
                self._send_json(translate_title_text(_required_str(payload, "title")))
            elif self.path == "/api/jobs/download-subtitle":
                self._send_json(download_subtitle_job(payload).to_dict())
            elif self.path == "/api/jobs/download-video":
                self._send_json(download_video_job(payload).to_dict())
            elif self.path == "/api/jobs/download-thumbnail":
                self._send_json(download_thumbnail_job(payload).to_dict())
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
            elif self.path == "/api/jobs/mobile-asr-translate":
                self._send_json(mobile_asr_translate_job(payload).to_dict())
            elif self.path == "/api/jobs/video-overlay":
                self._send_json(video_overlay_job(payload).to_dict())
            elif self.path == "/api/ocr-preview-frame":
                self._send_json(ocr_preview_frame(payload))
            elif self.path == "/api/assets/delete-project":
                self._send_json(delete_download_project(payload))
            elif self.path == "/api/assets/register-local-project":
                self._send_json(register_local_project(payload))
            elif self.path == "/api/subtitle/read":
                self._send_json(read_subtitle_file(payload))
            elif self.path == "/api/subtitle/write":
                self._send_json(write_subtitle_file(payload))
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

    def _read_video_upload(self) -> dict[str, Any]:
        fields = self._read_multipart_fields()
        file_field = fields.get("file") or {}
        filename = str(file_field.get("filename") or "")
        content = file_field.get("content") if isinstance(file_field.get("content"), bytes) else b""
        title = str((fields.get("title") or {}).get("text") or "")
        if not filename or not content:
            raise ValueError("上传文件为空")
        return save_uploaded_video_file(filename=filename, content=content, title=title)

    def _read_project_cover_upload(self) -> dict[str, Any]:
        fields = self._read_multipart_fields()
        file_field = fields.get("file") or {}
        filename = str(file_field.get("filename") or "")
        content = file_field.get("content") if isinstance(file_field.get("content"), bytes) else b""
        project_path = str((fields.get("project_path") or {}).get("text") or "")
        if not project_path:
            raise ValueError("缺少参数: project_path")
        if not filename or not content:
            raise ValueError("上传封面为空")
        return save_uploaded_project_cover(project_path=project_path, filename=filename, content=content)

    def _read_multipart_fields(self) -> dict[str, dict[str, Any]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("上传文件必须使用 multipart/form-data")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("上传文件为空")
        body = self.rfile.read(length)
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        message = BytesParser(policy=email_default_policy).parsebytes(header + body)
        fields: dict[str, dict[str, Any]] = {}
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = str(part.get_param("name", header="content-disposition") or "")
            payload = part.get_payload(decode=True)
            content = payload if isinstance(payload, bytes) else b""
            fields[name] = {
                "filename": str(part.get_filename() or ""),
                "content": content,
                "text": content.decode(part.get_content_charset() or "utf-8", errors="replace") if content else "",
            }
        return fields

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
        "srt": ["YoutubeDownloads/**/*.srt", "outputs/**/*.srt"],
        "glossary": ["configs/glossaries/*.yaml", "configs/glossaries/*.yml", "configs/glossaries/*.json"],
    }.get(kind, ["YoutubeDownloads/**/*.srt"])
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
