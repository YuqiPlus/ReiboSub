from __future__ import annotations

import argparse
from pathlib import Path

from video_translate.cache import configure_model_cache
from video_translate.pipeline import extract_subtitles_from_video, merge_ocr_samples, reprocess_tracks_json
from video_translate.run_config import run_config
from video_translate.translate.apply import apply_translation_json
from video_translate.translate.batch import prepare_translation_batch
from video_translate.translate.volcengine import translate_srt_with_volcengine


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="video-translate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="从视频 OCR 提取硬字幕")
    extract.add_argument("video", type=Path)
    extract.add_argument("--lang", default="korean", help="PaddleOCR 语言，例如 korean、japan、ch")
    extract.add_argument("--out", type=Path, default=Path("outputs"))
    extract.add_argument("--sample-fps", type=float, default=3.0)
    extract.add_argument("--bottom-ratio", type=float, default=0.42)
    extract.add_argument("--scan-full-frame", action="store_true")
    extract.add_argument("--device", default="auto", help="auto、cpu、gpu 或 gpu:0")

    merge = subparsers.add_parser("merge-ocr", help="合并已有 OCR JSON 采样结果")
    merge.add_argument("ocr_json", type=Path)
    merge.add_argument("--out", type=Path, default=Path("outputs"))
    merge.add_argument("--video-duration", type=float, default=None)

    reprocess = subparsers.add_parser("reprocess-tracks", help="重新过滤已有 tracks.json 并生成 SRT/debug")
    reprocess.add_argument("tracks_json", type=Path)
    reprocess.add_argument("--out", type=Path, default=Path("outputs"))
    reprocess.add_argument("--video-duration", type=float, default=None)

    prepare = subparsers.add_parser("prepare-translation", help="生成带术语表上下文的翻译批次 JSON")
    prepare.add_argument("source_srt", type=Path)
    prepare.add_argument("--glossary", type=Path, default=None)
    prepare.add_argument("--out", type=Path, default=Path("outputs/translation_batch.json"))
    prepare.add_argument("--batch-size", type=int, default=60)

    apply = subparsers.add_parser("apply-translation", help="把大模型返回的 JSON 应用回中文 SRT")
    apply.add_argument("source_srt", type=Path)
    apply.add_argument("translation_json", type=Path)
    apply.add_argument("--out", type=Path, default=Path("outputs/zh.srt"))

    volc = subparsers.add_parser("translate-volcengine", help="使用火山方舟/豆包翻译 SRT")
    volc.add_argument("source_srt", type=Path)
    volc.add_argument("--glossary", type=Path, default=None)
    volc.add_argument("--out", type=Path, default=Path("outputs/zh.srt"))
    volc.add_argument("--batch-size", type=int, default=40)
    volc.add_argument("--model", default=None)
    volc.add_argument("--base-url", default=None)
    volc.add_argument("--target-language", default="简体中文")

    config_run = subparsers.add_parser("run-config", help="读取 YAML 配置运行 OCR/翻译")
    config_run.add_argument("config", type=Path, default=Path("configs/run.yaml"), nargs="?")

    doctor = subparsers.add_parser("doctor", help="检查依赖和模型缓存路径")
    doctor.add_argument("--cache-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "extract":
        outputs = extract_subtitles_from_video(
            args.video,
            args.out,
            lang=args.lang,
            sample_fps=args.sample_fps,
            bottom_ratio=args.bottom_ratio,
            scan_full_frame=args.scan_full_frame,
            device=args.device,
        )
        _print_outputs(outputs)
    elif args.command == "merge-ocr":
        outputs = merge_ocr_samples(args.ocr_json, args.out, video_duration=args.video_duration)
        _print_outputs(outputs)
    elif args.command == "reprocess-tracks":
        outputs = reprocess_tracks_json(args.tracks_json, args.out, video_duration=args.video_duration)
        _print_outputs(outputs)
    elif args.command == "prepare-translation":
        path = prepare_translation_batch(args.source_srt, args.out, args.glossary, args.batch_size)
        print(f"translation_batch: {path}")
    elif args.command == "apply-translation":
        path = apply_translation_json(args.source_srt, args.translation_json, args.out)
        print(f"zh_srt: {path}")
    elif args.command == "translate-volcengine":
        path = translate_srt_with_volcengine(
            args.source_srt,
            args.out,
            glossary_path=args.glossary,
            batch_size=args.batch_size,
            model=args.model,
            base_url=args.base_url,
            target_language=args.target_language,
        )
        print(f"zh_srt: {path}")
    elif args.command == "run-config":
        run_config(args.config)
    elif args.command == "doctor":
        cache_dir = configure_model_cache(args.cache_dir)
        print(f"cache_dir: {cache_dir}")
        _check_dependency("cv2")
        _check_dependency("yaml")
        _check_dependency("paddleocr")


def _print_outputs(outputs: dict[str, Path]) -> None:
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _check_dependency(module_name: str) -> None:
    __import__(module_name)
    print(f"{module_name}: ok")
