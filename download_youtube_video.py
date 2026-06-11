import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import MaxDownloadsReached


DEFAULT_OUTPUT_DIR = "/data/wjq/Video_Translate/YoutubeDownloads"
DEFAULT_QUALITY = "1080p"
DEFAULT_PROXY = os.environ.get("YTDLP_PROXY", "http://127.0.0.1:7890")
DEFAULT_VIDEO_URL = "41qyU57ahfc"


def normalize_url(url):
    url = url.strip()

    if not url.startswith(("http://", "https://")):
        return "https://www.youtube.com/watch?v=" + url

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.strip("/")
    video_id = None

    if "youtube.com" in domain:
        query = parse_qs(parsed.query)
        if "v" in query:
            video_id = query["v"][0]
        elif path.startswith("shorts/"):
            parts = path.split("/")
            if len(parts) >= 2:
                video_id = parts[1]
        elif path.startswith("embed/"):
            parts = path.split("/")
            if len(parts) >= 2:
                video_id = parts[1]
    elif "youtu.be" in domain:
        video_id = path.split("/")[0]

    if not video_id:
        raise ValueError("无法从输入中解析 YouTube 视频 ID: " + url)

    return "https://www.youtube.com/watch?v=" + video_id


def parse_quality(quality):
    quality = quality.lower().replace("p", "").strip()
    if not quality.isdigit():
        raise ValueError("分辨率格式错误，例如: 1080p、1080、720p、720")
    return int(quality)


def download_video(url, quality=DEFAULT_QUALITY, output_dir=DEFAULT_OUTPUT_DIR):
    height = parse_quality(quality)
    video_url = normalize_url(url)
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestvideo[height<=%d][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<=%d][ext=mp4][vcodec^=avc1]/best[height<=%d]" % (height, height, height),
        "outtmpl": str(output_path / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": 5,
        "max_downloads": 1,
        "retries": 10,
        "verbose": True,
    }
    if DEFAULT_PROXY:
        ydl_opts["proxy"] = DEFAULT_PROXY

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    except MaxDownloadsReached:
        print("Reached the maximum number of downloads. Download completed successfully.")


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
