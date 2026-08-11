from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from video_translate.asr_v2 import (
    ASR_V2_VERSION,
    AsrWord,
    assign_speakers_to_words,
    build_asr_v2_cues,
    enrich_asr_review_regions,
    merge_cue_quality_report,
    write_asr_v2_outputs,
)
from video_translate.subtitle.srt import read_srt
from video_translate.tools.diarize_speakers import SpeakerTurn
from video_translate.tools.transcribe_audio_v2 import (
    _focused_words_for_targets,
    _recovery_text_similarity,
    build_focused_recovery_windows,
    merge_recovery_words,
    normalize_focused_audio_window,
    run_focused_recovery_pass,
    transcribe_audio_v2,
)


def _word(
    index: int,
    start: float,
    end: float,
    text: str,
    *,
    probability: float = 0.9,
    segment_id: int = 0,
    speaker: str = "",
) -> AsrWord:
    return AsrWord(
        index=index,
        start=start,
        end=end,
        text=text,
        probability=probability,
        segment_id=segment_id,
        speaker=speaker,
    )


def test_word_level_speaker_alignment_splits_at_speaker_change() -> None:
    words = [
        _word(1, 0.0, 0.4, " Hello"),
        _word(2, 0.4, 0.8, " there."),
        _word(3, 0.9, 1.2, " Hi"),
        _word(4, 1.2, 1.6, " back."),
    ]
    turns = [
        SpeakerTurn(0.0, 0.85, "Speaker 1"),
        SpeakerTurn(0.85, 1.8, "Speaker 2"),
    ]

    aligned = assign_speakers_to_words(words, turns)
    cues = build_asr_v2_cues(aligned)

    assert [cue.speaker for cue in cues] == ["Speaker 1", "Speaker 2"]
    assert [cue.text for cue in cues] == ["Hello there.", "Hi back."]


def test_smart_segmentation_uses_silence_and_max_duration() -> None:
    words = [
        _word(1, 0.0, 0.5, "첫"),
        _word(2, 0.5, 1.0, " 문장"),
        _word(3, 2.0, 2.5, "다음"),
        _word(4, 2.5, 8.5, " 문장"),
    ]

    cues = build_asr_v2_cues(words, max_duration=6.0, silence_gap=0.75)

    assert [cue.text for cue in cues] == ["첫 문장", "다음", "문장"]


def test_smart_segmentation_splits_internal_sentence_punctuation() -> None:
    words = [
        _word(1, 0.0, 1.0, " 그러니까. 아"),
        _word(2, 1.0, 1.5, " 맞아"),
    ]

    cues = build_asr_v2_cues(words, min_sentence_duration=0.1)

    assert [cue.text for cue in cues] == ["그러니까.", "아 맞아"]
    assert cues[0].end <= cues[1].start


def test_smart_segmentation_respects_meaningful_whisper_segment_boundaries() -> None:
    words = [
        _word(1, 0.0, 2.3, "첫 번째 문장입니다", segment_id=1),
        _word(2, 2.35, 2.9, "두 번째", segment_id=2),
    ]

    cues = build_asr_v2_cues(words)

    assert [cue.text for cue in cues] == ["첫 번째 문장입니다", "두 번째"]


def test_short_cues_get_readable_timing_without_overlap() -> None:
    words = [
        _word(1, 0.0, 0.1, "네."),
        _word(2, 1.0, 1.2, "다음"),
        _word(3, 1.2, 2.0, " 문장."),
    ]

    cues = build_asr_v2_cues(words)

    assert [cue.text for cue in cues] == ["네.", "다음 문장."]
    assert cues[0].end - cues[0].start == 0.8
    assert cues[0].end < cues[1].start


def test_duplicate_timestamp_flash_is_removed() -> None:
    words = [
        _word(1, 0.0, 1.0, "반복 문장."),
        _word(2, 1.04, 1.08, "반복 문장."),
    ]

    cues = build_asr_v2_cues(words)

    assert [cue.text for cue in cues] == ["반복 문장."]
    assert cues[0].start == 0.0
    assert cues[0].end == 1.08
    assert cues[0].word_indexes == (1, 2)


def test_normal_repetition_is_not_removed() -> None:
    words = [
        _word(1, 0.0, 0.8, "맞아."),
        _word(2, 0.85, 1.65, "맞아."),
    ]

    cues = build_asr_v2_cues(words)

    assert [cue.text for cue in cues] == ["맞아.", "맞아."]


