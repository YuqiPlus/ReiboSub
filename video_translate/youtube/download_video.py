import argparse
import io
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

import requests
import yt_dlp
from PIL import Image
from yt_dlp.utils import DownloadError, MaxDownloadsReached

from video_translate.env import load_dotenv
from video_translate.youtube.filenames import normalize_download_format_tag, youtube_output_template
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
DOWNLOAD_CONTAINERS = {"mp4", "mkv", "webm"}
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:\+[A-Za-z0-9][A-Za-z0-9._-]{0,127})?$")
FORMAT_SELECTOR_KEYWORDS = {
    "all",
    "b",
    "ba",
    "bv",
    "best",
    "bestaudio",
    "bestvideo",
    "mergeall",
    "w",
    "wa",
    "worst",
    "worstaudio",
    "worstvideo",
    "wv",
}


def normalize_url(url):
    return normalize_youtube_url(url)


def parse_quality(quality):
    quality = str(quality or DEFAULT_QUALITY).lower().strip()
    if quality in {"best", "highest", "max", "最高"}:
        return None
    quality = quality.replace("p", "").strip()
    if not quality.isdigit():
        raise ValueError("分辨率格式错误，例如: best、2160p、1440p、1080p、720p")
    return int(quality)


def build_video_options(
    output_dir,
    height,
    *,
    proxy=DEFAULT_PROXY,
    format_selector=None,
    http_chunk_size=DEFAULT_HTTP_CHUNK_SIZE,
    archive=False,
    project_title=None,
    format_tag=None,
    container="mp4",
):
    output_path = Path(output_dir).expanduser()
    safe_format_tag = normalize_download_format_tag(format_tag)
    container = normalize_download_container(container)
    if archive and safe_format_tag:
        raise ValueError("archive 与 format_tag 不能同时使用")
    if safe_format_tag:
        filename_template = f"%(title)s.{safe_format_tag}.%(ext)s"
    elif archive:
        filename_template = "%(title)s.best.%(ext)s"
    else:
        filename_template = "%(title)s.%(ext)s"
    outtmpl = (
        youtube_output_template(output_path, project_title, archive=archive, format_tag=safe_format_tag)
        if project_title
        else str(output_path / "%(title)s" / filename_template)
    )
    ydl_opts = {
        "format": format_selector or (best_format_selector() if height is None else h264_format_selector(height)),
        "outtmpl": outtmpl,
        "noplaylist": True,
        "merge_output_format": container,
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


def normalize_exact_format_id(value: str | None) -> str:
    format_id = str(value or "").strip()
    if not format_id:
        return ""
    if not FORMAT_ID_RE.fullmatch(format_id):
        raise ValueError("下载格式 ID 无效")
    if any(part.casefold() in FORMAT_SELECTOR_KEYWORDS for part in format_id.split("+")):
        raise ValueError("下载格式 ID 必须是探测返回的具体格式，不能使用 best/all 等选择器")
    return format_id


def normalize_download_container(value: str | None) -> str:
    container = str(value or "mp4").strip().lower().lstrip(".")
    if container not in DOWNLOAD_CONTAINERS:
        raise ValueError("下载封装格式无效，可选: mp4、mkv、webm")
    return container


def update_yt_dlp_outtmpl(ydl, ydl_opts: dict, outtmpl: str) -> None:
    ydl_opts["outtmpl"] = outtmpl
    if not hasattr(ydl, "params"):
        return
    current = ydl.params.get("outtmpl")
    if isinstance(current, dict):
        current["default"] = outtmpl
    else:
        ydl.params["outtmpl"] = {"default": outtmpl}


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and not path.name.startswith("._")


def snapshot_video_files(output_dir: Path) -> set[Path]:
    return {path for path in output_dir.rglob("*") if is_video_file(path)}


def changed_video_files(output_dir: Path, before: set[Path]) -> list[Path]:
    return sorted(
        [path for path in snapshot_video_files(output_dir) - before if path.exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def comparable_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split()).casefold()


def h264_format_selector(height):
    return (
        "bestvideo[height<=%d][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
        "best[height<=%d][ext=mp4][vcodec^=avc1]/"
        "best[height<=%d]"
    ) % (height, height, height)


def best_format_selector():
    return (
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo*+bestaudio/best"
    )


def fallback_format_selector(height):
    if height is None:
        return "bestvideo*+bestaudio/best"
    return (
        "bestvideo[height<=%d][ext=mp4]+bestaudio[ext=m4a]/"
        "best[height<=%d][ext=mp4]"
    ) % (height, height)


def download_attempts(height):
    if height is None:
        return [
            ("best", best_format_selector(), DEFAULT_HTTP_CHUNK_SIZE),
            ("best-small-chunks", best_format_selector(), 4 * 1024 * 1024),
            ("best-fallback", fallback_format_selector(None), DEFAULT_HTTP_CHUNK_SIZE),
        ]
    attempts = [
        ("h264-%dp" % height, h264_format_selector(height), DEFAULT_HTTP_CHUNK_SIZE),
        ("h264-%dp-small-chunks" % height, h264_format_selector(height), 4 * 1024 * 1024),
    ]
    if height > 720:
        attempts.append(("h264-720p-fallback", h264_format_selector(720), DEFAULT_HTTP_CHUNK_SIZE))
    attempts.append(("mp4-%dp-fallback" % height, fallback_format_selector(height), DEFAULT_HTTP_CHUNK_SIZE))
    return attempts


def exact_format_download_attempts(format_id: str):
    format_id = normalize_exact_format_id(format_id)
    if not format_id:
        raise ValueError("下载格式 ID 不能为空")
    return [
        (f"exact-{format_id}", format_id, DEFAULT_HTTP_CHUNK_SIZE),
        (f"exact-{format_id}-small-chunks", format_id, 4 * 1024 * 1024),
    ]


def video_codec(path: Path) -> str:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return ""
    return result.stdout.strip().splitlines()[0].lower() if result.stdout.strip() else ""


def remove_incompatible_existing_h264_targets(output_dir: Path, title: str) -> None:
    comparable = comparable_title(title)
    # The compatibility download owns only the unsuffixed ``Title.ext`` target.
    # Exact/archive variants (``Title.2160p.av1.mp4`` / ``Title.best.av1.mp4``)
    # are separate assets and must survive a later quick 1080p download.
    for video_path in matching_video_files(output_dir, title):
        if comparable_title(video_path.stem) != comparable:
            continue
        codec = video_codec(video_path)
        if codec and codec not in {"h264", "avc1"}:
            print(f"replace_incompatible_video: {video_path} codec={codec}")
            video_path.unlink()


def is_archive_quality(quality) -> bool:
    return str(quality or "").strip().lower() in {"best", "highest", "max", "最高", "archive", "best_archive", "best-archive"}


def matching_archive_video_files(output_dir: Path, title: str) -> list[Path]:
    return [path for path in matching_video_files(output_dir, title) if ".best" in path.stem]


def matching_exact_video_files(output_dir: Path, title: str, format_tag: str) -> list[Path]:
    safe_format_tag = normalize_download_format_tag(format_tag)
    marker = f".{safe_format_tag}"
    return [path for path in matching_video_files(output_dir, title) if path.stem.endswith(marker)]


def archive_video_path(path: Path) -> Path:
    if ".best." in path.stem:
        return path
    codec = video_codec(path) or "video"
    codec = "".join(ch for ch in codec.lower() if ch.isalnum() or ch in {"_", "-"}) or "video"
    if path.stem.endswith(".best"):
        target = path.with_name(f"{path.stem}.{codec}{path.suffix}")
    else:
        target = path.with_name(f"{path.stem}.best.{codec}{path.suffix}")
    if target == path:
        return path
    if target.exists():
        target.unlink()
    path.rename(target)
    return target


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


def download_video(
    url,
    quality=DEFAULT_QUALITY,
    output_dir=DEFAULT_OUTPUT_DIR,
    *,
    thumbnail_format=DEFAULT_THUMBNAIL_FORMAT,
    project_title=None,
    format_id=None,
    format_tag=None,
    container=None,
):
    height = parse_quality(quality)
    exact_format_id = normalize_exact_format_id(format_id)
    exact_format_tag = normalize_download_format_tag(format_tag)
    exact_container = normalize_download_container(container) if container else "mp4"
    if exact_format_id and not exact_format_tag:
        raise ValueError("精确下载必须提供格式标签")
    if not exact_format_id and (exact_format_tag or container):
        raise ValueError("format_tag/container 只能与 format_id 一起使用")
    archive = is_archive_quality(quality) and not exact_format_id
    video_url = normalize_url(url)
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    before_videos = snapshot_video_files(output_path)

    last_error = None
    try:
        attempts = exact_format_download_attempts(exact_format_id) if exact_format_id else download_attempts(height)
        for attempt_name, format_selector, chunk_size in attempts:
            ydl_opts = build_video_options(
                output_path,
                height,
                format_selector=format_selector,
                http_chunk_size=chunk_size,
                archive=archive,
                project_title=project_title,
                format_tag=exact_format_tag,
                container=exact_container,
            )
            print(f"download_attempt: {attempt_name}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False) if hasattr(ydl, "extract_info") else {}
                    title = str(info.get("title") or "")
                    output_title = str(project_title or title)
                    if output_title:
                        update_yt_dlp_outtmpl(
                            ydl,
                            ydl_opts,
                            youtube_output_template(
                                output_path,
                                output_title,
                                archive=archive,
                                format_tag=exact_format_tag,
                            ),
                        )
                    if height is not None and not exact_format_id:
                        remove_incompatible_existing_h264_targets(output_path, output_title)
                    try:
                        ydl.download([video_url])
                    except MaxDownloadsReached:
                        print("Reached the maximum number of downloads. Download completed successfully.")
                if exact_format_id:
                    matcher = lambda root, candidate_title: matching_exact_video_files(
                        root, candidate_title, exact_format_tag
                    )
                else:
                    matcher = matching_archive_video_files if archive else matching_video_files
                if project_title:
                    videos = matcher(output_path, output_title)
                else:
                    videos = changed_video_files(output_path, before_videos)
                    if archive:
                        videos = [path for path in videos if ".best" in path.stem]
                    elif exact_format_id:
                        marker = f".{exact_format_tag}"
                        videos = [path for path in videos if path.stem.endswith(marker)]
                    if not videos:
                        videos = matcher(output_path, output_title)
                if archive:
                    videos = [archive_video_path(path) for path in videos]
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
        videos = matching_video_files(output_path, str(project_title)) if project_title else changed_video_files(output_path, before_videos)
        return videos
    if last_error:
        raise last_error


def matching_video_files(output_dir: Path, title: str) -> list[Path]:
    if not title:
        return []
    comparable = comparable_title(title)
    return sorted(
        [
            path
            for path in output_dir.rglob("*")
            if is_video_file(path)
            and comparable_title(path.stem).startswith(comparable)
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
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Video quality: best, 2160p, 1440p, 1080p, 720p, etc.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--thumbnail-format", default=DEFAULT_THUMBNAIL_FORMAT, choices=sorted(THUMBNAIL_FORMATS), help="Thumbnail format: jpg, png, webp, or source")
    parser.add_argument("--project-title", default="", help="Optional fixed project folder and filename stem")
    parser.add_argument("--format-id", default="", help="Exact yt-dlp format ID, for example 401+140")
    parser.add_argument("--format-tag", default="", help="Safe filename tag returned by the format probe")
    parser.add_argument("--container", default="", choices=sorted(DOWNLOAD_CONTAINERS), help="Exact download output container")
    args = parser.parse_args(argv)

    print(f"Downloading video: {args.url}")
    kwargs = {
        "quality": args.quality,
        "output_dir": args.output_dir,
        "thumbnail_format": args.thumbnail_format,
    }
    if args.project_title:
        kwargs["project_title"] = args.project_title
    if args.format_id:
        kwargs["format_id"] = args.format_id
        kwargs["format_tag"] = args.format_tag
        kwargs["container"] = args.container or "mp4"
    download_video(args.url, **kwargs)
    print("Download process finished.")


if __name__ == "__main__":
    main()
