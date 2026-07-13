from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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
    context_overlap: int = 2
    max_reading_candidates: int = 8
    max_token_candidates: int = 16


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
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    machine_cues = read_srt(source_srt)
    if not machine_cues:
        write_srt([], out_srt)
        return {"refined_srt": out_srt}
    boxes = [OCRBox.from_dict(item) for item in json.loads(ocr_boxes_json.read_text(encoding="utf-8"))]
    refined = refine_cues_with_llm(
        machine_cues,
        boxes,
        model=model,
        base_url=base_url,
        config=config,
        progress_callback=progress_callback,
    )
    write_srt(refined, out_srt)
    if progress_callback:
        progress_callback(f"ocr_refine: finished; wrote {len(refined)} cues")
    return {"refined_srt": out_srt}


def refine_cues_with_llm(
    machine_cues: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: OCRRefinementConfig | None = None,
    progress_callback: Callable[[str], None] | None = None,
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
    model_message = f"ocr_refine_model: {selected_model}"
    print(model_message, flush=True)
    if progress_callback:
        progress_callback(model_message)
    initial_message = f"ocr_refine: {len(machine_cues)} cues in {total_batches} batches"
    print(initial_message, flush=True)
    if progress_callback:
        progress_callback(initial_message)
    for batch_index, offset in enumerate(range(0, len(machine_cues), config.batch_size), start=1):
        batch = machine_cues[offset : offset + config.batch_size]
        context_start = max(0, offset - config.context_overlap)
        context_end = min(len(machine_cues), offset + config.batch_size + config.context_overlap)
        context = machine_cues[context_start:context_end]
        progress_message = f"ocr_refine_batch: {batch_index}/{total_batches} cues {batch[0].index}-{batch[-1].index}"
        print(progress_message, flush=True)
        if progress_callback:
            progress_callback(progress_message)
        refined.extend(
            _request_refine_batch(
                batch,
                boxes,
                context=context,
                endpoint=endpoint,
                api_key=key,
                model=selected_model,
                config=config,
                batch_label=f"{batch_index}/{total_batches}",
            )
        )
    refined = _merge_adjacent_related_cues(_normalize_refined_cues(refined))
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
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    cues = read_srt(source_srt)
    if not cues:
        if progress_callback:
            progress_callback("source_cleanup: no cues; writing empty subtitle")
        write_srt([], out_srt)
        return {"cleaned_srt": out_srt}
    cleaned = cleanup_cues_with_llm(
        cues,
        model=model,
        base_url=base_url,
        config=config,
        progress_callback=progress_callback,
    )
    write_srt(cleaned, out_srt)
    if progress_callback:
        progress_callback(f"source_cleanup: finished; wrote {len(cleaned)} cues")
    return {"cleaned_srt": out_srt}


def cleanup_cues_with_llm(
    cues: list[SubtitleCue],
    *,
    model: str | None = None,
    base_url: str | None = None,
    config: SourceCleanupConfig | None = None,
    progress_callback: Callable[[str], None] | None = None,
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
    model_message = f"source_cleanup_model: {selected_model}"
    print(model_message, flush=True)
    if progress_callback:
        progress_callback(model_message)
    initial_message = f"source_cleanup: {len(cues)} cues in {total_batches} batches"
    print(initial_message, flush=True)
    if progress_callback:
        progress_callback(initial_message)
    for batch_index, offset in enumerate(range(0, len(cues), batch_size), start=1):
        target = cues[offset : offset + batch_size]
        context_start = max(0, offset - overlap)
        context_end = min(len(cues), offset + batch_size + overlap)
        context = cues[context_start:context_end]
        progress_message = f"source_cleanup_batch: {batch_index}/{total_batches} cues {target[0].index}-{target[-1].index}"
        print(progress_message, flush=True)
        if progress_callback:
            progress_callback(progress_message)
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
    context: list[SubtitleCue],
    endpoint: str,
    api_key: str,
    model: str,
    config: OCRRefinementConfig,
    batch_label: str,
) -> list[SubtitleCue]:
    payload = build_ocr_refinement_payload(batch, boxes, model=model, config=config, context=context)
    content = _request_translation(endpoint, api_key, payload)
    try:
        actions = parse_ocr_refinement_actions(content)
        _validate_refinement_actions(batch, actions)
        return apply_ocr_refinement_actions(batch, boxes, actions)
    except Exception as exc:
        if len(batch) <= 1:
            print(f"ocr_refine_fallback: {batch_label} cue {batch[0].index} parse_failed {type(exc).__name__}: {exc}", flush=True)
            return [] if _is_single_sample_cue(batch[0], boxes) else batch
        mid = max(1, len(batch) // 2)
        left = batch[:mid]
        right = batch[mid:]
        print(f"ocr_refine_split: {batch_label} size={len(batch)} -> {len(left)}+{len(right)} after {type(exc).__name__}", flush=True)
        return _request_refine_batch(left, boxes, context=context, endpoint=endpoint, api_key=api_key, model=model, config=config, batch_label=f"{batch_label}a") + _request_refine_batch(right, boxes, context=context, endpoint=endpoint, api_key=api_key, model=model, config=config, batch_label=f"{batch_label}b")


def build_ocr_refinement_payload(
    batch: list[SubtitleCue],
    boxes: list[OCRBox],
    *,
    model: str,
    config: OCRRefinementConfig | None = None,
    context: list[SubtitleCue] | None = None,
) -> dict[str, Any]:
    config = config or OCRRefinementConfig()
    context = context or batch
    evidence = [_cue_evidence_payload(cue, boxes, config) for cue in batch]
    context_items = [
        {
            "id": cue.index,
            "start": format_srt_time(cue.start),
            "end": format_srt_time(cue.end),
            "duration_ms": round((cue.end - cue.start) * 1000),
            "text": cue.text,
            "target": any(target.index == cue.index for target in batch),
        }
        for cue in context
    ]
    user_content = json.dumps(
        {
            "target_ids": [cue.index for cue in batch],
            "context_cues": context_items,
            "cue_evidence": evidence,
        },
        ensure_ascii=False,
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 OCR 原文字幕的轨迹分类与精修器，只处理原语言，不翻译。"
                    "必须先把每个目标分类为 subtitle、program_caption、scene_text 或 noise，再决定动作。"
                    "subtitle 和 program_caption 可以保留、替换或与相邻目标合并；scene_text 和 noise 默认删除。"
                    "单帧残片、极短闪字、衣服/招牌/车牌文字、Logo、水印、角标、随机英文数字和位置漂移文字通常是 noise。"
                    "真实台词、节目效果字幕、剧情说明即使字体夸张或识别略有错误也应保留。"
                    "evidence_strength=single_sample 的条目不可单独保留，只能与前后相关字幕合并，否则必须删除。"
                    "reading_candidates 是同一字幕在不同帧的完整候选，token_candidates 给出文字块跨帧支持度；"
                    "候选之间不是前后相接的文本，绝对不要串接 machine_text 与候选。"
                    "重构时依据跨帧支持度和视觉顺序；少数帧若提供更符合原语言正字规则的近似写法，可保守校正一两个字符。"
                    "输出前检查重复词句、无证据扩写和低支持度乱码。每个 target_id 必须且只能被一个动作覆盖。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "返回严格 JSON，格式为 {\"actions\":[...]}。每项必须包含 classification 和 action。"
                    "允许格式："
                    "{\"id\":1,\"classification\":\"subtitle\",\"action\":\"keep\"}；"
                    "{\"id\":1,\"classification\":\"noise\",\"action\":\"drop\",\"reason\":\"...\"}；"
                    "{\"id\":1,\"classification\":\"subtitle\",\"action\":\"replace\",\"text\":\"修正后原文\"}；"
                    "{\"ids\":[1,2],\"classification\":\"program_caption\",\"action\":\"merge\",\"text\":\"合并后原文\"}。"
                    "不要返回解释，不要 markdown。输入：\n" + user_content
                ),
            },
        ],
        "temperature": 0.1,
    }


