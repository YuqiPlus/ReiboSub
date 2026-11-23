from __future__ import annotations

import argparse
from pathlib import Path

import requests
import yt_dlp

from video_translate.youtube.download_video import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROXY,
    DEFAULT_THUMBNAIL_FORMAT,
    THUMBNAIL_FORMATS,
    convert_thumbnail_bytes,
    normalize_url,
    normalize_thumbnail_format,
    thumbnail_extension,
    thumbnail_url_from_info,
    thumbnail_candidates,
    download_thumbnail as save_video_thumbnail,
)
from video_translate.youtube.filenames import filesystem_safe_title, youtube_project_dir
from video_translate.video_source import platform_options, video_title, video_platform, validate_video_info


def build_thumbnail_options(output_dir=DEFAULT_OUTPUT_DIR, *, proxy=DEFAULT_PROXY):
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(output_path / "%(title)s" / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "skip_download": True,
        "retries": 10,
        "verbose": True,
    }
    if proxy:
        opts["proxy"] = proxy
    return opts


def download_thumbnail(url, output_dir=DEFAULT_OUTPUT_DIR, *, proxy=DEFAULT_PROXY, image_format=DEFAULT_THUMBNAIL_FORMAT):
    video_url = normalize_url(url)
    image_format = normalize_thumbnail_format(image_format)
    ydl_opts = build_thumbnail_options(output_dir, proxy=proxy)
    ydl_opts.update(platform_options(video_url, youtube_proxy=proxy))
    proxy = ydl_opts.get("proxy")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        validate_video_info(info, video_url)
        thumbnail_url = thumbnail_url_from_info(info)
        candidates = thumbnail_candidates(info, video_url)
        if not thumbnail_url and not candidates:
            raise RuntimeError("没有找到视频封面 URL")
        title = video_title(str(info.get("title") or "youtube_video"), video_url)
        safe_title = filesystem_safe_title(title)
        base = youtube_project_dir(output_dir, title) / f'{safe_title}.mp4'
        base.parent.mkdir(parents=True, exist_ok=True)
        # An explicit empty proxy also prevents inherited proxy settings for Bilibili.
        return save_video_thumbnail(thumbnail_url, base, proxy=proxy or '', image_format=image_format, fallback_urls=candidates,
                                    disable_env_proxy=video_platform(video_url)=='bilibili')


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download one YouTube/Bilibili thumbnail.")
    parser.add_argument("url", help="YouTube/Bilibili URL or video ID")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="Proxy URL; use an empty string to disable")
    parser.add_argument("--format", default=DEFAULT_THUMBNAIL_FORMAT, choices=sorted(THUMBNAIL_FORMATS), help="Thumbnail format: jpg, png, webp, or source")
    args = parser.parse_args(argv)

    print(f"Downloading thumbnail: {args.url}")
    download_thumbnail(args.url, output_dir=args.output_dir, proxy=args.proxy or None, image_format=args.format)
    print("Thumbnail process finished.")


if __name__ == "__main__":
    main()
