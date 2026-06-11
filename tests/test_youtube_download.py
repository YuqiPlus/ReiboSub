from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_subtitle_module():
    path = Path(__file__).resolve().parents[1] / "download_youtube_subtitles.py"
    spec = importlib.util.spec_from_file_location("youtube_subtitles_1_linux", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_video_download_main_uses_cli_url(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "download_youtube_video.py"
    spec = importlib.util.spec_from_file_location("youtube_dl_1_linux_video", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    calls = []

    def fake_download_video(url, quality=module.DEFAULT_QUALITY, output_dir=module.DEFAULT_OUTPUT_DIR):
        calls.append((url, quality, output_dir))

    monkeypatch.setattr(module, "download_video", fake_download_video)

    module.main(["abc123", "--quality", "720p", "--output-dir", "/tmp/videos"])

    assert calls == [("abc123", "720p", "/tmp/videos")]


def test_video_download_template_matches_subtitle_basename(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "download_youtube_video.py"
    spec = importlib.util.spec_from_file_location("youtube_dl_1_linux_video_template", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
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

    assert captured["outtmpl"] == str(tmp_path / "%(title)s.%(ext)s")
    assert ".h264." not in captured["outtmpl"]
    assert "vcodec^=avc1" in captured["format"]

