from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from video_translate.cache import configure_model_cache
from video_translate.models import OCRBox
from video_translate.utils.text import normalize_ocr_text, text_similarity


@dataclass(slots=True)
class ExtractConfig:
    sample_fps: float = 3.0
    bottom_ratio: float = 0.42
    crop_top_ratio: float | None = None
    crop_bottom_ratio: float = 0.0
    crop_left_ratio: float = 0.0
    crop_right_ratio: float = 0.0
    exclude_enabled: bool = False
    exclude_top_ratio: float = 0.04
    exclude_bottom_ratio: float = 0.82
    exclude_left_ratio: float = 0.76
    exclude_right_ratio: float = 0.02
    min_confidence: float = 0.45
    refine_timing_boundaries: bool = False
    timing_refine_max_frames: int = 24
    scan_full_frame: bool = False
    auto_trim_side_noise: bool = True
    suppress_full_frame_duplicates: bool = True
    device: str = "auto"
    extraction_mode: str = "auto"
    shape_mode: str | None = None
    horizontal_preferred_max_angle_degrees: float = 15.0
    horizontal_strict_max_angle_degrees: float = 8.0


_EXTRACTION_MODES = {"auto", "region", "region_v3"}
_SHAPE_MODES = {"unrestricted", "horizontal_preferred", "horizontal_strict"}


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
    normalized = _configured_device(device)
    has_cuda = bool(paddle.device.is_compiled_with_cuda())
    if normalized == "auto":
        return "gpu:0" if has_cuda else "cpu"
    if normalized == "gpu":
        normalized = "gpu:0"
    if normalized.startswith("gpu") and not has_cuda:
        raise RuntimeError(
            "当前环境安装的是 CPU 版 paddlepaddle，无法使用 GPU。"
            "请先安装匹配 CUDA 的 paddlepaddle-gpu，或把 ocr.device 改为 cpu/auto。"
        )
    if normalized.startswith("gpu:") and has_cuda:
        device_id = _parse_gpu_device_id(normalized)
        device_count = int(paddle.device.cuda.device_count())
        if device_id >= device_count:
            raise RuntimeError(f"当前只检测到 {device_count} 张 GPU，不能使用 {normalized}。请改为 gpu:0、gpu 或 auto。")
    return normalized


