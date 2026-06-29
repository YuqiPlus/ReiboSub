import argparse
import io
import os
import shutil
from pathlib import Path

import requests
import yt_dlp
from PIL import Image
from yt_dlp.utils import DownloadError, MaxDownloadsReached

from video_translate.env import load_dotenv
from video_translate.youtube_url import normalize_youtube_url


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT)


def _default_output_dir() -> str:
    raw = os.environ.get("YTDLP_OUTPUT_DIR", "").strip()
    path = Path(raw).expanduser() if raw else ROOT / "YoutubeDownloads"
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve())


DEFAULT_OUTPUT_DIR = _default_output_dir()
DEFAULT_QUALITY = "1080p"
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "").strip()
DEFAULT_VIDEO_URL = "41qyU57ahfc"
DEFAULT_HTTP_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_THUMBNAIL_FORMAT = os.environ.get("YTDLP_THUMBNAIL_FORMAT", "jpg").strip().lower() or "jpg"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
THUMBNAIL_FORMATS = {"jpg", "jpeg", "png", "webp", "source"}


def normalize_url(url):
    return normalize_youtube_url(url)


def parse_quality(quality):
    quality = quality.lower().replace("p", "").strip()
    if not quality.isdigit():
        raise ValueError("分辨率格式错误，例如: 1080p、1080、720p、720")
    return int(quality)


