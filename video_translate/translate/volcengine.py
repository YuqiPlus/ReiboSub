from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.translate.glossary import Glossary, GlossaryEntry, load_glossary
from video_translate.utils.text import comparable_text, text_similarity


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def translate_srt_with_volcengine(
    source_srt: Path,
    out_srt: Path,
    *,
    glossary_path: Path | None = None,
    batch_size: int = 40,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    target_language: str = "简体中文",
    ignored_texts: list[str] | None = None,
    ignored_patterns: list[str] | None = None,
    extra_prompt: str = "",
    dedupe_translated: bool = False,
    dedupe_similarity: float = 0.88,
    dedupe_max_gap_seconds: float = 1.2,
    llm_cleanup_translated: bool = False,
    llm_cleanup_max_gap_seconds: float = 1.8,
    llm_cleanup_max_window_size: int = 6,
    cleanup_residual_fragments: bool = False,
    residual_max_gap_seconds: float = 3.0,
    residual_short_text_chars: int = 6,
    retime_translated: bool = False,
    retime_chars_per_second: float = 7.5,
    retime_max_extension_seconds: float = 2.5,
) -> Path:
    _load_dotenv(source_srt)
    key = api_key or os.environ.get("ARK_API_KEY")
    selected_model = model or os.environ.get("ARK_MODEL")
    endpoint = _chat_completions_url(base_url or os.environ.get("ARK_BASE_URL") or DEFAULT_BASE_URL)

    if not key:
        raise RuntimeError("缺少 ARK_API_KEY，请先配置火山方舟 API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ARK_MODEL，请先配置火山方舟模型名或接入点 ID。")

    cues = read_srt(source_srt)
    glossary = load_glossary(glossary_path)
    translated: list[SubtitleCue] = []

    total_batches = max(1, (len(cues) + batch_size - 1) // batch_size)
    for batch_index, offset in enumerate(range(0, len(cues), batch_size), start=1):
        batch = cues[offset : offset + batch_size]
        context = glossary.to_context([cue.text for cue in batch])
        print(f"translate_batch: {batch_index}/{total_batches} cues {batch[0].index}-{batch[-1].index}", flush=True)
        _print_glossary_context(context)
        payload = _build_payload(
            batch,
            context,
            selected_model,
            target_language,
            ignored_texts or [],
            extra_prompt,
        )
        mapping = _request_translation_mapping(endpoint, key, payload, f"{batch_index}/{total_batches}")
        missing = [cue for cue in batch if cue.index not in mapping]
        if missing:
            print(
                f"translate_batch_missing: {batch_index}/{total_batches} retry ids {[cue.index for cue in missing]}",
                flush=True,
            )
            retry_payload = _build_payload(
                missing,
                glossary.to_context([cue.text for cue in missing]),
                selected_model,
                target_language,
                ignored_texts or [],
                extra_prompt,
            )
            retry_mapping = _request_translation_mapping(endpoint, key, retry_payload, f"{batch_index}/{total_batches} missing")
            mapping.update(retry_mapping)
            still_missing_cues = [cue for cue in missing if cue.index not in mapping]
            for missing_cue in still_missing_cues:
                print(f"translate_single_retry: id {missing_cue.index}", flush=True)
                single_payload = _build_payload(
                    [missing_cue],
                    glossary.to_context([missing_cue.text]),
                    selected_model,
                    target_language,
                    ignored_texts or [],
                    extra_prompt,
                )
                mapping.update(
                    _request_translation_mapping(
                        endpoint,
                        key,
                        single_payload,
                        f"{batch_index}/{total_batches} single {missing_cue.index}",
                    )
                )
            still_missing = [cue.index for cue in missing if cue.index not in mapping]
            if still_missing:
                print(f"translate_batch_still_missing: {still_missing}", flush=True)
        print(f"translate_batch_done: {batch_index}/{total_batches} mapped {len(mapping)}/{len(batch)}", flush=True)
        for cue in batch:
            translated.append(
                SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=mapping.get(cue.index, cue.text),
                    source_track_id=cue.source_track_id,
                )
            )

    translated = enforce_glossary_translations(
        source_cues=cues,
        translated_cues=translated,
        glossary=glossary,
    )

    translated = drop_noise_cues(
        source_cues=cues,
        translated_cues=translated,
        ignored_texts=ignored_texts or [],
        ignored_patterns=ignored_patterns or [],
    )

    if cleanup_residual_fragments:
        translated = cleanup_residual_fragment_cues(
            translated,
            max_gap_seconds=residual_max_gap_seconds,
            short_text_chars=residual_short_text_chars,
        )

    if llm_cleanup_translated:
        translated = cleanup_translated_cues_with_llm(
            source_cues=cues,
            translated_cues=translated,
            endpoint=endpoint,
            api_key=key,
            model=selected_model,
            target_language=target_language,
            extra_prompt=extra_prompt,
            glossary=glossary,
            max_gap_seconds=llm_cleanup_max_gap_seconds,
            max_window_size=llm_cleanup_max_window_size,
        )

    if cleanup_residual_fragments:
        translated = cleanup_residual_fragment_cues(
            translated,
            max_gap_seconds=residual_max_gap_seconds,
            short_text_chars=residual_short_text_chars,
        )

    if dedupe_translated:
        translated = dedupe_adjacent_translated_cues(
            translated,
            similarity_threshold=dedupe_similarity,
            max_gap_seconds=dedupe_max_gap_seconds,
            source_cues=cues,
            source_max_gap_seconds=max(dedupe_max_gap_seconds, llm_cleanup_max_gap_seconds, 3.5),
        )

    if retime_translated:
        translated = retime_translated_cues_for_readability(
            translated,
            chars_per_second=retime_chars_per_second,
            max_extension_seconds=retime_max_extension_seconds,
        )

    translated = enforce_glossary_translations(
        source_cues=cues,
        translated_cues=translated,
        glossary=glossary,
    )

    write_srt(translated, out_srt)
    return out_srt



