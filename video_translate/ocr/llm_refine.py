from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_translate.llm_config import load_llm_task_config
from video_translate.models import OCRBox, SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.translate.volcengine import DEFAULT_BASE_URL, _chat_completions_url, _load_dotenv, _parse_json_content, _request_translation
from video_translate.utils.timecode import format_srt_time, parse_srt_time


@dataclass(slots=True)
class OCRRefinementConfig:
    batch_size: int = 12
    window_padding_seconds: float = 0.50
    max_boxes_per_frame: int = 16


@dataclass(slots=True)
class SourceCleanupConfig:
    batch_size: int = 18
    overlap: int = 3


def refine_ocr_source_with_llm(
    source_srt: Path,
    ocr_boxes_json: Path,
    out_srt: Path,
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: OCRRefinementConfig | None = None,
) -> dict[str, Path]:
    machine_cues = read_srt(source_srt)
    if not machine_cues:
        write_srt([], out_srt)
        return {"refined_srt": out_srt}
    boxes = [OCRBox.from_dict(item) for item in json.loads(ocr_boxes_json.read_text(encoding="utf-8"))]
    refined = refine_cues_with_llm(machine_cues, boxes, model=model, base_url=base_url, config=config)
    write_srt(refined, out_srt)
    return {"refined_srt": out_srt}


