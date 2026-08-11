from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from video_translate.youtube_url import normalize_youtube_url

PROJECT_MANIFEST_NAME = 'project.yaml'
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.ts', '.m2ts'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
SUBTITLE_EXTENSIONS = {'.srt', '.vtt', '.ass', '.ssa', '.bcc'}


def load_project_manifest(project_dir: Path) -> dict[str, Any]:
    path = Path(project_dir) / PROJECT_MANIFEST_NAME
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return data if isinstance(data, dict) else {}


def save_project_manifest(project_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    data = dict(manifest)
    data.setdefault('schema_version', 1)
    data.setdefault('project_id', safe_project_id(data.get('title') or project_dir.name))
    data['project_dir'] = str(project_dir.resolve())
    data['updated_at'] = time.time()
    (project_dir / PROJECT_MANIFEST_NAME).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding='utf-8',
    )
    return data


def update_youtube_project_manifest(
    video_path: Path,
    *,
    source_url: str,
    title: str = '',
    thumbnail_path: Path | None = None,
) -> dict[str, Any]:
    video_path = Path(video_path).resolve()
    return update_youtube_project_metadata(
        video_path.parent,
        source_url=source_url,
        title=title,
        primary_video=video_path,
        thumbnail_path=thumbnail_path,
    )


def update_youtube_project_metadata(
    project_dir: Path,
    *,
    source_url: str,
    title: str = '',
    primary_video: Path | None = None,
    thumbnail_path: Path | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    manifest = load_project_manifest(project_dir)
    normalized = normalize_youtube_url(source_url)
    manifest.update(
        {
            'source_type': 'youtube',
            'source_url': source_url,
            'normalized_url': normalized,
            'video_id': youtube_video_id(normalized),
            'title': title or manifest.get('title') or project_dir.name,
        }
    )
    if primary_video:
        manifest['primary_video'] = str(Path(primary_video).resolve())
    if thumbnail_path:
        manifest['thumbnail'] = str(Path(thumbnail_path).resolve())
    return save_project_manifest(project_dir, manifest)


def update_local_project_manifest(video_path: Path, *, download_dir: Path, title: str = '') -> dict[str, Any]:
    return update_local_media_project_manifest(video_path, download_dir=download_dir, title=title)


def update_local_media_project_manifest(media_path: Path, *, download_dir: Path, title: str = '') -> dict[str, Any]:
    media_path = Path(media_path).resolve()
    download_dir = Path(download_dir).resolve()
    suffix = media_path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        primary_key = 'primary_video'
    elif suffix in AUDIO_EXTENSIONS:
        primary_key = 'primary_audio'
    else:
        raise ValueError(f'unsupported local media format: {suffix or "<none>"}')
    if is_relative_to(media_path, download_dir) and media_path.parent != download_dir:
        project_dir = media_path.parent
    else:
        project_dir = download_dir / safe_project_id(title or media_path.stem)
    manifest = load_project_manifest(project_dir)
    manifest.update(
        {
            'source_type': 'local',
            'source_url': '',
            'normalized_url': '',
            'video_id': '',
            'title': title or manifest.get('title') or media_path.stem,
            primary_key: str(media_path),
        }
    )
    return save_project_manifest(project_dir, manifest)


def infer_project_manifest(project_dir: Path) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    manifest = load_project_manifest(project_dir)
    videos = sorted(
        [path for path in project_dir.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and not path.name.startswith('._')],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if project_dir.exists() else []
    audios = sorted(
        [path for path in project_dir.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and not path.name.startswith('._')],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if project_dir.exists() else []
    images = sorted(
        [path for path in project_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith('._')],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if project_dir.exists() else []
    data = dict(manifest)
    data.setdefault('schema_version', 1)
    data.setdefault('project_id', safe_project_id(data.get('title') or project_dir.name))
    data.setdefault('title', project_dir.name)
    data.setdefault('source_type', 'youtube' if data.get('source_url') else 'unknown')
    data.setdefault('source_url', '')
    data.setdefault('normalized_url', normalize_youtube_url(str(data.get('source_url') or '')) if data.get('source_url') else '')
    data.setdefault('video_id', youtube_video_id(str(data.get('normalized_url') or '')))
    data.setdefault('project_dir', str(project_dir))
    if not data.get('primary_video') and videos:
        data['primary_video'] = str(videos[0].resolve())
    if not data.get('primary_audio') and audios:
        data['primary_audio'] = str(audios[0].resolve())
    if not data.get('thumbnail') and images:
        data['thumbnail'] = str(images[0].resolve())
    return data


def safe_project_id(value: Any) -> str:
    text = str(value or '').strip().lower()
    text = re.sub(r'[^0-9a-zA-Z\u3131-\u318e\uac00-\ud7a3\u3040-\u30ff\u4e00-\u9fff]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text[:90] or 'video_project'


def youtube_video_id(url: str) -> str:
    parsed = urlparse(str(url or ''))
    if parsed.netloc.endswith('youtu.be'):
        return parsed.path.strip('/').split('/')[0]
    return (parse_qs(parsed.query).get('v') or [''])[0]


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False