_HANGUL_RE = re.compile(r"[\uac00-\ud7a3\u3130-\u318f]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def cleanup_residual_fragment_cues(
    cues: list[SubtitleCue],
    *,
    max_gap_seconds: float = 3.0,
    short_text_chars: int = 6,
) -> list[SubtitleCue]:
    # Keep this local pass deliberately conservative. Semantic cleanup belongs to the LLM
    # because short words, repeated words, and partial-looking phrases can be intentional speech.
    return [_copy_cue(cue) for cue in cues if not _is_local_visual_noise(cue.text)]


def _is_local_visual_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _looks_like_plate_or_random_code(stripped):
        return True
    return False


def _looks_like_plate_or_random_code(text: str) -> bool:
    compact = comparable_text(text)
    if not compact:
        return True
    if _HAN_RE.search(text):
        return False
    digits = sum(char.isdigit() for char in compact)
    hangul = len(_HANGUL_RE.findall(compact))
    latin = sum(("a" <= char <= "z") or ("A" <= char <= "Z") for char in compact)
    if digits >= 2 and hangul <= 2 and latin <= 2:
        return True
    if digits >= 4 and hangul + latin <= 4:
        return True
    return False




def enforce_glossary_translations(
    *,
    source_cues: list[SubtitleCue],
    translated_cues: list[SubtitleCue],
    glossary: Glossary,
) -> list[SubtitleCue]:
    source_by_index = {cue.index: cue for cue in source_cues}
    result: list[SubtitleCue] = []
    for cue in translated_cues:
        source = _matching_source_cue(source_cues, cue) or source_by_index.get(cue.index)
        text = cue.text
        if source:
            for entry in glossary.entries:
                if entry.matches(source.text):
                    text = _enforce_glossary_entry(text, entry)
            if glossary.program and glossary.program.matches(source.text):
                text = _enforce_glossary_entry(text, glossary.program)
        result.append(
            SubtitleCue(
                index=cue.index,
                start=cue.start,
                end=cue.end,
                text=text,
                source_track_id=cue.source_track_id,
            )
        )
    return result


