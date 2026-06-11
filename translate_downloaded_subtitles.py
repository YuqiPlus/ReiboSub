import argparse
from pathlib import Path

from video_translate.translate.volcengine import translate_srt_with_volcengine


DEFAULT_TARGET_LANGUAGE = "简体中文"
DEFAULT_BATCH_SIZE = 40
DEFAULT_EXTRA_PROMPT = """这是作者上传或平台提供的外挂字幕，时间轴通常可信，不需要改写或重排时间。
请只翻译字幕文本，保持简洁、自然、口语化，适合外挂字幕显示。
严格遵守 glossary 中的人名、节目名、品牌名和固定术语；不要自由改译。
如果源字幕里有说话人标签、括号说明或屏幕文字，请按中文观看习惯自然保留或翻译。
"""


def default_output_path(source_srt: Path, target_language: str = DEFAULT_TARGET_LANGUAGE) -> Path:
    suffix = ".zh" if "中文" in target_language or "Chinese" in target_language else ".translated"
    return source_srt.with_name(source_srt.stem + suffix + ".srt")


def translate_downloaded_subtitles(
    source_srt: Path,
    out_srt: Path | None = None,
    *,
    glossary: Path | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str | None = None,
    base_url: str | None = None,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    extra_prompt: str = DEFAULT_EXTRA_PROMPT,
) -> Path:
    source_srt = source_srt.expanduser().resolve()
    if not source_srt.exists():
        raise FileNotFoundError(f"字幕文件不存在: {source_srt}")
    if source_srt.suffix.lower() != ".srt":
        raise ValueError("当前翻译入口只接受 .srt；YouTube 字幕请先用 download_youtube_subtitles.py 默认转换为 srt。")

    if out_srt is None:
        out_srt = default_output_path(source_srt, target_language)
    else:
        out_srt = out_srt.expanduser().resolve()

    return translate_srt_with_volcengine(
        source_srt,
        out_srt,
        glossary_path=glossary,
        batch_size=batch_size,
        model=model,
        base_url=base_url,
        target_language=target_language,
        extra_prompt=extra_prompt,
        dedupe_translated=False,
        llm_cleanup_translated=False,
        cleanup_residual_fragments=False,
        retime_translated=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Translate downloaded sidecar .srt subtitles while preserving timing.")
    parser.add_argument("source_srt", type=Path, help="Downloaded .srt subtitle file")
    parser.add_argument("--out", type=Path, default=None, help="Output translated .srt path; default is <source>.zh.srt")
    parser.add_argument("--glossary", type=Path, default=None, help="Task glossary YAML/JSON for names and terms")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--model", default=None, help="Override ARK_MODEL")
    parser.add_argument("--base-url", default=None, help="Override ARK_BASE_URL")
    parser.add_argument("--target-language", default=DEFAULT_TARGET_LANGUAGE)
    parser.add_argument("--extra-prompt", default="", help="Extra task instruction appended to the default prompt")
    args = parser.parse_args(argv)

    extra_prompt = DEFAULT_EXTRA_PROMPT
    if args.extra_prompt.strip():
        extra_prompt += "\n" + args.extra_prompt.strip() + "\n"

    out = translate_downloaded_subtitles(
        args.source_srt,
        args.out,
        glossary=args.glossary,
        batch_size=args.batch_size,
        model=args.model,
        base_url=args.base_url,
        target_language=args.target_language,
        extra_prompt=extra_prompt,
    )
    print(f"translated_srt: {out}")


if __name__ == "__main__":
    main()
