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


class _FakeOCR:
    def __init__(self, items):
        self.items = items
        self.seen_shapes = []

    def predict(self, image, **kwargs):
        self.seen_shapes.append(tuple(image.shape[:2]))
        return [{
            "rec_texts": [item[0] for item in self.items],
            "rec_scores": [item[1] for item in self.items],
            "rec_polys": [item[2] for item in self.items],
        }]


def test_ocr_frame_applies_horizontal_bottom_crop_and_restores_coordinates():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    fake = _FakeOCR([("자막", 0.9, [(10, 4), (60, 4), (60, 20), (10, 20)])])

    boxes = list(_ocr_frame(fake, frame, 1.0, 3, ExtractConfig(bottom_ratio=0.40, crop_left_ratio=0.10, crop_right_ratio=0.20, scan_full_frame=False)))

    assert fake.seen_shapes == [(40, 140)]
    assert boxes[0].bbox == (30.0, 64.0, 80.0, 80.0)
    assert boxes[0].region == "bottom"


def test_ocr_frame_filters_small_bottom_edge_noise_by_default():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    fake = _FakeOCR([
        ("LOGO", 0.95, [(176, 24), (196, 24), (196, 36), (176, 36)]),
        ("정상 자막입니다", 0.95, [(60, 8), (150, 8), (150, 28), (60, 28)]),
    ])

    boxes = list(_ocr_frame(fake, frame, 1.0, 3, ExtractConfig(bottom_ratio=0.40)))

    assert [box.text for box in boxes] == ["정상 자막입니다"]



def test_ocr_frame_applies_vertical_crop_and_restores_coordinates():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    fake = _FakeOCR([("상단 자막", 0.9, [(10, 4), (80, 4), (80, 18), (10, 18)])])

    boxes = list(_ocr_frame(fake, frame, 2.0, 4, ExtractConfig(crop_top_ratio=0.25, crop_bottom_ratio=0.30, crop_left_ratio=0.10, crop_right_ratio=0.20)))

    assert fake.seen_shapes == [(45, 140)]
    assert boxes[0].bbox == (30.0, 29.0, 100.0, 43.0)
    assert boxes[0].region == "bottom"


def test_ocr_frame_filters_boxes_inside_exclude_region():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    fake = _FakeOCR([
        ("LOGO", 0.95, [(156, 8), (194, 8), (194, 24), (156, 24)]),
        ("정상 자막", 0.95, [(40, 70), (150, 70), (150, 90), (40, 90)]),
    ])

    boxes = list(
        _ocr_frame(
            fake,
            frame,
            2.0,
            4,
            ExtractConfig(
                crop_top_ratio=0.0,
                crop_bottom_ratio=0.0,
                exclude_enabled=True,
                exclude_top_ratio=0.0,
                exclude_bottom_ratio=0.70,
                exclude_left_ratio=0.75,
                exclude_right_ratio=0.0,
                auto_trim_side_noise=False,
            ),
        )
    )

    assert [box.text for box in boxes] == ["정상 자막"]


def test_timing_refinement_only_rescans_presence_boundaries():
    from video_translate.models import OCRBox
    from video_translate.ocr.extractor import _timing_refinement_frame_indexes

    visible = [OCRBox("안", (10, 10, 30, 30), 0.9, 0.0, 0, "bottom")]
    indexes = _timing_refinement_frame_indexes(
        {
            0: [],
            5: visible,
            10: visible,
            15: [],
        },
        frame_count=20,
        max_frames=24,
    )

    assert indexes == [1, 2, 3, 4, 11, 12, 13, 14]


def test_timing_refinement_limits_large_sampling_gaps():
    from video_translate.models import OCRBox
    from video_translate.ocr.extractor import _timing_refinement_frame_indexes

    visible = [OCRBox("안", (10, 10, 30, 30), 0.9, 0.0, 0, "bottom")]
    indexes = _timing_refinement_frame_indexes({0: [], 60: visible}, frame_count=90, max_frames=24)

    assert indexes == list(range(61, 85))