def _enforce_glossary_entry(text: str, entry: GlossaryEntry) -> str:
    if not entry.zh:
        return text
    key = comparable_text(text)
    zh_key = comparable_text(entry.zh)
    if zh_key and zh_key in key:
        return text
    fixed = text
    for variant in _glossary_zh_variants(entry):
        if variant and variant != entry.zh:
            fixed = fixed.replace(variant, entry.zh)
    if fixed != text:
        return fixed
    return text


def _glossary_zh_variants(entry: GlossaryEntry) -> list[str]:
    variants: list[str] = []
    for name in entry.names():
        stripped = name.strip().strip("'\"“”‘’《》<>「」『』")
        if stripped and stripped != entry.zh:
            variants.append(stripped)
    return _dedupe_strings(variants)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def drop_noise_cues(
    *,
    source_cues: list[SubtitleCue],
    translated_cues: list[SubtitleCue],
    ignored_texts: list[str],
    ignored_patterns: list[str],
) -> list[SubtitleCue]:
    source_by_index = {cue.index: cue for cue in source_cues}
    compiled_patterns = [re.compile(pattern) for pattern in ignored_patterns]
    dropped: list[int] = []
    result: list[SubtitleCue] = []
    for cue in translated_cues:
        source = source_by_index.get(cue.index)
        texts = [cue.text]
        if source:
            texts.append(source.text)
        if _is_noise_text(texts, ignored_texts, compiled_patterns):
            dropped.append(cue.index)
            continue
        result.append(_copy_cue(cue))
    if dropped:
        print(f"dropped_noise_cues: {dropped}")
    return result


def _is_noise_text(texts: list[str], ignored_texts: list[str], patterns: list[re.Pattern[str]]) -> bool:
    ignored_keys = {comparable_text(text) for text in ignored_texts if comparable_text(text)}
    for text in texts:
        stripped = text.strip()
        key = comparable_text(stripped)
        if key and key in ignored_keys:
            return True
        if any(pattern.search(stripped) for pattern in patterns):
            return True
    return False


def retime_translated_cues_for_readability(
    cues: list[SubtitleCue],
    *,
    chars_per_second: float = 7.5,
    max_extension_seconds: float = 2.5,
    min_gap_seconds: float = 0.04,
) -> list[SubtitleCue]:
    result = [_copy_cue(cue) for cue in cues]
    for index, cue in enumerate(result):
        readable_chars = len(comparable_text(cue.text))
        current_duration = cue.end - cue.start
        if readable_chars <= 0 or current_duration <= 0:
            continue
        desired_duration = readable_chars / max(chars_per_second, 1.0)
        if desired_duration <= current_duration + 0.15:
            continue
        desired_end = cue.start + desired_duration
        extension_limit = cue.end + max_extension_seconds
        if index + 1 < len(result):
            extension_limit = min(extension_limit, result[index + 1].start - min_gap_seconds)
        cue.end = max(cue.end, min(desired_end, extension_limit))
    return result