def _parse_gpu_device_id(device: str) -> int:
    try:
        return int(device.split(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"GPU 设备格式错误: {device}，应类似 gpu:0") from exc


def _configured_device(device: str) -> str:
    normalized = (device or "auto").strip().lower()
    if normalized != "auto":
        return normalized
    env_device = os.environ.get("VIDEO_TRANSLATE_OCR_DEVICE", "").strip().lower()
    return env_device or normalized


def extract_video_ocr(
    video_path: Path,
    lang: str,
    config: ExtractConfig | None = None,
    sampled_frames: list[dict[str, Any]] | None = None,
    rejected_boxes: list[dict[str, Any]] | None = None,
) -> list[OCRBox]:
    config = config or ExtractConfig()
    _normalize_extraction_mode(config.extraction_mode)
    _resolved_shape_mode(config)
    cv2 = _load_cv2()
    ocr = _load_paddle_ocr(lang, config.device)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    native_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    video_duration = frame_count / native_fps if frame_count else None
    step = max(1, round(native_fps / config.sample_fps))
    total_samples = (frame_count + step - 1) // step if frame_count else None
    frame_index = 0
    sampled_count = 0
    frame_results: dict[int, tuple[list[OCRBox], str]] = {}
    progress_open = True

    _print_ocr_progress(0, total_samples, 0.0, video_duration)
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step != 0:
                frame_index += 1
                continue

            time_seconds = frame_index / native_fps
            frame_boxes = list(
                _ocr_frame(
                    ocr,
                    frame,
                    time_seconds,
                    frame_index,
                    config,
                    rejected_boxes=rejected_boxes,
                )
            )
            frame_results[frame_index] = (frame_boxes, "coarse")
            sampled_count += 1
            _print_ocr_progress(sampled_count, total_samples, time_seconds, video_duration)
            frame_index += 1

        # End the coarse-scan progress line before FFmpeg performs any random
        # access for boundary refinement.  Otherwise decoder diagnostics are
        # appended to the ``100%`` line and make a healthy follow-up stage look
        # like a crashed OCR run.
        _finish_ocr_progress()
        progress_open = False
        if config.refine_timing_boundaries:
            # Start boundary refinement with a fresh decoder at frame zero.
            # Sequential H.264 decoding preserves reference-frame state and
            # avoids the FFmpeg ``mmco`` warning storm caused by thousands of
            # random ``CAP_PROP_POS_FRAMES`` seeks on the exhausted decoder.
            capture.release()
            capture = cv2.VideoCapture(str(video_path))
            if capture.isOpened():
                _refine_timing_boundaries(
                    ocr,
                    capture,
                    frame_results,
                    frame_count=frame_count,
                    native_fps=native_fps,
                    config=config,
                    rejected_boxes=rejected_boxes,
                )
            else:
                sys.stderr.write(
                    "OCR timing refine warning: could not reopen video; coarse OCR samples were preserved\n"
                )
                sys.stderr.flush()
    finally:
        capture.release()
        if progress_open:
            _finish_ocr_progress()

    if sampled_frames is not None:
        sampled_frames.extend(
            {
                "frame_index": index,
                "time": index / native_fps,
                "scan_type": scan_type,
                "boxes": [box.to_dict() for box in frame_boxes],
            }
            for index, (frame_boxes, scan_type) in sorted(frame_results.items())
        )
    return [box for frame_boxes, _ in frame_results.values() for box in frame_boxes]


def _refine_timing_boundaries(
    ocr,
    capture,
    frame_results: dict[int, tuple[list[OCRBox], str]],
    *,
    frame_count: int,
    native_fps: float,
    config: ExtractConfig,
    rejected_boxes: list[dict[str, Any]] | None = None,
) -> None:
    indexes = _timing_refinement_frame_indexes(
        {index: frame_boxes for index, (frame_boxes, _) in frame_results.items()},
        frame_count=frame_count,
        max_frames=config.timing_refine_max_frames,
    )
    if not indexes:
        return

    sys.stderr.write(
        f"OCR timing refine: {len(indexes)} boundary frames via sequential decode\n"
    )
    sys.stderr.flush()
    target_cursor = 0
    next_target = indexes[target_cursor]
    decoded_index = 0
    refined_count = 0
    progress_interval = max(1, (len(indexes) + 19) // 20)
    while target_cursor < len(indexes):
        ok, frame = capture.read()
        if not ok:
            break
        if decoded_index == next_target:
            frame_results[next_target] = (
                list(
                    _ocr_frame(
                        ocr,
                        frame,
                        next_target / native_fps,
                        next_target,
                        config,
                        rejected_boxes=rejected_boxes,
                    )
                ),
                "timing_refine",
            )
            refined_count += 1
            target_cursor += 1
            if refined_count % progress_interval == 0 or target_cursor == len(indexes):
                percent = refined_count * 100.0 / len(indexes)
                sys.stderr.write(
                    f"OCR timing refine: {percent:5.1f}% "
                    f"{refined_count}/{len(indexes)} boundary frames\n"
                )
                sys.stderr.flush()
            if target_cursor == len(indexes):
                break
            next_target = indexes[target_cursor]
        decoded_index += 1

    failed_reads = len(indexes) - refined_count
    if failed_reads:
        sys.stderr.write(
            f"OCR timing refine warning: skipped {failed_reads} undecodable boundary frames; "
            "coarse OCR samples were preserved\n"
        )
        sys.stderr.flush()


def _timing_refinement_frame_indexes(
    frame_boxes: dict[int, list[OCRBox]],
    *,
    frame_count: int,
    max_frames: int,
) -> list[int]:
    indexes = sorted(frame_boxes)
    if not indexes:
        return []
    maximum = max(0, int(max_frames))
    selected: set[int] = set()
    for previous, current in zip(indexes, indexes[1:]):
        if bool(frame_boxes[previous]) == bool(frame_boxes[current]):
            continue
        between = list(range(previous + 1, current))
        if len(between) <= maximum:
            selected.update(between)
    last_index = indexes[-1]
    if frame_boxes[last_index]:
        trailing = range(last_index + 1, min(frame_count, last_index + maximum + 1))
        selected.update(trailing)
    return sorted(selected)


def _print_ocr_progress(
    sampled_count: int,
    total_samples: int | None,
    time_seconds: float,
    video_duration: float | None,
) -> None:
    width = 28
    if total_samples:
        ratio = min(1.0, sampled_count / total_samples)
        filled = min(width, int(width * ratio))
        bar = "#" * filled + "-" * (width - filled)
        percent = ratio * 100
        message = (
            f"\rOCR [{bar}] {percent:6.2f}% "
            f"{sampled_count}/{total_samples} samples "
            f"{_format_duration(time_seconds)}/{_format_duration(video_duration)}"
        )
    else:
        message = f"\rOCR {sampled_count} samples {_format_duration(time_seconds)}"
    sys.stderr.write(message)
    sys.stderr.flush()


def _finish_ocr_progress() -> None:
    sys.stderr.write("\n")
    sys.stderr.flush()


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _ocr_frame(
    ocr,
    frame,
    time_seconds: float,
    frame_index: int,
    config: ExtractConfig,
    rejected_boxes: list[dict[str, Any]] | None = None,
) -> Iterable[OCRBox]:
    height, width = frame.shape[:2]
    top_y, bottom_y = _vertical_crop_bounds(height, config)
    left_x, right_x = _horizontal_crop_bounds(width, config.crop_left_ratio, config.crop_right_ratio)
    bottom_boxes = list(
        _ocr_region(
            ocr,
            frame[top_y:bottom_y, left_x:right_x],
            time_seconds,
            frame_index,
            config,
            "bottom",
            left_x,
            top_y,
            height,
            width,
            rejected_boxes,
        )
    )
    for box in bottom_boxes:
        yield box

    if config.scan_full_frame:
        full_boxes = _ocr_region(
            ocr,
            frame,
            time_seconds,
            frame_index,
            config,
            "full",
            0,
            0,
            height,
            width,
            rejected_boxes,
        )
        for box in full_boxes:
            if config.suppress_full_frame_duplicates and _duplicates_bottom_box(box, bottom_boxes):
                if _normalize_extraction_mode(config.extraction_mode) == "region_v3":
                    _record_rejected_box(rejected_boxes, box, "full_frame_duplicate")
                continue
            yield box


def _ocr_region(
    ocr,
    image,
    time_seconds: float,
    frame_index: int,
    config: ExtractConfig,
    region_name: str,
    offset_x: int,
    offset_y: int,
    frame_height: int,
    frame_width: int,
    rejected_boxes: list[dict[str, Any]] | None = None,
) -> Iterable[OCRBox]:
    result = ocr.predict(
        image,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    is_region_v3 = _normalize_extraction_mode(config.extraction_mode) == "region_v3"
    shape_mode = _resolved_shape_mode(config)
    for text, confidence, raw_points in _iter_ocr_items(result):
        confidence = float(confidence)
        polygon = tuple((float(point[0]) + offset_x, float(point[1]) + offset_y) for point in raw_points)
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        if not xs or not ys:
            continue
        bbox = (min(xs), min(ys), max(xs), max(ys))
        angle_degrees = _polygon_baseline_angle_degrees(polygon) if is_region_v3 else None
        box = OCRBox(
            text=str(text),
            bbox=bbox,
            confidence=confidence,
            time=time_seconds,
            frame_index=frame_index,
            region=_position_region(region_name, bbox, frame_height),
            polygon=polygon if is_region_v3 else None,
            angle_degrees=angle_degrees,
        )
        if is_region_v3:
            box.shape_hint, box.shape_limit_degrees = _shape_hint(
                box.angle_degrees,
                shape_mode,
                config,
            )
        if confidence < config.min_confidence:
            if is_region_v3:
                _record_rejected_box(rejected_boxes, box, "below_min_confidence")
            continue
        if config.exclude_enabled and _box_center_in_exclude_region(bbox, frame_width, frame_height, config):
            if is_region_v3:
                _record_rejected_box(rejected_boxes, box, "inside_exclude_region")
            continue
        if region_name == "bottom" and config.auto_trim_side_noise and _looks_like_bottom_side_noise(bbox, str(text), frame_width, frame_height):
            if is_region_v3:
                _record_rejected_box(rejected_boxes, box, "bottom_side_noise")
            continue
        rejection_reason, angle_limit = _shape_rejection(box.angle_degrees, shape_mode, config)
        if is_region_v3 and rejection_reason:
            _record_rejected_box(
                rejected_boxes,
                box,
                rejection_reason,
                shape_mode=shape_mode,
                angle_limit_degrees=angle_limit,
            )
            continue
        yield box


def _normalize_extraction_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in _EXTRACTION_MODES:
        raise ValueError(f"未知 OCR 提取模式: {mode}")
    return mode


def _resolved_shape_mode(config: ExtractConfig) -> str:
    if _normalize_extraction_mode(config.extraction_mode) != "region_v3":
        return "unrestricted"
    raw_mode = config.shape_mode
    if raw_mode is None or not str(raw_mode).strip():
        return "horizontal_preferred"
    mode = str(raw_mode).strip().lower()
    if mode not in _SHAPE_MODES:
        raise ValueError(f"未知 OCR 文字形态模式: {mode}")
    return mode


def _polygon_baseline_angle_degrees(polygon: tuple[tuple[float, float], ...]) -> float | None:
    """Return the signed text baseline angle normalized to [-90, 90).

    PaddleOCR orders quadrilateral points around the text line. The first edge
    and the reversed opposite edge therefore point along the reading baseline.
    Averaging both makes the estimate less sensitive to perspective skew while
    still handling one-character boxes whose height can exceed their width.
    """

    if len(polygon) < 2:
        return None
    first_dx = polygon[1][0] - polygon[0][0]
    first_dy = polygon[1][1] - polygon[0][1]
    dx = first_dx
    dy = first_dy
    if len(polygon) >= 4:
        opposite_dx = polygon[2][0] - polygon[3][0]
        opposite_dy = polygon[2][1] - polygon[3][1]
        if math.hypot(opposite_dx, opposite_dy) > 1e-6:
            dx += opposite_dx
            dy += opposite_dy
    if math.hypot(dx, dy) <= 1e-6:
        dx, dy = first_dx, first_dy
    if math.hypot(dx, dy) <= 1e-6:
        return None
    angle = math.degrees(math.atan2(dy, dx))
    normalized = (angle + 90.0) % 180.0 - 90.0
    return round(normalized, 3)


def _shape_rejection(
    angle_degrees: float | None,
    shape_mode: str,
    config: ExtractConfig,
) -> tuple[str | None, float | None]:
    if shape_mode == "unrestricted":
        return None, None
    if angle_degrees is None or not math.isfinite(angle_degrees):
        if shape_mode == "horizontal_strict":
            return "shape_missing_polygon_geometry", None
        # Preferred mode is deliberately conservative when PaddleOCR supplies
        # no usable geometry, avoiding a new false-negative source.
        return None, None
    if shape_mode != "horizontal_strict":
        # OCR 3.0 preferred mode is a soft geometry hint. The candidate must
        # reach the track/LLM stage; angle alone cannot distinguish a product
        # label from a deliberately slanted program caption.
        return None, _clamp_angle_limit(config.horizontal_preferred_max_angle_degrees, 15.0)
    limit = _clamp_angle_limit(config.horizontal_strict_max_angle_degrees, 8.0)
    reason = "shape_angle_exceeds_horizontal_strict"
    if abs(angle_degrees) > limit:
        return reason, limit
    return None, limit


def _shape_hint(
    angle_degrees: float | None,
    shape_mode: str,
    config: ExtractConfig,
) -> tuple[str, float | None]:
    if shape_mode == "unrestricted":
        return "unrestricted_candidate", None
    if shape_mode == "horizontal_strict":
        limit = _clamp_angle_limit(config.horizontal_strict_max_angle_degrees, 8.0)
        if angle_degrees is None or not math.isfinite(angle_degrees):
            return "geometry_missing_hard_reject", limit
        if abs(angle_degrees) > limit:
            return "tilted_hard_reject", limit
        return "horizontal_candidate", limit
    limit = _clamp_angle_limit(config.horizontal_preferred_max_angle_degrees, 15.0)
    if angle_degrees is None or not math.isfinite(angle_degrees):
        return "geometry_unknown_candidate", limit
    if abs(angle_degrees) > limit:
        return "tilted_soft_candidate", limit
    return "horizontal_candidate", limit


def _record_rejected_box(
    rejected_boxes: list[dict[str, Any]] | None,
    box: OCRBox,
    reason: str,
    *,
    shape_mode: str | None = None,
    angle_limit_degrees: float | None = None,
) -> None:
    if rejected_boxes is None:
        return
    item = box.to_dict()
    item["reason"] = reason
    if shape_mode is not None:
        item["shape_mode"] = shape_mode
    if angle_limit_degrees is not None:
        item["angle_limit_degrees"] = angle_limit_degrees
    rejected_boxes.append(item)


def _clamp_angle_limit(value: float, fallback: float) -> float:
    try:
        limit = float(value)
    except (TypeError, ValueError):
        limit = fallback
    if not math.isfinite(limit):
        limit = fallback
    return max(0.0, min(90.0, limit))




def _vertical_crop_bounds(height: int, config: ExtractConfig) -> tuple[int, int]:
    if config.crop_top_ratio is None:
        top_ratio = 1 - _clamp_crop_ratio(config.bottom_ratio)
        bottom_ratio = 0.0
    else:
        top_ratio = _clamp_vertical_crop_ratio(config.crop_top_ratio)
        bottom_ratio = _clamp_vertical_crop_ratio(config.crop_bottom_ratio)
    top_y = int(height * top_ratio)
    bottom_y = int(height * (1 - bottom_ratio))
    if bottom_y <= top_y:
        return int(height * (1 - _clamp_crop_ratio(config.bottom_ratio))), height
    return top_y, bottom_y

def _horizontal_crop_bounds(width: int, left_ratio: float, right_ratio: float) -> tuple[int, int]:
    left = _clamp_crop_ratio(left_ratio)
    right = _clamp_crop_ratio(right_ratio)
    left_x = int(width * left)
    right_x = int(width * (1 - right))
    if right_x <= left_x:
        return 0, width
    return left_x, right_x


def _box_center_in_exclude_region(
    bbox: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    config: ExtractConfig,
) -> bool:
    left, top, right, bottom = _exclude_region_bounds(frame_width, frame_height, config)
    if right <= left or bottom <= top:
        return False
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return left <= center_x <= right and top <= center_y <= bottom


def _exclude_region_bounds(width: int, height: int, config: ExtractConfig) -> tuple[int, int, int, int]:
    left_ratio = _clamp_unit_ratio(config.exclude_left_ratio)
    right_ratio = _clamp_unit_ratio(config.exclude_right_ratio)
    top_ratio = _clamp_unit_ratio(config.exclude_top_ratio)
    bottom_ratio = _clamp_unit_ratio(config.exclude_bottom_ratio)
    left = int(width * left_ratio)
    right = int(width * (1 - right_ratio))
    top = int(height * top_ratio)
    bottom = int(height * (1 - bottom_ratio))
    if right <= left or bottom <= top:
        return 0, 0, 0, 0
    return left, top, right, bottom


def _clamp_crop_ratio(value: float) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(0.45, ratio))


def _clamp_vertical_crop_ratio(value: float) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(0.95, ratio))


def _clamp_unit_ratio(value: float) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(0.98, ratio))