def refine_cues_with_llm(
    machine_cues: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: OCRRefinementConfig | None = None,
) -> list[SubtitleCue]:
    config = config or OCRRefinementConfig()
    _load_dotenv(Path.cwd())
    task_llm = load_llm_task_config("ocr_source_refinement", explicit_model=model, explicit_base_url=base_url)
    key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ocr_source_refinement 模型配置或 LLM_MODEL。")

    refined: list[SubtitleCue] = []
    total_batches = max(1, (len(machine_cues) + config.batch_size - 1) // config.batch_size)
    for batch_index, offset in enumerate(range(0, len(machine_cues), config.batch_size), start=1):
        batch = machine_cues[offset : offset + config.batch_size]
        print(f"ocr_refine_batch: {batch_index}/{total_batches} cues {batch[0].index}-{batch[-1].index}", flush=True)
        refined.extend(
            _request_refine_batch(
                batch,
                boxes,
                endpoint=endpoint,
                api_key=key,
                model=selected_model,
                config=config,
                batch_label=f"{batch_index}/{total_batches}",
            )
        )
    refined = _normalize_refined_cues(refined)
    for index, cue in enumerate(refined, start=1):
        cue.index = index
    return refined


def cleanup_ocr_source_with_llm(
    source_srt: Path,
    out_srt: Path,
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: SourceCleanupConfig | None = None,
) -> dict[str, Path]:
    cues = read_srt(source_srt)
    if not cues:
        write_srt([], out_srt)
        return {"cleaned_srt": out_srt}
    cleaned = cleanup_cues_with_llm(cues, model=model, base_url=base_url, config=config)
    write_srt(cleaned, out_srt)
    return {"cleaned_srt": out_srt}


def cleanup_cues_with_llm(
    cues: list[SubtitleCue],
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: SourceCleanupConfig | None = None,
) -> list[SubtitleCue]:
    config = config or SourceCleanupConfig()
    _load_dotenv(Path.cwd())
    task_llm = load_llm_task_config("ocr_source_cleanup", explicit_model=model, explicit_base_url=base_url)
    key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ocr_source_cleanup 模型配置或 LLM_MODEL。")

    cleaned: list[SubtitleCue] = []
    batch_size = max(1, config.batch_size)
    overlap = max(0, config.overlap)
    total_batches = max(1, (len(cues) + batch_size - 1) // batch_size)
    for batch_index, offset in enumerate(range(0, len(cues), batch_size), start=1):
        target = cues[offset : offset + batch_size]
        context_start = max(0, offset - overlap)
        context_end = min(len(cues), offset + batch_size + overlap)
        context = cues[context_start:context_end]
        print(f"source_cleanup_batch: {batch_index}/{total_batches} cues {target[0].index}-{target[-1].index}", flush=True)
        cleaned.extend(
            _request_source_cleanup_batch(
                target,
                context,
                endpoint=endpoint,
                api_key=key,
                model=selected_model,
                batch_label=f"{batch_index}/{total_batches}",
            )
        )
    cleaned = _normalize_refined_cues(cleaned)
    for index, cue in enumerate(cleaned, start=1):
        cue.index = index
    return cleaned


def _request_source_cleanup_batch(
    target: list[SubtitleCue],
    context: list[SubtitleCue],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    batch_label: str,
) -> list[SubtitleCue]:
    payload = build_source_cleanup_payload(target, context, model=model)
    content = _request_translation(endpoint, api_key, payload)
    try:
        actions = parse_source_cleanup_response(content)
        return apply_source_cleanup_actions(target, actions)
    except Exception as exc:
        if len(target) <= 1:
            print(f"source_cleanup_fallback: {batch_label} cue {target[0].index} parse_failed {type(exc).__name__}: {exc}", flush=True)
            return [_copy_cue(target[0])]
        mid = max(1, len(target) // 2)
        left = target[:mid]
        right = target[mid:]
        print(f"source_cleanup_split: {batch_label} size={len(target)} -> {len(left)}+{len(right)} after {type(exc).__name__}", flush=True)
        return _request_source_cleanup_batch(left, context, endpoint=endpoint, api_key=api_key, model=model, batch_label=f"{batch_label}a") + _request_source_cleanup_batch(right, context, endpoint=endpoint, api_key=api_key, model=model, batch_label=f"{batch_label}b")


def build_source_cleanup_payload(target: list[SubtitleCue], context: list[SubtitleCue], *, model: str) -> dict[str, Any]:
    target_ids = [cue.index for cue in target]
    items = [
        {
            "id": cue.index,
            "start": format_srt_time(cue.start),
            "end": format_srt_time(cue.end),
            "text": cue.text,
            "target": cue.index in target_ids,
        }
        for cue in context
    ]
    user_content = json.dumps({"target_ids": target_ids, "context_cues": items}, ensure_ascii=False)
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 OCR 原文字幕去噪器，只处理原语言字幕，不翻译。"
                    "你会看到一组上下文字幕，其中 target=true 的条目是本次必须判断的目标。"
                    "任务是删除与上下文完全无关的 OCR 噪声、水印、角标、车牌/编号、单帧残片、广告平台标识和画面无关文字。"
                    "如果某条虽然识别不完美但明显是台词、节目字幕、屏幕说明或剧情文案，要保留。"
                    "可以把相邻目标条目合并，或轻度修正明显错字/异常换行；不要翻译，不要凭空补长句。"
                    "只允许对 target_ids 中的条目给出动作，不要改动非 target 上下文条目。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回严格 JSON，格式为 {\"actions\":[...] }。"
                    "每个 action 必须是以下之一："
                    "{\"id\":1,\"action\":\"keep\"}；"
                    "{\"id\":1,\"action\":\"drop\",\"reason\":\"...\"}；"
                    "{\"id\":1,\"action\":\"replace\",\"text\":\"修正后原文\"}；"
                    "{\"ids\":[1,2],\"action\":\"merge\",\"text\":\"合并后原文\",\"start\":\"00:00:00,000\",\"end\":\"00:00:02,000\"}。"
                    "不要返回解释，不要 markdown。输入：\n" + user_content
                ),
            },
        ],
        "temperature": 0.1,
    }


def parse_source_cleanup_response(content: str) -> list[dict[str, Any]]:
    parsed = _parse_json_content(content.strip())
    if isinstance(parsed, dict):
        parsed = parsed.get("actions")
    if not isinstance(parsed, list):
        raise ValueError("source cleanup response must be a JSON array or {actions: [...]} object")
    result: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            result.append(item)
    return result


