from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_translate.subtitle.srt import read_srt
from video_translate.translate.glossary import load_glossary


def prepare_translation_batch(
    source_srt: Path,
    out_path: Path,
    glossary_path: Path | None = None,
    batch_size: int = 60,
) -> Path:
    cues = read_srt(source_srt)
    glossary = load_glossary(glossary_path)
    payload: dict[str, Any] = {"batches": []}

    for offset in range(0, len(cues), batch_size):
        batch = cues[offset : offset + batch_size]
        texts = [cue.text for cue in batch]
        payload["batches"].append(
            {
                "context": glossary.to_context(texts),
                "subtitles": [
                    {
                        "id": cue.index,
                        "start": cue.start,
                        "end": cue.end,
                        "source": cue.text,
                    }
                    for cue in batch
                ],
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
