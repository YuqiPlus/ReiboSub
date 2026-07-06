from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from video_translate.youtube import download_subtitles, download_thumbnail, download_video


def _load_subtitle_module():
    return download_subtitles


def _load_video_module():
    return download_video


def _load_thumbnail_module():
    return download_thumbnail


def _image_bytes(image_format="WEBP"):
    output = io.BytesIO()
    Image.new("RGB", (2, 2), color=(120, 80, 40)).save(output, format=image_format)
    return output.getvalue()


def test_parse_subtitle_languages_from_csv():
    module = _load_subtitle_module()

    assert module.parse_subtitle_languages("ko, en.*, zh-Hans") == ["ko", "en.*", "zh-Hans"]


def test_build_subtitle_options_downloads_subtitles_only(tmp_path):
    module = _load_subtitle_module()

    opts = module.build_subtitle_options(
        output_dir=tmp_path,
        subtitle_languages="ko,en.*",
        proxy="",
    )

    assert opts["skip_download"] is True
    assert opts["writesubtitles"] is True
    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == ["ko", "en.*"]
    assert opts["subtitlesformat"] == "srt/vtt/best"
    assert opts["convertsubtitles"] == "srt"
    assert opts["overwrites"] is True
    assert opts["outtmpl"] == str(tmp_path / "%(title)s" / "%(title)s.%(ext)s")
    assert "proxy" not in opts


def test_build_subtitle_options_can_list_subtitles(tmp_path):
    module = _load_subtitle_module()

    opts = module.build_subtitle_options(output_dir=tmp_path, list_subtitles=True, proxy=None)

    assert opts["skip_download"] is True
    assert opts["listsubtitles"] is True


def test_build_subtitle_options_can_download_auto_only(tmp_path):
    module = _load_subtitle_module()

    opts = module.build_subtitle_options(output_dir=tmp_path, manual_subtitles=False, auto_subtitles=True)

    assert opts["writesubtitles"] is False
    assert opts["writeautomaticsub"] is True


def test_video_quality_accepts_best_and_resolution_caps():
    module = _load_video_module()

    assert module.DEFAULT_QUALITY == "1080p"
    assert module.parse_quality("best") is None
    assert module.parse_quality("2160p") == 2160
    assert module.parse_quality("1080") == 1080


def test_video_download_best_attempts_use_highest_available_selector():
    module = _load_video_module()

    attempts = module.download_attempts(module.parse_quality("best"))

    assert [name for name, _, _ in attempts] == ["best", "best-small-chunks", "best-fallback"]
    assert "height<=" not in attempts[0][1]
    assert "bestvideo" in attempts[0][1]


def test_video_download_main_uses_cli_url(monkeypatch):
    module = _load_video_module()
    calls = []

    def fake_download_video(url, quality=module.DEFAULT_QUALITY, output_dir=module.DEFAULT_OUTPUT_DIR, *, thumbnail_format=module.DEFAULT_THUMBNAIL_FORMAT):
        calls.append((url, quality, output_dir, thumbnail_format))

    monkeypatch.setattr(module, "download_video", fake_download_video)

    module.main(["abc123", "--quality", "720p", "--output-dir", "/tmp/videos"])

    assert calls == [("abc123", "720p", "/tmp/videos", "jpg")]


def test_thumbnail_download_uses_project_folder_and_downloads_image(monkeypatch, tmp_path):
    module = _load_thumbnail_module()
    requests_seen = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"id": "abc123", "title": "Demo Video", "thumbnail": "https://img.youtube.com/demo.webp"}

        def prepare_filename(self, info):
            return str(Path(self.opts["outtmpl"].replace("%(title)s", info["title"]).replace("%(ext)s", info["ext"])))

    def fake_get(url, *, timeout, proxies):
        requests_seen["url"] = url
        requests_seen["timeout"] = timeout
        requests_seen["proxies"] = proxies
        return SimpleNamespace(
            headers={"Content-Type": "image/webp"},
            content=_image_bytes("WEBP"),
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module.requests, "get", fake_get)

    thumbnail = module.download_thumbnail("abc123", output_dir=tmp_path, proxy="", image_format="jpg")

    assert thumbnail == tmp_path / "Demo Video" / "Demo Video.jpg"
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
    assert requests_seen["url"] == "https://img.youtube.com/demo.webp"