def apply_source_cleanup_actions(target: list[SubtitleCue], actions: list[dict[str, Any]]) -> list[SubtitleCue]:
    by_id = {cue.index: cue for cue in target}
    consumed: set[int] = set()
    output: list[SubtitleCue] = []
    action_by_id: dict[int, dict[str, Any]] = {}
    merge_actions: list[dict[str, Any]] = []
    for action in actions:
        kind = str(action.get("action") or "keep").strip().lower()
        ids = action.get("ids")
        if kind == "merge" and isinstance(ids, list):
            merge_actions.append(action)
            continue
        try:
            cue_id = int(action.get("id"))
        except (TypeError, ValueError):
            continue
        if cue_id in by_id:
            action_by_id[cue_id] = action

    for action in merge_actions:
        ids = _action_ids(action)
        member_ids = [cue_id for cue_id in ids if cue_id in by_id and cue_id not in consumed]
        if len(member_ids) < 2:
            continue
        members = [by_id[cue_id] for cue_id in member_ids]
        text = _clean_refined_text(str(action.get("text") or "").strip())
        if not text:
            text = _clean_refined_text(" ".join(member.text for member in members))
        start = _action_time(action.get("start"), min(member.start for member in members))
        end = _action_time(action.get("end"), max(member.end for member in members))
        if end > start and text:
            output.append(SubtitleCue(index=len(output) + 1, start=start, end=end, text=text))
            consumed.update(member_ids)

    for cue in target:
        if cue.index in consumed:
            continue
        action = action_by_id.get(cue.index, {})
        kind = str(action.get("action") or "keep").strip().lower()
        if kind == "drop":
            consumed.add(cue.index)
            continue
        if kind == "replace":
            text = _clean_refined_text(str(action.get("text") or "").strip())
            if text:
                output.append(SubtitleCue(index=len(output) + 1, start=cue.start, end=cue.end, text=text))
                consumed.add(cue.index)
                continue
        output.append(_copy_cue(cue))
    return _normalize_refined_cues(output)


def _request_refine_batch(
    batch: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    config: OCRRefinementConfig,
    batch_label: str,
) -> list[SubtitleCue]:
    payload = build_ocr_refinement_payload(batch, boxes, model=model, config=config)
    content = _request_translation(endpoint, api_key, payload)
    try:
        cues = parse_ocr_refinement_response(content)
        return cues or batch
    except Exception as exc:
        if len(batch) <= 1:
            print(f"ocr_refine_fallback: {batch_label} cue {batch[0].index} parse_failed {type(exc).__name__}: {exc}", flush=True)
            return batch
        mid = max(1, len(batch) // 2)
        left = batch[:mid]
        right = batch[mid:]
        print(f"ocr_refine_split: {batch_label} size={len(batch)} -> {len(left)}+{len(right)} after {type(exc).__name__}", flush=True)
        return _request_refine_batch(left, boxes, endpoint=endpoint, api_key=api_key, model=model, config=config, batch_label=f"{batch_label}a") + _request_refine_batch(right, boxes, endpoint=endpoint, api_key=api_key, model=model, config=config, batch_label=f"{batch_label}b")


def build_ocr_refinement_payload(batch: list[SubtitleCue], boxes: list[OCRBox], *, model: str, config: OCRRefinementConfig | None = None) -> dict[str, Any]:
    config = config or OCRRefinementConfig()
    start = min(cue.start for cue in batch) - config.window_padding_seconds
    end = max(cue.end for cue in batch) + config.window_padding_seconds
    frames = _frame_payload([box for box in boxes if start <= box.time <= end], config.max_boxes_per_frame)
    items = [
        {
            "id": cue.index,
            "start": format_srt_time(cue.start),
            "end": format_srt_time(cue.end),
            "text": cue.text,
        }
        for cue in batch
    ]
    user_content = json.dumps({"machine_cues": items, "raw_frames": frames}, ensure_ascii=False)
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 OCR 字幕原文精修器。你会看到机器分段字幕和同一时间窗口内的逐帧 OCR 文字框。"
                    "任务是输出更干净的原语言字幕，不翻译。可以删除明显噪声、合并误切片、修正异常换行。"
                    "优先依据 bottom/lower 区域的连续字幕；top/middle 常是姓名牌、标题、水印或画面文字，只有在底部无字幕且它像真实字幕时才保留。"
                    "不得凭空创造 OCR 证据中没有的长句。输出严格 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请返回 JSON 数组，每项格式为 {\"start\":\"00:00:00,000\",\"end\":\"00:00:01,000\",\"text\":\"...\"}。"
                    "不要返回解释，不要 markdown。输入：\n" + user_content
                ),
            },
        ],
        "temperature": 0.1,
    }


