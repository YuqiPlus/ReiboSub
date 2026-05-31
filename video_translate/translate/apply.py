from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt


def apply_translation_json(source_srt: Path, translation_json: Path, out_srt: Path) -> Path:
    cues = read_srt(source_srt)
    translations = _load_translations(translation_json)

    translated_cues: list[SubtitleCue] = []
    for cue in cues:
        translated = translations.get(cue.index, cue.text)
        translated_cues.append(
            SubtitleCue(
                index=cue.index,
                start=cue.start,
                end=cue.end,
                text=translated,
                source_track_id=cue.source_track_id,
            )
        )

    write_srt(translated_cues, out_srt)
    return out_srt


def _load_translations(path: Path) -> dict[int, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = _extract_items(raw)
    translations: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("index")
        raw_text = item.get("zh") or item.get("text") or item.get("translation")
        if raw_id is None or raw_text is None:
            continue
        translations[int(raw_id)] = str(raw_text)
    return translations


def _extract_items(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("translations"), list):
            return raw["translations"]
        if isinstance(raw.get("items"), list):
            return raw["items"]
        if isinstance(raw.get("batches"), list):
            flattened: list[Any] = []
            for batch in raw["batches"]:
                if isinstance(batch, dict) and isinstance(batch.get("translations"), list):
                    flattened.extend(batch["translations"])
            return flattened
    return []
