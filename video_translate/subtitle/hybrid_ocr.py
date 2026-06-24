from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, Any

from video_translate.models import OCRBox, SubtitleCue
from video_translate.llm_config import load_llm_task_config
from video_translate.ocr.extractor import ExtractConfig, _finish_ocr_progress, _format_duration, _load_cv2, _load_paddle_ocr, _ocr_frame
from video_translate.pipeline import CueTimingConfig, _build_subtitle_snapshots, _choose_snapshot_text, _is_subtitle_snapshot_box
from video_translate.subtitle.srt import write_srt
from video_translate.translate.volcengine import DEFAULT_BASE_URL, _chat_completions_url, _load_dotenv, _parse_json_content, _request_translation
from video_translate.utils.text import normalize_ocr_text


DEFAULT_ANCHOR_PADDING_SECONDS = 0.15
DEFAULT_OCR_WINDOW_SECONDS = 1.20
DEFAULT_RECONSTRUCT_BATCH_SIZE = 25
ReconstructFn = Callable[[list[SubtitleCue]], dict[int, str]]


def extract_hybrid_ocr_source(
    video_path: Path,
    anchor_cues: list[SubtitleCue],
    out_dir: Path,
    *,
    lang: str = "korean",
    sample_fps: float = 2.0,
    bottom_ratio: float = 0.42,
    scan_full_frame: bool = False,
    device: str = "auto",
    anchor_padding_seconds: float = DEFAULT_ANCHOR_PADDING_SECONDS,
    ocr_window_seconds: float = DEFAULT_OCR_WINDOW_SECONDS,
    reconstruct_korean: bool = False,
) -> dict[str, Path]:
    boxes = extract_ocr_boxes_for_anchor_cues(
        video_path,
        anchor_cues,
        lang=lang,
        sample_fps=sample_fps,
        bottom_ratio=bottom_ratio,
        scan_full_frame=scan_full_frame,
        device=device,
        anchor_padding_seconds=max(anchor_padding_seconds, ocr_window_seconds),
    )
    result = write_hybrid_outputs(
        anchor_cues,
        boxes,
        out_dir,
        anchor_padding_seconds=ocr_window_seconds,
        reconstruct_korean=reconstruct_korean,
    )
    boxes_path = out_dir / "hybrid.ocr_boxes.json"
    boxes_path.write_text(json.dumps([box.to_dict() for box in boxes], ensure_ascii=False, indent=2), encoding="utf-8")
    result["ocr_boxes"] = boxes_path
    return result


def extract_ocr_boxes_for_anchor_cues(
    video_path: Path,
    anchor_cues: list[SubtitleCue],
    *,
    lang: str = "korean",
    sample_fps: float = 2.0,
    bottom_ratio: float = 0.42,
    scan_full_frame: bool = False,
    device: str = "auto",
    anchor_padding_seconds: float = DEFAULT_ANCHOR_PADDING_SECONDS,
) -> list[OCRBox]:
    if sample_fps <= 0:
        raise ValueError("sample_fps must be greater than 0")
    if not anchor_cues:
        return []

    cv2 = _load_cv2()
    ocr = _load_paddle_ocr(lang, device)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    native_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    video_duration = frame_count / native_fps if frame_count else None
    frame_indexes = _anchor_sample_frame_indexes(anchor_cues, native_fps, frame_count, sample_fps, anchor_padding_seconds)
    config = ExtractConfig(
        sample_fps=sample_fps,
        bottom_ratio=bottom_ratio,
        scan_full_frame=scan_full_frame,
        device=device,
    )
    boxes: list[OCRBox] = []
    try:
        for offset, frame_index in enumerate(frame_indexes, start=1):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            time_seconds = frame_index / native_fps
            boxes.extend(_ocr_frame(ocr, frame, time_seconds, frame_index, config))
            _print_hybrid_ocr_progress(offset, len(frame_indexes), time_seconds, video_duration)
    finally:
        capture.release()
        _finish_ocr_progress()
    return boxes