def parse_ocr_refinement_response(content: str) -> list[SubtitleCue]:
    parsed = _parse_json_content(content.strip())
    if isinstance(parsed, dict) and isinstance(parsed.get("cues"), list):
        parsed = parsed["cues"]
    if not isinstance(parsed, list):
        raise ValueError("OCR refinement response must be a JSON array or {cues: [...]} object")
    cues: list[SubtitleCue] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = parse_srt_time(str(item.get("start") or ""))
        end = parse_srt_time(str(item.get("end") or ""))
        if end <= start:
            continue
        cues.append(SubtitleCue(index=len(cues) + 1, start=start, end=end, text=_clean_refined_text(text)))
    return _normalize_refined_cues(cues)


def _frame_payload(boxes: list[OCRBox], max_boxes_per_frame: int) -> list[dict[str, Any]]:
    by_time: dict[float, list[OCRBox]] = {}
    for box in boxes:
        by_time.setdefault(round(box.time, 3), []).append(box)
    frames: list[dict[str, Any]] = []
    for time in sorted(by_time):
        frame_boxes = sorted(by_time[time], key=_box_score, reverse=True)[:max_boxes_per_frame]
        frames.append(
            {
                "time": format_srt_time(time),
                "boxes": [
                    {
                        "text": box.text,
                        "bbox": [round(value, 1) for value in box.bbox],
                        "region": box.region,
                        "confidence": round(box.confidence, 3),
                    }
                    for box in sorted(frame_boxes, key=lambda item: (item.bbox[1], item.bbox[0]))
                ],
            }
        )
    return frames


def _box_score(box: OCRBox) -> tuple[int, float, int]:
    region_score = 2 if box.region in {"bottom", "full_lower"} else 1 if box.region == "full_middle" else 0
    return (region_score, box.confidence, len(box.text.strip()))


def _clean_refined_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return text.strip()
    joined = " ".join(lines)
    if len(joined) <= 80:
        return joined
    return "\n".join(lines)


def _copy_cue(cue: SubtitleCue) -> SubtitleCue:
    return SubtitleCue(index=cue.index, start=cue.start, end=cue.end, text=_clean_refined_text(cue.text), source_track_id=cue.source_track_id)


def _action_ids(action: dict[str, Any]) -> list[int]:
    raw_ids = action.get("ids")
    if isinstance(raw_ids, list):
        values = raw_ids
    else:
        values = [action.get("id")]
    result: list[int] = []
    for value in values:
        try:
            cue_id = int(value)
        except (TypeError, ValueError):
            continue
        if cue_id not in result:
            result.append(cue_id)
    return result


def _action_time(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return parse_srt_time(text)
    except Exception:
        return fallback


def _normalize_refined_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    result: list[SubtitleCue] = []
    for cue in ordered:
        cue.text = _clean_refined_text(cue.text)
        if result and cue.start < result[-1].end:
            cue.start = result[-1].end
        if cue.end > cue.start and cue.text.strip():
            result.append(cue)
    return result
