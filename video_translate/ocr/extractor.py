from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from video_translate.cache import configure_model_cache
from video_translate.models import OCRBox


@dataclass(slots=True)
class ExtractConfig:
    sample_fps: float = 3.0
    bottom_ratio: float = 0.42
    min_confidence: float = 0.45
    scan_full_frame: bool = False
    device: str = "auto"


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 opencv-python，请先安装依赖。") from exc
    return cv2


def _load_paddle_ocr(lang: str, device: str = "auto"):
    configure_model_cache()
    try:
        import paddle  # type: ignore
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 paddleocr，请先安装依赖。") from exc
    selected_device = _resolve_device(device, paddle)
    return PaddleOCR(
        lang=lang,
        device=selected_device,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _resolve_device(device: str, paddle) -> str:
    normalized = (device or "auto").strip().lower()
    has_cuda = bool(paddle.device.is_compiled_with_cuda())
    if normalized == "auto":
        return "gpu:0" if has_cuda else "cpu"
    if normalized.startswith("gpu") and not has_cuda:
        raise RuntimeError(
            "当前环境安装的是 CPU 版 paddlepaddle，无法使用 GPU。"
            "请先安装匹配 CUDA 的 paddlepaddle-gpu，或把 ocr.device 改为 cpu/auto。"
        )
    return normalized


def extract_video_ocr(
    video_path: Path,
    lang: str,
    config: ExtractConfig | None = None,
) -> list[OCRBox]:
    config = config or ExtractConfig()
    cv2 = _load_cv2()
    ocr = _load_paddle_ocr(lang, config.device)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    native_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(native_fps / config.sample_fps))
    frame_index = 0
    boxes: list[OCRBox] = []

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step != 0:
                frame_index += 1
                continue

            time_seconds = frame_index / native_fps
            boxes.extend(_ocr_frame(ocr, frame, time_seconds, frame_index, config))
            frame_index += 1
    finally:
        capture.release()

    return boxes


def _ocr_frame(ocr, frame, time_seconds: float, frame_index: int, config: ExtractConfig) -> Iterable[OCRBox]:
    height, width = frame.shape[:2]
    regions: list[tuple[str, int, object]] = []
    bottom_y = int(height * (1 - config.bottom_ratio))
    regions.append(("bottom", bottom_y, frame[bottom_y:height, 0:width]))
    if config.scan_full_frame:
        regions.append(("full", 0, frame))

    for region_name, offset_y, image in regions:
        result = ocr.predict(
            image,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        for text, confidence, raw_points in _iter_ocr_items(result):
            confidence = float(confidence)
            if confidence < config.min_confidence:
                continue
            xs = [float(point[0]) for point in raw_points]
            ys = [float(point[1]) + offset_y for point in raw_points]
            yield OCRBox(
                text=str(text),
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                confidence=confidence,
                time=time_seconds,
                frame_index=frame_index,
                region=region_name,
            )


def _iter_ocr_items(result):
    for page in result or []:
        if isinstance(page, dict) and "rec_texts" in page:
            polys = page.get("rec_polys") or page.get("dt_polys") or []
            for text, score, poly in zip(page.get("rec_texts", []), page.get("rec_scores", []), polys):
                yield text, score, poly
            continue

        for line in page or []:
            for item in line or []:
                raw_points, raw_text = item
                text, confidence = raw_text
                yield text, confidence, raw_points