def cleanup_translated_cues_with_llm(
    *,
    source_cues: list[SubtitleCue],
    translated_cues: list[SubtitleCue],
    endpoint: str,
    api_key: str,
    model: str,
    target_language: str,
    extra_prompt: str = "",
    glossary: Glossary | None = None,
    max_gap_seconds: float = 1.8,
    max_window_size: int = 6,
) -> list[SubtitleCue]:
    source_by_index = {cue.index: cue for cue in source_cues}
    cleaned: list[SubtitleCue] = []
    index = 0
    while index < len(translated_cues):
        end = _llm_cleanup_window_end(source_by_index, translated_cues, index, max_gap_seconds, max_window_size)
        window = translated_cues[index : end + 1]
        if len(window) < 2:
            cleaned.append(_copy_cue(window[0]))
            index += 1
            continue

        print(
            f"llm_cleanup_window: cues {index + 1}-{end + 1}/{len(translated_cues)} ids {window[0].index}-{window[-1].index}",
            flush=True,
        )
        cleaned.extend(
            _cleanup_window_with_llm(
                source_by_index=source_by_index,
                window=window,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                target_language=target_language,
                extra_prompt=extra_prompt,
                glossary=glossary,
            )
        )
        index = end + 1

    for new_index, cue in enumerate(cleaned, start=1):
        cue.index = new_index
    return cleaned


def _llm_cleanup_window_end(
    source_by_index: dict[int, SubtitleCue],
    cues: list[SubtitleCue],
    start: int,
    max_gap_seconds: float,
    max_window_size: int,
) -> int:
    end = start
    while end + 1 < len(cues) and end - start + 1 < max_window_size:
        if not _is_llm_cleanup_candidate_pair(source_by_index, cues[end], cues[end + 1], max_gap_seconds):
            break
        end += 1
    return end


def _is_llm_cleanup_candidate_pair(
    source_by_index: dict[int, SubtitleCue],
    left: SubtitleCue,
    right: SubtitleCue,
    max_gap_seconds: float,
) -> bool:
    gap = right.start - left.end
    if gap < -0.5 or gap > max_gap_seconds:
        return False

    left_key = comparable_text(left.text)
    right_key = comparable_text(right.text)
    if not left_key or not right_key:
        return False

    left_source = source_by_index.get(left.index)
    right_source = source_by_index.get(right.index)
    source_similarity = 0.0
    if left_source and right_source:
        source_similarity = text_similarity(left_source.text, right_source.text)

    return bool(
        len(left_key) <= 24
        or len(right_key) <= 24
        or text_similarity(left.text, right.text) >= 0.25
        or source_similarity >= 0.25
        or _longest_common_substring_length(left_key, right_key) >= 4
    )


def _cleanup_window_with_llm(
    *,
    source_by_index: dict[int, SubtitleCue],
    window: list[SubtitleCue],
    endpoint: str,
    api_key: str,
    model: str,
    target_language: str,
    extra_prompt: str,
    glossary: Glossary | None,
) -> list[SubtitleCue]:
    payload = _build_cleanup_payload(source_by_index, window, model, target_language, extra_prompt, glossary)
    try:
        content = _request_translation(endpoint, api_key, payload)
        parsed = _parse_json_content(content)
        items = parsed if isinstance(parsed, list) else parsed.get("items") or parsed.get("subtitles") or parsed.get("result")
        return _apply_llm_cleanup_items(window, items)
    except Exception as exc:
        print(f"LLM cleanup skipped for ids {[cue.index for cue in window]}: {exc}")
        return [_copy_cue(cue) for cue in window]


