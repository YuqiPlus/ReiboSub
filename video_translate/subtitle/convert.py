from __future__ import annotations

import html
import json
import re
from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.utils.timecode import format_srt_time


SUPPORTED_FORMATS = {"srt", "vtt", "ass", "ssa", "bcc", "json", "lrc", "txt"}


def convert_subtitle_file(
    source: Path,
    out: Path | None = None,
    *,
    output_format: str | None = None,
) -> Path:
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"字幕文件不存在: {source}")
    fmt = normalize_subtitle_format(output_format or (out.suffix[1:] if out else "srt"))
    if out is None:
        out = source.with_suffix(f".{fmt}")
    else:
        out = out.expanduser().resolve()
    cues = read_subtitle_file(source)
    write_subtitle_file(cues, out, fmt)
    return out


def normalize_subtitle_format(value: str) -> str:
    fmt = str(value or "").strip().lower().lstrip(".")
    if fmt == "bbc":
        fmt = "bcc"
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"不支持的字幕格式: {value}; 支持 {', '.join(sorted(SUPPORTED_FORMATS))}")
    return fmt


def read_subtitle_file(path: Path) -> list[SubtitleCue]:
    fmt = normalize_subtitle_format(path.suffix[1:])
    if fmt == "srt":
        return read_srt(path)
    if fmt == "vtt":
        return _read_vtt(path)
    if fmt == "bcc":
        return _read_bcc(path)
    if fmt == "json":
        return _read_json(path)
    if fmt in {"ass", "ssa"}:
        return _read_ass(path)
    if fmt == "lrc":
        return _read_lrc(path)
    if fmt == "txt":
        return _read_txt(path)
    raise ValueError(f"不支持读取格式: {fmt}")


def write_subtitle_file(cues: list[SubtitleCue], path: Path, output_format: str) -> None:
    fmt = normalize_subtitle_format(output_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "srt":
        write_srt(cues, path)
    elif fmt == "vtt":
        _write_vtt(cues, path)
    elif fmt in {"ass", "ssa"}:
        _write_ass(cues, path, script_type="v4.00+" if fmt == "ass" else "v4.00")
    elif fmt == "bcc":
        _write_bcc(cues, path)
    elif fmt == "json":
        _write_json(cues, path)
    elif fmt == "lrc":
        _write_lrc(cues, path)
    elif fmt == "txt":
        _write_txt(cues, path)
    else:
        raise ValueError(f"不支持输出格式: {fmt}")


def _read_vtt(path: Path) -> list[SubtitleCue]:
    content = path.read_text(encoding="utf-8-sig")
    content = re.sub(r"^\s*WEBVTT.*?(?:\n\s*\n|$)", "", content, count=1, flags=re.S)
    blocks = re.split(r"\n\s*\n", content.strip())
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if time_index < 0:
            continue
        start_raw, end_raw = lines[time_index].split("-->", 1)
        end_raw = end_raw.strip().split()[0]
        text = "\n".join(_strip_markup(line) for line in lines[time_index + 1 :])
        cues.append(SubtitleCue(index=len(cues) + 1, start=_parse_time(start_raw), end=_parse_time(end_raw), text=text))
    return cues


def _write_vtt(cues: list[SubtitleCue], path: Path) -> None:
    blocks = ["WEBVTT", ""]
    for cue in cues:
        blocks.extend(
            [
                str(cue.index),
                f"{_format_vtt_time(cue.start)} --> {_format_vtt_time(cue.end)}",
                cue.text.strip(),
                "",
            ]
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


def _read_bcc(path: Path) -> list[SubtitleCue]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    body = data.get("body") if isinstance(data, dict) else data
    if not isinstance(body, list):
        raise ValueError("BCC 内容必须包含 body 数组")
    cues: list[SubtitleCue] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        start = float(item.get("from", item.get("start", 0.0)))
        end = float(item.get("to", item.get("end", start)))
        text = str(item.get("content", item.get("text", "")))
        cues.append(SubtitleCue(index=len(cues) + 1, start=start, end=end, text=text))
    return cues


def _write_bcc(cues: list[SubtitleCue], path: Path) -> None:
    data = {
        "font_size": 0.4,
        "font_color": "#FFFFFF",
        "background_alpha": 0.5,
        "background_color": "#9C27B0",
        "Stroke": "none",
        "body": [
            {
                "from": round(cue.start, 3),
                "to": round(cue.end, 3),
                "location": 2,
                "content": cue.text.strip(),
            }
            for cue in cues
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> list[SubtitleCue]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("cues") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("JSON 字幕必须是数组或包含 cues 数组")
    cues: list[SubtitleCue] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", item.get("start", 0.0))),
                text=str(item.get("text", "")),
            )
        )
    return cues


def _write_json(cues: list[SubtitleCue], path: Path) -> None:
    path.write_text(json.dumps({"cues": [cue.to_dict() for cue in cues]}, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_ass(path: Path) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        payload = line.split(":", 1)[1].strip()
        parts = payload.split(",", 9)
        if len(parts) < 10:
            continue
        text = _strip_ass_text(parts[9])
        cues.append(SubtitleCue(index=len(cues) + 1, start=_parse_ass_time(parts[1]), end=_parse_ass_time(parts[2]), text=text))
    return cues


def _write_ass(cues: list[SubtitleCue], path: Path, *, script_type: str) -> None:
    lines = [
        "[Script Info]",
        f"ScriptType: {script_type}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,42,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,36,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        text = _escape_ass_text(cue.text.strip())
        lines.append(f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_lrc(path: Path) -> list[SubtitleCue]:
    entries: list[tuple[float, str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\](.*)", line)
        if not match:
            continue
        minutes, seconds, fraction, text = match.groups()
        frac = (fraction or "0").ljust(3, "0")[:3]
        entries.append((int(minutes) * 60 + int(seconds) + int(frac) / 1000, text.strip()))
    cues: list[SubtitleCue] = []
    for idx, (start, text) in enumerate(entries):
        end = entries[idx + 1][0] if idx + 1 < len(entries) else start + 3.0
        cues.append(SubtitleCue(index=idx + 1, start=start, end=max(end, start + 0.2), text=text))
    return cues


def _write_lrc(cues: list[SubtitleCue], path: Path) -> None:
    lines = [f"[{_format_lrc_time(cue.start)}]{_single_line(cue.text)}" for cue in cues]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_txt(path: Path) -> list[SubtitleCue]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return [SubtitleCue(index=index, start=(index - 1) * 3.0, end=index * 3.0, text=line) for index, line in enumerate(lines, start=1)]


def _write_txt(cues: list[SubtitleCue], path: Path) -> None:
    lines = [f"[{format_srt_time(cue.start)}] {cue.text.strip()}" for cue in cues]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_time(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"无法解析时间: {value}")


def _parse_ass_time(value: str) -> float:
    return _parse_time(value)


def _format_vtt_time(seconds: float) -> str:
    return format_srt_time(seconds).replace(",", ".")


def _format_ass_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{millis // 10:02d}"


def _format_lrc_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    minutes, remainder = divmod(milliseconds, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis // 10:02d}"


def _strip_markup(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _strip_ass_text(text: str) -> str:
    text = re.sub(r"\{[^}]*\}", "", text)
    return text.replace(r"\N", "\n").replace(r"\n", "\n").strip()


def _escape_ass_text(text: str) -> str:
    return text.replace("\n", r"\N").replace("{", r"\{").replace("}", r"\}")


def _single_line(text: str) -> str:
    return " ".join(part.strip() for part in text.splitlines() if part.strip())