def test_adjacent_micro_sentences_are_merged_instead_of_flashing() -> None:
    words = [
        _word(1, 0.0, 0.21, "같아."),
        _word(2, 0.26, 0.53, " 그치?"),
    ]

    cues = build_asr_v2_cues(words, min_sentence_duration=0.1)

    assert [cue.text for cue in cues] == ["같아. 그치?"]
    assert cues[0].end - cues[0].start >= 0.8


def test_low_confidence_cue_is_reported(tmp_path: Path) -> None:
    words = [
        _word(1, 0.0, 0.5, " uncertain", probability=0.3),
        _word(2, 0.5, 1.0, " words.", probability=0.7),
    ]
    outputs = write_asr_v2_outputs(tmp_path, words)
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(
        json.dumps({"word_summary": {"low_confidence_word_count": 1}}),
        encoding="utf-8",
    )

    report = merge_cue_quality_report(quality_path, cues=outputs["cues"])

    assert report["cue_summary"]["low_confidence_cue_count"] == 1
    assert [cue.text for cue in read_srt(outputs["source_srt"])] == ["uncertain words."]


def test_write_outputs_adds_speaker_labels_without_changing_plain_text(tmp_path: Path) -> None:
    words = [
        _word(1, 0.0, 0.5, " Hello"),
        _word(2, 0.5, 1.0, " there."),
    ]
    turns = [SpeakerTurn(0.0, 1.0, "Speaker 1")]

    outputs = write_asr_v2_outputs(tmp_path, words, turns=turns)

    assert outputs["transcript_text"] == "Speaker 1: Hello there.\n"
    assert outputs["plain_transcript_text"] == "Hello there.\n"
    assert [cue.text for cue in read_srt(outputs["source_srt"])] == [
        "Speaker 1: Hello there."
    ]


def test_recovery_pass_only_fills_uncovered_confident_words() -> None:
    primary = [
        {
            "index": 1,
            "segment_id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": " 기존",
            "probability": 0.9,
            "source_pass": "primary",
        },
        {
            "index": 2,
            "segment_id": 1,
            "start": 3.0,
            "end": 4.0,
            "text": " 문장",
            "probability": 0.9,
            "source_pass": "primary",
        },
    ]
    recovery = [
        {
            "index": 1,
            "segment_id": 10,
            "start": 0.05,
            "end": 0.95,
            "text": " 기존",
            "probability": 0.95,
            "source_pass": "recovery",
        },
        {
            "index": 2,
            "segment_id": 10,
            "start": 1.25,
            "end": 2.6,
            "text": " 빠진 말",
            "probability": 0.84,
            "source_pass": "recovery",
        },
        {
            "index": 3,
            "segment_id": 11,
            "start": 1.5,
            "end": 3.25,
            "text": " 跨越已有台词",
            "probability": 0.9,
            "source_pass": "recovery",
        },
        {
            "index": 4,
            "segment_id": 11,
            "start": 4.7,
            "end": 5.2,
            "text": " 불확실",
            "probability": 0.2,
            "source_pass": "recovery",
        },
    ]
    segments = [
        {
            "id": 10,
            "avg_logprob": -0.2,
            "no_speech_prob": 0.1,
        },
        {
            "id": 11,
            "avg_logprob": -0.3,
            "no_speech_prob": 0.1,
        },
    ]

    merged, summary = merge_recovery_words(
        primary,
        recovery,
        recovery_segments=segments,
        media_duration=6.0,
    )

    assert [word["text"] for word in merged] == [" 기존", " 빠진 말", " 문장"]
    assert [word["index"] for word in merged] == [1, 2, 3]
    assert summary["recovered_word_count"] == 1
    assert summary["recovered_region_count"] == 1
    assert summary["suspected_missing_region_count"] == 1
    assert summary["recovered_regions"][0]["text"] == "빠진 말"


def test_focused_recovery_windows_merge_nearby_targets_and_keep_review_ids() -> None:
    windows = build_focused_recovery_windows(
        [
            {"start": 10.0, "end": 10.4, "text": "하나"},
            {"start": 11.0, "end": 11.4, "text": "둘"},
            {"start": 20.0, "end": 20.3, "text": "셋"},
        ],
        media_duration=21.0,
        padding_seconds=1.0,
        post_padding_seconds=1.0,
    )

    assert len(windows) == 2
    assert windows[0]["start"] == 9.0
    assert windows[0]["end"] == 12.4
    assert [item["review_id"] for item in windows[0]["targets"]] == [
        "gap-001-10000",
        "gap-002-11000",
    ]
    assert windows[1]["end"] == 21.0


