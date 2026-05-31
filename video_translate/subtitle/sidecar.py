from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SidecarConfig:
    enabled: bool = False
    copy_source: bool = True
    copy_translated: bool = True
    source_suffix: str = ".source"
    translated_suffix: str = ".zh"


def copy_sidecar_subtitles(
    video_path: Path,
    *,
    source_srt: Path | None = None,
    translated_srt: Path | None = None,
    config: SidecarConfig | None = None,
) -> dict[str, Path]:
    config = config or SidecarConfig()
    if not config.enabled:
        return {}

    copied: dict[str, Path] = {}
    if config.copy_source and source_srt and source_srt.exists():
        target = _sidecar_path(video_path, config.source_suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_srt, target)
        copied["source_sidecar"] = target

    if config.copy_translated and translated_srt and translated_srt.exists():
        target = _sidecar_path(video_path, config.translated_suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(translated_srt, target)
        copied["translated_sidecar"] = target

    return copied


def _sidecar_path(video_path: Path, suffix: str) -> Path:
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return video_path.with_name(f"{video_path.stem}{clean_suffix}.srt")
