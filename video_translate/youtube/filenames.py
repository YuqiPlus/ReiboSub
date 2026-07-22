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

DOWNLOAD_FORMAT_TAG_RE = re.compile(
    r"^[1-9][0-9]{1,4}p(?:[1-9][0-9]{1,2})?(?:\.hdr)?\.[a-z0-9][a-z0-9_-]{0,19}$"
)


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


def normalize_download_format_tag(value: str | None) -> str:
    """Validate the short, server-generated suffix used for exact-format files."""

    tag = str(value or "").strip().lower()
    if not tag:
        return ""
    if not DOWNLOAD_FORMAT_TAG_RE.fullmatch(tag) or ".." in tag:
        raise ValueError("下载格式标签无效")
    return tag


def youtube_output_template(
    output_dir: str | Path,
    title: str,
    *,
    archive: bool = False,
    format_tag: str | None = None,
) -> str:
    safe_title = filesystem_safe_title(title)
    safe_format_tag = normalize_download_format_tag(format_tag)
    if archive and safe_format_tag:
        raise ValueError("archive 与 format_tag 不能同时使用")
    if safe_format_tag:
        filename = f"{safe_title}.{safe_format_tag}.%(ext)s"
    elif archive:
        filename = f"{safe_title}.best.%(ext)s"
    else:
        filename = f"{safe_title}.%(ext)s"
    return str(youtube_project_dir(output_dir, title) / filename)
