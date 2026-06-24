from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def normalize_youtube_url(value: str) -> str:
    video_id = extract_youtube_video_id(value)
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_youtube_video_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("无法从输入中解析 YouTube 视频 ID: " + raw)

    if not raw.startswith(("http://", "https://")):
        return raw

    parsed = urlparse(raw)
    domain = parsed.netloc.lower()
    path = parsed.path.strip("/")
    video_id = ""

    if "youtube.com" in domain:
        query = parse_qs(parsed.query)
        if query.get("v"):
            video_id = query["v"][0]
        elif path.startswith("shorts/"):
            video_id = path.split("/", 1)[1].split("/", 1)[0]
        elif path.startswith("embed/"):
            video_id = path.split("/", 1)[1].split("/", 1)[0]
    elif "youtu.be" in domain:
        video_id = path.split("/", 1)[0]

    if not video_id:
        raise ValueError("无法从输入中解析 YouTube 视频 ID: " + raw)
    return video_id