def build_hybrid_source_cues(
    anchor_cues: list[SubtitleCue],
    ocr_boxes: list[OCRBox],
    *,
    anchor_padding_seconds: float = DEFAULT_OCR_WINDOW_SECONDS,
    timing: CueTimingConfig | None = None,
) -> tuple[list[SubtitleCue], list[dict[str, object]]]:
    timing = timing or CueTimingConfig(snapshot_min_confidence=0.50)
    hybrid: list[SubtitleCue] = []
    debug: list[dict[str, object]] = []
    for index, anchor in enumerate(anchor_cues, start=1):
        cue_boxes = [
            box
            for box in ocr_boxes
            if anchor.start - anchor_padding_seconds <= box.time <= anchor.end + anchor_padding_seconds
            and _is_subtitle_snapshot_box(box, timing)
        ]
        text, confidence = _choose_text_for_anchor(cue_boxes, timing)
        if text:
            source_text = f"韩文OCR候选：{text}\n英文参考：{anchor.text.strip()}"
            mode = "ocr_context_with_english_reference"
        else:
            source_text = f"英文参考：{anchor.text.strip()}"
            mode = "english_reference_fallback"
        hybrid.append(
            SubtitleCue(
                index=index,
                start=anchor.start,
                end=anchor.end,
                text=source_text.strip(),
                source_track_id=anchor.source_track_id,
            )
        )
        debug.append(
            {
                "index": index,
                "start": anchor.start,
                "end": anchor.end,
                "anchor_text": anchor.text,
                "korean_ocr": text,
                "confidence": confidence,
                "mode": mode,
                "box_count": len(cue_boxes),
            }
        )
    return hybrid, debug


def write_hybrid_outputs(
    anchor_cues: list[SubtitleCue],
    ocr_boxes: list[OCRBox],
    out_dir: Path,
    *,
    anchor_padding_seconds: float = DEFAULT_OCR_WINDOW_SECONDS,
    reconstruct_korean: bool = False,
    reconstruct_fn: Callable[..., dict[int, str]] | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    context_cues, debug = build_hybrid_source_cues(
        anchor_cues,
        ocr_boxes,
        anchor_padding_seconds=anchor_padding_seconds,
    )
    context_srt = out_dir / "hybrid.context.srt"
    source_srt = out_dir / "hybrid.source.srt"
    debug_json = out_dir / "hybrid.debug.json"
    write_srt(context_cues, context_srt)
    source_cues = context_cues
    if reconstruct_korean:
        reconstruct = reconstruct_fn or reconstruct_korean_cues_with_llm
        mapping = reconstruct(context_cues)
        source_cues = []
        for cue, item in zip(context_cues, debug):
            korean = str(mapping.get(cue.index) or "").strip()
            if korean:
                item["reconstructed_korean"] = korean
                item["mode"] = "llm_reconstructed_korean"
                text = korean
            else:
                item["reconstructed_korean"] = ""
                text = cue.text
            source_cues.append(
                SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=text,
                    source_track_id=cue.source_track_id,
                )
            )
    write_srt(source_cues, source_srt)
    debug_json.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"source_srt": source_srt, "context_srt": context_srt, "debug_json": debug_json}


