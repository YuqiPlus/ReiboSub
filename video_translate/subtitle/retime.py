from __future__ import annotations

from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt, write_srt


def align_srt_timing(reference_srt: Path, target_srt: Path, out_srt: Path) -> Path:
    reference = read_srt(reference_srt)
    target = read_srt(target_srt)
    aligned: list[SubtitleCue] = []

    for index, (ref, target_cue) in enumerate(zip(reference, target), start=1):
        aligned.append(
            SubtitleCue(
                index=index,
                start=ref.start,
                end=ref.end,
                text=target_cue.text,
                source_track_id=target_cue.source_track_id,
            )
        )

    write_srt(aligned, out_srt)
    return out_srt