def _looks_like_bottom_side_noise(
    bbox: tuple[float, float, float, float],
    text: str,
    frame_width: int,
    frame_height: int,
) -> bool:
    if frame_width <= 0 or frame_height <= 0:
        return False
    normalized = normalize_ocr_text(text)
    if not normalized:
        return True
    x1, y1, x2, y2 = bbox
    box_width_ratio = max(0.0, x2 - x1) / frame_width
    box_height_ratio = max(0.0, y2 - y1) / frame_height
    center_x_ratio = ((x1 + x2) / 2) / frame_width
    near_edge = x1 <= frame_width * 0.08 or x2 >= frame_width * 0.92 or center_x_ratio <= 0.15 or center_x_ratio >= 0.85
    compact = box_width_ratio <= 0.20 and box_height_ratio <= 0.12 and len(normalized) <= 16
    return bool(near_edge and compact)

def _position_region(region_name: str, bbox: tuple[float, float, float, float], frame_height: int) -> str:
    if region_name == "bottom":
        return "bottom"
    center_y = (bbox[1] + bbox[3]) / 2
    ratio = center_y / max(1, frame_height)
    if ratio < 0.30:
        band = "top"
    elif ratio < 0.62:
        band = "middle"
    else:
        band = "lower"
    return f"full_{band}"


def _duplicates_bottom_box(box: OCRBox, bottom_boxes: list[OCRBox]) -> bool:
    text = normalize_ocr_text(box.text)
    if not text:
        return False
    for bottom in bottom_boxes:
        if _bbox_iou(box.bbox, bottom.bbox) >= 0.55:
            return True
        if abs(_box_center_y(box) - _box_center_y(bottom)) <= 36 and text_similarity(text, normalize_ocr_text(bottom.text)) >= 0.86:
            return True
    return False


def _bbox_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _box_center_y(box: OCRBox) -> float:
    return (box.bbox[1] + box.bbox[3]) / 2


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