def reconstruct_korean_cues_with_llm(
    context_cues: list[SubtitleCue],
    *,
    model: str | None = None,
    base_url: str | None = None,
    batch_size: int = DEFAULT_RECONSTRUCT_BATCH_SIZE,
) -> dict[int, str]:
    if not context_cues:
        return {}
    _load_dotenv(Path.cwd())
    key = os.environ.get("ARK_API_KEY")
    task_llm = load_llm_task_config("hybrid_source_reconstruction", explicit_model=model, explicit_base_url=base_url)
    selected_model = task_llm.model
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 ARK_API_KEY，请先配置火山方舟 API Key。")
    if not selected_model:
        raise RuntimeError("缺少 hybrid_source_reconstruction 模型配置或 ARK_MODEL。")

    mapping: dict[int, str] = {}
    total_batches = max(1, (len(context_cues) + batch_size - 1) // batch_size)
    for batch_index, offset in enumerate(range(0, len(context_cues), batch_size), start=1):
        batch = context_cues[offset : offset + batch_size]
        print(f"hybrid_reconstruct_batch: {batch_index}/{total_batches} cues {batch[0].index}-{batch[-1].index}", flush=True)
        mapping.update(
            _request_reconstruction_batch(
                batch,
                endpoint=endpoint,
                api_key=key,
                model=selected_model,
                batch_label=f"{batch_index}/{total_batches}",
            )
        )
    return mapping


def _request_reconstruction_batch(
    batch: list[SubtitleCue],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    batch_label: str,
) -> dict[int, str]:
    payload = build_reconstruction_payload(batch, model)
    content = _request_translation(endpoint, api_key, payload)
    try:
        return parse_reconstruction_response(content)
    except Exception as exc:
        if len(batch) <= 1:
            print(
                f"hybrid_reconstruct_skipped: {batch_label} cue {batch[0].index} parse_failed {type(exc).__name__}: {exc}",
                flush=True,
            )
            return {}
        mid = max(1, len(batch) // 2)
        left = batch[:mid]
        right = batch[mid:]
        print(
            f"hybrid_reconstruct_split: {batch_label} size={len(batch)} -> {len(left)}+{len(right)} after {type(exc).__name__}",
            flush=True,
        )
        result = _request_reconstruction_batch(
            left,
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            batch_label=f"{batch_label}a",
        )
        result.update(
            _request_reconstruction_batch(
                right,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                batch_label=f"{batch_label}b",
            )
        )
        return result


def build_reconstruction_payload(cues: list[SubtitleCue], model: str) -> dict[str, Any]:
    items = [
        {
            "id": cue.index,
            "time": f"{cue.start:.3f}-{cue.end:.3f}",
            "context": cue.text,
        }
        for cue in cues
    ]
    user = {
        "task": "根据英文人工字幕的时间轴和画面 OCR 候选，还原每条字幕应对应的韩文原句。",
        "rules": [
            "每条输出必须保持同一个 id，不得合并、拆分、删除或新增条目。",
            "英文参考的时间轴可信，最终韩文原句必须对应该英文参考的语义。",
            "韩文 OCR 候选可能有错字、漏字、串到前后句或时间错位；请结合英文参考纠正。",
            "如果 OCR 候选与英文参考明显不对应，可以参考前后条目判断；仍无法判断时，可按英文参考回译成自然韩文，但不要编造专有名词。",
            "只输出韩文原句，不要中文，不要解释，不要保留“韩文OCR候选/英文参考”标签。",
        ],
        "output_schema": [{"id": 1, "ko": "韩文原句，可为空"}],
        "items": items,
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是韩语字幕校对助手。只输出 JSON 数组，不要 Markdown，不要解释。"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }


def parse_reconstruction_response(content: str) -> dict[int, str]:
    parsed = _parse_json_content(content.strip())
    if isinstance(parsed, dict):
        parsed = parsed.get("items") or parsed.get("subtitles") or parsed.get("result") or []
    if not isinstance(parsed, list):
        raise ValueError("hybrid reconstruction response must be a JSON array")
    mapping: dict[int, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("index")
        raw_text = item.get("ko") or item.get("korean") or item.get("text")
        if raw_id is None or raw_text is None:
            continue
        mapping[int(raw_id)] = str(raw_text).strip()
    return mapping


def _anchor_sample_frame_indexes(
    cues: list[SubtitleCue],
    native_fps: float,
    frame_count: int,
    sample_fps: float,
    padding: float,
) -> list[int]:
    step_seconds = 1.0 / sample_fps
    indexes: set[int] = set()
    for cue in cues:
        start = max(0.0, cue.start - padding)
        end = max(start, cue.end + padding)
        current = start
        while current <= end + 0.001:
            frame_index = max(0, int(round(current * native_fps)))
            if frame_count:
                frame_index = min(frame_count - 1, frame_index)
            indexes.add(frame_index)
            current += step_seconds
        midpoint = start + (end - start) / 2
        frame_index = max(0, int(round(midpoint * native_fps)))
        if frame_count:
            frame_index = min(frame_count - 1, frame_index)
        indexes.add(frame_index)
    return sorted(indexes)


def _choose_text_for_anchor(boxes: list[OCRBox], timing: CueTimingConfig) -> tuple[str, float]:
    snapshots = _build_subtitle_snapshots(boxes)
    if not snapshots:
        return "", 0.0
    text = normalize_ocr_text(_choose_snapshot_text(snapshots))
    confidence = max((snapshot.confidence for snapshot in snapshots), default=0.0)
    return text, confidence


def _print_hybrid_ocr_progress(
    sampled_count: int,
    total_samples: int,
    time_seconds: float,
    video_duration: float | None,
) -> None:
    width = 28
    ratio = min(1.0, sampled_count / total_samples) if total_samples else 0.0
    filled = min(width, int(width * ratio))
    bar = "#" * filled + "-" * (width - filled)
    sys.stderr.write(
        f"\rHybrid OCR [{bar}] {ratio * 100:6.2f}% "
        f"{sampled_count}/{total_samples} samples "
        f"{_format_duration(time_seconds)}/{_format_duration(video_duration)}"
    )
    sys.stderr.flush()
