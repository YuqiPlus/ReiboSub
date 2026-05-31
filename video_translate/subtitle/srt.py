from __future__ import annotations

import re
from pathlib import Path

from video_translate.models import SubtitleCue
from video_translate.utils.timecode import format_srt_time, parse_srt_time


_TIME_LINE_RE = re.compile(r"(.+?)\s+-->\s+(.+)")


def write_srt(cues: list[SubtitleCue], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}",
                    cue.text.strip(),
                ]
            )
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def read_srt(path: Path) -> list[SubtitleCue]:
    content = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line_index = 1 if lines[0].isdigit() else 0
        match = _TIME_LINE_RE.match(lines[time_line_index])
        if not match:
            continue
        index = len(cues) + 1
        text_lines = lines[time_line_index + 1 :]
        cues.append(
            SubtitleCue(
                index=index,
                start=parse_srt_time(match.group(1)),
                end=parse_srt_time(match.group(2)),
                text="\n".join(text_lines),
            )
        )
    return cues
