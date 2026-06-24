import argparse
import os
import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError, MaxDownloadsReached

from video_translate.youtube_url import normalize_youtube_url


DEFAULT_OUTPUT_DIR = "/data/wjq/Video_Translate/YoutubeDownloads"
DEFAULT_QUALITY = "1080p"
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "http://127.0.0.1:7890")
DEFAULT_VIDEO_URL = "41qyU57ahfc"
DEFAULT_HTTP_CHUNK_SIZE = 8 * 1024 * 1024


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
        "outtmpl": str(output_path / "%(title)s.%(ext)s"),
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


def download_video(url, quality=DEFAULT_QUALITY, output_dir=DEFAULT_OUTPUT_DIR):
    height = parse_quality(quality)
    video_url = normalize_url(url)
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

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
                    ydl.download([video_url])
                return
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download one YouTube video.")
    parser.add_argument("url", nargs="?", default=DEFAULT_VIDEO_URL, help="YouTube URL or video ID")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Maximum height, e.g. 1080p or 720p")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    print(f"Downloading video: {args.url}")
    download_video(args.url, quality=args.quality, output_dir=args.output_dir)
    print("Download process finished.")


if __name__ == "__main__":
    main()
