from __future__ import annotations

import argparse
from pathlib import Path

import requests
import yt_dlp

from video_translate.youtube.download_video import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROXY,
    DEFAULT_THUMBNAIL_FORMAT,
    IMAGE_EXTENSIONS,
    THUMBNAIL_FORMATS,
    convert_thumbnail_bytes,
    normalize_url,
    normalize_thumbnail_format,
    thumbnail_extension,
    thumbnail_url_from_info,
)


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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        thumbnail_url = thumbnail_url_from_info(info)
        if not thumbnail_url:
            raise RuntimeError("没有找到视频封面 URL")
        response = requests.get(thumbnail_url, timeout=30, proxies={"http": proxy, "https": proxy} if proxy else None)
        response.raise_for_status()
        extension = thumbnail_extension(thumbnail_url, response.headers.get("Content-Type", ""), image_format=image_format)
        thumbnail_path = Path(ydl.prepare_filename({**info, "ext": extension.lstrip(".")}))
        if thumbnail_path.suffix.lower() not in IMAGE_EXTENSIONS:
            thumbnail_path = thumbnail_path.with_suffix(extension)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.write_bytes(convert_thumbnail_bytes(response.content, image_format=image_format))
        print(f"thumbnail_path: {thumbnail_path}", flush=True)
        return thumbnail_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download one YouTube thumbnail.")
    parser.add_argument("url", help="YouTube URL or video ID")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="Proxy URL; use an empty string to disable")
    parser.add_argument("--format", default=DEFAULT_THUMBNAIL_FORMAT, choices=sorted(THUMBNAIL_FORMATS), help="Thumbnail format: jpg, png, webp, or source")
    args = parser.parse_args(argv)

    print(f"Downloading thumbnail: {args.url}")
    download_thumbnail(args.url, output_dir=args.output_dir, proxy=args.proxy or None, image_format=args.format)
    print("Thumbnail process finished.")


if __name__ == "__main__":
    main()
