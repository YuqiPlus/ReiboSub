from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import write_srt
from video_translate.tools.diarize_speakers import SpeakerTurn, UNKNOWN_SPEAKER


ASR_V2_VERSION = "2.2"
SENTENCE_END_RE = re.compile(r"[.!?。！？…][\"'”’）)\]}】》」』]*$")
SENTENCE_BOUNDARY_RE = re.compile(r"[.!?。！？…]+[\"'”’）)\]}】》」』]*")
MIN_CUE_DISPLAY_SECONDS = 0.8
CUE_BOUNDARY_GAP_SECONDS = 0.05
ASR_REVIEW_BEFORE_CONTEXT_SECONDS = 2.5
ASR_REVIEW_AFTER_CONTEXT_SECONDS = 4.0
ASR_REVIEW_EDGE_PADDING_SECONDS = 0.35
ASR_REVIEW_FALLBACK_PRE_ROLL_SECONDS = 1.8
ASR_REVIEW_FALLBACK_POST_ROLL_SECONDS = 1.8
ASR_REVIEW_MAX_PRE_ROLL_SECONDS = 5.0
ASR_REVIEW_MAX_POST_ROLL_SECONDS = 5.0
DUPLICATE_CUE_MAX_GAP_SECONDS = 0.12
DUPLICATE_CUE_SHORT_SECONDS = 0.25
MICRO_CUE_MAX_DURATION_SECONDS = 0.4
MICRO_CUE_MAX_GAP_SECONDS = 0.12
MICRO_CUE_MERGED_MAX_DURATION_SECONDS = 1.5
MICRO_CUE_MERGED_MAX_CHARACTERS = 14
SEGMENT_BOUNDARY_MIN_DURATION_SECONDS = 2.2
SEGMENT_BOUNDARY_MIN_CHARACTERS = 18
HARD_SILENCE_GAP_SECONDS = 0.75
SOFT_SILENCE_MIN_DURATION_SECONDS = 1.0
SOFT_SILENCE_MIN_CHARACTERS = 8


@dataclass(frozen=True, slots=True)
class AsrWord:
    index: int
    start: float
    end: float
    text: str
    probability: float | None
    segment_id: int
    speaker: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, fallback_index: int) -> "AsrWord":
        probability = value.get("probability")
        return cls(
            index=int(value.get("index", fallback_index)),
            start=float(value["start"]),
            end=float(value["end"]),
            text=str(value.get("text") or value.get("word") or ""),
            probability=float(probability) if probability is not None else None,
            segment_id=int(value.get("segment_id", 0)),
            speaker=str(value.get("speaker") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "probability": round(self.probability, 4) if self.probability is not None else None,
            "segment_id": self.segment_id,
            "speaker": self.speaker,
        }


@dataclass(frozen=True, slots=True)
class AsrV2Cue:
    index: int
    start: float
    end: float
    text: str
    speaker: str
    word_indexes: tuple[int, ...]
    average_probability: float | None
    minimum_probability: float | None
    low_confidence: bool

    def subtitle_text(self, *, include_speaker: bool) -> str:
        if include_speaker and self.speaker:
            return f"{self.speaker}: {self.text}"
        return self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "speaker": self.speaker,
            "word_indexes": list(self.word_indexes),
            "average_probability": (
                round(self.average_probability, 4) if self.average_probability is not None else None
            ),
            "minimum_probability": (
                round(self.minimum_probability, 4) if self.minimum_probability is not None else None
            ),
            "low_confidence": self.low_confidence,
        }