def _build_cleanup_payload(
    source_by_index: dict[int, SubtitleCue],
    window: list[SubtitleCue],
    model: str,
    target_language: str,
    extra_prompt: str,
    glossary: Glossary | None = None,
) -> dict[str, Any]:
    items = []
    for cue in window:
        source = source_by_index.get(cue.index)
        items.append(
            {
                "id": cue.index,
                "start": cue.start,
                "end": cue.end,
                "source": source.text if source else "",
                "zh": cue.text,
            }
        )

    glossary_context = glossary.to_context([item["source"] for item in items]) if glossary else {}

    system = (
        "你是专业字幕校对。判断相邻字幕是否因为 OCR 闪烁、残句、重复片段或同一句话的不同译法造成重复。"
        "只在非常确定时合并；不确定就保持原样。只输出 JSON，不要解释。"
    )
    rules = [
        '输入是一小段连续字幕，包含原文 source 和当前中文字幕 zh。',
        '你的职责是语义校对：判断相邻字幕是否为同一句 OCR 变体、重复尾巴、残句，或明显非对白视觉噪声。',
        '不要因为字幕短、只有一两个词、或看起来像重复就删除；综艺/花絮里人物可能故意重复、停顿、接话，这种要保留。',
        '只有在非常确定某条不是人物说话/旁白，而是车牌、门牌、背景招牌、角标、界面字、随机数字字母时，才返回 drop=true。',
        '如果 source 是可读韩文/日文/中文词句，即使很短，也优先保留或合并翻译；不要把真实台词当噪声删掉。',
        '如果多条相邻字幕表达同一句话，后一条只是前一条的 OCR 改写、重复尾巴或残片，可以合并这些 id。',
        '同一画面字幕的 OCR 变体即使隔了几秒，只要表达同一句话，也要合并成一条。',
        '合并时 start 取第一个 id 的 start，end 取最后一个 id 的 end，zh 写成一条自然、完整、简洁的中文字幕。',
        '严格遵守 context.program 和 context.glossary；清洗合并时不得改动固定译名。',
        '不确定是不是噪声、不确定是不是重复时，必须保留，不要合并或删除。',
        '必须覆盖每一个输入 id，且每个 id 只能出现一次。',
        '返回格式：{"items":[{"ids":[1,2],"zh":"合并后的字幕"},{"ids":[3],"drop":true},{"ids":[4],"zh":"原字幕"}]}',
    ]
    if extra_prompt.strip():
        rules.append(f"额外要求：{extra_prompt.strip()}")

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_language": target_language,
                        "context": glossary_context,
                        "rules": rules,
                        "subtitles": items,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.0,
    }


