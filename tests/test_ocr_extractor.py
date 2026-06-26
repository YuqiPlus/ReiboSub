from __future__ import annotations

import pytest

from video_translate.ocr.extractor import _resolve_device


class _FakeCuda:
    def __init__(self, count: int):
        self._count = count

    def device_count(self) -> int:
        return self._count


class _FakeDevice:
    def __init__(self, *, has_cuda: bool, count: int = 0):
        self._has_cuda = has_cuda
        self.cuda = _FakeCuda(count)

    def is_compiled_with_cuda(self) -> bool:
        return self._has_cuda


class _FakePaddle:
    def __init__(self, *, has_cuda: bool, count: int = 0):
        self.device = _FakeDevice(has_cuda=has_cuda, count=count)


def test_resolve_device_auto_uses_first_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_TRANSLATE_OCR_DEVICE", raising=False)
    assert _resolve_device("auto", _FakePaddle(has_cuda=True, count=1)) == "gpu:0"


def test_resolve_device_rejects_unavailable_gpu_id() -> None:
    with pytest.raises(RuntimeError, match="gpu:0"):
        _resolve_device("gpu:1", _FakePaddle(has_cuda=True, count=1))


def test_resolve_device_auto_uses_cpu_without_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_TRANSLATE_OCR_DEVICE", raising=False)
    assert _resolve_device("auto", _FakePaddle(has_cuda=False)) == "cpu"


def test_resolve_device_auto_uses_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_TRANSLATE_OCR_DEVICE", "cpu")

    assert _resolve_device("auto", _FakePaddle(has_cuda=True, count=1)) == "cpu"


def test_resolve_device_explicit_value_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_TRANSLATE_OCR_DEVICE", "cpu")

    assert _resolve_device("gpu:0", _FakePaddle(has_cuda=True, count=1)) == "gpu:0"
