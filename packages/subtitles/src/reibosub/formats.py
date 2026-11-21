"""String-based subtitle codecs and an instance-scoped extension registry.

These codecs deliberately do not import the web application's file/database layer.
The unified model preserves dialogue and timing, not complete native layout.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Protocol, runtime_checkable

from .errors import SubtitleFormatError, ValidationError
from .models import Cue, Subtitle


@runtime_checkable
class SubtitleCodec(Protocol):
    def loads(self, text: str) -> Subtitle: ...
    def dumps(self, subtitle: Subtitle) -> str: ...


def _name(value: str) -> str:
    if not isinstance(value, str):
        raise SubtitleFormatError("format must be a string")
    value = value.lower().lstrip(".")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
        raise SubtitleFormatError("provide a subtitle format or a file extension")
    return value


def format_time(seconds: float, *, separator: str = ",") -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def _time(text: str) -> float:
    match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{1,3})", text.strip())
    if not match:
        raise SubtitleFormatError("invalid subtitle timestamp")
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise SubtitleFormatError("minutes and seconds must be below 60")
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")) / 1000


class _TimedText:
    def __init__(self, fmt: str):
        self.fmt = fmt

    def loads(self, text: str) -> Subtitle:
        text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        cues = []
        for block in re.split(r"\n[ \t]*\n", text.strip()):
            if not block.strip():
                continue
            lines = block.splitlines()
            if self.fmt == "vtt" and re.match(r"^(?:WEBVTT|NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
                continue
            position = 0 if "-->" in lines[0] else 1
            if position >= len(lines) or "-->" not in lines[position]:
                raise SubtitleFormatError("subtitle block has no valid timing line")
            start, end = lines[position].split("-->", 1)
            end_parts = end.strip().split()
            if not end_parts:
                raise SubtitleFormatError("missing subtitle end time")
            if self.fmt == "srt" and len(end_parts) != 1:
                raise SubtitleFormatError("unexpected SRT timing suffix")
            index = int(lines[0]) if position == 1 and lines[0].isdigit() else len(cues) + 1
            cues.append(Cue(index=index, start=_time(start), end=_time(end_parts[0]), text="\n".join(lines[position + 1:])))
        notices = ("WebVTT identifiers, cue settings and regions are not retained.",) if self.fmt == "vtt" else ()
        return Subtitle(tuple(cues), notices=notices)

    def dumps(self, subtitle: Subtitle) -> str:
        sep = "." if self.fmt == "vtt" else ","
        if any(round(cue.end * 1000) <= round(cue.start * 1000) for cue in subtitle):
            raise SubtitleFormatError("cue duration is below SRT/WebVTT millisecond precision")
        blocks = [f"{cue.index}\n{format_time(cue.start, separator=sep)} --> {format_time(cue.end, separator=sep)}\n{cue.text}" for cue in subtitle]
        return ("WEBVTT\n\n" if self.fmt == "vtt" else "") + "\n\n".join(blocks) + ("\n" if blocks else "")


class _Json:
    def __init__(self, bcc: bool = False):
        self.bcc = bcc

    def loads(self, text: str) -> Subtitle:
        data = json.loads(text)
        if not self.bcc:
            return Subtitle.from_dict({"cues": data} if isinstance(data, list) else data)
        if not isinstance(data, (list, dict)):
            raise SubtitleFormatError("BCC requires an object or array")
        rows = data if isinstance(data, list) else data.get("body")
        if not isinstance(rows, list):
            raise SubtitleFormatError("BCC requires a body array")
        cues = tuple(Cue(index=index, start=row["from"], end=row["to"], text=row["content"]) for index, row in enumerate(rows, 1))
        return Subtitle(cues, notices=("BCC appearance and location metadata are not retained.",))

    def dumps(self, subtitle: Subtitle) -> str:
        data = {"body": [{"from": cue.start, "to": cue.end, "location": 2, "content": cue.text} for cue in subtitle]} if self.bcc else subtitle.to_dict()
        return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


class _Ass:
    def __init__(self, ssa: bool = False):
        self.ssa = ssa

    def loads(self, text: str) -> Subtitle:
        columns = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        in_events, cues = False, []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                in_events = line.lower() == "[events]"
            if not in_events:
                continue
            if line.lower().startswith("format:"):
                columns = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
                if not columns or columns[-1] != "text" or not {"start", "end", "text"}.issubset(columns):
                    raise SubtitleFormatError("ASS/SSA Events require Start, End and final Text columns")
            if line.lower().startswith("dialogue:"):
                parts = line.split(":", 1)[1].lstrip().split(",", len(columns) - 1)
                if len(parts) != len(columns):
                    raise SubtitleFormatError("invalid ASS/SSA dialogue fields")
                row = dict(zip(columns, parts))
                content = re.sub(r"\{[^}]*\}", "", row["text"]).replace(r"\N", "\n").replace(r"\n", "\n")
                cues.append(Cue(index=len(cues) + 1, start=_time(row["start"]), end=_time(row["end"]), text=content, speaker=row.get("name") or None))
        return Subtitle(tuple(cues), notices=("ASS/SSA styles, position, drawings and effects are not retained by the unified model.",))

    def dumps(self, subtitle: Subtitle) -> str:
        if self.ssa:
            header = "[Script Info]\nScriptType: v4.00\n\n[V4 Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\nStyle: Default,Arial,42,16777215,0,0,0,0,0,1,2,0,2,20,20,20,0,1\n\n[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        else:
            header = "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,42,&H00FFFFFF,&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        lines = []
        for cue in subtitle:
            start, end = round(cue.start * 100), round(cue.end * 100)
            if end <= start:
                raise SubtitleFormatError("cue duration is below ASS/SSA centisecond precision")
            speaker = cue.speaker or ""
            if any(char in speaker for char in ",\r\n"):
                raise SubtitleFormatError("ASS/SSA speaker names cannot contain commas or newlines")
            def clock(value):
                hours, rest = divmod(value, 360000)
                minutes, rest = divmod(rest, 6000)
                seconds, fraction = divmod(rest, 100)
                return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"
            content = cue.text.replace("\n", r"\N")
            layer = "Marked=0" if self.ssa else "0"
            lines.append(f"Dialogue: {layer},{clock(start)},{clock(end)},Default,{speaker},0,0,0,,{content}\n")
        return header + "".join(lines)


class _Lrc:
    def loads(self, text: str) -> Subtitle:
        entries = []
        for line in text.splitlines():
            if not line.strip() or re.match(r"^\[(?:ar|al|ti|by|offset|re|ve):", line, re.I):
                continue
            match = re.fullmatch(r"((?:\[\d+:\d{2}(?:[.:]\d{1,3})?\])+)(.*)", line)
            if not match:
                raise SubtitleFormatError("invalid LRC line")
            for minutes, seconds, fraction in re.findall(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]", match[1]):
                if int(seconds) >= 60:
                    raise SubtitleFormatError("invalid LRC seconds")
                entries.append((int(minutes) * 60 + int(seconds) + int((fraction or "0").ljust(3, "0")) / 1000, match[2]))
        entries.sort(key=lambda item: item[0])
        cues = tuple(Cue(index=i + 1, start=start, end=entries[i + 1][0] if i + 1 < len(entries) and entries[i + 1][0] > start else start + 3, text=content) for i, (start, content) in enumerate(entries))
        return Subtitle(cues, notices=("LRC end times are inferred; the final cue uses a 3-second duration.",))

    def dumps(self, subtitle: Subtitle) -> str:
        lines = []
        for cue in subtitle:
            minutes, rest = divmod(round(cue.start * 100), 6000)
            seconds, fraction = divmod(rest, 100)
            lines.append(f"[{minutes:02}:{seconds:02}.{fraction:02}]" + " ".join(cue.text.splitlines()))
        return "\n".join(lines) + ("\n" if lines else "")


class _Txt:
    def loads(self, text: str) -> Subtitle:
        lines = [line for line in text.splitlines() if line.strip()]
        return Subtitle(tuple(Cue(index=i + 1, start=i * 3, end=(i + 1) * 3, text=line) for i, line in enumerate(lines)), notices=("TXT timing is synthetic: 3 seconds per nonempty line, not audio alignment.",))

    def dumps(self, subtitle: Subtitle) -> str:
        return subtitle.to_text() + ("\n" if subtitle.cues else "")


class FormatRegistry:
    """Register custom codecs on your own instance, without global side effects."""

    def __init__(self, *, include_defaults: bool = True) -> None:
        self._codecs: dict[str, SubtitleCodec] = {}
        if include_defaults:
            self._codecs.update({"srt": _TimedText("srt"), "vtt": _TimedText("vtt"), "json": _Json(), "bcc": _Json(True), "ass": _Ass(), "ssa": _Ass(True), "lrc": _Lrc(), "txt": _Txt()})

    @property
    def formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._codecs))

    def register(self, format: str, codec: SubtitleCodec, *, replace_existing: bool = False) -> None:
        name = _name(format)
        if name in self._codecs and not replace_existing:
            raise ValidationError(f"codec already registered: {name}")
        if not callable(getattr(codec, "loads", None)) or not callable(getattr(codec, "dumps", None)):
            raise ValidationError("codec must implement loads(text) and dumps(subtitle)")
        self._codecs[name] = codec

    def _get(self, format: str) -> SubtitleCodec:
        name = _name(format)
        if name not in self._codecs:
            raise SubtitleFormatError(f"unsupported subtitle format: {name}")
        return self._codecs[name]

    def loads(self, text: str, format: str) -> Subtitle:
        if not isinstance(text, str):
            raise SubtitleFormatError("subtitle content must be a string")
        codec = self._get(format)
        try:
            result = codec.loads(text.removeprefix("\ufeff"))
            if not isinstance(result, Subtitle):
                raise SubtitleFormatError("codec loads() must return Subtitle")
            return replace(result, source_format=_name(format))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            if isinstance(exc, SubtitleFormatError):
                raise
            raise SubtitleFormatError(f"invalid {format} subtitle: {exc}") from exc

    def dumps(self, subtitle: Subtitle, format: str) -> str:
        if not isinstance(subtitle, Subtitle):
            raise ValidationError("dumps() requires Subtitle")
        result = self._get(format).dumps(subtitle)
        if not isinstance(result, str):
            raise SubtitleFormatError("codec dumps() must return str")
        return result


_DEFAULT: FormatRegistry | None = None


def default_registry() -> FormatRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FormatRegistry()
    return _DEFAULT
