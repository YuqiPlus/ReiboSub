from __future__ import annotations

from pathlib import Path
from typing import Any

from video_translate.pipeline import CueTimingConfig, extract_subtitles_from_video
from video_translate.subtitle.sidecar import SidecarConfig, copy_sidecar_subtitles
from video_translate.translate.volcengine import translate_srt_with_volcengine


def run_config(config_path: Path) -> None:
    config = _load_yaml(config_path)
    root = config_path.resolve().parent.parent

    mode = str(config.get("mode", "full")).lower()
    output_dir = _resolve_path(root, config.get("output_dir", "outputs/demo"))
    source_srt = _resolve_path(root, config.get("source_srt", output_dir / "source.srt"))
    glossary = _optional_path(root, config.get("glossary"))
    target_language = str(config.get("target_language", "简体中文"))
    input_video: Path | None = None
    filters = config.get("filters", {}) or {}
    ignored_texts = _string_list(filters.get("ignored_texts", []))
    ignored_contains = _string_list(filters.get("ignored_contains", []))
    ignored_patterns = _string_list(filters.get("ignored_patterns", []))
    cue_timing = _cue_timing_config(config.get("subtitle", {}) or {})

    if mode in {"full", "extract"}:
        input_video = _resolve_path(root, config["input_video"])
        ocr = config.get("ocr", {}) or {}
        source_language = str(config.get("source_language", "korean"))
        outputs = extract_subtitles_from_video(
            input_video,
            output_dir,
            lang=source_language,
            sample_fps=float(ocr.get("sample_fps", 3.0)),
            bottom_ratio=float(ocr.get("bottom_ratio", 0.42)),
            scan_full_frame=bool(ocr.get("scan_full_frame", False)),
            device=str(ocr.get("device", "auto")),
            ignored_texts=ignored_texts,
            ignored_contains=ignored_contains,
            ignored_patterns=ignored_patterns,
            cue_timing=cue_timing,
        )
        source_srt = outputs["source_srt"]
        print(f"source_srt: {source_srt}")

    if mode in {"full", "translate"}:
        translation = config.get("translation", {}) or {}
        provider = str(translation.get("provider", "volcengine")).lower()
        if provider != "volcengine":
            raise ValueError(f"暂不支持翻译 provider: {provider}")
        zh_srt = output_dir / "zh.srt"
        translate_srt_with_volcengine(
            source_srt,
            zh_srt,
            glossary_path=glossary,
            batch_size=int(translation.get("batch_size", 40)),
            model=translation.get("model"),
            base_url=translation.get("base_url"),
            target_language=target_language,
            ignored_texts=ignored_texts,
            ignored_patterns=ignored_patterns,
            extra_prompt=str(translation.get("extra_prompt", "") or ""),
            dedupe_translated=bool(translation.get("dedupe_translated", False)),
            dedupe_similarity=float(translation.get("dedupe_similarity", 0.88)),
            dedupe_max_gap_seconds=float(translation.get("dedupe_max_gap_seconds", 1.2)),
            llm_cleanup_translated=bool(translation.get("llm_cleanup_translated", False)),
            llm_cleanup_max_gap_seconds=float(translation.get("llm_cleanup_max_gap_seconds", 1.8)),
            llm_cleanup_max_window_size=int(translation.get("llm_cleanup_max_window_size", 6)),
            cleanup_residual_fragments=bool(translation.get("cleanup_residual_fragments", False)),
            residual_max_gap_seconds=float(translation.get("residual_max_gap_seconds", 3.0)),
            residual_short_text_chars=int(translation.get("residual_short_text_chars", 6)),
            retime_translated=bool(translation.get("retime_translated", False)),
            retime_chars_per_second=float(translation.get("retime_chars_per_second", 7.5)),
            retime_max_extension_seconds=float(translation.get("retime_max_extension_seconds", 2.5)),
        )
        print(f"zh_srt: {zh_srt}")
    else:
        zh_srt = None

    if mode not in {"full", "extract", "translate"}:
        raise ValueError(f"未知 mode: {mode}")

    sidecar = _sidecar_config(config.get("sidecar", {}) or {})
    if sidecar.enabled:
        if input_video is None:
            input_video = _optional_path(root, config.get("input_video"))
        if input_video is None:
            raise ValueError("sidecar.enabled=true 时需要配置 input_video。")
        copied = copy_sidecar_subtitles(
            input_video,
            source_srt=source_srt,
            translated_srt=zh_srt,
            config=sidecar,
        )
        for name, path in copied.items():
            print(f"{name}: {path}")


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 YAML 对象: {path}")
    return data


def _resolve_path(root: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _optional_path(root: Path, value: Any) -> Path | None:
    if value in {None, ""}:
        return None
    return _resolve_path(root, value)


def _sidecar_config(raw: dict[str, Any]) -> SidecarConfig:
    return SidecarConfig(
        enabled=bool(raw.get("enabled", False)),
        copy_source=bool(raw.get("copy_source", True)),
        copy_translated=bool(raw.get("copy_translated", True)),
        source_suffix=str(raw.get("source_suffix", ".source")),
        translated_suffix=str(raw.get("translated_suffix", ".zh")),
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _cue_timing_config(raw: dict[str, Any]) -> CueTimingConfig:
    return CueTimingConfig(
        merge_gap_seconds=float(raw.get("merge_gap_seconds", 0.85)),
        end_padding_seconds=float(raw.get("end_padding_seconds", 0.35)),
        sample_interval_seconds=float(raw["sample_interval_seconds"]) if raw.get("sample_interval_seconds") is not None else None,
        sample_end_extension_ratio=float(raw.get("sample_end_extension_ratio", 0.75)),
        min_duration_seconds=float(raw.get("min_duration_seconds", 0.60)),
        same_text_similarity=float(raw.get("same_text_similarity", 0.88)),
        max_next_overlap_seconds=float(raw.get("max_next_overlap_seconds", 0.04)),
        enforce_no_overlap=bool(raw.get("enforce_no_overlap", True)),
        merge_same_start_seconds=float(raw.get("merge_same_start_seconds", 0.16)),
        merge_short_fragment_gap_seconds=float(raw.get("merge_short_fragment_gap_seconds", 0.50)),
        short_fragment_max_chars=int(raw.get("short_fragment_max_chars", 14)),
        short_fragment_similarity=float(raw.get("short_fragment_similarity", 0.55)),
        snapshot_similarity=float(raw.get("snapshot_similarity", 0.72)),
        snapshot_max_gap_seconds=float(raw["snapshot_max_gap_seconds"]) if raw.get("snapshot_max_gap_seconds") is not None else None,
        snapshot_min_confidence=float(raw.get("snapshot_min_confidence", 0.50)),
    )
