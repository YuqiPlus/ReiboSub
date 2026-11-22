"""Optional PaddleOCR adapter, image text and basic sampled-video subtitles.

This is not the web application's OCR 3.0/LLM refinement pipeline.
"""
from __future__ import annotations

from importlib import import_module
import math
import os
from pathlib import Path
import re
import threading
from typing import Any

from .errors import MissingDependencyError, ModelUnavailableError, RecognitionError, ValidationError
from .models import Cue, Progress, Subtitle
from .recognition import CancelCheck, OCRBackend, ProgressCallback, TextRegion, check_cancelled, finite, local_file


class PaddleOCRBackend:
    """PaddleOCR 3.x, with optional local detection/recognition model directories.

    Default downloads/cache are owned by PaddleX, not the ReiboSub wheel.
    Strict local mode requires both directories and disabling PaddleX's source
    connectivity probe before process start. No global environment is changed.
    """

    def __init__(
        self, *, language: str = "korean", device: str = "cpu",
        ocr_version: str = "PP-OCRv5", local_files_only: bool = False,
        detection_model_dir: str | Path | None = None,
        recognition_model_dir: str | Path | None = None,
        detection_model_name: str | None = None,
        recognition_model_name: str | None = None,
        enable_mkldnn: bool = False,
    ) -> None:
        if not isinstance(language, str) or not language.strip():
            raise ValidationError("OCR language must be a PaddleOCR language code")
        if not isinstance(device, str) or not re.fullmatch(r"cpu|gpu(?::\d+)?", device):
            raise ValidationError("OCR device must be cpu, gpu or gpu:N")
        if type(local_files_only) is not bool or type(enable_mkldnn) is not bool:
            raise ValidationError("local_files_only and enable_mkldnn must be booleans")
        if not isinstance(ocr_version, str) or not ocr_version.strip():
            raise ValidationError("ocr_version must be a non-empty string")
        for name in (detection_model_name, recognition_model_name):
            if name is not None and (not isinstance(name, str) or not name.strip()):
                raise ValidationError("model names must be non-empty strings or None")
        self._dirs = {
            "text_detection_model_dir": Path(detection_model_dir).expanduser() if detection_model_dir is not None else None,
            "text_recognition_model_dir": Path(recognition_model_dir).expanduser() if recognition_model_dir is not None else None,
        }
        if local_files_only and any(value is None for value in self._dirs.values()):
            raise ValidationError("Offline OCR requires both detection_model_dir and recognition_model_dir")
        self._offline = local_files_only
        self._options = dict(lang=language, device=device, ocr_version=ocr_version,
                             use_doc_orientation_classify=False, use_doc_unwarping=False,
                             use_textline_orientation=False, enable_mkldnn=enable_mkldnn)
        if detection_model_name is not None:
            self._options["text_detection_model_name"] = detection_model_name
        if recognition_model_name is not None:
            self._options["text_recognition_model_name"] = recognition_model_name
        self._model = None
        self._lock = threading.RLock()

    def prepare(self) -> PaddleOCRBackend:
        with self._lock:
            if self._model is not None:
                return self
            for directory in self._dirs.values():
                if directory is not None:
                    # Reject incomplete paths before the upstream loader could
                    # fall back to downloading official model weights.
                    if not directory.is_dir() or not (directory / "inference.pdiparams").is_file() or not any((directory / name).is_file() for name in ("inference.json", "inference.pdmodel")):
                        raise ModelUnavailableError("OCR model directory must contain inference.pdiparams and inference.json or inference.pdmodel")
            if self._offline and os.environ.get("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "").lower() not in {"true", "1"}:
                raise ModelUnavailableError("For offline OCR, set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True before starting Python to disable the upstream connectivity probe")
            try:
                paddle = import_module("paddle")
                factory = import_module("paddleocr").PaddleOCR
            except (ImportError, OSError):
                raise MissingDependencyError('OCR needs optional dependencies: python -m pip install "reibosub[ocr-cpu]"; for GPU install reibosub[ocr] and a compatible Paddle GPU runtime separately') from None
            device = self._options["device"]
            if device.startswith("gpu"):
                if not paddle.device.is_compiled_with_cuda():
                    raise ModelUnavailableError("GPU OCR requested but Paddle is CPU-only; install the matching GPU runtime or explicitly select cpu")
                index = int(device.split(":", 1)[1]) if ":" in device else 0
                if index >= paddle.device.cuda.device_count():
                    raise ModelUnavailableError("Requested OCR GPU does not exist")
            options = {**self._options, **{key: str(path) for key, path in self._dirs.items() if path is not None}}
            try:
                self._model = factory(**options)
            except Exception:
                raise ModelUnavailableError("Could not load OCR models. Check local model configuration, cache/network access and the Paddle runtime; no packages were installed or fallback model selected") from None
        return self

    def close(self) -> None:
        with self._lock:
            if self._model is not None:
                closer = getattr(self._model, "close", None)
                try:
                    if callable(closer):
                        closer()
                finally:
                    self._model = None

    def recognize(self, image: Any) -> tuple[TextRegion, ...]:
        if isinstance(image, (str, Path)):
            image = str(local_file(image))
        with self._lock:
            self.prepare()
            try:
                results = iter(self._model.predict(image))
                result = next(results)
                texts, scores, polygons = result["rec_texts"], result["rec_scores"], result["rec_polys"]
                if not len(texts) == len(scores) == len(polygons):
                    raise ValueError("mismatched OCR arrays")
                regions = tuple(TextRegion(text, float(score), tuple(tuple(float(v) for v in point) for point in polygon))
                                for text, score, polygon in zip(texts, scores, polygons))
                if next(results, None) is not None:
                    raise ValueError("Expected one image, not a PDF/batch")
                return regions
            except Exception:
                raise RecognitionError("OCR failed or returned malformed image regions; expected one image with text, score and polygon arrays") from None


def _rectangle(value, name):
    try:
        x0, y0, x1, y1 = tuple(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be (left, top, right, bottom) ratios") from None
    values = tuple(finite(v, name) for v in (x0, y0, x1, y1))
    if not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
        raise ValidationError(f"{name} requires 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
    return values


class OCR:
    """Image OCR and coarse video extraction; inject OCRBackend for other engines."""

    def __init__(self, backend: OCRBackend | None = None, **options) -> None:
        if backend is not None and options:
            raise ValidationError("Configure custom backend options on the backend itself")
        self.backend = backend if backend is not None else PaddleOCRBackend(**options)
        if not callable(getattr(self.backend, "recognize", None)):
            raise ValidationError("backend must implement recognize()")

    def read_image(self, image: Any, *, cancelled: CancelCheck | None = None) -> tuple[TextRegion, ...]:
        """Local image path or BGR ndarray; remote URLs are not downloaded."""
        check_cancelled(cancelled)
        if isinstance(image, (str, Path)):
            image = local_file(image)
        raw = self.backend.recognize(image)
        try:
            result = tuple(raw)
        except TypeError:
            raise RecognitionError("OCR backend must return an iterable of TextRegion objects") from None
        check_cancelled(cancelled)
        if any(not isinstance(region, TextRegion) for region in result):
            raise RecognitionError("OCR backend must return TextRegion objects")
        return result

    def extract_subtitles(
        self, source: str | Path, *, sample_fps: float = 3,
        crop: tuple[float, float, float, float] = (0, 0, 1, 1),
        exclude: tuple[tuple[float, float, float, float], ...] = (),
        start: float = 0, end: float | None = None, min_confidence: float = 0.5,
        language: str | None = None, on_progress: ProgressCallback | None = None,
        cancelled: CancelCheck | None = None,
    ) -> Subtitle:
        """Sequential decoding, crop/masks, and exact adjacent-text merging.

        Coordinates are ratios relative to the full frame. Timing is coarse
        (sample-resolution), not audio alignment. No LLM or website is involved.
        """
        sample_fps = finite(sample_fps, "sample_fps")
        if not 0 < sample_fps <= 60:
            raise ValidationError("sample_fps must be > 0 and <= 60")
        start = finite(start, "start")
        if end is not None:
            end = finite(end, "end")
            if end <= start:
                raise ValidationError("end must be greater than start")
        min_confidence = finite(min_confidence, "min_confidence")
        if min_confidence > 1:
            raise ValidationError("min_confidence must be <= 1")
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise ValidationError("language must be a non-empty code or None")
        crop = _rectangle(crop, "crop")
        exclude = tuple(_rectangle(rect, "exclude") for rect in exclude)
        check_cancelled(cancelled)
        source = local_file(source)
        try:
            av = import_module("av")
        except ImportError:
            raise MissingDependencyError('Video OCR needs: python -m pip install "reibosub[video]"') from None
        try:
            capture = av.open(str(source))
        except Exception:
            raise RecognitionError("Could not open video") from None
        cues, active, active_start, active_confidence = [], "", start, 1.0
        sampled, next_sample, decoded_end, last_time = 0, start, 0.0, -1.0
        try:
            if not capture.streams.video:
                raise RecognitionError("Media has no video stream")
            stream = capture.streams.video[0]
            native_fps = float(stream.average_rate or 0)
            duration = float(stream.duration * stream.time_base) if stream.duration is not None else float(capture.duration or 0) / av.time_base
            origin = float(stream.start_time * stream.time_base) if stream.start_time is not None else 0.0
            if not math.isfinite(native_fps) or native_fps <= 0 or not math.isfinite(duration) or duration <= 0:
                raise RecognitionError("Video must provide a finite FPS and duration")
            stop = min(duration, end) if end is not None else duration
            if start >= stop:
                raise ValidationError("start is outside the video")
            rate = sample_fps
            total = math.ceil((stop - start) * rate)
            iterator = iter(capture.decode(stream))
            while True:
                check_cancelled(cancelled)
                try:
                    decoded = next(iterator)
                except StopIteration:
                    if decoded_end + 0.5 / native_fps < stop:
                        raise RecognitionError("Video decoding ended before its declared duration; no partial subtitle returned")
                    break
                except Exception:
                    raise RecognitionError("Video decoding failed; no partial subtitle returned") from None
                if decoded.time is None:
                    raise RecognitionError("Video frame has no presentation timestamp")
                time = float(decoded.time) - origin
                if not math.isfinite(time) or time < 0 or time < last_time:
                    raise RecognitionError("Video frame timestamps are invalid or non-monotonic")
                last_time = time
                if time >= stop:
                    break
                decoded_end = min(stop, time + 1 / native_fps)
                if time + 1e-9 < next_sample:
                    continue
                # Move to the next future sample slot, including VFR gaps.
                next_sample = start + (math.floor((time - start) * rate + 1e-9) + 1) / rate
                try:
                    frame = decoded.to_ndarray(format="bgr24")
                except Exception:
                    raise RecognitionError("Could not convert decoded video frame to a BGR image") from None
                height, width = frame.shape[:2]
                left, top = int(crop[0] * width), int(crop[1] * height)
                right, bottom = int(crop[2] * width), int(crop[3] * height)
                if left >= right or top >= bottom:
                    raise ValidationError("crop is smaller than one pixel")
                image = frame[top:bottom, left:right].copy()
                for x0, y0, x1, y1 in exclude:
                    a, b = max(0, int(x0 * width) - left), max(0, int(y0 * height) - top)
                    c, d = min(right - left, math.ceil(x1 * width) - left), min(bottom - top, math.ceil(y1 * height) - top)
                    if a < c and b < d:
                        image[b:d, a:c] = 0
                regions = [r for r in self.read_image(image, cancelled=cancelled) if r.text.strip() and r.confidence >= min_confidence]
                regions.sort(key=lambda r: (min(y for x, y in r.polygon), min(x for x, y in r.polygon)))
                text = "\n".join(r.text.strip() for r in regions)
                confidence = min((r.confidence for r in regions), default=1.0)
                if text != active:
                    if active and time > active_start:
                        cues.append(Cue(len(cues) + 1, active_start, time, active, confidence=active_confidence))
                    active, active_start, active_confidence = text, time, confidence
                else:
                    active_confidence = min(active_confidence, confidence)
                sampled += 1
                if on_progress is not None:
                    on_progress(Progress(min(sampled, total), total, "ocr"))
            check_cancelled(cancelled)
            if active and decoded_end > active_start:
                cues.append(Cue(len(cues) + 1, active_start, decoded_end, active, confidence=active_confidence))
            if on_progress is not None:
                on_progress(Progress(total, total, "ocr"))
            return Subtitle(tuple(cues), language=language, notices=(
                "Basic sampled OCR: timings have sample-resolution uncertainty; adjacent exact text is merged. Not the web OCR 3.0/LLM refinement pipeline.",
            ))
        finally:
            capture.close()
