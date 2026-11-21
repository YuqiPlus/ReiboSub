"""Explicit paid/local service example; only sends requests when you run main()."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from reibosub import Subtitle, Translator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--target", default="en")
    args = parser.parse_args()
    key = os.environ.get("MY_TRANSLATION_API_KEY")
    if not key:
        parser.error("Set MY_TRANSLATION_API_KEY explicitly; website credentials are never loaded")
    if args.out.exists():
        parser.error("Output already exists; choose a new path before making a paid request")
    translator = Translator(base_url=args.base_url, api_key=key, model=args.model, glossary={"ReiboSub": "ReiboSub"}, timeout=60)
    result = translator.translate(Subtitle.load(args.source), target_language=args.target,
                                  on_progress=lambda event: print(f"{event.completed}/{event.total}"))
    result.save(args.out)


if __name__ == "__main__":
    main()
