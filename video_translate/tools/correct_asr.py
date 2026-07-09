from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt
from video_translate.llm_config import load_llm_task_config
from video_translate.translate.glossary import load_glossary
from video_translate.translate.volcengine import (
    DEFAULT_BASE_URL,
    _chat_completions_url,
    _load_dotenv,
    _parse_json_content,
    _request_translation,
)


DEFAULT_ASR_CORRECTION_MODEL = "doubao-seed-2.0-lite"
DEFAULT_BATCH_SIZE = 20
DEFAULT_SOURCE_LANGUAGE = "auto"


def default_output_path(source_srt: Path) -> Path:
    return source_srt.with_name(source_srt.stem + ".corrected.srt")


def _nearby_reference_payload(cue: SubtitleCue, reference_cues: list[SubtitleCue], *, window_seconds: float = 1.0, max_items: int = 4) -> list[dict[str, Any]]:
    nearby: list[tuple[float, float, SubtitleCue]] = []
    for ref in reference_cues:
        if ref.end < cue.start - window_seconds or ref.start > cue.end + window_seconds:
            continue
        overlap = max(0.0, min(cue.end, ref.end) - max(cue.start, ref.start))
        if overlap > 0:
            distance = 0.0
        elif ref.end < cue.start:
            distance = cue.start - ref.end
        else:
            distance = ref.start - cue.end
        nearby.append((-overlap, distance, ref))
    nearby.sort(key=lambda item: (item[0], item[1], item[2].start))
    return [
        {"start": ref.start, "end": ref.end, "text": ref.text}
        for _, _, ref in nearby[:max_items]
        if ref.text.strip()
    ]


