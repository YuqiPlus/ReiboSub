"""Supported video origins, single-part identity and platform download options.

YouTube's legacy bare IDs remain supported. Bilibili is deliberately limited to
ordinary uploads: one BV/av video and one P per task, never an entire collection.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from video_translate.youtube_url import normalize_youtube_url

_BILI_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}
_SHORT_HOSTS = {"b23.tv", "www.b23.tv"}
_BILI_ID = r"(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]*)"


def _part(query: str) -> int:
    values = parse_qs(query, keep_blank_values=True).get("p", ["1"])
    if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,4}", values[0]):
        raise ValueError("B 站分 P 必须是正整数，例如 ?p=2")
    return int(values[0])


def _safe_http_url(value: str):
    parsed = urlparse(value)
    if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
            or parsed.port not in {None, 80, 443}):
        raise ValueError("请输入有效的 YouTube 或 B 站普通视频链接")
    return parsed


def _resolve_b23(url: str) -> str:
    """Resolve only allowlisted redirects; never follow an arbitrary origin."""
    for _ in range(5):
        parsed = _safe_http_url(url)
        host = (parsed.hostname or "").lower()
        if host in _BILI_HOSTS:
            return url
        if host not in _SHORT_HOSTS or not re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path):
            raise ValueError("B 站短链接未指向普通投稿视频")
        try:
            response = requests.get(url, allow_redirects=False, timeout=15,
                                    proxies={"http": "", "https": ""}, stream=True)
            try:
                response.raise_for_status()
                location = response.headers.get("Location", "")
                if response.status_code not in {301, 302, 303, 307, 308} or not location:
                    raise ValueError("无法解析 B 站短链接，请粘贴完整 BV 链接")
                url = urljoin(url, location)
            finally:
                response.close()
        except requests.RequestException:
            raise ValueError("B 站短链接解析失败，请稍后重试或粘贴完整 BV 链接") from None
    raise ValueError("B 站短链接跳转过多，请粘贴完整 BV 链接")


def normalize_video_url(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(_BILI_ID, raw):
        raw = f"https://www.bilibili.com/video/{raw}"
    elif raw.startswith(("www.bilibili.com/", "bilibili.com/", "m.bilibili.com/", "b23.tv/", "www.b23.tv/")):
        raw = "https://" + raw
    if not raw.startswith(("http://", "https://")):
        if not raw or re.search(r"[/\\:\s]", raw):
            raise ValueError("请输入 YouTube / B 站视频链接或视频 ID")
        return normalize_youtube_url(raw)
    parsed = _safe_http_url(raw)
    host = (parsed.hostname or "").lower()
    if host in _SHORT_HOSTS:
        requested_part = _part(parsed.query) if "p" in parse_qs(parsed.query, keep_blank_values=True) else None
        resolved = normalize_video_url(_resolve_b23(raw))
        if video_platform(resolved) != "bilibili":
            raise ValueError("B 站短链接未指向普通投稿视频")
        if requested_part is not None:
            return resolved.split("?", 1)[0] + (f"?p={requested_part}" if requested_part > 1 else "")
        return resolved
    if host in _BILI_HOSTS:
        match = re.fullmatch(rf"/video/({_BILI_ID})/?", parsed.path)
        if not match:
            raise ValueError("当前支持 B 站普通投稿视频 BV/av 链接，不支持番剧、直播或合集链接")
        part = _part(parsed.query)
        return f"https://www.bilibili.com/video/{match[1]}" + (f"?p={part}" if part > 1 else "")
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return normalize_youtube_url(raw)
    raise ValueError("当前仅支持 YouTube 和 Bilibili 普通视频链接")


def explicit_video_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.startswith(("http://", "https://")):
        return ""
    try:
        return normalize_video_url(raw)
    except ValueError:
        return ""


def video_platform(normalized_url: str) -> str:
    return "bilibili" if (urlparse(normalized_url).hostname or "").lower() in _BILI_HOSTS else "youtube"


def video_part(normalized_url: str) -> int:
    return _part(urlparse(normalized_url).query) if video_platform(normalized_url) == "bilibili" else 1


def video_id(normalized_url: str) -> str:
    parsed = urlparse(normalized_url)
    if video_platform(normalized_url) == "bilibili":
        return parsed.path.strip("/").split("/")[-1]
    return (parse_qs(parsed.query).get("v") or [""])[0]


def video_task_key(normalized_url: str) -> str:
    identity = video_id(normalized_url)
    if video_platform(normalized_url) == "bilibili":
        # Task slugs are casefolded elsewhere, while BVIDs are case-sensitive.
        digest = hashlib.sha256(normalized_url.encode()).hexdigest()[:10]
        return f"bilibili_{identity}_p{video_part(normalized_url)}_{digest}"
    return identity


def video_title(title: str, normalized_url: str) -> str:
    """Stable file identity even for equal titles or very long multipart titles."""
    if video_platform(normalized_url) != "bilibili":
        return title
    suffix = f" [{video_id(normalized_url)} P{video_part(normalized_url)}]"
    base = str(title or "bilibili_video").strip()
    if base.endswith(suffix):
        base = base[:-len(suffix)]
    return base[:max(1, 180 - len(suffix))].rstrip() + suffix


def platform_options(normalized_url: str, *, youtube_proxy: str | None = None) -> dict:
    if video_platform(normalized_url) != "bilibili":
        return {"proxy": youtube_proxy} if youtube_proxy else {}
    # An explicit empty proxy also disables yt-dlp's environment proxy discovery.
    opts: dict = {"proxy": os.environ.get("BILIBILI_PROXY", "").strip(),
                  "http_headers": {"Referer": "https://www.bilibili.com/"},
                  "noplaylist": True}
    cookie_file = os.environ.get("BILIBILI_COOKIE_FILE", "").strip()
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if not path.is_file():
            raise ValueError("B 站 Cookie 文件不存在，请检查 bilibili_cookie_file 配置")
        opts["cookiefile"] = str(path.resolve())
    return opts


def validate_video_info(info: dict, normalized_url: str) -> None:
    if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
        raise ValueError("未取得单个视频，请使用普通视频链接；分 P 请指定 ?p=2")
    if video_platform(normalized_url) == "bilibili" and info.get("extractor_key") not in {None, "BiliBili"}:
        raise ValueError("当前仅支持 B 站普通投稿视频，不支持番剧、直播或合集")
    if video_platform(normalized_url) == "bilibili" and video_part(normalized_url) > 1:
        actual_id = str(info.get("id") or "")
        if actual_id and not actual_id.endswith(f"_p{video_part(normalized_url)}"):
            raise ValueError("平台没有返回指定分 P，请检查该视频是否包含这个分 P")


def caption_language(language: str) -> str:
    value = str(language or "").lower().replace("_", "-")
    return value[3:] if value.startswith("ai-") else value


def bilibili_caption_tracks(info: dict) -> list[dict]:
    tracks = []
    for kind, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
        for lang, formats in (info.get(key) or {}).items():
            # yt-dlp includes danmaku XML in `subtitles`; it is not dialogue.
            formats = [f for f in formats if isinstance(f, dict) and f.get("ext") in {"srt", "vtt", "ass", "bcc", "json"}]
            if lang.lower() in {"danmaku", "live_chat"} or not formats:
                continue
            auto = kind == "auto" or lang.lower().startswith("ai-")
            tracks.append({"lang": lang, "kind": "auto" if auto else "manual",
                           "label": f"{caption_language(lang)} · {'自动字幕' if auto else '人工字幕'}",
                           "formats": sorted({f["ext"] for f in formats}),
                           "storage": key})
    return tracks
