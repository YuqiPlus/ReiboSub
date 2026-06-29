from __future__ import annotations

from typing import Any


TARGET_CHINESE_PREFIXES = ("zh", "zh-hans", "zh-hant", "zh-cn", "zh-tw", "zh-hk")


def build_agent_plan(
    captions: list[dict[str, Any]],
    *,
    target_language: str = "zh",
    detected_source_language: str = "",
    embedded_subtitle_hint: str = "unknown",
) -> dict[str, Any]:
    normalized = [_normalize_caption(item) for item in captions if isinstance(item, dict)]
    target_caption = _find_caption(normalized, target_language, kind="manual")
    if target_caption:
        return _plan(
            route="download_target_subtitle",
            selected_subtitle=target_caption,
            requires_translation=False,
            needs_source_correction=False,
                confidence=0.95,
                recommended_action="download_subtitle",
                reasons=["检测到目标语言字幕，优先直接下载。"],
            )

    source_language = detected_source_language.strip().lower()
    english_manual = _find_caption(normalized, "en", kind="manual")
    if source_language:
        manual_source = _find_caption(normalized, source_language, kind="manual")
        if manual_source:
            if english_manual and not _language_matches(manual_source.get("lang_key", ""), _language_key("en")):
                return _plan(
                    route="dual_subtitle_reference",
                    selected_subtitle=manual_source,
                    reference_subtitle=english_manual,
                    requires_translation=True,
                    needs_source_correction=False,
                    confidence=0.9,
                    recommended_action="download_dual_subtitles_then_translate",
                    reasons=["检测到原声语言人工字幕和英文人工字幕；推荐以原文字幕为主，英文字幕只作为理解和 glossary 审核参考。"],
                )
            return _plan(
                route="translate_source_subtitle",
                selected_subtitle=manual_source,
                requires_translation=True,
                needs_source_correction=False,
                confidence=0.88,
                recommended_action="download_then_translate_subtitle",
                reasons=["没有目标语言字幕，检测到原声语言的作者字幕，适合作为翻译源。"],
            )
    hint = _normalize_embedded_subtitle_hint(embedded_subtitle_hint)
    if english_manual and hint == "yes":
        return _plan(
            route="hybrid_anchor_ocr",
            selected_subtitle=english_manual,
            requires_translation=True,
            needs_source_correction=False,
            confidence=0.82,
            recommended_action="download_anchor_subtitle_then_hybrid_ocr",
            reasons=["检测到英文人工字幕，且用户确认画面有内嵌字幕；推荐用英文时间轴定轴，并用韩文 OCR 提升翻译精度。"],
        )

    manual_candidates = [item for item in normalized if item.get("kind") == "manual"]
    if manual_candidates and not source_language:
        return _plan(
            route="probe_audio_language",
            selected_subtitle=None,
            requires_translation=True,
            needs_source_correction=False,
            confidence=0.55,
            recommended_action="probe_audio_language",
            reasons=["检测到作者上传字幕，但还不知道原视频音源语言；需要先探测音源语言，再选择最合适的字幕源。"],
            candidate_subtitles=manual_candidates,
        )

    english = english_manual
    if english:
        return _plan(
            route="translate_fallback_subtitle",
            selected_subtitle=english,
            requires_translation=True,
            needs_source_correction=english["kind"] == "auto",
            confidence=0.62,
            recommended_action="download_then_translate_subtitle",
            reasons=["没有目标语言或原声语言字幕，可用英文字幕作为中转源，但建议人工确认。"],
        )

    if hint == "yes":
        return _plan(
            route="ocr",
            selected_subtitle=None,
            requires_translation=True,
            needs_source_correction=False,
            confidence=0.78,
            recommended_action="run_ocr",
            reasons=["用户确认画面有内嵌字幕，优先 OCR。"],
        )
    if hint == "no":
        return _plan(
            route="asr",
            selected_subtitle=None,
            requires_translation=True,
            needs_source_correction=True,
            confidence=0.78,
            recommended_action="run_asr",
            reasons=["用户确认画面没有可用内嵌字幕，优先 ASR。"],
        )
    return _plan(
        route="diagnose_ocr_asr",
        selected_subtitle=None,
        requires_translation=True,
        needs_source_correction=False,
        confidence=0.5,
        recommended_action="diagnose_video_route",
        reasons=["没有可用字幕且用户不确定是否有内嵌字幕，建议先做 OCR/ASR 样本诊断。"],
    )


def _plan(
    *,
    route: str,
    selected_subtitle: dict[str, Any] | None,
    requires_translation: bool,
    needs_source_correction: bool,
    confidence: float,
    recommended_action: str,
    reasons: list[str],
    candidate_subtitles: list[dict[str, Any]] | None = None,
    reference_subtitle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "route": route,
        "selected_subtitle": selected_subtitle,
        "reference_subtitle": reference_subtitle,
        "candidate_subtitles": candidate_subtitles or [],
        "requires_translation": requires_translation,
        "needs_source_correction": needs_source_correction,
        "confidence": confidence,
        "recommended_action": recommended_action,
        "reasons": reasons,
    }


def _normalize_caption(item: dict[str, Any]) -> dict[str, Any]:
    lang = str(item.get("lang") or item.get("language") or "").strip()
    kind = str(item.get("kind") or "manual").strip().lower()
    result = dict(item)
    result["lang"] = lang
    result["lang_key"] = _language_key(lang)
    result["kind"] = "auto" if kind == "auto" else "manual"
    return result


def _find_caption(captions: list[dict[str, Any]], language: str, *, kind: str) -> dict[str, Any] | None:
    wanted = _language_key(language)
    for caption in captions:
        if caption["kind"] != kind:
            continue
        if _language_matches(caption["lang_key"], wanted):
            return caption
    return None


def _language_matches(candidate: str, wanted: str) -> bool:
    if wanted in {"zh", "zho", "chi", "cn"}:
        return candidate.startswith(TARGET_CHINESE_PREFIXES)
    return candidate == wanted or candidate.startswith(wanted + "-")


def _language_key(language: str) -> str:
    return str(language or "").strip().lower().replace("_", "-")


def _normalize_embedded_subtitle_hint(value: str) -> str:
    key = str(value or "unknown").strip().lower()
    if key in {"yes", "true", "1", "有", "有内嵌字幕"}:
        return "yes"
    if key in {"no", "false", "0", "没有", "无", "没有内嵌字幕"}:
        return "no"
    return "unknown"
