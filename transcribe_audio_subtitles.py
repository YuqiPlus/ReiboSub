from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from video_translate.cache import configure_model_cache, cuda_library_dirs, prepend_library_path


DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_LANGUAGE = "auto"
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE_TYPE = "float16"

LANGUAGE_MAP = {
    "auto": None,
    "korean": "ko",
    "ko": "ko",
    "english": "en",
    "en": "en",
    "japanese": "ja",
    "ja": "ja",
    "chinese": "zh",
    "zh": "zh",
}


def transcribe_audio_to_srt(
    input_media: Path,
    out_srt: Path,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
    language: str = DEFAULT_LANGUAGE,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    vad_filter: bool = True,
    word_timestamps: bool = True,
) -> Path:
    input_media = input_media.expanduser().resolve()
    out_srt = out_srt.expanduser().resolve()
    if not input_media.exists():
        raise FileNotFoundError(f"媒体文件不存在: {input_media}")

    configure_model_cache()
    ensure_cuda_library_path_ready(device)

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper，请先在环境中安装：pip install faster-whisper") from exc

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(input_media),
        language=normalize_language(language),
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
    )
    write_segments_as_srt(segments, out_srt)
    detected = getattr(info, "language", "") or "unknown"
    print(f"detected_language: {detected}", flush=True)
    print(f"source_srt: {out_srt}", flush=True)
    return out_srt


def ensure_cuda_library_path_ready(device: str) -> None:
    if not str(device).lower().startswith("cuda"):
        return
    before = os.environ.get("LD_LIBRARY_PATH", "")
    prepend_library_path(os.environ, cuda_library_dirs())
    after = os.environ.get("LD_LIBRARY_PATH", "")
    if after == before or os.environ.get("VIDEO_TRANSLATE_CUDA_LIB_READY") == "1":
        return
    os.environ["VIDEO_TRANSLATE_CUDA_LIB_READY"] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], os.environ)


def normalize_language(value: str | None) -> str | None:
    key = str(value or DEFAULT_LANGUAGE).strip().lower()
    if key not in LANGUAGE_MAP:
        raise ValueError(f"不支持的音频识别语言: {value}")
    return LANGUAGE_MAP[key]


def write_segments_as_srt(segments: Iterable[Any], out_srt: Path) -> None:
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    index = 1
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start, end = segment_timing(segment)
        lines.extend([str(index), f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}", text, ""])
        index += 1
    out_srt.write_text("\n".join(lines), encoding="utf-8")


def segment_timing(segment: Any) -> tuple[float, float]:
    segment_start = max(0.0, float(getattr(segment, "start")))
    segment_end = max(segment_start + 0.01, float(getattr(segment, "end")))
    word_times = [
        (float(getattr(word, "start")), float(getattr(word, "end")))
        for word in getattr(segment, "words", []) or []
        if getattr(word, "start", None) is not None and getattr(word, "end", None) is not None
    ]
    if not word_times:
        return segment_start, segment_end
    word_start = min(start for start, _end in word_times)
    word_end = max(end for _start, end in word_times)
    start = min(max(0.0, word_start), segment_end)
    end = min(max(start + 0.01, word_end), segment_end)
    return start, end


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Transcribe media audio to SRT using faster-whisper.")
    parser.add_argument("input_media", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--compute-type", default=DEFAULT_COMPUTE_TYPE)
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--no-word-timestamps", action="store_true")
    args = parser.parse_args(argv)
    transcribe_audio_to_srt(
        args.input_media,
        args.out,
        model_size=args.model_size,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        vad_filter=not args.no_vad,
        word_timestamps=not args.no_word_timestamps,
    )


if __name__ == "__main__":
    main()