def _cue_evidence_payload(cue: SubtitleCue, boxes: list[OCRBox], config: OCRRefinementConfig) -> dict[str, Any]:
    cue_boxes = [box for box in boxes if cue.start <= box.time <= cue.end]
    frames = _frame_payload(cue_boxes, config.max_boxes_per_frame)
    reading_counts: Counter[tuple[str, str]] = Counter()
    for frame in frames:
        lines = frame["reading_lines"]
        lower_lines = [line for line in lines if line["region"] in {"bottom", "full_lower"}]
        selected = lower_lines or lines
        text = "\n".join(line["text"] for line in selected if line["text"].strip())
        if text:
            region = "lower" if lower_lines else str(selected[0]["region"])
            reading_counts[(region, text)] += 1

    reading_candidates = [
        {
            "text": text,
            "region": region,
            "frames": count,
            "support_ratio": round(count / max(1, len(frames)), 3),
        }
        for (region, text), count in reading_counts.most_common(config.max_reading_candidates)
    ]

    token_frames: dict[str, set[int]] = defaultdict(set)
    token_confidence: dict[str, list[float]] = defaultdict(list)
    token_boxes: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    region_frames: dict[str, set[int]] = defaultdict(set)
    for box in cue_boxes:
        text = box.text.strip()
        if not text:
            continue
        token_frames[text].add(box.frame_index)
        token_confidence[text].append(box.confidence)
        token_boxes[text].append(box.bbox)
        region_frames[box.region].add(box.frame_index)

    token_candidates = []
    for text in sorted(token_frames, key=lambda item: (len(token_frames[item]), sum(token_confidence[item]), len(item)), reverse=True):
        bboxes = token_boxes[text]
        token_candidates.append(
            {
                "text": text,
                "frames": len(token_frames[text]),
                "support_ratio": round(len(token_frames[text]) / max(1, len(frames)), 3),
                "average_confidence": round(sum(token_confidence[text]) / len(token_confidence[text]), 3),
                "average_bbox": [round(sum(bbox[index] for bbox in bboxes) / len(bboxes), 1) for index in range(4)],
            }
        )
        if len(token_candidates) >= config.max_token_candidates:
            break

    duration = max(0.0, cue.end - cue.start)
    if len(frames) <= 1:
        evidence_strength = "single_sample"
    elif len(frames) < 3 or duration < 0.50:
        evidence_strength = "weak"
    else:
        evidence_strength = "stable"

    return {
        "id": cue.index,
        "start": format_srt_time(cue.start),
        "end": format_srt_time(cue.end),
        "duration_ms": round(duration * 1000),
        "machine_text": cue.text,
        "sample_frames": len(frames),
        "evidence_strength": evidence_strength,
        "region_frame_support": {
            region: len(frame_indices)
            for region, frame_indices in sorted(region_frames.items(), key=lambda item: len(item[1]), reverse=True)
        },
        "reading_candidates": reading_candidates,
        "token_candidates": token_candidates,
    }


