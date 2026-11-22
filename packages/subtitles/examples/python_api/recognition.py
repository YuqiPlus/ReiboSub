"""Optional recognition demo. Install the source product's matching extras first."""
from __future__ import annotations

import argparse
from pathlib import Path

from reibosub import ASR, OCR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('asr', 'image', 'video'))
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, help='Required for ASR/video; existing files are never overwritten')
    parser.add_argument('--language', help='ASR: ko/ja/zh/en; OCR: korean/japan/ch/en')
    parser.add_argument('--model', default='small')
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--detection-model-dir', type=Path)
    parser.add_argument('--recognition-model-dir', type=Path)
    args = parser.parse_args()
    if args.mode != 'image' and args.out is None:
        parser.error('--out is required')
    if args.out is not None and (args.out.exists() or args.out.is_symlink()):
        parser.error('Output exists; choose a new path')
    if args.mode == 'asr':
        ASR(model=args.model, cache_dir=args.cache_dir, local_files_only=args.offline).transcribe(
            args.source, language=args.language,
        ).save(args.out)
    else:
        engine = OCR(language=args.language or 'korean', local_files_only=args.offline,
                     detection_model_dir=args.detection_model_dir,
                     recognition_model_dir=args.recognition_model_dir)
        if args.mode == 'image':
            for region in engine.read_image(args.source):
                print(region)
        else:
            engine.extract_subtitles(args.source).save(args.out)


if __name__ == '__main__':
    main()