def _apply_llm_cleanup_items(window: list[SubtitleCue], items: Any) -> list[SubtitleCue]:
    if not isinstance(items, list):
        raise ValueError("cleanup response items must be a list")

    cue_by_id = {cue.index: cue for cue in window}
    expected_ids = [cue.index for cue in window]
    id_order = {cue_id: position for position, cue_id in enumerate(expected_ids)}
    seen: list[int] = []
    parsed_items: list[tuple[int, list[int], dict[str, Any]]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("cleanup item must be an object")
        raw_ids = item.get("ids") or item.get("id")
        ids = [int(raw_ids)] if isinstance(raw_ids, int) else [int(value) for value in raw_ids or []]
        if not ids or any(cue_id not in cue_by_id for cue_id in ids):
            raise ValueError(f"invalid cleanup ids: {ids}")
        ordered_ids = sorted(ids, key=id_order.__getitem__)
        seen.extend(ordered_ids)
        parsed_items.append((id_order[ordered_ids[0]], ordered_ids, item))

    ordered_seen = sorted(seen, key=id_order.__getitem__)
    if ordered_seen != expected_ids or len(seen) != len(set(seen)):
        raise ValueError(f"cleanup ids must cover window once: got {seen}, expected {expected_ids}")

    cleaned: list[SubtitleCue] = []
    for _, ids, item in sorted(parsed_items, key=lambda parsed: parsed[0]):
        if bool(item.get("drop", False)):
            continue
        text = str(item.get("zh") or item.get("text") or item.get("translation") or "").strip()
        if not text:
            raise ValueError("cleanup item missing zh text")
        first = cue_by_id[ids[0]]
        last = cue_by_id[ids[-1]]
        cleaned.append(
            SubtitleCue(
                index=first.index,
                start=first.start,
                end=last.end,
                text=_clean_repeated_translation(text),
                source_track_id=first.source_track_id,
            )
        )
    return cleaned


def _parse_json_content(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_json_candidate(text)
        if candidate == text:
            raise
        return json.loads(candidate)


def _copy_cue(cue: SubtitleCue) -> SubtitleCue:
    return SubtitleCue(
        index=cue.index,
        start=cue.start,
        end=cue.end,
        text=cue.text,
        source_track_id=cue.source_track_id,
    )


def dedupe_adjacent_translated_cues(
    cues: list[SubtitleCue],
    *,
    similarity_threshold: float = 0.88,
    max_gap_seconds: float = 1.2,
    source_cues: list[SubtitleCue] | None = None,
    source_similarity_threshold: float = 0.65,
    source_max_gap_seconds: float | None = None,
) -> list[SubtitleCue]:
    source_context = source_cues or []
    merged: list[SubtitleCue] = []
    for cue in cues:
        cleaned_text = _clean_repeated_translation(cue.text)
        cleaned = SubtitleCue(
            index=cue.index,
            start=cue.start,
            end=cue.end,
            text=cleaned_text,
            source_track_id=cue.source_track_id,
        )
        if merged and _should_merge_translated_cues(
            merged[-1],
            cleaned,
            similarity_threshold,
            max_gap_seconds,
            left_source=_matching_source_cue(source_context, merged[-1]),
            right_source=_matching_source_cue(source_context, cleaned),
            source_similarity_threshold=source_similarity_threshold,
            source_max_gap_seconds=source_max_gap_seconds,
        ):
            previous = merged[-1]
            previous.end = max(previous.end, cleaned.end)
            previous.text = _choose_merged_translation(previous.text, cleaned.text)
            continue
        merged.append(cleaned)

    for index, cue in enumerate(merged, start=1):
        cue.index = index
    return merged


def _matching_source_cue(source_cues: list[SubtitleCue], cue: SubtitleCue) -> SubtitleCue | None:
    tolerance = 0.05
    matches = [
        source
        for source in source_cues
        if source.end >= cue.start - tolerance and source.start <= cue.end + tolerance
    ]
    if not matches:
        return None
    return SubtitleCue(
        index=matches[0].index,
        start=matches[0].start,
        end=matches[-1].end,
        text="\n".join(source.text for source in matches if source.text.strip()),
        source_track_id=matches[0].source_track_id,
    )


def _should_merge_translated_cues(
    left: SubtitleCue,
    right: SubtitleCue,
    similarity_threshold: float,
    max_gap_seconds: float,
    *,
    left_source: SubtitleCue | None = None,
    right_source: SubtitleCue | None = None,
    source_similarity_threshold: float = 0.65,
    source_max_gap_seconds: float | None = None,
) -> bool:
    gap = right.start - left.end
    if gap < -0.5:
        return False
    left_key = comparable_text(left.text)
    right_key = comparable_text(right.text)
    if not left_key or not right_key:
        return False

    source_gap_limit = source_max_gap_seconds if source_max_gap_seconds is not None else max_gap_seconds
    short_pair = (left.end - left.start) <= 4.0 and (right.end - right.start) <= 4.0
    if short_pair and left_source and right_source and gap <= source_gap_limit:
        left_source_key = comparable_text(left_source.text)
        right_source_key = comparable_text(right_source.text)
        if _is_fragment_variant(left_source_key, right_source_key):
            return True
        if _longest_common_substring_length(left_source_key, right_source_key) >= 8:
            return True
        if text_similarity(left_source.text, right_source.text) >= source_similarity_threshold:
            return True

    if _is_fragment_variant(left_key, right_key):
        return gap <= max(max_gap_seconds, 2.0)
    if gap > max_gap_seconds:
        return False
    return text_similarity(left.text, right.text) >= similarity_threshold


def _is_fragment_variant(left_key: str, right_key: str) -> bool:
    shorter, longer = sorted([left_key, right_key], key=len)
    if len(shorter) < 4:
        return False
    if shorter in longer:
        return True
    return _longest_common_substring_length(left_key, right_key) >= max(5, int(len(shorter) * 0.75))


def _choose_merged_translation(left: str, right: str) -> str:
    left_clean = _clean_repeated_translation(left)
    right_clean = _clean_repeated_translation(right)
    left_key = comparable_text(left_clean)
    right_key = comparable_text(right_clean)
    if left_key == right_key:
        return left_clean if len(left_clean) >= len(right_clean) else right_clean
    if left_key and left_key in right_key:
        return right_clean
    if right_key and right_key in left_key:
        return left_clean
    return left_clean if len(left_key) >= len(right_key) else right_clean


def _clean_repeated_translation(text: str) -> str:
    lines = [_clean_repeated_line(line.strip()) for line in text.splitlines() if line.strip()]
    result: list[str] = []
    for line in lines:
        key = comparable_text(line)
        if not key:
            continue
        if any(key == comparable_text(existing) or key in comparable_text(existing) for existing in result):
            continue
        result = [existing for existing in result if comparable_text(existing) not in key]
        result.append(line)
    return "\n".join(result)


def _clean_repeated_line(text: str) -> str:
    pieces = [piece.strip() for piece in re.split(r"[，,、；;。.!！?？]+", text) if piece.strip()]
    if len(pieces) <= 1:
        return text

    cleaned: list[str] = []
    for piece in pieces:
        key = comparable_text(piece)
        if not key:
            continue
        if any(key == comparable_text(existing) or key in comparable_text(existing) for existing in cleaned):
            continue
        cleaned = [existing for existing in cleaned if comparable_text(existing) not in key]
        cleaned.append(piece)
    if not cleaned:
        return text
    return "，".join(cleaned)


def _longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char == right_char:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def _build_payload(
    cues: list[SubtitleCue],
    context: dict[str, Any],
    model: str,
    target_language: str,
    ignored_texts: list[str],
    extra_prompt: str = "",
) -> dict[str, Any]:
    subtitles = [
        {
            "id": cue.index,
            "start": cue.start,
            "end": cue.end,
            "source": cue.text,
        }
        for cue in cues
    ]
    system = (
        f"你是专业影视字幕翻译。把韩语/日语等原文字幕翻译成自然、简洁、口语化的{target_language}。"
        "必须保持 id 不变，不要增删字幕条目，不要解释。只输出 JSON 数组。"
    )
    rules = [
        '严格遵守 context.program 和 context.glossary；source 或 aliases 命中时，必须使用对应 zh。',
        'aliases 包含别名、简称、助词形态和 OCR 误识；命中 aliases 也按同一 zh 翻译。',
        '人物名、角色名、节目名、固定术语不得自行改译、音译或使用近义词。',
        '修复明显 OCR 断字或多余空格，但不要凭空补剧情。',
        '如果相邻字幕明显是同一句话的 OCR 变体，请尽量使用一致译法，避免只改一个小词造成闪烁感。',
        'ignored_texts 中的内容是 logo、水印、固定角标或不应进入字幕正文的噪声；如果输入中残留这些内容，请删除而不是翻译。',
        '不要翻译 logo、水印或节目固定标题，输入里若出现也保持克制处理。',
        '输出格式为 [{"id": 1, "zh": "中文字幕"}]。',
    ]
    if extra_prompt.strip():
        rules.append(f"额外要求：{extra_prompt.strip()}")

    user = {
        "context": context,
        "ignored_texts": ignored_texts,
        "rules": rules,
        "subtitles": subtitles,
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }


def _print_glossary_context(context: dict[str, Any]) -> None:
    entries = context.get("glossary") or []
    names = [str(entry.get("source", "")) for entry in entries if isinstance(entry, dict)]
    program = context.get("program") or {}
    program_name = program.get("source") if isinstance(program, dict) else None
    parts = []
    if program_name:
        parts.append(f"program={program_name}")
    if names:
        parts.append(f"glossary={len(names)}:{','.join(names[:12])}")
    else:
        parts.append("glossary=0")
    print("translate_rag: " + " ".join(parts), flush=True)


def _request_translation(url: str, api_key: str, payload: dict[str, Any]) -> str:
    timeout = _request_timeout_seconds()
    max_attempts = _request_max_attempts()
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                status = response.status_code
                if attempt < max_attempts and (status == 429 or 500 <= status < 600):
                    _sleep_before_retry(attempt, max_attempts, f"status={status}")
                    continue
                body = response.text.strip()
                model = payload.get("model", "")
                raise RuntimeError(f"Volcengine request failed: status={status}, model={model}, url={url}, body={body}") from exc
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt >= max_attempts:
                raise
            _sleep_before_retry(attempt, max_attempts, repr(exc))
    raise RuntimeError("Volcengine request failed after retries")


def _request_timeout_seconds() -> float:
    return float(os.environ.get("ARK_REQUEST_TIMEOUT", "240"))


def _request_max_attempts() -> int:
    return max(1, int(os.environ.get("ARK_REQUEST_RETRIES", "3")))


def _sleep_before_retry(attempt: int, max_attempts: int, reason: str) -> None:
    wait_seconds = min(2 ** (attempt - 1), 8)
    print(f"translate_request_retry: attempt {attempt}/{max_attempts} wait={wait_seconds}s {reason}", flush=True)
    time.sleep(wait_seconds)


def _request_translation_mapping(url: str, api_key: str, payload: dict[str, Any], batch_label: str) -> dict[int, str]:
    result = _request_translation(url, api_key, payload)
    try:
        return _parse_translation_mapping(result)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"translate_json_retry: {batch_label} {exc}", flush=True)
        repair_payload = _build_json_repair_payload(payload, result, str(exc))
        repair_result = _request_translation(url, api_key, repair_payload)
        try:
            return _parse_translation_mapping(repair_result)
        except (json.JSONDecodeError, ValueError) as repair_exc:
            print(f"translate_json_retry_failed: {batch_label} {repair_exc}; retry original batch", flush=True)
            retry_result = _request_translation(url, api_key, payload)
            return _parse_translation_mapping(retry_result)


def _build_json_repair_payload(payload: dict[str, Any], bad_content: str, error: str) -> dict[str, Any]:
    messages = list(payload.get("messages") or [])
    return {
        **payload,
        "messages": messages
        + [
            {"role": "assistant", "content": bad_content[:12000]},
            {
                "role": "user",
                "content": (
                    "你上一次回复不是合法 JSON，解析错误为："
                    f"{error}\n"
                    "请只修复 JSON 格式，不要改写、增删或解释翻译内容。"
                    "输出必须是合法 JSON 数组，格式严格为 "
                    '[{"id": 1, "zh": "中文字幕"}]。'
                ),
            },
        ],
        "temperature": 0,
    }


def _parse_translation_mapping(content: str) -> dict[int, str]:
    parsed = _parse_json_content(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("translations") or parsed.get("items") or []
    if not isinstance(parsed, list):
        raise ValueError("translation response must be a JSON array or object containing translations/items")
    mapping: dict[int, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("index")
        raw_text = item.get("zh") or item.get("text") or item.get("translation")
        if raw_id is not None and raw_text is not None:
            mapping[int(raw_id)] = str(raw_text)
    return mapping


def _extract_json_candidate(text: str) -> str:
    start = -1
    opening = ""
    for index, char in enumerate(text):
        if char in "[{":
            start = index
            opening = char
            break
    if start < 0:
        return text

    closing = "]" if opening == "[" else "}"
    stack = [closing]
    in_string = False
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append("]" if char == "[" else "}")
        elif char in "]}":
            if not stack or char != stack[-1]:
                return text[start:]
            stack.pop()
            if not stack:
                return text[start : index + 1]
    return text[start:]


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _load_dotenv(anchor: Path) -> None:
    for candidate in [Path.cwd() / ".env", anchor.resolve().parent / ".env"]:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