def test_focused_recovery_uses_longer_post_roll_for_trailing_speech() -> None:
    [window] = build_focused_recovery_windows(
        [{"start": 10.0, "end": 10.5, "text": "후보"}],
        media_duration=20.0,
    )

    assert window["start"] == 7.0
    assert window["end"] == 13.5


def test_focused_recovery_exposes_full_window_context_for_review() -> None:
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            segment = SimpleNamespace(
                id=0,
                start=3.0,
                end=4.2,
                text=" 후보 뒷말",
                avg_logprob=-0.2,
                compression_ratio=1.0,
                no_speech_prob=0.1,
                temperature=0.0,
                words=[
                    SimpleNamespace(
                        start=3.0,
                        end=3.5,
                        word=" 후보",
                        probability=0.7,
                    ),
                    SimpleNamespace(
                        start=3.5,
                        end=4.2,
                        word=" 뒷말",
                        probability=0.8,
                    ),
                ],
            )
            return iter([segment]), SimpleNamespace()

    _segments, _words, evidence = run_focused_recovery_pass(
        FakeModel(),
        np.ones(20 * 16000, dtype=np.float32),
        [{"start": 10.0, "end": 10.5, "text": "후보"}],
        media_duration=20.0,
        language="ko",
        hotwords="",
        segment_id_offset=10,
    )

    review = evidence["gap-001-10000"]
    assert review["focused_window_start"] == 7.0
    assert review["focused_window_end"] == 13.5
    assert review["focused_context_text"] == "후보 뒷말"
    assert review["focused_speech_end"] == 11.2


def test_focused_audio_normalization_raises_quiet_signal_without_clipping() -> None:
    source = np.asarray([0.001, -0.001, 0.001, -0.001], dtype=np.float32)

    normalized = normalize_focused_audio_window(
        source,
        target_rms=0.08,
        max_gain=12.0,
    )

    assert np.sqrt(np.mean(np.square(normalized))) > np.sqrt(np.mean(np.square(source)))
    assert float(np.max(np.abs(normalized))) <= 0.98
    assert source.tolist() == [0.0010000000474974513, -0.0010000000474974513] * 2


def test_focused_consensus_can_accept_medium_confidence_gap() -> None:
    primary = [
        {
            "index": 1,
            "segment_id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": " 앞",
            "probability": 0.9,
            "source_pass": "primary",
        },
        {
            "index": 2,
            "segment_id": 1,
            "start": 3.0,
            "end": 4.0,
            "text": " 뒤",
            "probability": 0.9,
            "source_pass": "primary",
        },
    ]
    focused = [
        {
            "index": 1,
            "segment_id": 20,
            "start": 1.4,
            "end": 2.2,
            "text": " 들린 말",
            "probability": 0.52,
            "source_pass": "focused_recovery",
            "review_target_id": "gap-001-1400",
            "consensus_confirmed": True,
            "consensus_probability": 0.62,
        }
    ]

    merged, summary = merge_recovery_words(
        primary,
        focused,
        recovery_segments=[
            {"id": 20, "avg_logprob": -0.4, "no_speech_prob": 0.1}
        ],
        media_duration=5.0,
        min_word_probability=0.25,
        min_region_probability=0.72,
        consensus_min_probability=0.42,
        candidate_source_pass="focused_recovery",
    )

    assert [item["text"] for item in merged] == [" 앞", " 들린 말", " 뒤"]
    assert summary["recovered_word_count"] == 1
    assert summary["recovered_regions"][0]["review_target_ids"] == [
        "gap-001-1400"
    ]


def test_focused_consensus_does_not_treat_incidental_single_character_as_match() -> None:
    assert _recovery_text_similarity("아", "괜찮아") < 0.58
    assert _recovery_text_similarity("왜", "왜") == 1.0


