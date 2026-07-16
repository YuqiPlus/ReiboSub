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


def test_region_v3_preferred_keeps_tilted_text_as_soft_geometry_candidate():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    fake = _FakeOCR([
        ("정상 자막", 0.95, [(40, 8), (150, 8), (150, 28), (40, 28)]),
        ("기울어진 글자", 0.95, [(40, 8), (140, 44), (136, 58), (36, 22)]),
    ])
    rejected = []

    boxes = list(
        _ocr_frame(
            fake,
            frame,
            2.0,
            4,
            ExtractConfig(extraction_mode="region_v3", auto_trim_side_noise=False),
            rejected_boxes=rejected,
        )
    )

    assert [box.text for box in boxes] == ["정상 자막", "기울어진 글자"]
    assert boxes[0].polygon == ((40.0, 66.0), (150.0, 66.0), (150.0, 86.0), (40.0, 86.0))
    assert boxes[0].angle_degrees == 0.0
    assert boxes[0].shape_hint == "horizontal_candidate"
    assert boxes[1].angle_degrees > 15.0
    assert boxes[1].shape_hint == "tilted_soft_candidate"
    assert boxes[1].shape_limit_degrees == 15.0
    assert rejected == []


def test_region_v3_shape_modes_have_distinct_angle_policy():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    item = ("살짝 기울어진 자막", 0.95, [(30, 8), (150, 29), (147, 45), (27, 24)])

    preferred = list(
        _ocr_frame(
            _FakeOCR([item]),
            frame,
            1.0,
            3,
            ExtractConfig(extraction_mode="region_v3", shape_mode="horizontal_preferred", auto_trim_side_noise=False),
        )
    )
    strict_rejected = []
    strict = list(
        _ocr_frame(
            _FakeOCR([item]),
            frame,
            1.0,
            3,
            ExtractConfig(extraction_mode="region_v3", shape_mode="horizontal_strict", auto_trim_side_noise=False),
            rejected_boxes=strict_rejected,
        )
    )
    unrestricted = list(
        _ocr_frame(
            _FakeOCR([item]),
            frame,
            1.0,
            3,
            ExtractConfig(extraction_mode="region_v3", shape_mode="unrestricted", auto_trim_side_noise=False),
        )
    )

    assert len(preferred) == 1
    assert strict == []
    assert strict_rejected[0]["reason"] == "shape_angle_exceeds_horizontal_strict"
    assert len(unrestricted) == 1


def test_region_v2_ignores_shape_mode_and_preserves_legacy_json_shape():
    import numpy as np
    from video_translate.ocr.extractor import ExtractConfig, _ocr_frame

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    tilted = ("기울어진 글자", 0.95, [(40, 8), (140, 44), (136, 58), (36, 22)])

    boxes = list(
        _ocr_frame(
            _FakeOCR([tilted]),
            frame,
            1.0,
            3,
            ExtractConfig(extraction_mode="region", shape_mode="horizontal_strict", auto_trim_side_noise=False),
        )
    )

    assert len(boxes) == 1
    assert boxes[0].polygon is None
    assert boxes[0].angle_degrees is None
    assert "polygon" not in boxes[0].to_dict()
    assert "angle_degrees" not in boxes[0].to_dict()


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


def test_timing_refinement_uses_sequential_decode_without_seeking(monkeypatch: pytest.MonkeyPatch):
    import numpy as np

    from video_translate.models import OCRBox
    from video_translate.ocr import extractor

    class _FakeCapture:
        def __init__(self):
            self.next_index = 0
            self.read_indexes = []

        def read(self):
            index = self.next_index
            self.next_index += 1
            self.read_indexes.append(index)
            return True, np.zeros((20, 40, 3), dtype=np.uint8)

    visible = [OCRBox("안", (10, 10, 30, 30), 0.9, 0.0, 0, "bottom")]
    frame_results = {
        0: ([], "coarse"),
        5: (visible, "coarse"),
        10: (visible, "coarse"),
        15: ([], "coarse"),
    }
    capture = _FakeCapture()
    refined_indexes = []

    def fake_ocr_frame(*args, **kwargs):
        refined_indexes.append(args[3])
        return []

    monkeypatch.setattr(extractor, "_ocr_frame", fake_ocr_frame)

    extractor._refine_timing_boundaries(
        object(),
        capture,
        frame_results,
        frame_count=20,
        native_fps=30.0,
        config=extractor.ExtractConfig(refine_timing_boundaries=True),
    )

    assert capture.read_indexes == list(range(15))
    assert refined_indexes == [1, 2, 3, 4, 11, 12, 13, 14]
    assert all(frame_results[index][1] == "timing_refine" for index in refined_indexes)
