from __future__ import annotations

import base64
import time
from pathlib import Path

from PIL import Image

from video_translate import web_agent


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def test_video_overlay_job_builds_two_layer_ffmpeg_command(monkeypatch, tmp_path):
    video = tmp_path / "YoutubeDownloads" / "demo" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    image = tmp_path / "overlay.png"
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(image)
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "_video_dimensions", lambda path: (1920, 1080))
    calls: list[list[str]] = []

    def fake_run_command(job_id, args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"overlay-video")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.video_overlay_job({
        "input_video": str(video),
        "layers": [
            {"kind": "watermark", "image_data_url": _data_url(image), "x": 0.10, "y": 0.20, "width": 0.25, "opacity": 0.8},
            {"kind": "logo_cover", "image_data_url": _data_url(image), "x": 0.70, "y": 0.80, "width": 0.12, "opacity": 1.0, "remove_background": True},
        ],
    })
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done", job.error
    assert job.result["output_video"].endswith("demo.overlay.mp4")
    assert Path(job.result["output_video"]).exists()
    command = calls[0]
    assert command[:3] == ["ffmpeg", "-y", "-i"]
    assert command.count("-i") == 3
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "scale=480:-1" in filter_complex
    assert "overlay=192:216" in filter_complex
    assert "scale=230:-1" in filter_complex
    assert "overlay=1344:864" in filter_complex
    assert command[-1] == str(video.with_name("demo.overlay.mp4"))


def test_video_overlay_job_requires_at_least_one_enabled_layer(monkeypatch, tmp_path):
    video = tmp_path / "YoutubeDownloads" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")

    try:
        web_agent.video_overlay_job({"input_video": str(video), "layers": []})
    except ValueError as exc:
        assert "至少启用一层贴图" in str(exc)
    else:
        raise AssertionError("expected ValueError")

def test_video_overlay_output_defaults_to_mp4_for_non_mp4_input(tmp_path):
    video = tmp_path / "clip.webm"
    video.write_bytes(b"video")

    assert web_agent._unique_overlay_output_path(video) == tmp_path / "clip.overlay.mp4"

    (tmp_path / "clip.overlay.mp4").write_bytes(b"exists")
    assert web_agent._unique_overlay_output_path(video) == tmp_path / "clip.overlay-2.mp4"

