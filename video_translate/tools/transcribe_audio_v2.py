from __future__ import annotations

import argparse
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from video_translate.asr_v2 import ASR_V2_VERSION
from video_translate.cache import configure_model_cache
from video_translate.tools.transcribe_audio import (
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL_SIZE,
    ensure_cuda_library_path_ready,
    normalize_language,
    write_segments_as_srt,
)


DEFAULT_VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 120,
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 300,
}
RECOVERY_VAD_PARAMETERS = {
    "threshold": 0.25,
    "min_speech_duration_ms": 80,
    "min_silence_duration_ms": 350,
    "speech_pad_ms": 500,
}
RECOVERY_MIN_PRIMARY_GAP_SECONDS = 0.45
RECOVERY_PRIMARY_COVERAGE_PADDING_SECONDS = 0.12
RECOVERY_MIN_WORD_PROBABILITY = 0.35
RECOVERY_MIN_REGION_PROBABILITY = 0.68
RECOVERY_DUPLICATE_WINDOW_SECONDS = 1.75
RECOVERY_REGION_JOIN_GAP_SECONDS = 0.8
FOCUSED_RECOVERY_WINDOW_PADDING_SECONDS = 3.0
FOCUSED_RECOVERY_WINDOW_POST_PADDING_SECONDS = 3.0
FOCUSED_RECOVERY_TARGET_PADDING_SECONDS = 0.3
FOCUSED_RECOVERY_TARGET_RMS = 0.08
FOCUSED_RECOVERY_MAX_GAIN = 12.0
FOCUSED_RECOVERY_MIN_WORD_PROBABILITY = 0.25
FOCUSED_RECOVERY_MIN_REGION_PROBABILITY = 0.72
FOCUSED_RECOVERY_CONSENSUS_MIN_PROBABILITY = 0.42
FOCUSED_RECOVERY_CONSENSUS_MIN_SIMILARITY = 0.58


def _bounded_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _fallback_probability(avg_logprob: float | None) -> float | None:
    if avg_logprob is None:
        return None
    return _bounded_probability(math.exp(float(avg_logprob)))


