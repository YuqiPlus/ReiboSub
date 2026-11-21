"""Standalone subtitle uploads and mechanical operations; no Agent/project creation."""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

from video_translate.chinese_script import convert_chinese_text, normalize_chinese_script
from video_translate.subtitle.convert import normalize_subtitle_format, read_subtitle_file, write_subtitle_file
from video_translate.subtitle.srt import write_srt
from video_translate.youtube.filenames import filesystem_safe_title

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CUES = 20000
ENCODINGS = {"utf-8-sig", "utf-16", "gb18030", "big5"}


def _validate_cues(cues):
    if not cues:
        raise ValueError("没有读到有效字幕，请检查文件格式与编码")
    if len(cues) > MAX_CUES:
        raise ValueError(f"单文件最多支持 {MAX_CUES} 条字幕")
    if any(not math.isfinite(c.start) or not math.isfinite(c.end) or c.start < 0 or c.end <= c.start for c in cues):
        raise ValueError("字幕存在无效时间段，请先修复开始/结束时间")


def save_upload(root: Path, *, filename: str, content: bytes, encoding: str = "utf-8-sig") -> dict:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("请上传非空且不超过 10 MB 的字幕文件")
    filename = Path(str(filename).replace("\\", "/")).name
    fmt = normalize_subtitle_format(Path(filename).suffix)
    if encoding not in ENCODINGS:
        raise ValueError("不支持的字幕编码")
    try:
        text = content.decode(encoding)
    except UnicodeError as exc:
        raise ValueError("字幕解码失败，请在编码选项中选择 UTF-8、UTF-16、GB18030 或 Big5 后重新上传") from exc
    if "\x00" in text:
        raise ValueError("字幕包含无效字符，请检查文件类型或编码")
    upload_id = uuid.uuid4().hex
    directory = root / upload_id
    directory.mkdir(parents=True, exist_ok=False)
    stem = filesystem_safe_title(Path(filename).stem).strip(". ")[:100] or "subtitle"
    source = directory / f"source.{fmt}"
    original = directory / f"original.{fmt}"
    try:
        original.write_bytes(content)
        source.write_text(text, encoding="utf-8")
        cues = read_subtitle_file(source)
        _validate_cues(cues)
        write_srt(cues, directory / "normalized.srt")
        info = {"upload_id": upload_id, "name": stem + "." + fmt, "format": fmt, "encoding": encoding, "cue_count": len(cues), "preview": [cue.to_dict() for cue in cues[:6]]}
        (directory / "upload.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return info
    except Exception:
        # Only remove this call's private, newly created upload directory.
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        raise


def load_upload(root: Path, upload_id: str) -> tuple[dict, Path]:
    if not isinstance(upload_id, str) or not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise ValueError("请先上传字幕文件")
    directory = (root / upload_id).resolve()
    if not directory.is_relative_to(root.resolve()):
        raise ValueError("字幕文件路径无效")
    try:
        info = json.loads((directory / "upload.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError("上传的字幕已不存在，请重新上传") from exc
    return info, directory


def _convert_markup_text(text: str, script: str) -> str:
    # Do not rename ASS override parameters, HTML tags, fonts or voice attributes.
    return "".join(piece if index % 2 else convert_chinese_text(piece, script)
                   for index, piece in enumerate(re.split(r"(<[^>]*>|\{\\[^}]*\})", text)))


def convert_script_document(text: str, fmt: str, script: str) -> str:
    """Convert text fields only, retaining native timing/layout/metadata."""
    script = normalize_chinese_script(script)
    if fmt in {"json", "bcc"}:
        data = json.loads(text)
        rows = data if isinstance(data, list) else data["body" if fmt == "bcc" else "cues"]
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("text", "content"):
                if isinstance(row.get(key), str):
                    row[key] = _convert_markup_text(row[key], script)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if fmt in {"ass", "ssa"}:
        output = []
        for line in text.splitlines(keepends=True):
            parts = line.split(",", 9) if line.startswith("Dialogue:") else []
            if len(parts) == 10:
                line = ",".join(parts[:9]) + "," + _convert_markup_text(parts[9], script)
            output.append(line)
        return "".join(output)
    if fmt == "lrc":
        return "".join(re.sub(r"^(\[\d{1,}:\d{2}(?:[.:]\d{1,3})?\])(.*)", lambda m: m[1] + _convert_markup_text(m[2], script), line) for line in text.splitlines(keepends=True))
    if fmt in {"srt", "vtt"}:
        blocks = re.split(r"(\r?\n[ \t]*\r?\n)", text)
        for index in range(0, len(blocks), 2):
            lines = blocks[index].splitlines(keepends=True)
            if not lines or re.match(r"^(?:WEBVTT|NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
                continue
            timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing is not None:
                blocks[index] = "".join(lines[:timing + 1]) + _convert_markup_text("".join(lines[timing + 1:]), script)
        return "".join(blocks)
    return convert_chinese_text(text, script)


def run_mechanical(info: dict, directory: Path, output_dir: Path, *, operation: str, output_format: str = "srt", script: str = "simplified") -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = directory / f"source.{info['format']}"
    stem = Path(info["name"]).stem
    if operation == "convert":
        fmt = normalize_subtitle_format(output_format)
        out = output_dir / f"{stem}.converted.{fmt}"
        cues = read_subtitle_file(source)
        write_subtitle_file(cues, out, fmt)
    elif operation == "script":
        script = normalize_chinese_script(script)
        fmt = info["format"]
        out = output_dir / f"{stem}.{script}.{fmt}"
        out.write_text(convert_script_document(source.read_text(encoding="utf-8"), fmt, script), encoding="utf-8")
        cues = read_subtitle_file(out)
    else:
        raise ValueError("不支持的字幕工具操作")
    return {"kind": "subtitle_toolbox", "operation": operation, "output_path": str(out), "format": fmt, "cue_count": len(cues), "preview": [cue.to_dict() for cue in cues[:6]], "input_name": info["name"], "chinese_script": script if operation == "script" else None}
