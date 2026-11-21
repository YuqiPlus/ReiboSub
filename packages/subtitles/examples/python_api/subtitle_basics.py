"""Offline subtitle API example. Run with --out-dir pointing to a new directory."""
from __future__ import annotations

import argparse
from pathlib import Path

from reibosub import Cue, Subtitle, convert


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional subtitle; otherwise use synthetic demo cues")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source = Subtitle.load(args.input) if args.input else Subtitle((Cue(1, 0, 2, "數據與美學。"), Cue(2, 3, 5, "字幕 API 示例。")), language="zh")
    simplified = source.to_simplified()
    simplified.save(args.out_dir / "simplified.srt")
    source.to_traditional().save(args.out_dir / "traditional.srt")
    source.save(args.out_dir / "source.json")
    convert(args.out_dir / "simplified.srt", args.out_dir / "converted.vtt")
    print(simplified.to_text())
    for issue in source.check():
        print(issue.code, issue.cue_indexes, issue.message)


if __name__ == "__main__":
    main()
