from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from video_translate.youtube.download_video import DEFAULT_OUTPUT_DIR, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".bcc"}
OVERWRITE_EXTENSIONS = SUBTITLE_EXTENSIONS | IMAGE_EXTENSIONS | {".json", ".txt", ".yaml", ".yml"}
JUNK_NAMES = {".DS_Store"}
JUNK_PREFIXES = ("._",)
PROJECT_SUFFIXES = {
    "source",
    "corrected",
    "zh",
    "zh-hans",
    "zh-hant",
    "zh-cn",
    "zh-tw",
    "cn",
    "ko",
    "kr",
    "en",
    "en-us",
    "en-gb",
    "ja",
    "jp",
    "jpn",
    "h264",
    "avc",
    "hevc",
    "live_chat",
}


@dataclass(frozen=True)
class OrganizeAction:
    action: str
    src: str
    dst: str = ""

    def line(self) -> str:
        if self.dst:
            return f"{self.action}: {self.src} -> {self.dst}"
        return f"{self.action}: {self.src}"


def organize_downloads(download_dir: str | Path = DEFAULT_OUTPUT_DIR, *, dry_run: bool = True) -> list[OrganizeAction]:
    root = Path(download_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    actions: list[OrganizeAction] = []

    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_dir():
            continue
        if _is_junk(path):
            actions.append(OrganizeAction("delete", str(path)))
            if not dry_run:
                path.unlink(missing_ok=True)
            continue
        if not path.is_file():
            continue

        project_name = project_name_for_file(path)
        if not project_name:
            continue
        target_dir = root / project_name
        target = target_dir / path.name
        final_target = _overwrite_target(path, target) if _can_overwrite(path) else _unique_target(target)
        actions.append(OrganizeAction("move", str(path), str(final_target)))
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            if final_target.exists() and _can_overwrite(path):
                final_target.unlink()
            shutil.move(str(path), str(final_target))

    return actions


def project_name_for_file(path: str | Path) -> str:
    path = Path(path)
    stem = path.stem
    parts = stem.split(".")
    while len(parts) > 1 and parts[-1].casefold() in PROJECT_SUFFIXES:
        parts.pop()
    name = ".".join(parts).strip()
    return name or stem


def _can_overwrite(path: Path) -> bool:
    return path.suffix.casefold() in OVERWRITE_EXTENSIONS


def _overwrite_target(path: Path, target: Path) -> Path:
    return target


def _unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    index = 1
    while True:
        candidate = parent / f"{stem}.copy{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _is_junk(path: Path) -> bool:
    return path.name in JUNK_NAMES or path.name.startswith(JUNK_PREFIXES)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Organize YoutubeDownloads into one folder per video title.")
    parser.add_argument("download_dir", nargs="?", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--apply", action="store_true", help="Actually move/delete files. Default is dry-run.")
    args = parser.parse_args(argv)

    actions = organize_downloads(args.download_dir, dry_run=not args.apply)
    mode = "apply" if args.apply else "dry_run"
    print(f"organize_mode: {mode}")
    for action in actions:
        print(action.line())
    print(f"organize_actions: {len(actions)}")


if __name__ == "__main__":
    main()
