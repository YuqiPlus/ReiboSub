from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from video_translate.tools import transcribe_audio as audio_asr


def test_format_srt_timestamp_rounds_milliseconds():
    assert audio_asr.format_srt_timestamp(65.4326) == "00:01:05,433"


def test_normalize_language_accepts_auto_and_names():
    assert audio_asr.normalize_language("auto") is None
    assert audio_asr.normalize_language("korean") == "ko"
    assert audio_asr.normalize_language("ja") == "ja"


def test_write_segments_as_srt_skips_empty_text(tmp_path: Path):
    out = tmp_path / "source.srt"
    segments = [
        SimpleNamespace(start=0.0, end=1.2, text=" 안녕하세요 "),
        SimpleNamespace(start=1.4, end=2.0, text=""),
        SimpleNamespace(start=2.2, end=3.0, text="반갑습니다"),
    ]

    audio_asr.write_segments_as_srt(segments, out)

    assert out.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,200\n안녕하세요\n\n"
        "2\n00:00:02,200 --> 00:00:03,000\n반갑습니다\n"
    )


def test_write_segments_as_srt_tightens_timing_with_word_timestamps(tmp_path: Path):
    out = tmp_path / "source.srt"
    segments = [
        SimpleNamespace(
            start=0.0,
            end=5.0,
            text="안녕하세요",
            words=[
                SimpleNamespace(start=0.3, end=0.7, word="안녕"),
                SimpleNamespace(start=0.75, end=1.1, word="하세요"),
            ],
        ),
        SimpleNamespace(
            start=5.0,
            end=8.0,
            text="반갑습니다",
            words=[
                SimpleNamespace(start=5.4, end=6.0, word="반갑습니다"),
            ],
        ),
    ]

    audio_asr.write_segments_as_srt(segments, out)

    assert out.read_text(encoding="utf-8") == (
        "1\n00:00:00,300 --> 00:00:01,100\n안녕하세요\n\n"
        "2\n00:00:05,400 --> 00:00:06,000\n반갑습니다\n"
    )


def test_normalize_language_rejects_unknown():
    with pytest.raises(ValueError):
        audio_asr.normalize_language("esperanto")


def test_transcribe_audio_to_srt_configures_model_cache(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_text("video", encoding="utf-8")
    out = tmp_path / "source.srt"
    cache_root = tmp_path / "models"
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            captured["model_size"] = model_size
            captured["hf_home"] = audio_asr.os.environ.get("HF_HOME")
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, media, **kwargs):
            captured["media"] = media
            captured["kwargs"] = kwargs
            return [SimpleNamespace(start=0.0, end=1.0, text="안녕")], SimpleNamespace(language="ko")

    fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setenv("VIDEO_TRANSLATE_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("HF_HOME", raising=False)

    audio_asr.transcribe_audio_to_srt(video, out, model_size="large-v3", language="korean", device="cpu")

    assert captured["hf_home"] == str(cache_root / "huggingface")
    assert captured["kwargs"]["word_timestamps"] is True
    assert out.exists()


def test_detect_audio_language_returns_whisper_language_metadata(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_text("video", encoding="utf-8")
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, media, **kwargs):
            captured["media"] = media
            captured["kwargs"] = kwargs
            return iter(()), SimpleNamespace(language="ko", language_probability=0.91)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))

    result = audio_asr.detect_audio_language(video, model_size="large-v3", device="cpu", compute_type="int8")

    assert result == {"language": "ko", "language_probability": 0.91}
    assert captured["kwargs"]["language"] is None
    assert captured["kwargs"]["word_timestamps"] is False


def test_ensure_cuda_library_path_reexecs_when_path_changes(monkeypatch, tmp_path: Path):
    lib_dir = tmp_path / "nvidia" / "cublas" / "lib"
    lib_dir.mkdir(parents=True)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("VIDEO_TRANSLATE_CUDA_LIB_READY", raising=False)
    monkeypatch.setattr(audio_asr, "cuda_library_dirs", lambda: [lib_dir])
    captured = {}

    def fake_execvpe(executable, argv, env):
        captured["executable"] = executable
        captured["argv"] = argv
        captured["env"] = env
        raise RuntimeError("reexec")

    monkeypatch.setattr(audio_asr.os, "execvpe", fake_execvpe)

    with pytest.raises(RuntimeError, match="reexec"):
        audio_asr.ensure_cuda_library_path_ready("cuda")

    assert captured["env"]["LD_LIBRARY_PATH"] == str(lib_dir)
    assert captured["env"]["VIDEO_TRANSLATE_CUDA_LIB_READY"] == "1"