def test_thumbnail_download_can_keep_source_format(monkeypatch, tmp_path):
    module = _load_thumbnail_module()
    source_bytes = _image_bytes("WEBP")

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"id": "abc123", "title": "Demo Video", "thumbnail": "https://img.youtube.com/demo.webp"}

        def prepare_filename(self, info):
            return str(Path(self.opts["outtmpl"].replace("%(title)s", info["title"]).replace("%(ext)s", info["ext"])))

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, *, timeout, proxies: SimpleNamespace(
            headers={"Content-Type": "image/webp"},
            content=source_bytes,
            raise_for_status=lambda: None,
        ),
    )

    thumbnail = module.download_thumbnail("abc123", output_dir=tmp_path, proxy="", image_format="source")

    assert thumbnail == tmp_path / "Demo Video" / "Demo Video.webp"
    assert thumbnail.read_bytes() == source_bytes


def test_video_download_template_uses_project_folder(monkeypatch, tmp_path):
    module = _load_video_module()
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            captured["urls"] = urls

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "DEFAULT_PROXY", "")

    module.download_video("abc123", output_dir=tmp_path)

    assert captured["outtmpl"] == str(tmp_path / "%(title)s" / "%(title)s.%(ext)s")
    assert ".h264." not in captured["outtmpl"]
    assert "vcodec^=avc1" in captured["format"]
    assert "height<=1080" in captured["format"]
    assert captured["http_chunk_size"] == module.DEFAULT_HTTP_CHUNK_SIZE


def test_best_video_download_uses_archive_template_and_preserves_primary(monkeypatch, tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video_dir.mkdir()
    primary = video_dir / "Demo Video.mp4"
    primary.write_text("primary", encoding="utf-8")
    archive_tmp = video_dir / "Demo Video.best.mp4"
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"title": "Demo Video", "thumbnail": ""}

        def download(self, urls):
            archive_tmp.write_text("archive", encoding="utf-8")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "video_codec", lambda path: "av1" if path.name.startswith("Demo Video.best") else "h264")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    downloaded = module.download_video("abc123", quality="best", output_dir=tmp_path)

    archive = video_dir / "Demo Video.best.av1.mp4"
    assert downloaded == [archive]
    assert primary.read_text(encoding="utf-8") == "primary"
    assert archive.read_text(encoding="utf-8") == "archive"
    assert calls[0]["outtmpl"] == str(tmp_path / "%(title)s" / "%(title)s.best.%(ext)s")


def test_video_download_still_downloads_thumbnail_after_max_downloads_reached(monkeypatch, tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video = video_dir / "Demo Video.mp4"
    requests_seen = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"title": "Demo Video", "thumbnail": "https://img.youtube.com/demo.jpg"}

        def download(self, urls):
            video_dir.mkdir()
            video.write_text("video", encoding="utf-8")
            raise module.MaxDownloadsReached()

    def fake_get(url, *, timeout, proxies):
        requests_seen["url"] = url
        return SimpleNamespace(
            headers={"Content-Type": "image/jpeg"},
            content=_image_bytes("JPEG"),
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module.requests, "get", fake_get)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    downloaded = module.download_video("abc123", output_dir=tmp_path)

    assert downloaded == [video]
    assert requests_seen["url"] == "https://img.youtube.com/demo.jpg"
    assert (video_dir / "Demo Video.jpg").exists()


def test_video_download_downloads_thumbnail_with_video_stem(monkeypatch, tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video = video_dir / "Demo Video.h264.mp4"
    requests_seen = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"title": "Demo Video", "thumbnail": "https://img.youtube.com/demo.jpg"}

        def download(self, urls):
            video_dir.mkdir()
            video.write_text("video", encoding="utf-8")

    def fake_get(url, *, timeout, proxies):
        requests_seen["url"] = url
        requests_seen["timeout"] = timeout
        requests_seen["proxies"] = proxies
        return SimpleNamespace(
            headers={"Content-Type": "image/jpeg"},
            content=_image_bytes("JPEG"),
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module.requests, "get", fake_get)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    downloaded = module.download_video("abc123", output_dir=tmp_path)

    thumbnail = video_dir / "Demo Video.h264.jpg"
    assert downloaded == [video]
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
    assert requests_seen["url"] == "https://img.youtube.com/demo.jpg"