def correct_asr_srt(
    source_srt: Path,
    out_srt: Path | None = None,
    *,
    glossary_path: Path | None = None,
    reference_srt: Path | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str | None = None,
    base_url: str | None = None,
    source_language: str = DEFAULT_SOURCE_LANGUAGE,
    extra_prompt: str = "",
) -> Path:
    source_srt = source_srt.expanduser().resolve()
    if not source_srt.exists():
        raise FileNotFoundError(f"字幕文件不存在: {source_srt}")
    if source_srt.suffix.lower() != ".srt":
        raise ValueError("ASR 纠错入口只接受 .srt 文件。")
    if reference_srt is not None:
        reference_srt = reference_srt.expanduser().resolve()
        if not reference_srt.exists():
            raise FileNotFoundError(f"OCR 参考字幕不存在: {reference_srt}")
        if reference_srt.suffix.lower() != ".srt":
            raise ValueError("OCR 参考字幕只接受 .srt 文件。")
    out_srt = (out_srt or default_output_path(source_srt)).expanduser().resolve()

    _load_dotenv(source_srt)
    task_llm = load_llm_task_config(
        "asr_correction",
        explicit_model=model,
        explicit_base_url=base_url,
    )
    key = getattr(task_llm, "api_key", None) or os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY")
    selected_model = task_llm.model or DEFAULT_ASR_CORRECTION_MODEL
    endpoint = _chat_completions_url(task_llm.base_url or DEFAULT_BASE_URL)
    if not key:
        raise RuntimeError("缺少 LLM_API_KEY，请先配置 OpenAI-compatible API Key。")
    if not selected_model:
        raise RuntimeError("缺少 ASR 纠错模型，请传 --model 或配置 ASR_CORRECTION_MODEL。")

    cues = read_srt(source_srt)
    reference_cues = read_srt(reference_srt) if reference_srt else []
    glossary = load_glossary(glossary_path)
    corrected: list[SubtitleCue] = []
    print(f"asr_correct_model: {selected_model}", flush=True)
    total_batches = max(1, (len(cues) + batch_size - 1) // batch_size)
    for batch_index, offset in enumerate(range(0, len(cues), batch_size), start=1):
        batch = cues[offset : offset + batch_size]
        print(f"asr_correct_batch: {batch_index}/{total_batches} cues {batch[0].index}-{batch[-1].index}", flush=True)
        mapping = _request_batch_correction_mapping(
            batch,
            endpoint=endpoint,
            api_key=key,
            model=selected_model,
            source_language=source_language,
            glossary_context=glossary.to_context([cue.text for cue in batch]),
            extra_prompt=extra_prompt,
            reference_cues=reference_cues,
            batch_label=f"{batch_index}/{total_batches}",
        )
        for cue in batch:
            corrected.append(
                SubtitleCue(
                    index=cue.index,
                    start=cue.start,
                    end=cue.end,
                    text=mapping.get(cue.index, cue.text),
                    source_track_id=cue.source_track_id,
                )
            )
        print(f"asr_correct_batch_done: {batch_index}/{total_batches} mapped {len(mapping)}/{len(batch)}", flush=True)

    write_srt(corrected, out_srt)
    print(f"corrected_srt: {out_srt}", flush=True)
    return out_srt


def build_correction_payload(
    cues: list[SubtitleCue],
    *,
    model: str,
    source_language: str,
    glossary_context: dict[str, Any],
    extra_prompt: str = "",
    reference_cues: list[SubtitleCue] | None = None,
) -> dict[str, Any]:
    subtitles = [
        {
            "id": cue.index,
            "start": cue.start,
            "end": cue.end,
            "source": cue.text,
            "ocr_reference": _nearby_reference_payload(cue, reference_cues or []),
        }
        for cue in cues
    ]
    rules = [
        "这是 faster-whisper 音频识别生成的原文字幕，可能存在同音、近音、人名、昵称、品牌名、歌曲名误识别。",
        "只纠正原文字幕文本，不要翻译成中文，不要解释。",
        "必须保持 id 不变，不要增删字幕条目，不要拆分或合并字幕。",
        "不要改时间轴；输出只包含 id 和 corrected。",
        "参考 context.glossary 中的 source、aliases 和 zh 来判断固定人名/术语，但 corrected 仍然必须是原语言文本。",
        "如果 subtitles[].ocr_reference 有内容，它来自同一视频、相近时间段的画面内嵌字幕 OCR；ASR 仍然主导时间轴和说话内容，OCR 只用于修正明显同音误识别、人名/术语或补足同一句中被 ASR 漏掉的短词。",
        "不要把与 ASR 当前句无关的画面说明、姓名牌、角标、水印或后期花字强行加入 corrected。",
        "不确定时保留原文，避免过度脑补。",
    ]
    if extra_prompt.strip():
        rules.append(f"任务提示：{extra_prompt.strip()}")
    user = {
        "source_language": source_language,
        "context": glossary_context,
        "rules": rules,
        "subtitles": subtitles,
        "output_schema": [{"id": 1, "corrected": "修正后的原文字幕"}],
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 ASR 原文字幕纠错助手。只输出合法 JSON 数组，不要 Markdown，不要解释。"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }


def _request_batch_correction_mapping(
    batch: list[SubtitleCue],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    source_language: str,
    glossary_context: dict[str, Any],
    extra_prompt: str,
    reference_cues: list[SubtitleCue] | None,
    batch_label: str,
) -> dict[int, str]:
    payload = build_correction_payload(
        batch,
        model=model,
        source_language=source_language,
        glossary_context=glossary_context,
        extra_prompt=extra_prompt,
        reference_cues=reference_cues,
    )
    try:
        return _request_correction_mapping(endpoint, api_key, payload)
    except (requests.Timeout, requests.ConnectionError) as exc:
        if len(batch) <= 1:
            raise
        midpoint = max(1, len(batch) // 2)
        left = batch[:midpoint]
        right = batch[midpoint:]
        print(
            f"asr_correct_batch_split: {batch_label} size={len(batch)} -> {len(left)}+{len(right)} after {type(exc).__name__}: {exc}",
            flush=True,
        )
        mapping = _request_batch_correction_mapping(
            left,
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            source_language=source_language,
            glossary_context=glossary_context,
            extra_prompt=extra_prompt,
            reference_cues=reference_cues,
            batch_label=f"{batch_label}a",
        )
        mapping.update(
            _request_batch_correction_mapping(
                right,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                source_language=source_language,
                glossary_context=glossary_context,
                extra_prompt=extra_prompt,
                reference_cues=reference_cues,
                batch_label=f"{batch_label}b",
            )
        )
        return mapping


def _request_correction_mapping(url: str, api_key: str, payload: dict[str, Any]) -> dict[int, str]:
    content = _request_translation(url, api_key, payload)
    parsed = _parse_json_content(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("items") or parsed.get("subtitles") or parsed.get("corrections") or []
    if not isinstance(parsed, list):
        raise ValueError("ASR 纠错结果必须是 JSON 数组")
    mapping: dict[int, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        cue_id = item.get("id")
        corrected = item.get("corrected") or item.get("source") or item.get("text")
        if cue_id is None or corrected is None:
            continue
        mapping[int(cue_id)] = str(corrected).strip()
    return mapping


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Correct ASR-generated source SRT text while preserving timing.")
    parser.add_argument("source_srt", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--glossary", type=Path, default=None)
    parser.add_argument("--reference-srt", type=Path, default=None, help="Optional OCR SRT from the same video used as ASR correction reference.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--source-language", default=DEFAULT_SOURCE_LANGUAGE)
    parser.add_argument("--extra-prompt", default="")
    args = parser.parse_args(argv)
    correct_asr_srt(
        args.source_srt,
        args.out,
        glossary_path=args.glossary,
        reference_srt=args.reference_srt,
        batch_size=args.batch_size,
        model=args.model,
        base_url=args.base_url,
        source_language=args.source_language,
        extra_prompt=args.extra_prompt,
    )


if __name__ == "__main__":
    main()
