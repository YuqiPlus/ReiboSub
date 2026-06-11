from __future__ import annotations

import json
import os
import re
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
from urllib.parse import parse_qs, urlparse

import yaml
import yt_dlp

from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _parse_json_content,
    _request_translation,
)

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = ROOT / "YoutubeDownloads"
GLOSSARY_DIR = ROOT / "configs" / "glossaries"
JOB_DIR = ROOT / "outputs" / "agent_jobs"
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "http://127.0.0.1:7890")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7860
PYTHON = sys.executable


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
        }


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"Video Translate Agent UI: http://{host}:{port}", flush=True)
    server.serve_forever()


def probe_video(url: str, *, proxy: str | None = DEFAULT_PROXY) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if proxy:
        opts["proxy"] = proxy
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    manual = _caption_entries(info.get("subtitles") or {}, kind="manual")
    auto = _caption_entries(info.get("automatic_captions") or {}, kind="auto")
    subtitles = manual + auto
    recommendation = "ocr"
    if manual:
        recommendation = "manual"
    elif auto:
        recommendation = "auto"
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "subtitles": subtitles,
        "recommendation": recommendation,
    }


def translate_title_text(title: str, *, model: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("标题为空")
    _load_dotenv(ROOT)
    key = os.environ.get("ARK_API_KEY")
    selected_model = model or os.environ.get("ARK_MODEL")
    endpoint = _chat_completions_url(base_url or os.environ.get("ARK_BASE_URL") or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 ARK_API_KEY，请先配置火山方舟 API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ARK_MODEL，请先配置火山方舟模型名或接入点 ID。")
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
                job.result = result
                job.status = "done"
                job.updated_at = time.time()
            _append_log(job.id, "job_done")
        except Exception as exc:
            with _LOCK:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = time.time()
            _append_log(job.id, f"job_failed: {exc}")

    threading.Thread(target=runner, daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    with _LOCK:
        return _JOBS.get(job_id)


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
    before = _snapshot_files(DOWNLOAD_DIR, "*.srt")

    def target(job_id: str) -> dict[str, Any]:
        args = [PYTHON, str(ROOT / "download_youtube_subtitles.py"), url, "--output-dir", str(DOWNLOAD_DIR), "--sub-langs", lang]
        if kind == "manual":
            args.append("--no-auto")
        elif kind == "auto":
            args.append("--auto-only")
        _run_command(job_id, args)
        changed = _changed_files(DOWNLOAD_DIR, "*.srt", before)
        if not changed:
            changed = _newest_files(DOWNLOAD_DIR, "*.srt", limit=3)
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
        args = [PYTHON, str(ROOT / "generate_glossary_from_subtitles.py"), str(source_srt), "--out", str(out), "--source-language", source_language]
        if extra_hint.strip():
            args.extend(["--extra-hint", extra_hint.strip()])
        _run_command(job_id, args)
        return {"glossary_path": str(out), "content": out.read_text(encoding="utf-8") if out.exists() else ""}

    return start_job("生成 glossary 草稿", target)


def translate_subtitle_job(payload: dict[str, Any]) -> Job:
    source_srt = _resolve_project_path(_required_str(payload, "source_srt"))
    glossary_value = str(payload.get("glossary") or "").strip()
    glossary = _resolve_project_path(glossary_value) if glossary_value else None
    out = _resolve_project_path(payload.get("out") or str(source_srt.with_name(source_srt.stem + ".zh.srt")))
    _ensure_under_root(out)

    def target(job_id: str) -> dict[str, Any]:
        args = [PYTHON, str(ROOT / "translate_downloaded_subtitles.py"), str(source_srt), "--out", str(out)]
        if glossary:
            args.extend(["--glossary", str(glossary)])
        _run_command(job_id, args)
        return {"translated_srt": str(out)}

    return start_job("翻译外挂字幕", target)


def download_video_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    before = _snapshot_video_files(DOWNLOAD_DIR)

    def target(job_id: str) -> dict[str, Any]:
        _run_command(job_id, [PYTHON, str(ROOT / "download_youtube_video.py"), url])
        videos = _changed_video_files(DOWNLOAD_DIR, before)
        if not videos:
            videos = _newest_video_files(DOWNLOAD_DIR, limit=3)
        return {"video_paths": [str(path) for path in videos], "input_video": str(videos[0]) if videos else ""}

    return start_job("下载视频", target)


def ocr_full_job(payload: dict[str, Any]) -> Job:
    url = _required_str(payload, "url")
    extra_hint = str(payload.get("extra_hint") or "")
    job_slug = _safe_slug(payload.get("title") or "ocr_task")[:80]

    def target(job_id: str) -> dict[str, Any]:
        out_dir = JOB_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        before_videos = _snapshot_video_files(DOWNLOAD_DIR)
        _append_log(job_id, "download_video_start")
        _run_command(job_id, [PYTHON, str(ROOT / "download_youtube_video.py"), url])
        videos = _changed_video_files(DOWNLOAD_DIR, before_videos)
        if not videos:
            videos = _newest_video_files(DOWNLOAD_DIR, limit=1)
        if not videos:
            raise RuntimeError("视频下载完成后没有找到 mp4/mkv/webm 文件")
        input_video = videos[0]
        _append_log(job_id, f"input_video: {input_video}")
        config_path = out_dir / "run.yaml"
        config = _ocr_config(input_video, out_dir, extra_hint=extra_hint)
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _append_log(job_id, f"config: {config_path}")
        _run_command(job_id, [PYTHON, str(ROOT / "run_from_config.py"), str(config_path)])
        return {"input_video": str(input_video), "output_dir": str(out_dir), "source_srt": str(out_dir / "source.srt"), "translated_srt": str(out_dir / "zh.srt")}

    return start_job(f"OCR 全流程 {job_slug}", target)


def _ocr_config(input_video: Path, output_dir: Path, *, extra_hint: str) -> dict[str, Any]:
    prompt = """
严格遵守 glossary 中的人名、角色名、节目名和固定术语。
字幕要自然、简洁、口语化，适合 1-2 行外挂字幕显示。
如果相邻两条字幕明显是同一句话的 OCR 变体，请保持译文一致。
""".strip()
    if extra_hint.strip():
        prompt += "\n任务提示：" + extra_hint.strip()
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
        "translation": {"provider": "volcengine", "batch_size": 20, "model": None, "base_url": None, "extra_prompt": prompt, "llm_cleanup_translated": True, "llm_cleanup_max_gap_seconds": 3.0, "llm_cleanup_max_window_size": 8, "cleanup_residual_fragments": True, "residual_max_gap_seconds": 3.0, "residual_short_text_chars": 6, "dedupe_translated": True, "dedupe_similarity": 0.88, "dedupe_max_gap_seconds": 1.2, "retime_translated": False},
        "sidecar": {"enabled": True, "copy_source": True, "copy_translated": True, "source_suffix": ".source", "translated_suffix": ".zh"},
    }


def read_text_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


def write_text_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    content = str(payload.get("content") or "")
    _ensure_under_root(path)
    if not _is_relative_to(path, GLOSSARY_DIR):
        raise ValueError("UI 只允许保存 configs/glossaries 下的 glossary 文件")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "saved": True}


def read_glossary_items(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    data = _load_yaml_file(path)
    return {"path": str(path), "items": _glossary_items(data)}


def write_glossary_items(payload: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_project_path(_required_str(payload, "path"))
    _ensure_under_root(path)
    if not _is_relative_to(path, GLOSSARY_DIR):
        raise ValueError("UI 只允许保存 configs/glossaries 下的 glossary 文件")
    data = _load_yaml_file(path)
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "")
        index = int(item.get("index", -1))
        zh = str(item.get("zh") or "").strip()
        if section == "program" and isinstance(data.get("program"), dict):
            data["program"]["zh"] = zh
        elif section in {"characters", "terms"} and isinstance(data.get(section), list) and 0 <= index < len(data[section]):
            if isinstance(data[section][index], dict):
                data[section][index]["zh"] = zh
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    path.write_text(text, encoding="utf-8")
    return {"path": str(path), "saved": True, "content": text, "items": _glossary_items(data)}


def _load_yaml_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 内容必须是对象: {path}")
    return data


def _glossary_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    program = data.get("program")
    if isinstance(program, dict):
        result.append(_glossary_item("program", 0, program))
    for section in ["characters", "terms"]:
        values = data.get(section) or []
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if isinstance(item, dict):
                result.append(_glossary_item(section, index, item))
    return result


def _glossary_item(section: str, index: int, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": section,
        "index": index,
        "source": str(item.get("source") or ""),
        "zh": str(item.get("zh") or ""),
        "suggested_zh": str(item.get("suggested_zh") or ""),
        "aliases": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
        "type": str(item.get("type") or ""),
        "note": str(item.get("note") or ""),
        "always": bool(item.get("always", False)),
    }


def _run_command(job_id: str, args: list[str]) -> None:
    _append_log(job_id, "$ " + " ".join(_quote_arg(arg) for arg in args))
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    assert process.stdout is not None
    for line in process.stdout:
        _append_log(job_id, line.rstrip())
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"命令失败，退出码 {code}")


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
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
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
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/probe":
                data = probe_video(_required_str(payload, "url"), proxy=str(payload.get("proxy") or DEFAULT_PROXY) or None)
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
            elif self.path == "/api/jobs/ocr-full":
                self._send_json(ocr_full_job(payload).to_dict())
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


def _list_known_files(kind: str) -> list[str]:
    patterns = {
        "srt": ["YoutubeDownloads/*.srt", "outputs/**/*.srt"],
        "glossary": ["configs/glossaries/*.yaml", "configs/glossaries/*.yml", "configs/glossaries/*.json"],
    }.get(kind, ["YoutubeDownloads/*.srt"])
    files: list[Path] = []
    for pattern in patterns:
        files.extend(ROOT.glob(pattern))
    return [str(path) for path in sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:80]]

