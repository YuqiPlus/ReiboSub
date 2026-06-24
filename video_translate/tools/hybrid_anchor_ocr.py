from __future__ import annotations

import argparse
from pathlib import Path

from video_translate.subtitle.hybrid_ocr import extract_hybrid_ocr_source
from video_translate.subtitle.srt import read_srt


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Build a Korean-OCR + uploaded-subtitle anchored hybrid source SRT.")
    parser.add_argument("input_video", type=Path, help="Local video file")
    parser.add_argument("anchor_srt", type=Path, help="Trusted uploaded subtitle SRT whose timing will be preserved")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--lang", default="korean", help="PaddleOCR language, default: korean")
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--bottom-ratio", type=float, default=0.42)
    parser.add_argument("--scan-full-frame", action="store_true")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--anchor-padding-seconds", type=float, default=0.15)
    parser.add_argument("--ocr-window-seconds", type=float, default=1.20, help="Seconds around each anchor cue to collect OCR candidates")
    parser.add_argument("--reconstruct-korean", action="store_true", help="Use LLM to reconstruct timing-aligned Korean source subtitles")
    args = parser.parse_args(argv)

    input_video = args.input_video.expanduser().resolve()
    anchor_srt = args.anchor_srt.expanduser().resolve()
    if not input_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_video}")
    if not anchor_srt.exists():
        raise FileNotFoundError(f"字幕文件不存在: {anchor_srt}")

    result = extract_hybrid_ocr_source(
        input_video,
        read_srt(anchor_srt),
        args.out_dir.expanduser().resolve(),
        lang=args.lang,
        sample_fps=args.sample_fps,
        bottom_ratio=args.bottom_ratio,
        scan_full_frame=args.scan_full_frame,
        device=args.device,
        anchor_padding_seconds=args.anchor_padding_seconds,
        ocr_window_seconds=args.ocr_window_seconds,
        reconstruct_korean=args.reconstruct_korean,
    )
    for key, path in result.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
