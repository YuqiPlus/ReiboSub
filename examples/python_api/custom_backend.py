"""A runnable custom translation backend: no API key, network or LLM required."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from reibosub import Cue, Progress, Subtitle, translate


class DictionaryTranslator:
    def translate_batch(self, texts: Sequence[str], *, source_language: str, target_language: str) -> Sequence[str]:
        # Replace this body with your own local model, queue or remote client.
        # Always return one string per input in exactly the same order.
        dictionary = {"안녕하세요.": "Hello.", "감사합니다.": "Thank you."}
        return [dictionary[text] for text in texts]


def report(event: Progress):
    print(f"{event.stage}: {event.completed}/{event.total}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = Subtitle((Cue(1, 0, 2, "안녕하세요."), Cue(2, 3, 5, "감사합니다.")), language="ko")
    result = translate(source, translator=DictionaryTranslator(), target_language="en", batch_size=1, on_progress=report)
    result.save(args.out)
    assert source[0].text == "안녕하세요."  # Translation never mutates the input.


if __name__ == "__main__":
    main()