def parse_ocr_refinement_actions(content: str) -> list[dict[str, Any]]:
    parsed = _parse_json_content(content.strip())
    if isinstance(parsed, dict):
        parsed = parsed.get("actions")
    if not isinstance(parsed, list):
        raise ValueError("OCR refinement response must be {actions: [...]} JSON")
    return [item for item in parsed if isinstance(item, dict)]


def _validate_refinement_actions(batch: list[SubtitleCue], actions: list[dict[str, Any]]) -> None:
    target_ids = {cue.index for cue in batch}
    covered: list[int] = []
    allowed_actions = {"keep", "drop", "replace", "merge"}
    allowed_classes = {"subtitle", "program_caption", "scene_text", "noise"}
    for action in actions:
        kind = str(action.get("action") or "").strip().lower()
        classification = str(action.get("classification") or "").strip().lower()
        if kind not in allowed_actions:
            raise ValueError(f"invalid OCR refinement action: {kind or '<missing>'}")
        if classification not in allowed_classes:
            raise ValueError(f"invalid OCR refinement classification: {classification or '<missing>'}")
        ids = _action_ids(action)
        if kind == "merge" and len(ids) < 2:
            raise ValueError("merge action requires at least two ids")
        if not ids or any(cue_id not in target_ids for cue_id in ids):
            raise ValueError("OCR refinement action references an invalid target id")
        covered.extend(ids)
    if set(covered) != target_ids or len(covered) != len(set(covered)):
        raise ValueError("every target id must be covered exactly once")