def _serialize_segments(
    segments: list[Any],
    *,
    source_pass: str = "primary",
    segment_id_offset: int = 0,
    time_offset: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    serialized_segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    word_index = 1
    for fallback_segment_id, segment in enumerate(segments):
        segment_id = segment_id_offset + int(getattr(segment, "id", fallback_segment_id))
        segment_words: list[dict[str, Any]] = []
        for raw_word in getattr(segment, "words", []) or []:
            if getattr(raw_word, "start", None) is None or getattr(raw_word, "end", None) is None:
                continue
            text = str(getattr(raw_word, "word", "") or "")
            if not text.strip():
                continue
            item = {
                "index": word_index,
                "segment_id": segment_id,
                "start": round(time_offset + float(raw_word.start), 3),
                "end": round(time_offset + float(raw_word.end), 3),
                "text": text,
                "probability": _bounded_probability(getattr(raw_word, "probability", None)),
                "source_pass": source_pass,
            }
            word_index += 1
            words.append(item)
            segment_words.append(item)

        segment_text = str(getattr(segment, "text", "") or "").strip()
        if segment_text and not segment_words:
            probability = _fallback_probability(getattr(segment, "avg_logprob", None))
            item = {
                "index": word_index,
                "segment_id": segment_id,
                "start": round(time_offset + float(getattr(segment, "start", 0.0)), 3),
                "end": round(time_offset + float(getattr(segment, "end", 0.01)), 3),
                "text": segment_text,
                "probability": probability,
                "source_pass": source_pass,
            }
            word_index += 1
            words.append(item)
            segment_words.append(item)

        serialized_segments.append(
            {
                "id": segment_id,
                "start": round(time_offset + float(getattr(segment, "start", 0.0)), 3),
                "end": round(time_offset + float(getattr(segment, "end", 0.01)), 3),
                "text": segment_text,
                "avg_logprob": float(getattr(segment, "avg_logprob", 0.0)),
                "compression_ratio": float(getattr(segment, "compression_ratio", 0.0)),
                "no_speech_prob": float(getattr(segment, "no_speech_prob", 0.0)),
                "temperature": float(getattr(segment, "temperature", 0.0)),
                "word_indexes": [item["index"] for item in segment_words],
                "source_pass": source_pass,
            }
        )
    return serialized_segments, words


def _normalized_word_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def _primary_gap_at(
    midpoint: float,
    primary_words: list[dict[str, Any]],
    *,
    media_duration: float,
) -> tuple[float, float] | None:
    left_end = 0.0
    right_start = max(0.0, media_duration)
    padding = RECOVERY_PRIMARY_COVERAGE_PADDING_SECONDS
    for word in primary_words:
        start = float(word["start"])
        end = float(word["end"])
        if start - padding <= midpoint <= end + padding:
            return None
        if end < midpoint:
            left_end = max(left_end, end)
            continue
        if start > midpoint:
            right_start = min(right_start, start)
            break
    if right_start - left_end < RECOVERY_MIN_PRIMARY_GAP_SECONDS:
        return None
    return left_end, right_start


def _duplicates_nearby_primary(
    candidate: dict[str, Any],
    primary_words: list[dict[str, Any]],
) -> bool:
    normalized = _normalized_word_text(candidate.get("text"))
    if not normalized:
        return True
    candidate_midpoint = (float(candidate["start"]) + float(candidate["end"])) / 2.0
    for word in primary_words:
        word_midpoint = (float(word["start"]) + float(word["end"])) / 2.0
        if abs(candidate_midpoint - word_midpoint) > RECOVERY_DUPLICATE_WINDOW_SECONDS:
            continue
        if normalized == _normalized_word_text(word.get("text")):
            return True
    return False


def _partition_recovery_words(
    words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda item: (float(item["start"]), float(item["end"])))
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in ordered:
        same_primary_gap = bool(
            not current
            or (
                word.get("recovery_gap_start")
                == current[-1].get("recovery_gap_start")
                and word.get("recovery_gap_end")
                == current[-1].get("recovery_gap_end")
            )
        )
        if (
            current
            and (
                not same_primary_gap
                or float(word["start"]) - float(current[-1]["end"])
                > RECOVERY_REGION_JOIN_GAP_SECONDS
            )
        ):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _group_recovery_regions(
    words: list[dict[str, Any]],
    *,
    include_reason: bool = False,
) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for group in _partition_recovery_words(words):
        probabilities = [
            float(item["probability"])
            for item in group
            if item.get("probability") is not None
        ]
        region = {
            "start": round(min(float(item["start"]) for item in group), 3),
            "end": round(max(float(item["end"]) for item in group), 3),
            "text": "".join(str(item.get("text") or "") for item in group).strip(),
            "word_count": len(group),
            "average_probability": (
                round(sum(probabilities) / len(probabilities), 4)
                if probabilities
                else None
            ),
        }
        source_passes = sorted(
            {
                str(item.get("source_pass") or "")
                for item in group
                if item.get("source_pass")
            }
        )
        review_target_ids = sorted(
            {
                str(item.get("review_target_id") or "")
                for item in group
                if item.get("review_target_id")
            }
        )
        if source_passes:
            region["source_pass"] = source_passes[0] if len(source_passes) == 1 else source_passes
        if review_target_ids:
            region["review_target_ids"] = review_target_ids
        if any(bool(item.get("consensus_confirmed")) for item in group):
            region["consensus_confirmed"] = True
        if include_reason:
            region["reasons"] = sorted(
                {
                    str(item.get("recovery_rejection_reason") or "low_confidence")
                    for item in group
                }
            )
        regions.append(region)
    return regions


def merge_recovery_words(
    primary_words: list[dict[str, Any]],
    recovery_words: list[dict[str, Any]],
    *,
    recovery_segments: list[dict[str, Any]],
    media_duration: float,
    min_word_probability: float = RECOVERY_MIN_WORD_PROBABILITY,
    min_region_probability: float = RECOVERY_MIN_REGION_PROBABILITY,
    consensus_min_probability: float | None = None,
    candidate_source_pass: str = "recovery",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fill primary transcript gaps with a conservative low-VAD second pass."""

    ordered_primary = sorted(
        (dict(item) for item in primary_words),
        key=lambda item: (float(item["start"]), float(item["end"])),
    )
    segment_quality = {
        int(item["id"]): item
        for item in recovery_segments
        if isinstance(item, dict) and item.get("id") is not None
    }
    tentative: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for raw_candidate in sorted(
        recovery_words,
        key=lambda item: (float(item["start"]), float(item["end"])),
    ):
        candidate = dict(raw_candidate)
        midpoint = (float(candidate["start"]) + float(candidate["end"])) / 2.0
        gap = _primary_gap_at(
            midpoint,
            ordered_primary,
            media_duration=media_duration,
        )
        if gap is None or _duplicates_nearby_primary(candidate, ordered_primary):
            continue
        candidate_start = float(candidate["start"])
        candidate_end = float(candidate["end"])
        if (
            candidate_start < gap[0] - RECOVERY_PRIMARY_COVERAGE_PADDING_SECONDS
            or candidate_end > gap[1] + RECOVERY_PRIMARY_COVERAGE_PADDING_SECONDS
        ):
            # A long recovery token can contain both an already-recognized
            # phrase and a missing phrase.  Its timestamp cannot be split
            # reliably, so never merge it into the word timeline.
            continue
        candidate["start"] = round(max(candidate_start, gap[0]), 3)
        candidate["end"] = round(min(candidate_end, gap[1]), 3)
        if float(candidate["end"]) - float(candidate["start"]) < 0.08:
            continue

        probability = candidate.get("probability")
        segment = segment_quality.get(int(candidate.get("segment_id") or 0), {})
        avg_logprob = float(segment.get("avg_logprob", 0.0) or 0.0)
        no_speech_prob = float(segment.get("no_speech_prob", 0.0) or 0.0)
        rejection_reason = ""
        if probability is not None and float(probability) < min_word_probability:
            rejection_reason = "low_word_probability"
        elif avg_logprob < -1.0:
            rejection_reason = "low_segment_probability"
        elif no_speech_prob > 0.6 and avg_logprob < -0.8:
            rejection_reason = "possible_silence_hallucination"

        candidate["recovery_gap_start"] = round(gap[0], 3)
        candidate["recovery_gap_end"] = round(gap[1], 3)
        if rejection_reason:
            candidate["recovery_rejection_reason"] = rejection_reason
            unresolved.append(candidate)
        else:
            candidate["source_pass"] = candidate_source_pass
            tentative.append(candidate)

    accepted: list[dict[str, Any]] = []
    for group in _partition_recovery_words(tentative):
        probabilities = [
            float(item["probability"])
            for item in group
            if item.get("probability") is not None
        ]
        average_probability = (
            sum(probabilities) / len(probabilities)
            if probabilities
            else 0.0
        )
        consensus_confirmed = any(bool(item.get("consensus_confirmed")) for item in group)
        consensus_probabilities = [
            float(item["consensus_probability"])
            for item in group
            if item.get("consensus_probability") is not None
        ]
        consensus_probability = (
            sum(consensus_probabilities) / len(consensus_probabilities)
            if consensus_probabilities
            else average_probability
        )
        consensus_accepted = bool(
            consensus_confirmed
            and consensus_min_probability is not None
            and consensus_probability >= consensus_min_probability
        )
        if average_probability >= min_region_probability or consensus_accepted:
            accepted.extend(group)
            continue
        for candidate in group:
            candidate["recovery_rejection_reason"] = "low_region_probability"
            unresolved.append(candidate)

    merged = [*ordered_primary, *accepted]
    merged.sort(
        key=lambda item: (
            float(item["start"]),
            float(item["end"]),
            0 if item.get("source_pass") == "primary" else 1,
        )
    )
    for index, word in enumerate(merged, start=1):
        word["index"] = index

    recovered_regions = _group_recovery_regions(accepted)
    unresolved_regions = _group_recovery_regions(unresolved, include_reason=True)
    summary = {
        "enabled": True,
        "primary_word_count": len(primary_words),
        "secondary_word_count": len(recovery_words),
        "recovered_word_count": len(accepted),
        "recovered_region_count": len(recovered_regions),
        "recovered_regions": recovered_regions,
        "suspected_missing_region_count": len(unresolved_regions),
        "suspected_missing_regions": unresolved_regions,
        "vad_parameters": dict(RECOVERY_VAD_PARAMETERS),
    }
    return merged, summary


def _review_region_id(region: dict[str, Any], index: int) -> str:
    existing = str(region.get("review_id") or "").strip()
    if existing:
        return existing
    start_ms = max(0, int(round(float(region.get("start") or 0.0) * 1000)))
    return f"gap-{index:03d}-{start_ms}"


def _with_review_region_ids(
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **dict(region),
            "review_id": _review_region_id(region, index),
        }
        for index, region in enumerate(regions, start=1)
    ]


def build_focused_recovery_windows(
    regions: list[dict[str, Any]],
    *,
    media_duration: float,
    padding_seconds: float = FOCUSED_RECOVERY_WINDOW_PADDING_SECONDS,
    post_padding_seconds: float = FOCUSED_RECOVERY_WINDOW_POST_PADDING_SECONDS,
) -> list[dict[str, Any]]:
    """Create a small number of padded windows around unresolved speech gaps."""

    targets = _with_review_region_ids(regions)
    windows: list[dict[str, Any]] = []
    for target in sorted(targets, key=lambda item: (float(item["start"]), float(item["end"]))):
        start = max(0.0, float(target["start"]) - padding_seconds)
        end = min(
            max(0.0, media_duration),
            float(target["end"]) + post_padding_seconds,
        )
        if end <= start:
            continue
        if windows and start <= float(windows[-1]["end"]):
            windows[-1]["end"] = max(float(windows[-1]["end"]), end)
            windows[-1]["targets"].append(target)
            continue
        windows.append(
            {
                "start": start,
                "end": end,
                "targets": [target],
            }
        )
    return windows


def normalize_focused_audio_window(
    audio: Any,
    *,
    target_rms: float = FOCUSED_RECOVERY_TARGET_RMS,
    max_gain: float = FOCUSED_RECOVERY_MAX_GAIN,
) -> Any:
    """Apply conservative DC removal and RMS gain to a short decoded window."""

    import numpy as np

    normalized = np.asarray(audio, dtype=np.float32).copy()
    if normalized.size == 0:
        return normalized
    normalized -= float(np.mean(normalized))
    rms = float(np.sqrt(np.mean(np.square(normalized), dtype=np.float64)))
    if not math.isfinite(rms) or rms <= 1e-6:
        return normalized
    gain = min(max(1.0, target_rms / rms), max(1.0, max_gain))
    return np.clip(normalized * gain, -0.98, 0.98).astype(np.float32, copy=False)


def _recovery_text_similarity(left: Any, right: Any) -> float:
    left_text = _normalized_word_text(left)
    right_text = _normalized_word_text(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    shorter, longer = sorted((left_text, right_text), key=len)
    if (
        len(shorter) >= 2
        and shorter in longer
        and len(shorter) / len(longer) >= 0.6
    ):
        return 1.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _focused_words_for_targets(
    words: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    assigned: dict[str, list[dict[str, Any]]] = {
        str(target["review_id"]): []
        for target in targets
    }
    target_by_id = {
        str(target["review_id"]): target
        for target in targets
    }
    for raw_word in words:
        midpoint = (float(raw_word["start"]) + float(raw_word["end"])) / 2.0
        candidates = [
            target
            for target in targets
            if (
                float(target["start"]) - FOCUSED_RECOVERY_TARGET_PADDING_SECONDS
                <= midpoint
                <= float(target["end"]) + FOCUSED_RECOVERY_TARGET_PADDING_SECONDS
            )
        ]
        if not candidates:
            continue
        target = min(
            candidates,
            key=lambda item: abs(
                midpoint - (float(item["start"]) + float(item["end"])) / 2.0
            ),
        )
        assigned[str(target["review_id"])].append(dict(raw_word))

    focused_words: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, Any]] = {}
    for review_id, group in assigned.items():
        target = target_by_id[review_id]
        ordered = sorted(group, key=lambda item: (float(item["start"]), float(item["end"])))
        text = "".join(str(item.get("text") or "") for item in ordered).strip()
        probabilities = [
            float(item["probability"])
            for item in ordered
            if item.get("probability") is not None
        ]
        average_probability = (
            sum(probabilities) / len(probabilities)
            if probabilities
            else 0.0
        )
        similarity = _recovery_text_similarity(target.get("text"), text)
        target_normalized = _normalized_word_text(target.get("text"))
        focused_normalized = _normalized_word_text(text)
        length_ratio = (
            min(len(target_normalized), len(focused_normalized))
            / max(len(target_normalized), len(focused_normalized))
            if target_normalized and focused_normalized
            else 0.0
        )
        consensus_confirmed = bool(
            text
            and similarity >= FOCUSED_RECOVERY_CONSENSUS_MIN_SIMILARITY
            and length_ratio >= 0.67
        )
        target_probability = target.get("average_probability")
        cross_pass_probability = (
            (
                float(target_probability)
                + average_probability
            )
            / 2.0
            if target_probability is not None and probabilities
            else average_probability
        )
        if (
            consensus_confirmed
            and cross_pass_probability >= FOCUSED_RECOVERY_CONSENSUS_MIN_PROBABILITY
            and ordered
        ):
            # The independent focused pass can assign a very wide timestamp to
            # a short word.  Once both passes agree on the text, the recovery
            # pass's narrow gap timestamp is the safer insertion boundary.
            target_start = float(target["start"])
            target_end = float(target["end"])
            focused_start = min(float(item["start"]) for item in ordered)
            focused_end = max(float(item["end"]) for item in ordered)
            focused_duration = focused_end - focused_start
            target_duration = target_end - target_start
            for word_index, word in enumerate(ordered):
                if focused_duration > 0.01:
                    relative_start = (
                        float(word["start"]) - focused_start
                    ) / focused_duration
                    relative_end = (
                        float(word["end"]) - focused_start
                    ) / focused_duration
                else:
                    relative_start = word_index / len(ordered)
                    relative_end = (word_index + 1) / len(ordered)
                word["start"] = round(
                    target_start + relative_start * target_duration,
                    3,
                )
                word["end"] = round(
                    target_start + relative_end * target_duration,
                    3,
                )
        evidence[review_id] = {
            "focused_text": text,
            "focused_average_probability": round(average_probability, 4),
            "cross_pass_probability": round(cross_pass_probability, 4),
            "consensus_similarity": round(similarity, 4),
            "consensus_length_ratio": round(length_ratio, 4),
            "consensus_confirmed": consensus_confirmed,
        }
        for word in ordered:
            word["review_target_id"] = review_id
            word["consensus_confirmed"] = consensus_confirmed
            word["consensus_probability"] = cross_pass_probability
            focused_words.append(word)
    return focused_words, evidence


def run_focused_recovery_pass(
    model: Any,
    audio: Any,
    regions: list[dict[str, Any]],
    *,
    media_duration: float,
    language: str | None,
    hotwords: str,
    segment_id_offset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Re-transcribe only unresolved gaps after local loudness normalization."""

    windows = build_focused_recovery_windows(
        regions,
        media_duration=media_duration,
    )
    serialized_segments: list[dict[str, Any]] = []
    serialized_words: list[dict[str, Any]] = []
    window_evidence: dict[str, dict[str, Any]] = {}
    next_segment_offset = segment_id_offset
    sampling_rate = 16000
    for window_index, window in enumerate(windows, start=1):
        start = float(window["start"])
        end = float(window["end"])
        start_sample = max(0, int(math.floor(start * sampling_rate)))
        end_sample = min(len(audio), int(math.ceil(end * sampling_rate)))
        normalized_audio = normalize_focused_audio_window(audio[start_sample:end_sample])
        if len(normalized_audio) < int(0.08 * sampling_rate):
            continue
        print(
            f"asr_v2_focused_window: {window_index}/{len(windows)} "
            f"{start:.2f}-{end:.2f}",
            flush=True,
        )
        segment_iter, _focused_info = model.transcribe(
            normalized_audio,
            language=language,
            vad_filter=False,
            word_timestamps=True,
            hallucination_silence_threshold=1.0,
            beam_size=5,
            condition_on_previous_text=False,
            hotwords=hotwords.strip() or None,
            initial_prompt=None,
            log_progress=False,
        )
        window_segments = list(segment_iter)
        current_segments, current_words = _serialize_segments(
            window_segments,
            source_pass="focused_recovery",
            segment_id_offset=next_segment_offset,
            time_offset=start,
        )
        serialized_segments.extend(current_segments)
        serialized_words.extend(current_words)
        window_text = "".join(
            str(item.get("text") or "")
            for item in current_words
        ).strip()
        speech_start = min(
            (float(item["start"]) for item in current_words),
            default=start,
        )
        speech_end = max(
            (float(item["end"]) for item in current_words),
            default=end,
        )
        for target in window["targets"]:
            window_evidence[str(target["review_id"])] = {
                "focused_window_start": round(start, 3),
                "focused_window_end": round(end, 3),
                "focused_context_text": window_text,
                "focused_speech_start": round(speech_start, 3),
                "focused_speech_end": round(speech_end, 3),
            }
        next_segment_offset = (
            max((int(item["id"]) for item in current_segments), default=next_segment_offset - 1)
            + 1
        )

    targets = [
        target
        for window in windows
        for target in window["targets"]
    ]
    focused_words, evidence = _focused_words_for_targets(serialized_words, targets)
    evidence = {
        review_id: {
            **window_evidence.get(review_id, {}),
            **evidence.get(review_id, {}),
        }
        for review_id in {
            *window_evidence,
            *evidence,
        }
    }
    return serialized_segments, focused_words, evidence


def merge_focused_recovery_summary(
    recovery_summary: dict[str, Any],
    focused_summary: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summary = dict(recovery_summary)
    original_suspected = _with_review_region_ids(
        list(summary.get("suspected_missing_regions") or [])
    )
    focused_recovered_regions = list(focused_summary.get("recovered_regions") or [])
    resolved_ids = {
        str(review_id)
        for region in focused_recovered_regions
        for review_id in region.get("review_target_ids") or []
    }
    remaining: list[dict[str, Any]] = []
    for region in original_suspected:
        review_id = str(region["review_id"])
        if review_id in resolved_ids:
            continue
        remaining.append(
            {
                **region,
                **evidence.get(review_id, {}),
            }
        )

    second_pass_word_count = int(summary.get("recovered_word_count") or 0)
    second_pass_region_count = int(summary.get("recovered_region_count") or 0)
    focused_word_count = int(focused_summary.get("recovered_word_count") or 0)
    focused_region_count = int(focused_summary.get("recovered_region_count") or 0)
    summary.update(
        {
            "second_pass_recovered_word_count": second_pass_word_count,
            "second_pass_recovered_region_count": second_pass_region_count,
            "focused_recovered_word_count": focused_word_count,
            "focused_recovered_region_count": focused_region_count,
            "focused_reviewed_region_count": len(original_suspected),
            "recovered_word_count": second_pass_word_count + focused_word_count,
            "recovered_region_count": second_pass_region_count + focused_region_count,
            "recovered_regions": [
                *list(summary.get("recovered_regions") or []),
                *focused_recovered_regions,
            ],
            "suspected_missing_region_count": len(remaining),
            "suspected_missing_regions": remaining,
            "focused_recovery": {
                "enabled": True,
                "candidate_word_count": int(focused_summary.get("secondary_word_count") or 0),
                "recovered_word_count": focused_word_count,
                "recovered_region_count": focused_region_count,
            },
        }
    )
    return summary


def _quality_report(
    segments: list[dict[str, Any]],
    words: list[dict[str, Any]],
    *,
    info: dict[str, Any],
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    low_words = [
        item
        for item in words
        if item.get("probability") is not None and float(item["probability"]) < 0.55
    ]
    suspicious_segments: list[dict[str, Any]] = []
    for segment in segments:
        reasons: list[str] = []
        if segment["avg_logprob"] < -1.0:
            reasons.append("low_log_probability")
        if segment["compression_ratio"] > 2.4:
            reasons.append("high_compression_ratio")
        if segment["no_speech_prob"] > 0.6 and segment["avg_logprob"] < -1.0:
            reasons.append("possible_silence_hallucination")
        if reasons:
            suspicious_segments.append({"id": segment["id"], "reasons": reasons})
    return {
        "version": ASR_V2_VERSION,
        "language": info.get("language"),
        "language_probability": info.get("language_probability"),
        "duration": info.get("duration"),
        "duration_after_vad": info.get("duration_after_vad"),
        "word_summary": {
            "word_count": len(words),
            "low_confidence_word_count": len(low_words),
            "low_confidence_word_indexes": [item["index"] for item in low_words],
        },
        "segment_summary": {
            "segment_count": len(segments),
            "suspicious_segment_count": len(suspicious_segments),
            "suspicious_segments": suspicious_segments,
        },
        "recovery": recovery or {
            "enabled": False,
            "primary_word_count": len(words),
            "secondary_word_count": 0,
            "recovered_word_count": 0,
            "recovered_region_count": 0,
            "recovered_regions": [],
            "suspected_missing_region_count": 0,
            "suspected_missing_regions": [],
        },
    }


def transcribe_audio_v2(
    input_media: Path,
    output_dir: Path,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    hotwords: str = "",
    initial_prompt: str = "",
    recovery_enabled: bool = True,
) -> dict[str, Path]:
    input_media = input_media.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_media.is_file():
        raise FileNotFoundError(f"媒体文件不存在: {input_media}")
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_model_cache()
    ensure_cuda_library_path_ready(device)

    try:
        from faster_whisper import WhisperModel
        from huggingface_hub.errors import LocalEntryNotFoundError
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper，请先在环境中安装：pip install faster-whisper") from exc

    try:
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )
        print(f"asr_v2_model_source: local cache ({model_size})", flush=True)
    except LocalEntryNotFoundError:
        print(
            f"asr_v2_model_source: {model_size} is not cached; downloading from Hugging Face",
            flush=True,
        )
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    common_transcribe_options = {
        "language": normalize_language(language),
        "word_timestamps": True,
        "hallucination_silence_threshold": 2.0,
        "beam_size": 5,
        "hotwords": hotwords.strip() or None,
        "initial_prompt": initial_prompt.strip() or None,
        "log_progress": True,
    }
    segment_iter, raw_info = model.transcribe(
        str(input_media),
        vad_filter=True,
        vad_parameters=DEFAULT_VAD_PARAMETERS,
        condition_on_previous_text=True,
        **common_transcribe_options,
    )
    segments = list(segment_iter)
    serialized_segments, primary_words = _serialize_segments(
        segments,
        source_pass="primary",
    )
    info = {
        "language": str(getattr(raw_info, "language", "") or "unknown"),
        "language_probability": float(getattr(raw_info, "language_probability", 0.0) or 0.0),
        "duration": float(getattr(raw_info, "duration", 0.0) or 0.0),
        "duration_after_vad": float(getattr(raw_info, "duration_after_vad", 0.0) or 0.0),
        "model_size": model_size,
        "device": device,
        "compute_type": compute_type,
        "vad_parameters": DEFAULT_VAD_PARAMETERS,
        "hotwords_enabled": bool(hotwords.strip()),
        "initial_prompt_enabled": bool(initial_prompt.strip()),
        "recovery_enabled": bool(recovery_enabled),
        "focused_recovery_enabled": bool(recovery_enabled),
    }

    recovery_segments: list[Any] = []
    serialized_recovery_segments: list[dict[str, Any]] = []
    recovery_words: list[dict[str, Any]] = []
    serialized_focused_segments: list[dict[str, Any]] = []
    focused_words: list[dict[str, Any]] = []
    focused_evidence: dict[str, dict[str, Any]] = {}
    recovery_summary: dict[str, Any] | None = None
    if recovery_enabled:
        print("asr_v2_recovery: starting low-VAD independent second pass", flush=True)
        recovery_iter, recovery_info = model.transcribe(
            str(input_media),
            vad_filter=True,
            vad_parameters=RECOVERY_VAD_PARAMETERS,
            condition_on_previous_text=False,
            **common_transcribe_options,
        )
        recovery_segments = list(recovery_iter)
        segment_offset = (
            max((int(item["id"]) for item in serialized_segments), default=-1) + 1
        )
        serialized_recovery_segments, recovery_words = _serialize_segments(
            recovery_segments,
            source_pass="recovery",
            segment_id_offset=segment_offset,
        )
        words, recovery_summary = merge_recovery_words(
            primary_words,
            recovery_words,
            recovery_segments=serialized_recovery_segments,
            media_duration=float(info["duration"]),
        )
        info["recovery_duration_after_vad"] = float(
            getattr(recovery_info, "duration_after_vad", 0.0) or 0.0
        )
        print(
            "asr_v2_recovery_done: "
            f"recovered_words={recovery_summary['recovered_word_count']} "
            f"regions={recovery_summary['recovered_region_count']} "
            f"suspected_missing={recovery_summary['suspected_missing_region_count']}",
            flush=True,
        )
        unresolved_regions = list(
            recovery_summary.get("suspected_missing_regions") or []
        )
        if unresolved_regions:
            print(
                "asr_v2_focused_recovery: decoding audio for "
                f"{len(unresolved_regions)} unresolved regions",
                flush=True,
            )
            from faster_whisper.audio import decode_audio

            decoded_audio = decode_audio(str(input_media), sampling_rate=16000)
            focused_segment_offset = (
                max(
                    (
                        int(item["id"])
                        for item in [
                            *serialized_segments,
                            *serialized_recovery_segments,
                        ]
                    ),
                    default=-1,
                )
                + 1
            )
            (
                serialized_focused_segments,
                focused_words,
                focused_evidence,
            ) = run_focused_recovery_pass(
                model,
                decoded_audio,
                unresolved_regions,
                media_duration=float(info["duration"]),
                language=normalize_language(language),
                hotwords=hotwords,
                segment_id_offset=focused_segment_offset,
            )
            words, focused_summary = merge_recovery_words(
                words,
                focused_words,
                recovery_segments=serialized_focused_segments,
                media_duration=float(info["duration"]),
                min_word_probability=FOCUSED_RECOVERY_MIN_WORD_PROBABILITY,
                min_region_probability=FOCUSED_RECOVERY_MIN_REGION_PROBABILITY,
                consensus_min_probability=FOCUSED_RECOVERY_CONSENSUS_MIN_PROBABILITY,
                candidate_source_pass="focused_recovery",
            )
            recovery_summary = merge_focused_recovery_summary(
                recovery_summary,
                focused_summary,
                focused_evidence,
            )
            print(
                "asr_v2_focused_recovery_done: "
                f"recovered_words={recovery_summary['focused_recovered_word_count']} "
                f"regions={recovery_summary['focused_recovered_region_count']} "
                f"remaining={recovery_summary['suspected_missing_region_count']}",
                flush=True,
            )
    else:
        words = [dict(item) for item in primary_words]

    raw_srt = output_dir / "source.raw.srt"
    recovery_raw_srt = output_dir / "source.recovery.raw.srt"
    words_path = output_dir / "words.json"
    recovery_words_path = output_dir / "words.recovery.json"
    focused_words_path = output_dir / "words.focused.json"
    segments_path = output_dir / "segments.json"
    recovery_segments_path = output_dir / "segments.recovery.json"
    focused_segments_path = output_dir / "segments.focused.json"
    quality_path = output_dir / "quality.json"
    write_segments_as_srt(segments, raw_srt)
    if recovery_enabled:
        write_segments_as_srt(recovery_segments, recovery_raw_srt)
    words_path.write_text(
        json.dumps(
            {"version": ASR_V2_VERSION, "info": info, "words": words},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    segments_path.write_text(
        json.dumps(
            {"version": ASR_V2_VERSION, "info": info, "segments": serialized_segments},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if recovery_enabled:
        recovery_words_path.write_text(
            json.dumps(
                {
                    "version": ASR_V2_VERSION,
                    "info": info,
                    "words": recovery_words,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        recovery_segments_path.write_text(
            json.dumps(
                {
                    "version": ASR_V2_VERSION,
                    "info": info,
                    "segments": serialized_recovery_segments,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        focused_words_path.write_text(
            json.dumps(
                {
                    "version": ASR_V2_VERSION,
                    "info": info,
                    "evidence": focused_evidence,
                    "words": focused_words,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        focused_segments_path.write_text(
            json.dumps(
                {
                    "version": ASR_V2_VERSION,
                    "info": info,
                    "segments": serialized_focused_segments,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    quality_path.write_text(
        json.dumps(
            _quality_report(
                serialized_segments,
                words,
                info=info,
                recovery=recovery_summary,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"detected_language: {info['language']}", flush=True)
    print(f"asr_v2_words: {words_path}", flush=True)
    print(f"asr_v2_segments: {segments_path}", flush=True)
    if recovery_enabled:
        print(f"asr_v2_recovery_segments: {recovery_segments_path}", flush=True)
        print(f"asr_v2_focused_segments: {focused_segments_path}", flush=True)
    print(f"asr_v2_quality: {quality_path}", flush=True)
    result = {
        "raw_srt": raw_srt,
        "words_path": words_path,
        "segments_path": segments_path,
        "quality_path": quality_path,
    }
    if recovery_enabled:
        result.update(
            {
                "recovery_raw_srt": recovery_raw_srt,
                "recovery_words_path": recovery_words_path,
                "recovery_segments_path": recovery_segments_path,
                "focused_words_path": focused_words_path,
                "focused_segments_path": focused_segments_path,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="ASR 2.2 high-recall word-level transcription pipeline.")
    parser.add_argument("input_media", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--compute-type", default=DEFAULT_COMPUTE_TYPE)
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--initial-prompt", default="")
    parser.add_argument(
        "--no-recovery",
        action="store_true",
        help="Disable the low-VAD independent recovery pass.",
    )
    args = parser.parse_args()
    transcribe_audio_v2(
        args.input_media,
        args.output_dir,
        model_size=args.model_size,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        hotwords=args.hotwords,
        initial_prompt=args.initial_prompt,
        recovery_enabled=not args.no_recovery,
    )


if __name__ == "__main__":
    main()
