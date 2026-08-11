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


def test_video_overlay_job_requires_a_layer_or_transform(monkeypatch, tmp_path):
    video = tmp_path / "YoutubeDownloads" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")

    try:
        web_agent.video_overlay_job({"input_video": str(video), "layers": []})
    except ValueError as exc:
        assert "至少启用一种画面变换" in str(exc)
    else:
        raise AssertionError("expected ValueError")

def test_video_overlay_output_defaults_to_mp4_for_non_mp4_input(tmp_path):
    video = tmp_path / "clip.webm"
    video.write_bytes(b"video")

    assert web_agent._unique_overlay_output_path(video) == tmp_path / "clip.overlay.mp4"

    (tmp_path / "clip.overlay.mp4").write_bytes(b"exists")
    assert web_agent._unique_overlay_output_path(video) == tmp_path / "clip.overlay-2.mp4"


def test_video_transform_only_job_builds_flip_crop_and_proportional_scale(monkeypatch, tmp_path):
    video = tmp_path / "YoutubeDownloads" / "demo" / "demo.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    monkeypatch.setattr(web_agent, "ROOT", tmp_path)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path / "YoutubeDownloads")
    monkeypatch.setattr(web_agent, "JOB_DIR", tmp_path / "outputs" / "agent_jobs")
    monkeypatch.setattr(web_agent, "_video_dimensions", lambda path: (1920, 1080))
    calls: list[list[str]] = []

    def fake_run_command(job_id, args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"processed-video")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)

    job = web_agent.video_overlay_job({
        "input_video": str(video),
        "layers": [],
        "transform": {
            "horizontal_flip": True,
            "crop_left_ratio": 0.10,
            "crop_right_ratio": 0.05,
            "crop_top_ratio": 0.10,
            "crop_bottom_ratio": 0.10,
            "output_width": 1280,
        },
    })
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done", job.error
    assert job.result["output_video"].endswith("demo.processed.mp4")
    assert job.result["layers"] == []
    assert job.result["transform"]["crop_width"] == 1632
    assert job.result["transform"]["crop_height"] == 864
    assert job.result["transform"]["output_width"] == 1280
    assert job.result["transform"]["output_height"] == 676
    command = calls[0]
    assert command.count("-i") == 1
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[0:v]hflip,crop=1632:864:192:108:exact=1,scale=1280:676:flags=lanczos,setsar=1[vbase]" in filter_complex
    assert "[vbase]format=yuv420p[vout]" in filter_complex
    assert command[command.index("-map") + 1] == "[vout]"


def test_video_transform_scales_overlay_against_final_output(monkeypatch, tmp_path):
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
        Path(args[-1]).write_bytes(b"processed-video")

    monkeypatch.setattr(web_agent, "_run_command", fake_run_command)
    job = web_agent.video_overlay_job({
        "input_video": str(video),
        "layers": [
            {"kind": "watermark", "image_data_url": _data_url(image), "x": 0.10, "y": 0.20, "width": 0.25},
        ],
        "transform": {
            "crop_left_ratio": 0.10,
            "crop_right_ratio": 0.10,
            "crop_top_ratio": 0.10,
            "crop_bottom_ratio": 0.10,
            "output_width": 1280,
            "output_height": 720,
        },
    })
    deadline = time.time() + 2
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert job.status == "done", job.error
    filter_complex = calls[0][calls[0].index("-filter_complex") + 1]
    assert "crop=1536:864:192:108:exact=1" in filter_complex
    assert "scale=1280:720:flags=lanczos" in filter_complex
    assert "scale=320:-1" in filter_complex
    assert "overlay=128:144" in filter_complex


def test_video_transform_rejects_invalid_crop_and_oversized_output():
    try:
        web_agent._normalize_video_transform({"crop_left_ratio": 0.60, "crop_right_ratio": 0.40})
    except ValueError as exc:
        assert "左右裁剪比例" in str(exc)
    else:
        raise AssertionError("expected invalid crop error")

    normalized = web_agent._normalize_video_transform({"output_width": 8192, "output_height": 4052})
    try:
        web_agent._resolve_video_transform(normalized, 8192, 4052)
    except ValueError as exc:
        assert "总像素过大" in str(exc)
    else:
        raise AssertionError("expected oversized output error")

    allowed = web_agent._normalize_video_transform({"output_width": 7680, "output_height": 4320})
    resolved = web_agent._resolve_video_transform(allowed, 7680, 4320)
    assert (resolved["output_width"], resolved["output_height"]) == (7680, 4320)


def test_processed_output_uses_a_non_conflicting_mp4_name(tmp_path):
    video = tmp_path / "clip.webm"
    video.write_bytes(b"video")

    assert web_agent._unique_processed_output_path(video) == tmp_path / "clip.processed.mp4"
    (tmp_path / "clip.processed.mp4").write_bytes(b"exists")
    assert web_agent._unique_processed_output_path(video) == tmp_path / "clip.processed-2.mp4"


def test_video_output_reservations_prevent_concurrent_name_collisions(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    first = web_agent._reserve_unique_derived_video_path(video, "processed")
    second = web_agent._reserve_unique_derived_video_path(video, "processed")
    try:
        assert first == tmp_path / "clip.processed.mp4"
        assert second == tmp_path / "clip.processed-2.mp4"
    finally:
        web_agent._release_reserved_video_output(first)
        web_agent._release_reserved_video_output(second)


def test_video_transform_parses_explicit_false_without_enabling_mirror():
    assert web_agent._normalize_video_transform({"horizontal_flip": "false"})["horizontal_flip"] is False
