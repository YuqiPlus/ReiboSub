from __future__ import annotations

from pathlib import Path
from typing import Any
import shutil

from video_translate.ocr.llm_refine import (
    OCRRefinementConfig,
    SourceCleanupConfig,
    cleanup_ocr_source_with_llm,
    refine_ocr_source_with_llm,
)
from video_translate.languages import normalize_source_language, ocr_language_for_source
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
        source_language = normalize_source_language(config.get("source_language", "korean"))
        outputs = extract_subtitles_from_video(
            input_video,
            output_dir,
            lang=ocr_language_for_source(source_language),
            sample_fps=float(ocr.get("sample_fps", 3.0)),
            bottom_ratio=float(ocr.get("bottom_ratio", 0.42)),
            crop_top_ratio=_optional_float(ocr.get("crop_top_ratio")),
            crop_bottom_ratio=float(ocr.get("crop_bottom_ratio", 0.0)),
            crop_left_ratio=float(ocr.get("crop_left_ratio", 0.0)),
            crop_right_ratio=float(ocr.get("crop_right_ratio", 0.0)),
            exclude_enabled=bool(ocr.get("exclude_enabled", False)),
            exclude_top_ratio=float(ocr.get("exclude_top_ratio", 0.04)),
            exclude_bottom_ratio=float(ocr.get("exclude_bottom_ratio", 0.82)),
            exclude_left_ratio=float(ocr.get("exclude_left_ratio", 0.76)),
            exclude_right_ratio=float(ocr.get("exclude_right_ratio", 0.02)),
            min_confidence=float(ocr.get("min_confidence", 0.45)),
            refine_timing_boundaries=bool(ocr.get("refine_timing_boundaries", False)),
            timing_refine_max_frames=int(ocr.get("timing_refine_max_frames", 24)),
            scan_full_frame=bool(ocr.get("scan_full_frame", False)),
            auto_trim_side_noise=bool(ocr.get("auto_trim_side_noise", True)),
            device=str(ocr.get("device", "auto")),
            extraction_mode=str(ocr.get("extraction_mode", "auto")),
            ignored_texts=ignored_texts,
            ignored_contains=ignored_contains,
            ignored_patterns=ignored_patterns,
            cue_timing=cue_timing,
        )
        source_srt = outputs["source_srt"]
        refinement = config.get("ocr_refinement", {}) or {}
        if str(refinement.get("mode") or "none") == "llm_boxes":
            machine_srt = output_dir / "source.machine.srt"
            refined_srt = output_dir / "source.refined.srt"
            shutil.copyfile(source_srt, machine_srt)
            refine_ocr_source_with_llm(
                machine_srt,
                outputs["ocr_boxes"],
                refined_srt,
                model=refinement.get("model"),
                base_url=refinement.get("base_url"),
                config=OCRRefinementConfig(
                    batch_size=int(refinement.get("batch_size", 12)),
                    window_padding_seconds=float(refinement.get("window_padding_seconds", 0.50)),
                    max_boxes_per_frame=int(refinement.get("max_boxes_per_frame", 16)),
                ),
            )
            shutil.copyfile(refined_srt, source_srt)
            print(f"machine_source_srt: {machine_srt}")
            print(f"refined_source_srt: {refined_srt}")
        source_cleanup = config.get("source_cleanup", {}) or {}
        if str(source_cleanup.get("mode") or "none") == "llm_context":
            cleanup_input_srt = output_dir / "source.before_cleanup.srt"
            cleaned_srt = output_dir / "source.cleaned.srt"
            shutil.copyfile(source_srt, cleanup_input_srt)
            cleanup_ocr_source_with_llm(
                cleanup_input_srt,
                cleaned_srt,
                model=source_cleanup.get("model"),
                base_url=source_cleanup.get("base_url"),
                config=SourceCleanupConfig(
                    batch_size=int(source_cleanup.get("batch_size", 18)),
                    overlap=int(source_cleanup.get("overlap", 3)),
                ),
            )
            if not bool(source_cleanup.get("preserve_source", False)):
                shutil.copyfile(cleaned_srt, source_srt)
            print(f"pre_cleanup_source_srt: {cleanup_input_srt}")
            print(f"cleaned_source_srt: {cleaned_srt}")
        print(f"source_srt: {source_srt}")

    if mode in {"full", "translate"}:
        translation = config.get("translation", {}) or {}
        provider = str(translation.get("provider", "openai-compatible")).lower().replace("_", "-")
        if provider not in {"openai-compatible", "volcengine"}:
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



def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)

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
        flicker_smoothing_max_duration_seconds=float(raw.get("flicker_smoothing_max_duration_seconds", 0.0)),
        flicker_smoothing_max_gap_seconds=float(raw.get("flicker_smoothing_max_gap_seconds", 0.35)),
    )
