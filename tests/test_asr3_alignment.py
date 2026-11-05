from copy import deepcopy

from scripts.asr3_alignment import plan_retry, refine_part, validate_retry, subtitle_cues_with_unresolved


def word(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_local_audio_retry_can_resolve_a_word_without_changing_text():
    original = [word("hello", 0, 0.8), word("my", 0.8, 0.8), word("friend", 0.8, 1.6)]
    candidate = [word("hello", 0, 0.7), word("my", 0.7, 0.9), word("friend", 0.9, 1.6)]
    original_copy = deepcopy(original)
    result, attempts = refine_part(original, (0, 2), [{"start": 0, "end": 2}], lambda p, w: candidate)
    assert original == original_copy
    assert [w["text"] for w in result] == [w["text"] for w in original]
    assert result[1]["end"] > result[1]["start"]
    assert attempts[0]["accepted"]


def test_unanchored_collapsed_text_stays_unresolved_without_fabricated_times():
    original = [word("unconfirmed", 4, 4), word("speech", 4, 4)]
    def no_inference(*args):
        raise AssertionError("A collapsed segment has no reliable local anchors")
    result, attempts = refine_part(original, (0, 30), [{"start": 0, "end": 30}], no_inference)
    assert [(w["start"], w["end"]) for w in result] == [(4, 4), (4, 4)]
    assert not any(a["accepted"] for a in attempts)


def test_dropped_or_changed_transcript_is_not_accepted():
    words = [word("hello", 0, 1), word("you", 1, 1)]
    plan = plan_retry(words, (1, 2), (0, 2))
    assert validate_retry(words, plan, [word("hello", 0, 1)], []) == "text_changed"


def test_positive_timing_without_speech_support_is_not_accepted():
    words = [word("hello", 0, 0.5), word("you", 0.5, 0.5)]
    plan = plan_retry(words, (1, 2), (0, 2))
    candidate = [word("hello", 0, 0.5), word("you", 0.6, 0.8)]
    assert validate_retry(words, plan, candidate, [{"start": 0, "end": 0.5}]) == "no_speech_support"


def test_retry_cannot_turn_a_previously_positive_word_into_zero_duration():
    words = [word("a", 0, 0.4), word("b", 0.4, 0.4), word("c", 0.4, 0.4)]
    plan = plan_retry(words, (1, 3), (0, 2))
    candidate = [word("a", 0, 0), word("b", 0, 0.2), word("c", 0.2, 0.4)]
    assert validate_retry(words, plan, candidate, [{"start": 0, "end": 2}]) == "regressed_existing_anchor"


def test_local_retry_must_not_cross_an_untouched_neighbor():
    words = [word("a", 0, 1), word("b", 1, 1), word("c", 1, 2)]
    plan = {"start_index": 1, "stop_index": 3, "audio_start": 0, "audio_end": 2}
    candidate = [word("b", 0.8, 1.2), word("c", 1.2, 2)]
    assert validate_retry(words, plan, candidate, [{"start": 0, "end": 2}]) == "overlaps_left_anchor"


def test_export_retains_interior_text_without_fabricating_word_timing():
    from video_translate.asr_v2 import AsrWord
    words = [AsrWord(1, 0, 0.5, "hello", None, 0),
             AsrWord(2, 0.5, 0.5, " my", None, 0),
             AsrWord(3, 0.5, 1, " friend", None, 0)]
    cues = subtitle_cues_with_unresolved(words, 1)
    assert cues[0][0].text == "hello my friend"
    assert cues[0][1] == [2]
    assert words[1].start == words[1].end == 0.5


def test_entirely_unlocated_transcript_is_not_given_invented_cue_times():
    from video_translate.asr_v2 import AsrWord
    assert subtitle_cues_with_unresolved([AsrWord(1, 0, 0, "unknown", None, 0)], 30) == []


def test_readability_padding_does_not_extend_subtitles_past_the_media():
    from video_translate.asr_v2 import AsrWord
    cues = subtitle_cues_with_unresolved([AsrWord(1, 0.9, 1, "end", None, 0)], 1)
    assert cues[0][0].end == 1