INDEX_HTML = '<!doctype html>\n<html lang="zh-CN">\n<head>\n  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1" />\n  <title>Video Translate Agent</title>\n  <style>\n    :root {\n      color-scheme: light;\n      --bg: #eef1ef;\n      --ink: #172027;\n      --muted: #63717a;\n      --faint: #8a969d;\n      --surface: #ffffff;\n      --soft: #f6f8f7;\n      --line: #d8dfdc;\n      --line-strong: #b8c5c1;\n      --teal: #0b6f79;\n      --teal-dark: #075d65;\n      --teal-soft: #e3f1f2;\n      --amber: #9a6200;\n      --amber-soft: #f7eddd;\n      --green: #197346;\n      --green-soft: #e4f3eb;\n      --red: #b3261e;\n      --red-soft: #f9e7e5;\n      --violet: #6b4ab6;\n      --violet-soft: #efeafa;\n      --shadow: 0 18px 42px rgba(22, 32, 39, .10);\n    }\n    * { box-sizing: border-box; }\n    body {\n      margin: 0;\n      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;\n      background: var(--bg);\n      color: var(--ink);\n      letter-spacing: 0;\n      overflow-x: hidden;\n    }\n    header {\n      position: sticky;\n      top: 0;\n      z-index: 10;\n      display: grid;\n      grid-template-columns: minmax(220px, auto) minmax(0, 1fr) auto;\n      gap: 18px;\n      align-items: center;\n      padding: 14px 20px;\n      background: rgba(255,255,255,.96);\n      border-bottom: 1px solid var(--line);\n      backdrop-filter: blur(12px);\n    }\n    h1 { margin: 0; font-size: 18px; font-weight: 780; }\n    h2 { margin: 0; font-size: 15px; font-weight: 760; }\n    h3 { margin: 0; font-size: 13px; font-weight: 740; }\n    label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 12px; }\n    input, textarea {\n      width: 100%;\n      min-height: 38px;\n      border: 1px solid var(--line);\n      border-radius: 7px;\n      background: #fff;\n      color: var(--ink);\n      font: inherit;\n      outline: none;\n      padding: 9px 10px;\n    }\n    input:focus, textarea:focus { border-color: var(--teal); box-shadow: 0 0 0 3px var(--teal-soft); }\n    textarea {\n      min-height: 210px;\n      resize: vertical;\n      line-height: 1.45;\n      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;\n      font-size: 12px;\n    }\n    button {\n      min-height: 36px;\n      border: 1px solid var(--teal);\n      border-radius: 7px;\n      background: var(--teal);\n      color: #fff;\n      padding: 8px 12px;\n      font: inherit;\n      cursor: pointer;\n      white-space: nowrap;\n    }\n    button:hover { background: var(--teal-dark); border-color: var(--teal-dark); }\n    button.secondary { background: #fff; color: var(--teal); }\n    button.secondary:hover { background: var(--teal-soft); }\n    button.warning { background: var(--amber); border-color: var(--amber); }\n    button.warning:hover { background: #805100; border-color: #805100; }\n    button.ghost { background: transparent; border-color: var(--line-strong); color: var(--ink); }\n    button.ghost:hover { background: var(--soft); border-color: var(--line-strong); }\n    button.mini { min-height: 30px; padding: 5px 8px; font-size: 12px; }\n    button:disabled { opacity: .55; cursor: not-allowed; }\n    main {\n      display: grid;\n      grid-template-columns: minmax(0, 1fr) 410px;\n      gap: 16px;\n      max-width: 1540px;\n      margin: 0 auto;\n      padding: 16px;\n    }\n    .brand { display: grid; gap: 3px; }\n    .brand small, .muted { color: var(--muted); }\n    .steps {\n      display: grid;\n      grid-template-columns: repeat(4, minmax(0, 1fr));\n      gap: 8px;\n    }\n    .step {\n      display: grid;\n      gap: 2px;\n      min-height: 46px;\n      padding: 8px 10px;\n      border: 1px solid var(--line);\n      border-left: 4px solid var(--line-strong);\n      border-radius: 8px;\n      background: var(--soft);\n    }\n    .step strong { font-size: 12px; }\n    .step span { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n    .step.active { border-left-color: var(--teal); background: var(--teal-soft); }\n    .stack { display: grid; gap: 14px; min-width: 0; }\n    .panel {\n      background: var(--surface);\n      border: 1px solid var(--line);\n      border-radius: 8px;\n      padding: 14px;\n      box-shadow: 0 1px 0 rgba(255,255,255,.8) inset;\n      min-width: 0;\n    }\n    .primary-panel {\n      display: grid;\n      gap: 12px;\n      padding: 16px;\n      border-top: 5px solid var(--teal);\n      box-shadow: var(--shadow);\n    }\n    .panel-head {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      gap: 12px;\n      margin-bottom: 12px;\n    }\n    .url-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; }\n    .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }\n    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }\n    .status { min-height: 18px; margin-top: 8px; color: var(--muted); font-size: 12px; }\n    .ok { color: var(--green); }\n    .bad { color: var(--red); }\n    .path {\n      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;\n      font-size: 12px;\n      word-break: break-all;\n      overflow-wrap: anywhere;\n      white-space: pre-wrap;\n    }\n    .empty {\n      border: 1px dashed var(--line-strong);\n      border-radius: 8px;\n      padding: 14px;\n      color: var(--muted);\n      background: var(--soft);\n    }\n    .info-block {\n      display: grid;\n      gap: 6px;\n      padding: 12px;\n      border: 1px solid var(--line);\n      border-radius: 8px;\n      background: var(--soft);\n    }\n    .video-title { font-size: 15px; font-weight: 720; line-height: 1.35; word-break: break-word; }\n    .title-tools { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: end; }\n    .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }\n    .metric {\n      display: grid;\n      gap: 2px;\n      padding: 10px;\n      border: 1px solid var(--line);\n      border-radius: 8px;\n      background: var(--soft);\n    }\n    .metric b { font-size: 18px; }\n    .metric span { color: var(--muted); font-size: 12px; }\n    table { width: 100%; border-collapse: collapse; font-size: 13px; }\n    th, td { padding: 9px 7px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }\n    th { color: var(--muted); font-weight: 700; background: var(--soft); }\n    tr:last-child td { border-bottom: 0; }\n    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }\n    .table-wrap table th:first-child, .table-wrap table td:first-child { padding-left: 10px; }\n    .subtitle-section { display: grid; gap: 10px; }\n    .section-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; }\n    details.more-subtitles {\n      border: 1px solid var(--line);\n      border-radius: 8px;\n      background: #fff;\n      overflow: hidden;\n    }\n    details.more-subtitles summary {\n      display: flex;\n      justify-content: space-between;\n      gap: 12px;\n      padding: 11px 12px;\n      cursor: pointer;\n      color: var(--ink);\n      background: var(--soft);\n      list-style: none;\n    }\n    details.more-subtitles summary::-webkit-details-marker { display: none; }\n    details.more-subtitles summary:after { content: "展开"; color: var(--teal); font-size: 12px; }\n    details.more-subtitles[open] summary:after { content: "收起"; }\n    .badge, .pill {\n      display: inline-flex;\n      align-items: center;\n      height: 22px;\n      padding: 0 8px;\n      border-radius: 999px;\n      border: 1px solid var(--line);\n      background: var(--soft);\n      color: var(--muted);\n      font-size: 12px;\n    }\n    .badge.manual { color: var(--teal); background: var(--teal-soft); border-color: #c9e4e7; }\n    .badge.auto { color: var(--amber); background: var(--amber-soft); border-color: #ead9bd; }\n    .badge.core { color: var(--violet); background: var(--violet-soft); border-color: #ddd2f3; }\n    .review-list { display: grid; gap: 10px; }\n    .review-item { border: 1px solid var(--line); border-radius: 8px; background: var(--soft); padding: 12px; }\n    .review-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }\n    .review-title { font-size: 14px; font-weight: 700; word-break: break-word; }\n    .review-meta { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.45; word-break: break-word; }\n    .review-edit { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: end; }\n    aside { position: sticky; top: 86px; align-self: start; min-width: 0; }\n    .job { padding: 10px 0; border-bottom: 1px solid var(--line); }\n    .job:last-child { border-bottom: 0; }\n    .job-title { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; min-width: 0; }\n    .job-title span:first-child { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }\n    .pill.done { background: var(--green-soft); color: var(--green); border-color: #c6e6d1; }\n    .pill.failed { background: var(--red-soft); color: var(--red); border-color: #efc9c6; }\n    .log {\n      height: 430px;\n      overflow: auto;\n      border-radius: 8px;\n      padding: 12px;\n      background: #101820;\n      color: #d7e2ea;\n      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;\n      white-space: pre-wrap;\n      overflow-wrap: anywhere;\n      word-break: break-word;\n    }\n    .outputs { display: grid; gap: 8px; }\n    .output-line { padding: 8px 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--soft); min-width: 0; overflow-wrap: anywhere; }\n    .tabs { display: flex; gap: 6px; border-bottom: 1px solid var(--line); margin-bottom: 12px; }\n    .tab {\n      min-height: 34px;\n      padding: 6px 10px;\n      border: 0;\n      border-bottom: 2px solid transparent;\n      border-radius: 0;\n      background: transparent;\n      color: var(--muted);\n    }\n    .tab:hover { background: var(--soft); color: var(--ink); }\n    .tab.active { color: var(--teal); border-bottom-color: var(--teal); }\n    .tab-panel[hidden] { display: none; }\n    @media (max-width: 1120px) {\n      header { grid-template-columns: 1fr; }\n      main { grid-template-columns: 1fr; }\n      aside { position: static; }\n    }\n    @media (max-width: 760px) {\n      header { padding: 12px; }\n      main { padding: 12px; }\n      .steps, .url-row, .grid2, .title-tools, .review-edit, .summary-grid { grid-template-columns: 1fr; }\n      .toolbar { align-items: stretch; }\n      .toolbar button { flex: 1 1 auto; }\n    }\n  </style>\n</head>\n<body>\n  <header>\n    <div class="brand">\n      <h1>Video Translate Agent</h1>\n      <small>/path/to/Video_Translate</small>\n    </div>\n    <div class="steps">\n      <div class="step active"><strong>1. 检测</strong><span>识别标题与可用字幕</span></div>\n      <div class="step"><strong>2. 下载</strong><span>字幕优先，必要时下载视频</span></div>\n      <div class="step"><strong>3. 术语</strong><span>生成并人工确认 glossary</span></div>\n      <div class="step"><strong>4. 输出</strong><span>翻译 SRT 或 OCR 全流程</span></div>\n    </div>\n    <span class="badge core">中 / 英 / 日 / 韩优先</span>\n  </header>\n  <main>\n    <div class="stack">\n      <section class="panel primary-panel">\n        <div class="panel-head">\n          <h2>输入视频</h2>\n          <span class="muted">先检测字幕，有原生字幕就不用 OCR 时间轴</span>\n        </div>\n        <div class="url-row">\n          <div>\n            <label for="url">YouTube 链接或视频 ID</label>\n            <input id="url" placeholder="https://www.youtube.com/watch?v=..." />\n          </div>\n          <button id="probeBtn" onclick="probe()">检测字幕</button>\n        </div>\n        <div class="toolbar">\n          <button class="secondary" onclick="startDownloadVideo()">下载视频</button>\n          <button class="warning" onclick="startOcrFull()">下载视频并 OCR 翻译</button>\n        </div>\n        <div class="status" id="probeStatus"></div>\n      </section>\n\n      <section class="panel">\n        <div class="panel-head">\n          <h2>视频与字幕</h2>\n          <span class="badge" id="recommendBadge">未检测</span>\n        </div>\n        <div id="videoInfo" class="empty">还没有检测视频。</div>\n        <div id="titleTranslateBox" class="empty" style="margin-top:12px; display:none"></div>\n        <div id="subtitleList" style="margin-top:12px"></div>\n      </section>\n\n      <section class="panel">\n        <div class="panel-head">\n          <h2>翻译链路</h2>\n          <span class="muted">SRT -> Glossary -> 中文 SRT</span>\n        </div>\n        <div class="grid2">\n          <div><label for="sourceSrt">源字幕 SRT</label><input id="sourceSrt" placeholder="下载字幕后会自动填入，也可以手填" /></div>\n          <div><label for="glossaryPath">Glossary YAML</label><input id="glossaryPath" placeholder="生成草稿后会自动填入" /></div>\n        </div>\n        <div style="margin-top:12px">\n          <label for="extraHint">任务提示</label>\n          <input id="extraHint" placeholder="例如：视频里的人是朴宝英，作品名 Gold Land，角色名 禧主" />\n        </div>\n        <div class="toolbar" style="margin-top:12px">\n          <button class="secondary" onclick="generateGlossary()">生成草稿</button>\n          <button class="ghost" onclick="loadGlossary()">读取</button>\n          <button class="ghost" onclick="applyAllSuggestions()">全部采用推荐</button>\n          <button onclick="saveGlossaryReview()">保存审核</button>\n          <button class="secondary" onclick="saveGlossaryText()">保存 YAML</button>\n          <button onclick="translateSubtitle()">正式翻译</button>\n        </div>\n        <div class="status" id="flowStatus"></div>\n        <div class="tabs">\n          <button class="tab active" id="reviewTab" onclick="switchGlossaryTab(\'review\')">审核</button>\n          <button class="tab" id="yamlTab" onclick="switchGlossaryTab(\'yaml\')">YAML</button>\n        </div>\n        <div id="reviewPanel" class="tab-panel"><div id="glossaryReview" class="empty">生成或读取 glossary 后会显示逐条审核。</div></div>\n        <div id="yamlPanel" class="tab-panel" hidden><label for="glossaryEditor">Glossary YAML 文本</label><textarea id="glossaryEditor" placeholder="也可以直接编辑 YAML。"></textarea></div>\n      </section>\n    </div>\n\n    <aside class="stack">\n      <section class="panel"><div class="panel-head"><h2>任务</h2><span class="badge" id="jobCount">0</span></div><div id="jobs" class="empty">暂无任务。</div></section>\n      <section class="panel"><div class="panel-head"><h2>日志</h2><button class="ghost mini" onclick="clearLog()">清空</button></div><div id="log" class="log">等待任务输出...</div></section>\n      <section class="panel"><div class="panel-head"><h2>输出</h2></div><div id="outputs" class="empty">任务完成后会显示文件路径。</div></section>\n    </aside>\n  </main>\n\n<script>\nconst state = { probe: null, jobs: {}, activeJob: null, glossaryItems: [] };\nconst CORE_LANG_ORDER = [\'zh\', \'zh-cn\', \'zh-hans\', \'zh-hant\', \'en\', \'ko\', \'ja\', \'jp\'];\n\nasync function api(path, data) {\n  const res = await fetch(path, { method:\'POST\', headers:{\'Content-Type\':\'application/json\'}, body:JSON.stringify(data || {}) });\n  const json = await res.json();\n  if (!res.ok || json.error) throw new Error(json.error || \'request failed\');\n  return json;\n}\nfunction setText(id, text, cls) {\n  const el = document.getElementById(id);\n  el.className = \'status \' + (cls || \'\');\n  el.textContent = text || \'\';\n}\nasync function probe() {\n  const url = document.getElementById(\'url\').value.trim();\n  if (!url) return setText(\'probeStatus\',\'先输入视频链接。\',\'bad\');\n  document.getElementById(\'probeBtn\').disabled = true;\n  setText(\'probeStatus\',\'正在检测字幕...\');\n  try {\n    const data = await api(\'/api/probe\', {url});\n    state.probe = data;\n    renderProbe(data);\n    translateTitle(data.title || \'\');\n    const coreCount = (data.subtitles || []).filter(isCoreSubtitle).length;\n    const otherCount = (data.subtitles || []).length - coreCount;\n    const msg = data.subtitles.length ? `检测完成：推荐语言 ${coreCount} 条，其他语言 ${otherCount} 条。` : \'没有检测到外挂字幕，可以走 OCR。\';\n    setText(\'probeStatus\', msg, data.subtitles.length ? \'ok\' : \'\');\n  } catch (err) {\n    setText(\'probeStatus\', err.message, \'bad\');\n  } finally {\n    document.getElementById(\'probeBtn\').disabled = false;\n  }\n}\nfunction renderProbe(data) {\n  const subtitles = data.subtitles || [];\n  const dur = data.duration ? `${Math.floor(data.duration / 60)}:${String(data.duration % 60).padStart(2, \'0\')}` : \'未知\';\n  document.getElementById(\'recommendBadge\').textContent = data.recommendation === \'manual\' ? \'优先人工字幕\' : data.recommendation === \'auto\' ? \'可用自动字幕\' : \'建议 OCR\';\n  document.getElementById(\'videoInfo\').className = \'info-block\';\n  document.getElementById(\'videoInfo\').innerHTML = `<div class="video-title">${escapeHtml(data.title || \'Untitled\')}</div><div class="muted">ID: ${escapeHtml(data.id || \'\')} · 时长: ${dur}</div>`;\n  const root = document.getElementById(\'subtitleList\');\n  if (!subtitles.length) {\n    root.innerHTML = \'<div class="empty">没有外挂字幕。可以走 OCR 全流程。</div>\';\n    return;\n  }\n  const indexed = subtitles.map((item, index) => ({ item, index }));\n  const core = indexed.filter(({item}) => isCoreSubtitle(item)).sort(compareSubtitles);\n  const other = indexed.filter(({item}) => !isCoreSubtitle(item)).sort(compareSubtitles);\n  const manualCount = subtitles.filter(item => item.kind === \'manual\').length;\n  const autoCount = subtitles.filter(item => item.kind !== \'manual\').length;\n  const summary = `<div class="summary-grid"><div class="metric"><b>${subtitles.length}</b><span>全部字幕轨</span></div><div class="metric"><b>${manualCount}</b><span>人工字幕</span></div><div class="metric"><b>${autoCount}</b><span>自动字幕</span></div></div>`;\n  const coreBlock = core.length\n    ? `<div class="subtitle-section"><div class="section-title"><h3>推荐语言</h3><span class="badge core">只默认显示中英日韩</span></div>${subtitleTable(core)}</div>`\n    : \'<div class="empty">没有中 / 英 / 日 / 韩字幕。可以展开其他语言，或直接走 OCR。</div>\';\n  const otherBlock = other.length\n    ? `<details class="more-subtitles"><summary><span>其他语言字幕</span><span class="muted">${other.length} 条，默认折叠</span></summary>${subtitleTable(other)}</details>`\n    : \'\';\n  root.innerHTML = summary + coreBlock + otherBlock;\n}\nfunction subtitleTable(entries) {\n  const rows = entries.map(({item,index}) => `<tr><td>${escapeHtml(item.lang)}</td><td><span class="badge ${item.kind}">${item.kind === \'manual\' ? \'人工字幕\' : \'自动字幕\'}</span></td><td>${escapeHtml((item.formats || []).join(\', \') || \'-\')}</td><td><button class="secondary mini" onclick="downloadSubtitle(${index})">下载</button></td></tr>`).join(\'\');\n  return `<div class="table-wrap"><table><thead><tr><th>语言</th><th>类型</th><th>格式</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`;\n}\nfunction isCoreSubtitle(item) {\n  const lang = normalizeLang(item.lang);\n  if (CORE_LANG_ORDER.some(code => lang === code || lang.startsWith(code + \'-\') || lang.startsWith(code + \'_\'))) return true;\n  return /(中文|Chinese|英语|English|日语|Japanese|韩语|Korean|한국|日本)/i.test(String(item.lang || \'\'));\n}\nfunction compareSubtitles(a, b) {\n  const ak = subtitleRank(a.item);\n  const bk = subtitleRank(b.item);\n  if (ak !== bk) return ak - bk;\n  if (a.item.kind !== b.item.kind) return a.item.kind === \'manual\' ? -1 : 1;\n  return String(a.item.lang || \'\').localeCompare(String(b.item.lang || \'\'));\n}\nfunction subtitleRank(item) {\n  const lang = normalizeLang(item.lang);\n  const found = CORE_LANG_ORDER.findIndex(code => lang === code || lang.startsWith(code + \'-\') || lang.startsWith(code + \'_\'));\n  return found >= 0 ? found : 99;\n}\nfunction normalizeLang(lang) {\n  return String(lang || \'\').trim().toLowerCase().replace(/_/g, \'-\');\n}\nasync function translateTitle(title) {\n  const box = document.getElementById(\'titleTranslateBox\');\n  if (!title) { box.style.display = \'none\'; return; }\n  box.style.display = \'block\';\n  box.className = \'empty\';\n  box.innerHTML = \'<span class="muted">正在盲翻标题...</span>\';\n  try {\n    const data = await api(\'/api/translate-title\', {title});\n    box.className = \'info-block\';\n    box.innerHTML = `<label for="zhTitle">中文标题</label><div class="title-tools"><input id="zhTitle" value="${escapeAttr(data.zh_title || \'\')}" /><div class="toolbar"><button class="secondary" onclick="copyZhTitle()">复制</button><button class="secondary" onclick="appendTitleHint()">填入任务提示</button></div></div><div class="status">原标题：${escapeHtml(title)}</div>`;\n  } catch (err) {\n    box.className = \'empty\';\n    box.innerHTML = `<span class="bad">标题翻译失败：${escapeHtml(err.message)}</span><div class="status">原标题：${escapeHtml(title)}</div>`;\n  }\n}\nfunction copyZhTitle() {\n  const input = document.getElementById(\'zhTitle\');\n  if (!input) return;\n  navigator.clipboard?.writeText(input.value);\n  input.select();\n}\nfunction appendTitleHint() {\n  const input = document.getElementById(\'zhTitle\');\n  const hint = document.getElementById(\'extraHint\');\n  if (!input || !hint) return;\n  const text = `视频标题可参考译为：${input.value}`;\n  hint.value = hint.value.trim() ? `${hint.value.trim()}；${text}` : text;\n}\nasync function downloadSubtitle(index) {\n  const item = state.probe.subtitles[index];\n  const url = document.getElementById(\'url\').value.trim();\n  const job = await api(\'/api/jobs/download-subtitle\', {url, lang:item.lang, kind:item.kind});\n  watchJob(job.id);\n}\nasync function startDownloadVideo() {\n  const url = document.getElementById(\'url\').value.trim();\n  if (!url) return setText(\'probeStatus\',\'先输入视频链接。\',\'bad\');\n  const job = await api(\'/api/jobs/download-video\', {url});\n  watchJob(job.id);\n}\nasync function generateGlossary() {\n  const source = document.getElementById(\'sourceSrt\').value.trim();\n  if (!source) return setText(\'flowStatus\',\'先下载或填写源字幕 SRT。\',\'bad\');\n  const job = await api(\'/api/jobs/generate-glossary\', {source_srt:source, extra_hint:document.getElementById(\'extraHint\').value.trim()});\n  watchJob(job.id);\n}\nasync function loadGlossary() {\n  const path = document.getElementById(\'glossaryPath\').value.trim();\n  if (!path) return setText(\'flowStatus\',\'先填写 glossary 路径。\',\'bad\');\n  try {\n    const data = await api(\'/api/read-text\', {path});\n    document.getElementById(\'glossaryEditor\').value = data.content;\n    await loadGlossaryReview(path);\n    setText(\'flowStatus\',\'glossary 已读取。\',\'ok\');\n  } catch (err) {\n    setText(\'flowStatus\',err.message,\'bad\');\n  }\n}\nasync function loadGlossaryReview(path) {\n  const data = await api(\'/api/read-glossary-items\', {path});\n  state.glossaryItems = data.items || [];\n  renderGlossaryReview();\n}\nfunction renderGlossaryReview() {\n  const root = document.getElementById(\'glossaryReview\');\n  const items = state.glossaryItems || [];\n  if (!items.length) {\n    root.className = \'empty\';\n    root.textContent = \'没有需要审核的条目。\';\n    return;\n  }\n  root.className = \'review-list\';\n  root.innerHTML = items.map((item, i) => `<div class="review-item"><div class="review-head"><div><div class="review-title">${escapeHtml(item.source || \'(empty)\')}</div><div class="review-meta">${escapeHtml(item.section)} · ${escapeHtml(item.type || \'\')}${item.aliases?.length ? \' · aliases: \' + escapeHtml(item.aliases.join(\', \')) : \'\'}</div></div><span class="pill ${item.zh ? \'done\' : \'\'}">${item.zh ? \'已填\' : \'待填\'}</span></div><div class="review-edit"><div><label>中文译名</label><input class="review-zh" data-index="${i}" value="${escapeAttr(item.zh || \'\')}" placeholder="${escapeAttr(item.suggested_zh || \'\')}" /></div><button class="secondary mini" onclick="useSuggestion(${i})" ${item.suggested_zh ? \'\' : \'disabled\'}>用推荐：${escapeHtml(item.suggested_zh || \'无\')}</button></div>${item.note ? `<div class="review-meta">${escapeHtml(item.note)}</div>` : \'\'}</div>`).join(\'\');\n}\nfunction useSuggestion(i) {\n  const item = state.glossaryItems[i];\n  const input = document.querySelector(`.review-zh[data-index="${i}"]`);\n  if (input && item?.suggested_zh) input.value = item.suggested_zh;\n}\nfunction applyAllSuggestions() {\n  document.querySelectorAll(\'.review-zh\').forEach(input => {\n    const item = state.glossaryItems[Number(input.dataset.index)];\n    if (item?.suggested_zh && !input.value.trim()) input.value = item.suggested_zh;\n  });\n}\nasync function saveGlossaryReview() {\n  const path = document.getElementById(\'glossaryPath\').value.trim();\n  if (!path) return setText(\'flowStatus\',\'先填写 glossary 路径。\',\'bad\');\n  const items = Array.from(document.querySelectorAll(\'.review-zh\')).map(input => ({...state.glossaryItems[Number(input.dataset.index)], zh: input.value.trim()}));\n  try {\n    const data = await api(\'/api/write-glossary-items\', {path, items});\n    state.glossaryItems = data.items || [];\n    document.getElementById(\'glossaryEditor\').value = data.content || \'\';\n    renderGlossaryReview();\n    setText(\'flowStatus\',\'审核结果已保存。\',\'ok\');\n  } catch (err) {\n    setText(\'flowStatus\',err.message,\'bad\');\n  }\n}\nasync function saveGlossaryText() {\n  const path = document.getElementById(\'glossaryPath\').value.trim();\n  if (!path) return setText(\'flowStatus\',\'先填写 glossary 路径。\',\'bad\');\n  try {\n    await api(\'/api/write-text\', {path, content:document.getElementById(\'glossaryEditor\').value});\n    await loadGlossaryReview(path);\n    setText(\'flowStatus\',\'YAML 已保存。\',\'ok\');\n  } catch (err) {\n    setText(\'flowStatus\',err.message,\'bad\');\n  }\n}\nasync function translateSubtitle() {\n  const source = document.getElementById(\'sourceSrt\').value.trim();\n  if (!source) return setText(\'flowStatus\',\'先填写源字幕 SRT。\',\'bad\');\n  const glossary = document.getElementById(\'glossaryPath\').value.trim();\n  const job = await api(\'/api/jobs/translate-subtitle\', {source_srt:source, glossary});\n  watchJob(job.id);\n}\nasync function startOcrFull() {\n  const url = document.getElementById(\'url\').value.trim();\n  if (!url) return setText(\'probeStatus\',\'先输入视频链接。\',\'bad\');\n  const job = await api(\'/api/jobs/ocr-full\', {url, title:state.probe?.title || \'\', extra_hint:document.getElementById(\'extraHint\').value.trim()});\n  watchJob(job.id);\n}\nfunction watchJob(id) {\n  state.activeJob = id;\n  pollJob(id);\n}\nasync function pollJob(id) {\n  const res = await fetch(`/api/jobs/${id}`);\n  const job = await res.json();\n  state.jobs[id] = job;\n  renderJobs();\n  renderLog(job);\n  if (job.status === \'done\') applyJobResult(job);\n  if (job.status === \'running\') setTimeout(()=>pollJob(id), 1000);\n}\nfunction renderJobs() {\n  const jobs = Object.values(state.jobs).sort((a,b)=>b.created_at-a.created_at);\n  document.getElementById(\'jobCount\').textContent = String(jobs.length);\n  const root = document.getElementById(\'jobs\');\n  if (!jobs.length) {\n    root.className=\'empty\';\n    root.textContent=\'暂无任务。\';\n    return;\n  }\n  root.className=\'\';\n  root.innerHTML = jobs.map(job=>`<div class="job"><div class="job-title"><span>${escapeHtml(job.name)}</span><span class="pill ${job.status}">${job.status}</span></div><div class="muted path">${job.id}</div>${job.error ? `<div class="bad">${escapeHtml(job.error)}</div>` : \'\'}</div>`).join(\'\');\n}\nfunction renderLog(job) {\n  const log = document.getElementById(\'log\');\n  log.textContent = (job.logs || []).join(\'\\n\') || \'等待任务输出...\';\n  log.scrollTop = log.scrollHeight;\n}\nfunction clearLog() {\n  document.getElementById(\'log\').textContent = \'等待任务输出...\';\n}\nasync function applyJobResult(job) {\n  const result = job.result || {};\n  if (result.subtitle_path) document.getElementById(\'sourceSrt\').value = result.subtitle_path;\n  if (result.glossary_path) {\n    document.getElementById(\'glossaryPath\').value = result.glossary_path;\n    if (result.content) document.getElementById(\'glossaryEditor\').value = result.content;\n    try {\n      await loadGlossaryReview(result.glossary_path);\n      switchGlossaryTab(\'review\');\n    } catch (err) {\n      setText(\'flowStatus\', err.message, \'bad\');\n    }\n  }\n  renderOutputs(result);\n}\nfunction renderOutputs(result) {\n  const entries = Object.entries(result || {}).filter(([_,value]) => value && (typeof value === \'string\' || Array.isArray(value)));\n  const root = document.getElementById(\'outputs\');\n  if (!entries.length) return;\n  root.className=\'outputs\';\n  root.innerHTML = entries.map(([key,value])=>`<div class="output-line"><div class="muted">${escapeHtml(key)}</div><div class="path">${escapeHtml(Array.isArray(value) ? value.join(\'\\n\') : value)}</div></div>`).join(\'\');\n}\nfunction switchGlossaryTab(name) {\n  document.getElementById(\'reviewPanel\').hidden = name !== \'review\';\n  document.getElementById(\'yamlPanel\').hidden = name !== \'yaml\';\n  document.getElementById(\'reviewTab\').classList.toggle(\'active\', name === \'review\');\n  document.getElementById(\'yamlTab\').classList.toggle(\'active\', name === \'yaml\');\n}\nfunction escapeHtml(value) {\n  return String(value).replace(/[&<>"\']/g, ch => ({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[ch]));\n}\nfunction escapeAttr(value) {\n  return escapeHtml(value).replace(/`/g, \'&#96;\');\n}\n</script>\n</body>\n</html>\n'
