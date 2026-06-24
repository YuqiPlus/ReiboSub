from __future__ import annotations

from video_translate.agent_planner import build_agent_plan


def test_agent_plan_prefers_manual_chinese_subtitle():
    captions = [
        {"lang": "en", "kind": "manual", "label": "en · 手动字幕"},
        {"lang": "zh-Hans", "kind": "manual", "label": "zh-Hans · 手动字幕"},
        {"lang": "ko", "kind": "manual", "label": "ko · 手动字幕"},
    ]

    plan = build_agent_plan(captions, target_language="zh", detected_source_language="ko")

    assert plan["route"] == "download_target_subtitle"
    assert plan["selected_subtitle"]["lang"] == "zh-Hans"
    assert plan["requires_translation"] is False


def test_agent_plan_uses_source_language_manual_subtitle_when_no_chinese():
    captions = [
        {"lang": "en", "kind": "manual"},
        {"lang": "ko", "kind": "manual"},
    ]

    plan = build_agent_plan(captions, target_language="zh", detected_source_language="ko")

    assert plan["route"] == "translate_source_subtitle"
    assert plan["selected_subtitle"]["lang"] == "ko"
    assert plan["requires_translation"] is True


def test_agent_plan_does_not_recommend_target_language_auto_subtitle():
    captions = [
        {"lang": "zh-Hans", "kind": "auto"},
        {"lang": "ko", "kind": "auto"},
    ]

    plan = build_agent_plan(captions, target_language="zh", detected_source_language="ko")

    assert plan["route"] == "diagnose_ocr_asr"
    assert plan["selected_subtitle"] is None


def test_agent_plan_does_not_recommend_source_language_auto_subtitle():
    captions = [
        {"lang": "en", "kind": "manual"},
        {"lang": "ko", "kind": "auto"},
    ]

    plan = build_agent_plan(captions, target_language="zh", detected_source_language="ko")

    assert plan["route"] == "translate_fallback_subtitle"
    assert plan["selected_subtitle"]["lang"] == "en"
    assert plan["needs_source_correction"] is False


def test_agent_plan_does_not_recommend_english_auto_fallback_subtitle():
    captions = [{"lang": "en", "kind": "auto"}]

    plan = build_agent_plan(captions, target_language="zh", detected_source_language="ko")

    assert plan["route"] == "diagnose_ocr_asr"
    assert plan["selected_subtitle"] is None


def test_agent_plan_recommends_hybrid_when_english_manual_and_embedded_subtitles_exist():
    captions = [{"lang": "en", "kind": "manual", "label": "en · 人工字幕"}]

    plan = build_agent_plan(captions, target_language="zh", embedded_subtitle_hint="yes")

    assert plan["route"] == "hybrid_anchor_ocr"
    assert plan["selected_subtitle"]["lang"] == "en"
    assert plan["recommended_action"] == "download_anchor_subtitle_then_hybrid_ocr"
    assert plan["requires_translation"] is True


def test_agent_plan_recommends_ocr_when_user_knows_embedded_subtitles_exist():
    plan = build_agent_plan([], target_language="zh", embedded_subtitle_hint="yes")

    assert plan["route"] == "ocr"
    assert plan["recommended_action"] == "run_ocr"


def test_agent_plan_recommends_asr_when_user_knows_no_embedded_subtitles():
    plan = build_agent_plan([], target_language="zh", embedded_subtitle_hint="no")

    assert plan["route"] == "asr"
    assert plan["recommended_action"] == "run_asr"


def test_agent_plan_recommends_diagnosis_when_embedded_subtitle_is_unknown():
    plan = build_agent_plan([], target_language="zh", embedded_subtitle_hint="unknown")

    assert plan["route"] == "diagnose_ocr_asr"
    assert plan["recommended_action"] == "diagnose_video_route"
