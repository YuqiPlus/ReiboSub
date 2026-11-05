"""Conservative, audio-backed retries for experimental Qwen word alignment.

No interpolation or minimum-duration padding is used here. Unsupported words
remain unresolved, and accepted changes retain the exact input token sequence.
"""
from __future__ import annotations

import math
from dataclasses import replace
import re


def zero_runs(words, epsilon=1e-6):
    runs = []
    start = None
    for i, word in enumerate(words):
        bad = word["end"] - word["start"] <= epsilon
        if bad and start is None:
            start = i
        if start is not None and (not bad or i == len(words) - 1):
            runs.append((start, i + 1 if bad else i))
            start = None
    return runs


def plan_retry(words, run, bounds, context=2, padding=0.4):
    start, stop = max(0, run[0] - context), min(len(words), run[1] + context)
    selected = words[start:stop]
    if not any(w["end"] - w["start"] > 1e-6 for w in selected):
        return None
    audio_start = max(bounds[0], min(w["start"] for w in selected) - padding)
    audio_end = min(bounds[1], max(w["end"] for w in selected) + padding)
    if not 0.5 <= audio_end - audio_start <= 14:
        return None
    return {"start_index": start, "stop_index": stop,
            "audio_start": audio_start, "audio_end": audio_end}


def validate_retry(words, plan, candidate, speech_regions, max_anchor_shift=1.0):
    start, stop = plan["start_index"], plan["stop_index"]
    previous = words[start:stop]
    if [w["text"] for w in candidate] != [w["text"] for w in previous]:
        return "text_changed"
    if sum(b - a for a, b in zero_runs(candidate)) >= sum(b - a for a, b in zero_runs(previous)):
        return "no_zero_reduction"
    for i, word in enumerate(candidate):
        a, b = word["start"], word["end"]
        if not math.isfinite(a) or not math.isfinite(b) or a > b:
            return "invalid_timestamp"
        if a < plan["audio_start"] - 0.001 or b > plan["audio_end"] + 0.001:
            return "outside_audio"
        if i and a < candidate[i - 1]["end"] - 0.001:
            return "nonmonotonic"
        old = previous[i]
        duration = old["end"] - old["start"]
        if duration > 1e-6 and b - a <= 1e-6:
            return "regressed_existing_anchor"
        if 1e-6 < duration <= 1.5:
            if abs((a + b - old["start"] - old["end"]) / 2) > max_anchor_shift:
                return "anchor_moved_too_far"
        if duration <= 1e-6 and b > a:
            covered = sum(max(0, min(b, r["end"]) - max(a, r["start"])) for r in speech_regions)
            if covered / (b - a) < 0.25:
                return "no_speech_support"
    if start and candidate[0]["start"] < words[start - 1]["end"] - 0.001:
        return "overlaps_left_anchor"
    if stop < len(words) and candidate[-1]["end"] > words[stop]["start"] + 0.001:
        return "overlaps_right_anchor"
    return None


def refine_part(words, bounds, speech_regions, align):
    revised = [dict(w, timing_source="original") for w in words]
    attempts = []
    for context, padding in [(2, 0.4), (4, 0.75)]:
        for run in zero_runs(revised):
            # A previous accepted context may already have repaired this run.
            if not any(w["end"] <= w["start"] + 1e-6 for w in revised[run[0]:run[1]]):
                continue
            plan = plan_retry(revised, run, bounds, context, padding)
            if plan is None:
                attempts.append({"run": list(run), "accepted": False, "reason": "no_reliable_local_context"})
                continue
            previous = revised[plan["start_index"]:plan["stop_index"]]
            candidate = align(plan, previous)
            reason = validate_retry(revised, plan, candidate, speech_regions)
            attempts.append({"run": list(run), **plan, "accepted": reason is None,
                             "reason": reason or "audio_realignment", "before": previous, "after": candidate})
            if reason is None:
                revised[plan["start_index"]:plan["stop_index"]] = [dict(w, timing_source="local_force_aligner") for w in candidate]
    return revised, attempts


def subtitle_cues_with_unresolved(words, duration):
    """Retain unresolved text *inside* an anchored cue, without timing its words.

    An entirely collapsed span has no cue and stays in the review queue. Cue
    display padding is bounded by the actual media duration.
    """
    from video_translate.asr_v2 import build_asr_v2_cues
    by_index = {w.index: w for w in words}
    output = []
    for cue in build_asr_v2_cues(words):
        indices = set(cue.word_indexes)
        positive = [by_index[i] for i in sorted(indices)]
        zero_inside = [w for w in words if min(indices) < w.index < max(indices)
                       and w.index not in indices and w.end <= w.start + 1e-6]
        # Do not undo a separate duplicate-text normalization performed by the
        # existing cue builder. Only insert missing, untimed interior tokens.
        clean = lambda text: re.sub(r"\s+", "", text)
        inserted = []
        if zero_inside and clean("".join(w.text for w in positive)) == clean(cue.text):
            inserted = [w.index for w in zero_inside]
            selected = sorted([*positive, *zero_inside], key=lambda w: w.index)
            cue = replace(cue, text="".join(w.text for w in selected).strip(),
                          word_indexes=tuple(w.index for w in selected))
        cue = replace(cue, end=min(cue.end, duration))
        if not 0 <= cue.start < cue.end <= duration:
            raise ValueError("Invalid subtitle bounds")
        output.append((cue, inserted))
    return output
