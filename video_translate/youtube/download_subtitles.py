import argparse
import os
import shutil
from pathlib import Path

import yt_dlp

from video_translate.env import load_dotenv
from video_translate.youtube.filenames import youtube_output_template
from video_translate.video_source import (
    normalize_video_url, video_title, video_platform, platform_options,
    validate_video_info, bilibili_caption_tracks,
)


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT)


def _default_output_dir() -> str:
    raw = os.environ.get("YTDLP_OUTPUT_DIR", "").strip()
    path = Path(raw).expanduser() if raw else ROOT / "YoutubeDownloads"
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve())


DEFAULT_OUTPUT_DIR = _default_output_dir()
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "").strip()
DEFAULT_VIDEO_URL = "0dD1bQZBdjs"
DEFAULT_SUBTITLE_LANGUAGES = os.environ.get("YTDLP_SUB_LANGS", "ko,en.*")
DEFAULT_SUBTITLE_FORMAT = "srt/vtt/best"
DEFAULT_CONVERT_SUBTITLES = "srt"


def normalize_url(url):
    return normalize_video_url(url)


def parse_subtitle_languages(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def build_subtitle_options(
    output_dir=DEFAULT_OUTPUT_DIR,
    *,
    proxy=DEFAULT_PROXY,
    auto_subtitles=True,
    manual_subtitles=True,
    list_subtitles=False,
    subtitle_languages=DEFAULT_SUBTITLE_LANGUAGES,
    subtitle_format=DEFAULT_SUBTITLE_FORMAT,
    convert_subtitles=DEFAULT_CONVERT_SUBTITLES,
    project_title=None,
):
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": youtube_output_template(output_path, project_title) if project_title else str(output_path / "%(title)s" / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "skip_download": True,
        "overwrites": True,
        "writesubtitles": bool(manual_subtitles),
        "writeautomaticsub": bool(auto_subtitles),
        "subtitleslangs": parse_subtitle_languages(subtitle_languages),
        "subtitlesformat": subtitle_format,
        "retries": 10,
        "verbose": True,
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    if shutil.which("node"):
        ydl_opts["js_runtimes"] = {"node": {}}
    if convert_subtitles:
        ydl_opts["convertsubtitles"] = convert_subtitles
    if list_subtitles:
        ydl_opts["listsubtitles"] = True

    return ydl_opts


def download_subtitles(
    url,
    output_dir=DEFAULT_OUTPUT_DIR,
    *,
    proxy=DEFAULT_PROXY,
    auto_subtitles=True,
    manual_subtitles=True,
    list_subtitles=False,
    subtitle_languages=DEFAULT_SUBTITLE_LANGUAGES,
    subtitle_format=DEFAULT_SUBTITLE_FORMAT,
    convert_subtitles=DEFAULT_CONVERT_SUBTITLES,
):
    video_url = normalize_url(url)
    probe_opts = {
        "noplaylist": True,
        "skip_download": True,
        "quiet": True,
    }
    if proxy:
        probe_opts["proxy"] = proxy
    probe_opts.update(platform_options(video_url, youtube_proxy=proxy))
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(video_url, download=False) if hasattr(ydl, "extract_info") else {}
    validate_video_info(info, video_url)
    selected_languages = subtitle_languages
    if video_platform(video_url) == "bilibili":
        # Bilibili AI captions live in yt-dlp's `subtitles`, not necessarily
        # `automatic_captions`. Filter by the real provenance, excluding danmaku.
        import re
        wanted = parse_subtitle_languages(subtitle_languages)
        tracks = bilibili_caption_tracks(info)
        selected_languages = [track["lang"] for track in tracks
                              if (auto_subtitles if track["kind"] == "auto" else manual_subtitles)
                              and any(re.fullmatch(pattern, track["lang"]) for pattern in wanted)]
        if not selected_languages and not list_subtitles:
            raise RuntimeError("没有可用的所选 B 站 CC 字幕；部分字幕需要登录 Cookie，弹幕不会作为字幕下载")
    ydl_opts = build_subtitle_options(
        output_dir,
        proxy=proxy,
        auto_subtitles=auto_subtitles,
        manual_subtitles=manual_subtitles,
        list_subtitles=list_subtitles,
        subtitle_languages=selected_languages,
        subtitle_format=subtitle_format,
        convert_subtitles=convert_subtitles,
        project_title=video_title(str(info.get("title") or ""), video_url),
    )
    ydl_opts.update(platform_options(video_url, youtube_proxy=proxy))
    if video_platform(video_url) == "bilibili":
        ydl_opts.update(writesubtitles=True, writeautomaticsub=True)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download YouTube/Bilibili sidecar subtitles, excluding danmaku.")
    parser.add_argument("url", nargs="?", default=DEFAULT_VIDEO_URL, help="YouTube/Bilibili URL or ID; use ?p=2 for a Bilibili part")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="Proxy URL; use an empty string to disable")
    parser.add_argument("--list", action="store_true", help="List available subtitle tracks instead of downloading")
    parser.add_argument("--no-auto", action="store_true", help="Do not download YouTube auto-generated captions")
    parser.add_argument("--auto-only", action="store_true", help="Only download YouTube auto-generated captions")
    parser.add_argument("--sub-langs", default=DEFAULT_SUBTITLE_LANGUAGES, help="Comma-separated languages, e.g. ko,en.*,zh-Hans")
    parser.add_argument("--sub-format", default=DEFAULT_SUBTITLE_FORMAT, help="yt-dlp subtitle format preference")
    parser.add_argument("--convert-subs", default=DEFAULT_CONVERT_SUBTITLES, help="Convert subtitles to this format; empty disables conversion")
    args = parser.parse_args(argv)

    action = "Listing subtitles" if args.list else "Downloading subtitles"
    print(f"{action}: {args.url}")
    download_subtitles(
        args.url,
        output_dir=args.output_dir,
        proxy=args.proxy or None,
        auto_subtitles=not args.no_auto or args.auto_only,
        manual_subtitles=not args.auto_only,
        list_subtitles=args.list,
        subtitle_languages=args.sub_langs,
        subtitle_format=args.sub_format,
        convert_subtitles=args.convert_subs or None,
    )
    print("Subtitle process finished.")


if __name__ == "__main__":
    main()
