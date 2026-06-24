from __future__ import annotations

import argparse
from pathlib import Path

from video_translate.subtitle.convert import convert_subtitle_file, normalize_subtitle_format


def default_output_path(source: Path, output_format: str) -> Path:
    fmt = normalize_subtitle_format(output_format)
    return source.with_suffix(f".{fmt}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Convert subtitle files between srt/vtt/ass/ssa/bcc/json/lrc/txt.")
    parser.add_argument("source", type=Path, help="Input subtitle file")
    parser.add_argument("--format", "--to", dest="output_format", default="srt", help="Target format")
    parser.add_argument("--out", type=Path, default=None, help="Output subtitle path")
    args = parser.parse_args(argv)

    out = args.out or default_output_path(args.source, args.output_format)
    result = convert_subtitle_file(args.source, out, output_format=args.output_format)
    print(f"converted_subtitle: {result}")


if __name__ == "__main__":
    main()
