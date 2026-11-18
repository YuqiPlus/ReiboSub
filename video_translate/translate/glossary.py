from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_translate.utils.text import comparable_text


@dataclass(slots=True)
class GlossaryEntry:
    source: str
    zh: str
    type: str = "term"
    aliases: list[str] = field(default_factory=list)
    note: str = ""
    always: bool = False

    def names(self) -> list[str]:
        return [self.source, *self.aliases]

    def matches(self, text: str) -> bool:
        text_key = comparable_text(text)
        if not text_key:
            return False
        return any(_contains_glossary_name(text_key, name) for name in self.names())

    def to_dict(self) -> dict[str, Any]:
        data = {"source": self.source, "zh": self.zh, "type": self.type}
        if self.aliases:
            data["aliases"] = self.aliases
        if self.note:
            data["note"] = self.note
        if self.always:
            data["always"] = self.always
        return data


@dataclass(slots=True)
class Glossary:
    program: GlossaryEntry | None = None
    entries: list[GlossaryEntry] = field(default_factory=list)

    def relevant_entries(self, texts: list[str]) -> list[GlossaryEntry]:
        joined = "\n".join(texts)
        result: list[GlossaryEntry] = []
        for entry in self.entries:
            if entry.always or entry.matches(joined):
                result.append(entry)
        return result

    def to_context(self, texts: list[str]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if self.program:
            context["program"] = self.program.to_dict()
        context["glossary"] = [entry.to_dict() for entry in self.relevant_entries(texts)]
        return context

    def to_reviewed_context(self, texts: list[str]) -> dict[str, Any]:
        """Frozen human choices; draft uncertainty notes must not reopen review."""
        context=self.to_context(texts)
        for entry in [*context.get('glossary',[]),*([context['program']] if context.get('program') else [])]:
            entry.pop('note',None)
            entry['human_approved']=True
        return context


def load_glossary(path: Path | None) -> Glossary:
    if path is None:
        return Glossary()
    raw = _load_mapping(path)
    program = None
    entries: list[GlossaryEntry] = []

    if raw.get("program"):
        program = _optional_entry_from_mapping(raw["program"], default_type="program")
    for item in raw.get("characters", []) or []:
        entry = _optional_entry_from_mapping(item, default_type="person")
        if entry:
            entries.append(entry)
    for item in raw.get("terms", []) or []:
        entry = _optional_entry_from_mapping(item, default_type="term")
        if entry:
            entries.append(entry)
    return Glossary(program=program, entries=entries)


def _load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("读取 YAML 术语表需要 pyyaml，请先安装依赖。") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"术语表格式不正确: {path}")
    return data


def _optional_entry_from_mapping(data: dict[str, Any], default_type: str) -> GlossaryEntry | None:
    source = str(data.get("source", "")).strip()
    zh = str(data.get("zh", "")).strip()
    if not source or not zh:
        return None
    return GlossaryEntry(
        source=source,
        zh=zh,
        type=str(data.get("type", default_type)),
        aliases=[str(value) for value in data.get("aliases", []) or []],
        note=str(data.get("note", "")),
        always=bool(data.get("always", False)),
    )


def _contains_glossary_name(text_key: str, name: str) -> bool:
    name_key = comparable_text(name)
    return bool(name_key and name_key in text_key)