def read_words_json(path: Path) -> tuple[dict[str, Any], list[AsrWord]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
        raise ValueError("ASR 2.x words.json 缺少 words 数组")
    words = [
        AsrWord.from_dict(item, fallback_index=index)
        for index, item in enumerate(payload["words"], start=1)
        if isinstance(item, dict)
    ]
    return payload, words


def _speaker_for_word(word: AsrWord, turns: list[SpeakerTurn], *, max_nearest_gap: float = 0.45) -> str:
    overlap_by_speaker: dict[str, float] = {}
    first_start: dict[str, float] = {}
    for turn in turns:
        overlap = max(0.0, min(word.end, turn.end) - max(word.start, turn.start))
        if overlap <= 0:
            continue
        overlap_by_speaker[turn.speaker] = overlap_by_speaker.get(turn.speaker, 0.0) + overlap
        first_start.setdefault(turn.speaker, turn.start)
    if overlap_by_speaker:
        return max(
            overlap_by_speaker,
            key=lambda speaker: (overlap_by_speaker[speaker], -first_start[speaker]),
        )

    nearest: tuple[float, float, str] | None = None
    for turn in turns:
        if turn.end < word.start:
            gap = word.start - turn.end
        elif turn.start > word.end:
            gap = turn.start - word.end
        else:
            gap = 0.0
        candidate = (gap, turn.start, turn.speaker)
        if nearest is None or candidate < nearest:
            nearest = candidate
    return nearest[2] if nearest and nearest[0] <= max_nearest_gap else UNKNOWN_SPEAKER


def assign_speakers_to_words(words: list[AsrWord], turns: list[SpeakerTurn]) -> list[AsrWord]:
    if not turns:
        return words
    return [replace(word, speaker=_speaker_for_word(word, turns)) for word in words]


def _joined_text(words: list[AsrWord]) -> str:
    return "".join(word.text for word in words).strip()


def _split_word_at_sentence_boundaries(word: AsrWord) -> list[AsrWord]:
    """Split a timestamped token that contains more than one spoken sentence."""

    text = word.text
    boundaries = [
        match.end()
        for match in SENTENCE_BOUNDARY_RE.finditer(text)
        if text[match.end() :].strip()
    ]
    if not boundaries:
        return [word]

    pieces: list[str] = []
    offset = 0
    for boundary in boundaries:
        piece = text[offset:boundary]
        if piece:
            pieces.append(piece)
        offset = boundary
    if text[offset:]:
        pieces.append(text[offset:])
    if len(pieces) <= 1:
        return [word]

    weights = [max(1, len(re.sub(r"\s+", "", piece))) for piece in pieces]
    total_weight = sum(weights)
    duration = max(0.01, word.end - word.start)
    expanded: list[AsrWord] = []
    elapsed_weight = 0
    for position, (piece, weight) in enumerate(zip(pieces, weights, strict=True)):
        piece_start = word.start + duration * (elapsed_weight / total_weight)
        elapsed_weight += weight
        piece_end = (
            word.end
            if position == len(pieces) - 1
            else word.start + duration * (elapsed_weight / total_weight)
        )
        expanded.append(
            replace(
                word,
                start=piece_start,
                end=max(piece_start + 0.01, piece_end),
                text=piece,
            )
        )
    return expanded


def _expand_sentence_words(words: list[AsrWord]) -> list[AsrWord]:
    return [
        piece
        for word in words
        for piece in _split_word_at_sentence_boundaries(word)
    ]


def _speaker_changed(current: list[AsrWord], word: AsrWord) -> bool:
    current_speaker = current[-1].speaker if current else ""
    return bool(
        current
        and current_speaker
        and word.speaker
        and current_speaker != word.speaker
    )


def _should_break_before(
    current: list[AsrWord],
    word: AsrWord,
    *,
    max_duration: float,
    max_characters: int,
    silence_gap: float,
) -> bool:
    if not current:
        return False
    if _speaker_changed(current, word):
        return True
    gap = word.start - current[-1].end
    if gap >= silence_gap:
        current_text = _joined_text(current)
        current_duration = current[-1].end - current[0].start
        if (
            gap >= HARD_SILENCE_GAP_SECONDS
            or current_duration >= SOFT_SILENCE_MIN_DURATION_SECONDS
            or len(current_text) >= SOFT_SILENCE_MIN_CHARACTERS
            or SENTENCE_END_RE.search(current_text)
        ):
            return True
    if current[-1].segment_id != word.segment_id:
        current_duration = current[-1].end - current[0].start
        if (
            (gap >= 0.3 and current_duration >= 0.8)
            or current_duration >= SEGMENT_BOUNDARY_MIN_DURATION_SECONDS
            or len(_joined_text(current)) >= SEGMENT_BOUNDARY_MIN_CHARACTERS
            or SENTENCE_END_RE.search(_joined_text(current))
        ):
            return True
    if word.end - current[0].start > max_duration:
        return True
    proposed = _joined_text([*current, word])
    return len(proposed) > max_characters and len(_joined_text(current)) >= max(8, max_characters // 3)


def _cue_from_words(index: int, words: list[AsrWord]) -> AsrV2Cue:
    probabilities = [word.probability for word in words if word.probability is not None]
    average = sum(probabilities) / len(probabilities) if probabilities else None
    minimum = min(probabilities) if probabilities else None
    speaker = next((word.speaker for word in words if word.speaker), "")
    low_confidence = bool(
        average is not None
        and minimum is not None
        and (average < 0.68 or minimum < 0.35)
    )
    return AsrV2Cue(
        index=index,
        start=max(0.0, words[0].start),
        end=max(words[0].start + 0.01, words[-1].end),
        text=_joined_text(words),
        speaker=speaker,
        word_indexes=tuple(word.index for word in words),
        average_probability=average,
        minimum_probability=minimum,
        low_confidence=low_confidence,
    )


def _normalized_cue_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _weighted_average_probability(left: AsrV2Cue, right: AsrV2Cue) -> float | None:
    values = [
        (cue.average_probability, max(1, len(cue.word_indexes)))
        for cue in (left, right)
        if cue.average_probability is not None
    ]
    if not values:
        return None
    total_weight = sum(weight for _value, weight in values)
    return sum(float(value) * weight for value, weight in values) / total_weight


def _merge_duplicate_flash_cues(cues: list[AsrV2Cue]) -> list[AsrV2Cue]:
    merged: list[AsrV2Cue] = []
    for cue in cues:
        if not merged:
            merged.append(cue)
            continue
        previous = merged[-1]
        previous_duration = previous.end - previous.start
        cue_duration = cue.end - cue.start
        same_speaker = (
            not previous.speaker
            or not cue.speaker
            or previous.speaker == cue.speaker
        )
        is_duplicate_flash = bool(
            same_speaker
            and _normalized_cue_text(previous.text) == _normalized_cue_text(cue.text)
            and cue.start - previous.end <= DUPLICATE_CUE_MAX_GAP_SECONDS
            and min(previous_duration, cue_duration) <= DUPLICATE_CUE_SHORT_SECONDS
        )
        if not is_duplicate_flash:
            merged.append(cue)
            continue
        minimum_probabilities = [
            value
            for value in (previous.minimum_probability, cue.minimum_probability)
            if value is not None
        ]
        merged[-1] = replace(
            previous,
            end=max(previous.end, cue.end),
            word_indexes=tuple(dict.fromkeys((*previous.word_indexes, *cue.word_indexes))),
            average_probability=_weighted_average_probability(previous, cue),
            minimum_probability=min(minimum_probabilities) if minimum_probabilities else None,
            low_confidence=previous.low_confidence or cue.low_confidence,
        )
    return merged


def _merge_micro_cues(cues: list[AsrV2Cue]) -> list[AsrV2Cue]:
    merged: list[AsrV2Cue] = []
    for cue in cues:
        if not merged:
            merged.append(cue)
            continue
        previous = merged[-1]
        previous_duration = previous.end - previous.start
        cue_duration = cue.end - cue.start
        same_speaker = (
            not previous.speaker
            or not cue.speaker
            or previous.speaker == cue.speaker
        )
        combined_text = f"{previous.text.rstrip()} {cue.text.lstrip()}".strip()
        should_merge = bool(
            same_speaker
            and min(previous_duration, cue_duration) < MICRO_CUE_MAX_DURATION_SECONDS
            and cue.start - previous.end <= MICRO_CUE_MAX_GAP_SECONDS
            and cue.end - previous.start <= MICRO_CUE_MERGED_MAX_DURATION_SECONDS
            and len(combined_text) <= MICRO_CUE_MERGED_MAX_CHARACTERS
        )
        if not should_merge:
            merged.append(cue)
            continue
        minimum_probabilities = [
            value
            for value in (previous.minimum_probability, cue.minimum_probability)
            if value is not None
        ]
        merged[-1] = replace(
            previous,
            end=max(previous.end, cue.end),
            text=combined_text,
            word_indexes=tuple(dict.fromkeys((*previous.word_indexes, *cue.word_indexes))),
            average_probability=_weighted_average_probability(previous, cue),
            minimum_probability=min(minimum_probabilities) if minimum_probabilities else None,
            low_confidence=previous.low_confidence or cue.low_confidence,
        )
    return merged


def stabilize_cue_timeline(
    cues: list[AsrV2Cue],
    *,
    min_display_seconds: float = MIN_CUE_DISPLAY_SECONDS,
    boundary_gap_seconds: float = CUE_BOUNDARY_GAP_SECONDS,
) -> list[AsrV2Cue]:
    """Remove timestamp flashes and give short cues a readable display window."""

    deduplicated = _merge_micro_cues(_merge_duplicate_flash_cues(cues))
    stabilized: list[AsrV2Cue] = []
    for position, cue in enumerate(deduplicated):
        start = cue.start
        end = cue.end
        if end - start < min_display_seconds:
            next_start = (
                deduplicated[position + 1].start
                if position + 1 < len(deduplicated)
                else float("inf")
            )
            latest_end = max(end, next_start - boundary_gap_seconds)
            end = max(end, min(start + min_display_seconds, latest_end))
            if end - start < min_display_seconds:
                previous_end = stabilized[-1].end if stabilized else 0.0
                earliest_start = max(
                    previous_end + boundary_gap_seconds,
                    end - min_display_seconds,
                )
                start = min(start, earliest_start)
        stabilized.append(
            replace(
                cue,
                index=len(stabilized) + 1,
                start=max(0.0, start),
                end=max(start + 0.01, end),
            )
        )
    return stabilized


def build_asr_v2_cues(
    words: list[AsrWord],
    *,
    max_duration: float = 4.5,
    max_characters: int = 30,
    silence_gap: float = 0.45,
    min_sentence_duration: float = 0.45,
) -> list[AsrV2Cue]:
    ordered = sorted(
        (
            word
            for word in _expand_sentence_words(words)
            if word.text.strip() and word.end > word.start
        ),
        key=lambda word: (word.start, word.end, word.index),
    )
    cues: list[AsrV2Cue] = []
    current: list[AsrWord] = []

    def flush() -> None:
        if not current:
            return
        cue = _cue_from_words(len(cues) + 1, list(current))
        if cue.text:
            cues.append(cue)
        current.clear()

    for word in ordered:
        if _should_break_before(
            current,
            word,
            max_duration=max_duration,
            max_characters=max_characters,
            silence_gap=silence_gap,
        ):
            flush()
        current.append(word)
        duration = current[-1].end - current[0].start
        if duration >= min_sentence_duration and SENTENCE_END_RE.search(_joined_text(current)):
            flush()
    flush()
    return stabilize_cue_timeline(cues)


def enrich_asr_review_regions(
    regions: list[dict[str, Any]],
    words: list[AsrWord],
    *,
    media_duration: float = 0.0,
) -> list[dict[str, Any]]:
    """Add speech context and a wider playback range without widening insertion."""

    ordered_words = sorted(
        (word for word in words if word.text.strip() and word.end > word.start),
        key=lambda word: (word.start, word.end, word.index),
    )
    enriched: list[dict[str, Any]] = []
    for raw_region in regions:
        region = dict(raw_region)
        start = max(0.0, float(region.get("start") or 0.0))
        end = max(start + 0.01, float(region.get("end") or start + 0.01))
        before = [
            word
            for word in ordered_words
            if (
                start - ASR_REVIEW_BEFORE_CONTEXT_SECONDS
                <= word.end
                <= start + 0.05
            )
        ][-8:]
        after = [
            word
            for word in ordered_words
            if (
                end - 0.05
                <= word.start
                <= end + ASR_REVIEW_AFTER_CONTEXT_SECONDS
            )
        ][:12]

        preceding_is_close = bool(
            before and start - before[-1].end <= 0.9
        )
        review_start = (
            before[0].start - ASR_REVIEW_EDGE_PADDING_SECONDS
            if preceding_is_close
            else start - ASR_REVIEW_FALLBACK_PRE_ROLL_SECONDS
        )
        review_end = end + ASR_REVIEW_FALLBACK_POST_ROLL_SECONDS
        if after and after[0].start - end <= 1.1:
            review_end = max(
                review_end,
                after[-1].end + ASR_REVIEW_EDGE_PADDING_SECONDS,
            )
        focused_speech_start = region.get("focused_speech_start")
        if focused_speech_start is not None:
            review_start = min(
                review_start,
                float(focused_speech_start) - ASR_REVIEW_EDGE_PADDING_SECONDS,
            )
        focused_speech_end = region.get("focused_speech_end")
        if focused_speech_end is not None:
            review_end = max(
                review_end,
                float(focused_speech_end) + ASR_REVIEW_EDGE_PADDING_SECONDS,
            )
        review_start = max(
            0.0,
            start - ASR_REVIEW_MAX_PRE_ROLL_SECONDS,
            review_start,
        )
        review_end = min(
            end + ASR_REVIEW_MAX_POST_ROLL_SECONDS,
            review_end,
        )
        review_end = max(review_start + 0.5, review_end)
        if media_duration > 0:
            review_end = min(media_duration, review_end)

        region.update(
            {
                "candidate_start": round(start, 3),
                "candidate_end": round(end, 3),
                "review_start": round(review_start, 3),
                "review_end": round(review_end, 3),
                "context_before": _joined_text(before).strip(),
                "context_after": _joined_text(after).strip(),
            }
        )
        enriched.append(region)
    return enriched


def write_asr_v2_outputs(
    output_dir: Path,
    words: list[AsrWord],
    *,
    turns: list[SpeakerTurn] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    include_speaker = bool(turns)
    aligned_words = assign_speakers_to_words(words, turns or [])
    cues = build_asr_v2_cues(aligned_words)
    source_srt = output_dir / "source.asr2.srt"
    cues_path = output_dir / "cues.asr2.json"
    transcript_path = output_dir / "transcript.txt"
    plain_text_path = output_dir / "transcript.plain.txt"

    write_srt(
        [
            SubtitleCue(
                index=cue.index,
                start=cue.start,
                end=cue.end,
                text=cue.subtitle_text(include_speaker=include_speaker),
            )
            for cue in cues
        ],
        source_srt,
    )
    cues_path.write_text(
        json.dumps(
            {
                "version": ASR_V2_VERSION,
                "speaker_aligned": include_speaker,
                "cues": [cue.to_dict() for cue in cues],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    transcript_text = "\n".join(
        cue.subtitle_text(include_speaker=include_speaker) for cue in cues
    )
    plain_transcript_text = "\n".join(cue.text for cue in cues)
    if transcript_text:
        transcript_text += "\n"
    if plain_transcript_text:
        plain_transcript_text += "\n"
    transcript_path.write_text(transcript_text, encoding="utf-8")
    plain_text_path.write_text(plain_transcript_text, encoding="utf-8")
    return {
        "source_srt": source_srt,
        "cues_path": cues_path,
        "text_path": transcript_path,
        "plain_text_path": plain_text_path,
        "transcript_text": transcript_text,
        "plain_transcript_text": plain_transcript_text,
        "cue_count": len(cues),
        "low_confidence_cue_count": sum(1 for cue in cues if cue.low_confidence),
        "words": aligned_words,
        "cues": cues,
    }


def merge_cue_quality_report(
    quality_path: Path,
    *,
    cues: list[AsrV2Cue],
) -> dict[str, Any]:
    try:
        payload = json.loads(quality_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["cue_summary"] = {
        "cue_count": len(cues),
        "low_confidence_cue_count": sum(1 for cue in cues if cue.low_confidence),
        "low_confidence_cue_indexes": [cue.index for cue in cues if cue.low_confidence],
    }
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload
