from __future__ import annotations

import re
from pathlib import Path


WINDOWS_FILENAME_TRANSLATION = str.maketrans(
    {
        "<": "＜",
        ">": "＞",
        ":": "：",
        '"': "＂",
        "/": "／",
        "\\": "＼",
        "|": "｜",
        "?": "？",
        "*": "＊",
    }
)

RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def filesystem_safe_title(title: str, *, default: str = "youtube_video", max_length: int = 180) -> str:
    safe = str(title or default).strip().translate(WINDOWS_FILENAME_TRANSLATION)
    safe = re.sub(r"[\x00-\x1f]", " ", safe)
    safe = " ".join(safe.split()).strip(" .")
    if not safe:
        safe = default
    if safe.casefold() in RESERVED_WINDOWS_NAMES:
        safe = f"{safe}_"
    safe = safe[:max_length].rstrip(" .")
    return safe or default


def youtube_project_dir(output_dir: str | Path, title: str) -> Path:
    return Path(output_dir).expanduser() / filesystem_safe_title(title)


def youtube_output_template(output_dir: str | Path, title: str, *, archive: bool = False) -> str:
    safe_title = filesystem_safe_title(title)
    filename = f"{safe_title}.best.%(ext)s" if archive else f"{safe_title}.%(ext)s"
    return str(youtube_project_dir(output_dir, title) / filename)