def build_video_options(output_dir, height, *, proxy=DEFAULT_PROXY, format_selector=None, http_chunk_size=DEFAULT_HTTP_CHUNK_SIZE):
    output_path = Path(output_dir).expanduser()
    ydl_opts = {
        "format": format_selector or h264_format_selector(height),
        "outtmpl": str(output_path / "%(title)s" / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": 5,
        "max_downloads": 1,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "http_chunk_size": http_chunk_size,
        "socket_timeout": 30,
        "continuedl": True,
        "verbose": True,
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    if shutil.which("node"):
        ydl_opts["js_runtimes"] = {"node": {}}
    return ydl_opts


def snapshot_video_files(output_dir: Path) -> set[Path]:
    return {path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS}


def changed_video_files(output_dir: Path, before: set[Path]) -> list[Path]:
    return sorted(
        [path for path in snapshot_video_files(output_dir) - before if path.exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def h264_format_selector(height):
    return (
        "bestvideo[height<=%d][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
        "best[height<=%d][ext=mp4][vcodec^=avc1]/"
        "best[height<=%d]"
    ) % (height, height, height)


def fallback_format_selector(height):
    return (
        "bestvideo[height<=%d][ext=mp4]+bestaudio[ext=m4a]/"
        "best[height<=%d][ext=mp4]/"
        "best[height<=%d]"
    ) % (height, height, height)


def download_attempts(height):
    attempts = [
        ("h264-%dp" % height, h264_format_selector(height), DEFAULT_HTTP_CHUNK_SIZE),
        ("h264-%dp-small-chunks" % height, h264_format_selector(height), 4 * 1024 * 1024),
    ]
    if height > 720:
        attempts.append(("h264-720p-fallback", h264_format_selector(720), DEFAULT_HTTP_CHUNK_SIZE))
    attempts.append(("mp4-%dp-fallback" % height, fallback_format_selector(height), DEFAULT_HTTP_CHUNK_SIZE))
    return attempts


def is_retriable_download_error(error):
    text = str(error)
    return any(
        marker in text
        for marker in [
            "HTTP Error 403",
            "HTTP Error 429",
            "HTTP Error 503",
            "timed out",
            "Connection reset",
            "IncompleteRead",
        ]
    )


def download_video(url, quality=DEFAULT_QUALITY, output_dir=DEFAULT_OUTPUT_DIR, *, thumbnail_format=DEFAULT_THUMBNAIL_FORMAT):
    height = parse_quality(quality)
    video_url = normalize_url(url)
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    before_videos = snapshot_video_files(output_path)

    last_error = None
    try:
        for attempt_name, format_selector, chunk_size in download_attempts(height):
            ydl_opts = build_video_options(
                output_path,
                height,
                format_selector=format_selector,
                http_chunk_size=chunk_size,
            )
            print(f"download_attempt: {attempt_name}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False) if hasattr(ydl, "extract_info") else {}
                    ydl.download([video_url])
                videos = changed_video_files(output_path, before_videos)
                if not videos:
                    videos = matching_video_files(output_path, str(info.get("title") or ""))
                thumbnail = thumbnail_url_from_info(info)
                for video_path in videos:
                    download_thumbnail(thumbnail, video_path, proxy=ydl_opts.get("proxy"), image_format=thumbnail_format)
                return videos
            except DownloadError as error:
                last_error = error
                if not is_retriable_download_error(error):
                    raise
                print(f"download_attempt_failed: {attempt_name}: {error}")
                print("download_retry_next_strategy")
    except MaxDownloadsReached:
        print("Reached the maximum number of downloads. Download completed successfully.")
        return
    if last_error:
        raise last_error


def matching_video_files(output_dir: Path, title: str) -> list[Path]:
    if not title:
        return []
    comparable = title.casefold()
    return sorted(
        [
            path
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in VIDEO_EXTENSIONS
            and path.stem.casefold().startswith(comparable)
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def thumbnail_url_from_info(info):
    if not isinstance(info, dict):
        return ""
    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return str(info.get("thumbnail") or "")


def download_thumbnail(url, video_path: Path, *, proxy="", image_format=DEFAULT_THUMBNAIL_FORMAT):
    if not url:
        return None
    image_format = normalize_thumbnail_format(image_format)
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(url, timeout=30, proxies=proxies)
    response.raise_for_status()
    extension = thumbnail_extension(url, response.headers.get("Content-Type", ""), image_format=image_format)
    thumbnail_path = video_path.with_suffix(extension)
    thumbnail_path.write_bytes(convert_thumbnail_bytes(response.content, image_format=image_format))
    print(f"thumbnail_path: {thumbnail_path}", flush=True)
    return thumbnail_path


def normalize_thumbnail_format(value: str | None) -> str:
    image_format = str(value or DEFAULT_THUMBNAIL_FORMAT).strip().lower()
    if image_format == "jpeg":
        image_format = "jpg"
    if image_format not in THUMBNAIL_FORMATS:
        raise ValueError("封面格式错误，可选: jpg、png、webp、source")
    return image_format


def thumbnail_extension(url: str, content_type: str, *, image_format=DEFAULT_THUMBNAIL_FORMAT) -> str:
    image_format = normalize_thumbnail_format(image_format)
    if image_format != "source":
        return ".jpg" if image_format == "jpeg" else f".{image_format}"
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def convert_thumbnail_bytes(content: bytes, *, image_format=DEFAULT_THUMBNAIL_FORMAT) -> bytes:
    image_format = normalize_thumbnail_format(image_format)
    if image_format == "source":
        return content
    target = "JPEG" if image_format in {"jpg", "jpeg"} else image_format.upper()
    with Image.open(io.BytesIO(content)) as image:
        if target == "JPEG":
            image = image.convert("RGB")
        output = io.BytesIO()
        save_kwargs = {"quality": 95} if target == "JPEG" else {}
        image.save(output, format=target, **save_kwargs)
        return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download one YouTube video.")
    parser.add_argument("url", nargs="?", default=DEFAULT_VIDEO_URL, help="YouTube URL or video ID")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Maximum height, e.g. 1080p or 720p")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--thumbnail-format", default=DEFAULT_THUMBNAIL_FORMAT, choices=sorted(THUMBNAIL_FORMATS), help="Thumbnail format: jpg, png, webp, or source")
    args = parser.parse_args(argv)

    print(f"Downloading video: {args.url}")
    download_video(args.url, quality=args.quality, output_dir=args.output_dir, thumbnail_format=args.thumbnail_format)
    print("Download process finished.")


if __name__ == "__main__":
    main()