def apply_ocr_refinement_actions(
    batch: list[SubtitleCue],
    boxes: list[OCRBox],
    actions: list[dict[str, Any]],
) -> list[SubtitleCue]:
    by_id = {cue.index: cue for cue in batch}
    consumed: set[int] = set()
    output: list[SubtitleCue] = []
    single_sample_ids = {
        cue.index
        for cue in batch
        if len({round(box.time, 3) for box in boxes if cue.start <= box.time <= cue.end}) <= 1
    }

    for action in actions:
        if str(action.get("action") or "").strip().lower() != "merge":
            continue
        ids = _action_ids(action)
        members = [by_id[cue_id] for cue_id in ids if cue_id in by_id and cue_id not in consumed]
        if len(members) < 2:
            continue
        classification = str(action.get("classification") or "noise").strip().lower()
        if classification in {"scene_text", "noise"}:
            consumed.update(ids)
            continue
        text = _clean_refined_text(str(action.get("text") or "").strip())
        if not text:
            text = max((member.text for member in members), key=lambda item: len(_compact_evidence_text(item)))
        output.append(
            SubtitleCue(
                index=len(output) + 1,
                start=min(member.start for member in members),
                end=max(member.end for member in members),
                text=text,
            )
        )
        consumed.update(ids)

    action_by_id = {
        _action_ids(action)[0]: action
        for action in actions
        if str(action.get("action") or "").strip().lower() != "merge" and _action_ids(action)
    }
    for cue in batch:
        if cue.index in consumed:
            continue
        action = action_by_id[cue.index]
        kind = str(action.get("action") or "drop").strip().lower()
        classification = str(action.get("classification") or "noise").strip().lower()
        isolated_single_sample = cue.index in single_sample_ids and not _has_related_neighbor(cue, batch)
        if classification in {"scene_text", "noise"} or kind == "drop" or isolated_single_sample:
            continue
        text = cue.text
        if kind == "replace":
            text = _clean_refined_text(str(action.get("text") or "").strip())
        if text.strip():
            output.append(SubtitleCue(index=len(output) + 1, start=cue.start, end=cue.end, text=text))
    return _normalize_refined_cues(output)


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
        ordered_boxes = sorted(frame_boxes, key=lambda item: (item.bbox[1], item.bbox[0]))
        frames.append(
            {
                "time": format_srt_time(time),
                "reading_lines": _frame_reading_lines(ordered_boxes),
                "boxes": [
                    {
                        "text": box.text,
                        "bbox": [round(value, 1) for value in box.bbox],
                        "region": box.region,
                        "confidence": round(box.confidence, 3),
                    }
                    for box in ordered_boxes
                ],
            }
        )
    return frames


def _frame_reading_lines(boxes: list[OCRBox]) -> list[dict[str, str]]:
    rows: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: ((item.bbox[1] + item.bbox[3]) / 2, item.bbox[0])):
        center_y = (box.bbox[1] + box.bbox[3]) / 2
        nearest = min(rows, key=lambda row: abs(row["center_y"] - center_y), default=None)
        if nearest is None or abs(nearest["center_y"] - center_y) > 48:
            rows.append({"center_y": center_y, "boxes": [box]})
            continue
        nearest["boxes"].append(box)
        nearest["center_y"] = sum((item.bbox[1] + item.bbox[3]) / 2 for item in nearest["boxes"]) / len(nearest["boxes"])

    reading_lines: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: item["center_y"]):
        row_boxes = sorted(row["boxes"], key=lambda item: item.bbox[0])
        text = " ".join(box.text.strip() for box in row_boxes if box.text.strip())
        if not text:
            continue
        region = max(row_boxes, key=lambda item: (_box_score(item), len(item.text.strip()))).region
        reading_lines.append({"region": region, "text": text})
    return reading_lines


def _box_score(box: OCRBox) -> tuple[int, float, int]:
    region_score = 2 if box.region in {"bottom", "full_lower"} else 1 if box.region == "full_middle" else 0
    return (region_score, box.confidence, len(box.text.strip()))


def _is_single_sample_cue(cue: SubtitleCue, boxes: list[OCRBox]) -> bool:
    return len({round(box.time, 3) for box in boxes if cue.start <= box.time <= cue.end}) <= 1


def _has_related_neighbor(cue: SubtitleCue, cues: list[SubtitleCue]) -> bool:
    cue_text = _compact_evidence_text(cue.text)
    if not cue_text:
        return False
    for neighbor in cues:
        if neighbor.index == cue.index:
            continue
        gap = max(neighbor.start - cue.end, cue.start - neighbor.end, 0.0)
        if gap > 0.12:
            continue
        neighbor_text = _compact_evidence_text(neighbor.text)
        if neighbor_text and (cue_text == neighbor_text or cue_text in neighbor_text or neighbor_text in cue_text):
            return True
    return False


def _compact_evidence_text(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text).casefold()


def _merge_adjacent_related_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    if not cues:
        return []
    merged: list[SubtitleCue] = []
    for cue in cues:
        current = _copy_cue(cue)
        if not merged:
            merged.append(current)
            continue
        previous = merged[-1]
        gap = current.start - previous.end
        previous_text = _compact_evidence_text(previous.text)
        current_text = _compact_evidence_text(current.text)
        related = bool(previous_text and current_text) and (
            previous_text == current_text or previous_text in current_text or current_text in previous_text
        )
        short_fragment = min(previous.end - previous.start, current.end - current.start) <= 0.55
        if gap <= 0.12 and related and (previous_text == current_text or short_fragment):
            previous.end = max(previous.end, current.end)
            if len(current_text) > len(previous_text):
                previous.text = current.text
            continue
        merged.append(current)
    return merged


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