def test_video_download_matches_yt_dlp_sanitized_pipe_title(tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "A ｜ B"
    video_dir.mkdir()
    video = video_dir / "A ｜ B.mp4"
    video.write_bytes(b"video")

    assert module.matching_video_files(tmp_path, "A | B") == [video]


def test_video_download_ignores_macos_resource_fork_files(tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video_dir.mkdir()
    resource = video_dir / "._Demo Video.mp4"
    video = video_dir / "Demo Video.mp4"
    resource.write_bytes(b"resource")
    video.write_bytes(b"video")

    assert resource not in module.snapshot_video_files(tmp_path)
    assert module.matching_video_files(tmp_path, "Demo Video") == [video]


def test_capped_h264_download_replaces_existing_non_h264_video(monkeypatch, tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video_dir.mkdir()
    video = video_dir / "Demo Video.mp4"
    video.write_text("old-av1", encoding="utf-8")
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {"title": "Demo Video", "thumbnail": ""}

        def download(self, urls):
            calls.append(list(urls))
            video_dir.mkdir(exist_ok=True)
            video.write_text("new-h264", encoding="utf-8")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "video_codec", lambda path: "av1")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    downloaded = module.download_video("abc123", quality="1080p", output_dir=tmp_path)

    assert calls == [["https://www.youtube.com/watch?v=abc123"]]
    assert downloaded == [video]
    assert video.read_text(encoding="utf-8") == "new-h264"


def test_video_download_matches_existing_video_inside_project_folder(monkeypatch, tmp_path):
    module = _load_video_module()
    video_dir = tmp_path / "Demo Video"
    video_dir.mkdir()
    video = video_dir / "Demo Video.mp4"
    video.write_text("video", encoding="utf-8")

    matches = module.matching_video_files(tmp_path, "Demo Video")

    assert matches == [video]


def test_organize_downloads_dry_run_groups_related_files_without_moving(tmp_path):
    from video_translate.youtube.organize_downloads import organize_downloads

    video = tmp_path / "Demo Video.mp4"
    subtitle = tmp_path / "Demo Video.source.corrected.zh.srt"
    resource = tmp_path / "._Demo Video.mp4"
    video.write_text("video", encoding="utf-8")
    subtitle.write_text("subtitle", encoding="utf-8")
    resource.write_text("junk", encoding="utf-8")

    actions = organize_downloads(tmp_path, dry_run=True)

    lines = [action.line() for action in actions]
    assert any("Demo Video.mp4" in line and "Demo Video/Demo Video.mp4" in line for line in lines)
    assert any("Demo Video.source.corrected.zh.srt" in line and "Demo Video/Demo Video.source.corrected.zh.srt" in line for line in lines)
    assert any(line.startswith("delete:") and "._Demo Video.mp4" in line for line in lines)
    assert video.exists()
    assert subtitle.exists()
    assert resource.exists()


def test_organize_downloads_apply_overwrites_subtitles_but_preserves_video_duplicates(tmp_path):
    from video_translate.youtube.organize_downloads import organize_downloads

    project = tmp_path / "Demo Video"
    project.mkdir()
    existing_video = project / "Demo Video.mp4"
    existing_subtitle = project / "Demo Video.zh.srt"
    incoming_video = tmp_path / "Demo Video.mp4"
    incoming_subtitle = tmp_path / "Demo Video.zh.srt"
    existing_video.write_text("old-video", encoding="utf-8")
    existing_subtitle.write_text("old-subtitle", encoding="utf-8")
    incoming_video.write_text("new-video", encoding="utf-8")
    incoming_subtitle.write_text("new-subtitle", encoding="utf-8")

    organize_downloads(tmp_path, dry_run=False)

    assert existing_video.read_text(encoding="utf-8") == "old-video"
    assert (project / "Demo Video.copy1.mp4").read_text(encoding="utf-8") == "new-video"
    assert existing_subtitle.read_text(encoding="utf-8") == "new-subtitle"


def test_video_download_retries_403_with_smaller_chunks(monkeypatch, tmp_path):
    module = _load_video_module()
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            if len(calls) == 1:
                raise module.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "DEFAULT_PROXY", "")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    module.download_video("abc123", output_dir=tmp_path)

    assert len(calls) == 2
    assert calls[0]["http_chunk_size"] == 8 * 1024 * 1024
    assert calls[1]["http_chunk_size"] == 4 * 1024 * 1024
    assert calls[0]["format"] == calls[1]["format"]


def test_video_download_falls_back_to_720p_after_repeated_403(monkeypatch, tmp_path):
    module = _load_video_module()
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            if len(calls) <= 2:
                raise module.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "DEFAULT_PROXY", "")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    module.download_video("abc123", quality="1080p", output_dir=tmp_path)

    assert len(calls) == 3
    assert "height<=720" in calls[2]["format"]


def test_video_download_does_not_retry_non_retriable_error(monkeypatch, tmp_path):
    module = _load_video_module()
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            raise module.DownloadError("ERROR: Requested format is not available")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(module, "DEFAULT_PROXY", "")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    try:
        module.download_video("abc123", output_dir=tmp_path)
    except module.DownloadError:
        pass
    else:
        raise AssertionError("DownloadError should be raised")

    assert len(calls) == 1
