from __future__ import annotations

from pathlib import Path

from video_translate.project_manifest import (
    PROJECT_MANIFEST_NAME,
    load_project_manifest,
    update_local_media_project_manifest,
    update_local_project_manifest,
    update_youtube_project_manifest,
)


def test_youtube_project_manifest_records_source_and_primary_video(tmp_path: Path):
    project = tmp_path / 'Demo Video'
    project.mkdir()
    video = project / 'Demo Video.mp4'
    thumbnail = project / 'Demo Video.jpg'
    video.write_bytes(b'video')
    thumbnail.write_bytes(b'jpg')

    manifest = update_youtube_project_manifest(
        video,
        source_url='https://www.youtube.com/watch?v=abc123&t=99s',
        title='Demo Video',
        thumbnail_path=thumbnail,
    )

    assert (project / PROJECT_MANIFEST_NAME).exists()
    assert manifest['source_type'] == 'youtube'
    assert manifest['source_url'] == 'https://www.youtube.com/watch?v=abc123&t=99s'
    assert manifest['normalized_url'] == 'https://www.youtube.com/watch?v=abc123'
    assert manifest['video_id'] == 'abc123'
    assert manifest['title'] == 'Demo Video'
    assert manifest['primary_video'] == str(video)
    assert manifest['thumbnail'] == str(thumbnail)

    loaded = load_project_manifest(project)
    assert loaded['primary_video'] == str(video)


def test_local_project_manifest_can_reference_external_video(tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    uploads = tmp_path / 'uploads'
    downloads.mkdir()
    uploads.mkdir()
    video = uploads / 'my upload.mp4'
    video.write_bytes(b'video')

    manifest = update_local_project_manifest(video, download_dir=downloads, title='my upload')

    project_dir = downloads / 'my_upload'
    assert (project_dir / PROJECT_MANIFEST_NAME).exists()
    assert manifest['source_type'] == 'local'
    assert manifest['title'] == 'my upload'
    assert manifest['primary_video'] == str(video)
    assert manifest['project_dir'] == str(project_dir)


def test_local_project_manifest_can_reference_external_audio(tmp_path: Path):
    downloads = tmp_path / 'YoutubeDownloads'
    uploads = tmp_path / 'uploads'
    downloads.mkdir()
    uploads.mkdir()
    audio = uploads / 'interview.wav'
    audio.write_bytes(b'audio')

    manifest = update_local_media_project_manifest(audio, download_dir=downloads, title='interview')

    project_dir = downloads / 'interview'
    assert (project_dir / PROJECT_MANIFEST_NAME).exists()
    assert manifest['source_type'] == 'local'
    assert manifest['primary_audio'] == str(audio)
    assert 'primary_video' not in manifest
