from __future__ import annotations

import json
from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt


DEFAULT_MIN_OVERLAP_SECONDS = 0.10


def build_dual_reference_cues(
    source_cues: list[SubtitleCue],
    reference_cues: list[SubtitleCue],
    *,
    min_overlap_seconds: float = DEFAULT_MIN_OVERLAP_SECONDS,
) -> tuple[list[SubtitleCue], list[dict[str, object]]]:
    dual_cues: list[SubtitleCue] = []
    debug: list[dict[str, object]] = []
    for source in source_cues:
        reference, overlap = _best_reference_cue(source, reference_cues, min_overlap_seconds=min_overlap_seconds)
        source_text = source.text.strip()
        reference_text = reference.text.strip() if reference else ""
        text = f"韩文原文：{source_text}"
        if reference_text:
            text += f"\n英文参考：{reference_text}"
        dual_cues.append(
            SubtitleCue(
                index=source.index,
                start=source.start,
                end=source.end,
                text=text,
                source_track_id=source.source_track_id,
            )
        )
        debug.append(
            {
                "index": source.index,
                "start": source.start,
                "end": source.end,
                "source_text": source_text,
                "reference_text": reference_text,
                "reference_index": reference.index if reference else None,
                "overlap_seconds": overlap,
            }
        )
    return dual_cues, debug


def write_dual_reference_outputs(
    source_cues: list[SubtitleCue],
    reference_cues: list[SubtitleCue],
    out_dir: Path,
    *,
    min_overlap_seconds: float = DEFAULT_MIN_OVERLAP_SECONDS,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dual_cues, debug = build_dual_reference_cues(
        source_cues,
        reference_cues,
        min_overlap_seconds=min_overlap_seconds,
    )
    source_srt = out_dir / "dual.source.srt"
    context_srt = out_dir / "dual.context.srt"
    debug_json = out_dir / "dual.debug.json"
    write_srt(dual_cues, source_srt)
    write_srt(dual_cues, context_srt)
    debug_json.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"source_srt": source_srt, "context_srt": context_srt, "debug_json": debug_json}


def _best_reference_cue(
    source: SubtitleCue,
    reference_cues: list[SubtitleCue],
    *,
    min_overlap_seconds: float,
) -> tuple[SubtitleCue | None, float]:
    best: SubtitleCue | None = None
    best_overlap = 0.0
    for reference in reference_cues:
        overlap = _overlap_seconds(source.start, source.end, reference.start, reference.end)
        if overlap > best_overlap:
            best = reference
            best_overlap = overlap
    if best is None or best_overlap < min_overlap_seconds:
        return None, 0.0
    return best, best_overlap


def _overlap_seconds(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))