def test_focused_consensus_uses_narrow_recovery_gap_timing() -> None:
    focused, evidence = _focused_words_for_targets(
        [
            {
                "start": 8.8,
                "end": 10.8,
                "text": " 머리",
                "probability": 0.33,
            }
        ],
        [
            {
                "review_id": "gap-001-10000",
                "start": 10.0,
                "end": 10.5,
                "text": "머리",
                "average_probability": 0.67,
            }
        ],
    )

    assert evidence["gap-001-10000"]["cross_pass_probability"] == 0.5
    assert focused[0]["consensus_confirmed"] is True
    assert focused[0]["start"] == 10.0
    assert focused[0]["end"] == 10.5


def test_focused_consensus_rejects_a_matching_word_with_extra_phrase() -> None:
    focused, evidence = _focused_words_for_targets(
        [
            {
                "start": 10.0,
                "end": 10.4,
                "text": " 엄지도",
                "probability": 0.93,
            },
            {
                "start": 10.4,
                "end": 10.8,
                "text": " 사람도",
                "probability": 0.78,
            },
        ],
        [
            {
                "review_id": "gap-001-10000",
                "start": 10.0,
                "end": 10.5,
                "text": "엄지도",
                "average_probability": 0.58,
            }
        ],
    )

    assert evidence["gap-001-10000"]["consensus_confirmed"] is False
    assert focused[1]["end"] == 10.8


def test_review_region_keeps_candidate_narrow_but_plays_full_context() -> None:
    words = [
        _word(1, 8.7, 9.3, "앞"),
        _word(2, 9.3, 9.8, " 문장"),
        _word(3, 10.7, 11.2, "뒤"),
        _word(4, 11.2, 12.1, " 문장"),
        _word(5, 12.1, 13.0, " 계속"),
    ]

    [region] = enrich_asr_review_regions(
        [
            {
                "start": 10.0,
                "end": 10.5,
                "text": "후보",
                "focused_speech_start": 8.1,
                "focused_speech_end": 12.8,
            }
        ],
        words,
        media_duration=20.0,
    )

    assert region["candidate_start"] == 10.0
    assert region["candidate_end"] == 10.5
    assert region["review_start"] == 7.75
    assert region["review_end"] == 13.35
    assert region["context_before"] == "앞 문장"
    assert region["context_after"] == "뒤 문장 계속"


def test_transcribe_audio_v2_preserves_word_and_quality_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    output_dir = tmp_path / "out"
    captured = {"calls": []}

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type, local_files_only):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type
            captured["local_files_only"] = local_files_only

        def transcribe(self, path, **kwargs):
            captured["path"] = path
            captured["calls"].append(kwargs)
            segment = SimpleNamespace(
                id=7,
                start=0.0,
                end=1.0,
                text=" hello",
                avg_logprob=-1.2,
                compression_ratio=1.1,
                no_speech_prob=0.2,
                temperature=0.0,
                words=[
                    SimpleNamespace(
                        start=0.1,
                        end=0.8,
                        word=" hello",
                        probability=0.42,
                    )
                ],
            )
            info = SimpleNamespace(
                language="en",
                language_probability=0.96,
                duration=1.0,
                duration_after_vad=0.8,
            )
            return iter([segment]), info

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    paths = transcribe_audio_v2(
        media,
        output_dir,
        model_size="small",
        language="english",
        device="cpu",
        compute_type="int8",
        hotwords="ReiboSub",
    )

    words = json.loads(paths["words_path"].read_text(encoding="utf-8"))
    quality = json.loads(paths["quality_path"].read_text(encoding="utf-8"))
    assert words["version"] == ASR_V2_VERSION
    assert len(captured["calls"]) == 2
    assert captured["calls"][0]["word_timestamps"] is True
    assert captured["local_files_only"] is True
    assert captured["calls"][0]["vad_parameters"]["min_silence_duration_ms"] == 500
    assert captured["calls"][0]["condition_on_previous_text"] is True
    assert captured["calls"][1]["vad_parameters"]["threshold"] == 0.25
    assert captured["calls"][1]["condition_on_previous_text"] is False
    assert captured["calls"][0]["hotwords"] == "ReiboSub"
    assert words["words"][0]["probability"] == 0.42
    assert quality["word_summary"]["low_confidence_word_count"] == 1
    assert quality["segment_summary"]["suspicious_segment_count"] == 1
    assert quality["recovery"]["enabled"] is True
    assert quality["recovery"]["recovered_word_count"] == 0
    assert paths["raw_srt"].exists()
    assert paths["recovery_raw_srt"].exists()
    assert paths["recovery_words_path"].exists()
