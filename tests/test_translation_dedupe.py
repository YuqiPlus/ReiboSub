from video_translate.models import SubtitleCue
from video_translate.translate.volcengine import cleanup_residual_fragment_cues
from video_translate.translate.volcengine import dedupe_adjacent_translated_cues
from video_translate.translate.volcengine import dedupe_exact_adjacent_translated_cues
from video_translate.translate.volcengine import _is_llm_cleanup_candidate_pair


def test_dedupe_adjacent_translated_cues_keeps_more_complete_text() -> None:
    cues = [
        SubtitleCue(1, 60.060, 61.688, "这是我们《黄金乐园》的7款钥匙扣哦"),
        SubtitleCue(2, 61.728, 63.023, "这是我们《黄金乐园》的钥匙扣哦"),
        SubtitleCue(3, 64.000, 65.000, "下一句完全不同"),
    ]

    merged = dedupe_adjacent_translated_cues(cues, similarity_threshold=0.88, max_gap_seconds=1.2)

    assert len(merged) == 2
    assert merged[0].start == 60.060
    assert merged[0].end == 63.023
    assert merged[0].text == "这是我们《黄金乐园》的7款钥匙扣哦"
    assert merged[0].index == 1
    assert merged[1].index == 2


def test_exact_adjacent_translated_duplicates_merge_even_in_locked_timing_mode() -> None:
    cues = [
        SubtitleCue(55, 245.912, 247.207, "简单对台词的禧主&小昱"),
        SubtitleCue(56, 247.247, 247.541, "简单对台词的禧主&小昱"),
        SubtitleCue(57, 247.581, 249.182, "简单对台词的禧主&小昱"),
        SubtitleCue(58, 250.000, 251.000, "下一句"),
    ]

    merged = dedupe_exact_adjacent_translated_cues(cues, max_gap_seconds=0.12)

    assert len(merged) == 2
    assert merged[0].start == 245.912
    assert merged[0].end == 249.182
    assert merged[0].text == "简单对台词的禧主&小昱"
    assert merged[1].index == 2


def test_dedupe_absorbs_repeated_phrase_and_late_fragment() -> None:
    cues = [
        SubtitleCue(1, 63.063, 69.029, "是李光洙前辈圣诞节的时候送给大家的礼物"),
        SubtitleCue(2, 69.069, 72.032, "其实是贴心的朴理事送的迷你金条"),
        SubtitleCue(3, 72.072, 72.772, "朴理事送的迷你金条，送的迷你金条"),
        SubtitleCue(4, 74.074, 74.368, "朴理事送的迷你"),
    ]

    merged = dedupe_adjacent_translated_cues(cues, similarity_threshold=0.88, max_gap_seconds=1.2)

    assert len(merged) == 2
    assert merged[0].text == "是李光洙前辈圣诞节的时候送给大家的礼物"
    assert merged[1].start == 69.069
    assert merged[1].end == 74.368
    assert merged[1].text == "其实是贴心的朴理事送的迷你金条"


def test_apply_llm_cleanup_items_merges_semantic_cleanup_result() -> None:
    from video_translate.translate.volcengine import _apply_llm_cleanup_items

    window = [
        SubtitleCue(21, 69.069, 72.032, "其实是贴心的朴理事送的迷你金条"),
        SubtitleCue(22, 72.072, 72.772, "朴理事准备的迷你小金条"),
        SubtitleCue(23, 74.074, 74.368, "这个小金条"),
    ]
    items = [
        {
            "ids": [21, 22, 23],
            "zh": "其实是贴心的朴理事送的迷你金条",
        }
    ]

    cleaned = _apply_llm_cleanup_items(window, items)

    assert len(cleaned) == 1
    assert cleaned[0].start == 69.069
    assert cleaned[0].end == 74.368
    assert cleaned[0].text == "其实是贴心的朴理事送的迷你金条"



def test_apply_llm_cleanup_items_accepts_complete_ids_out_of_order() -> None:
    from video_translate.translate.volcengine import _apply_llm_cleanup_items

    window = [
        SubtitleCue(61, 10.0, 11.0, "第一句"),
        SubtitleCue(62, 11.1, 12.0, "第二句"),
        SubtitleCue(63, 12.1, 13.0, "第三句"),
    ]
    items = [
        {"ids": [63], "zh": "第三句"},
        {"ids": [61, 62], "zh": "第一二句"},
    ]

    cleaned = _apply_llm_cleanup_items(window, items)

    assert [cue.text for cue in cleaned] == ["第一二句", "第三句"]
    assert cleaned[0].start == 10.0
    assert cleaned[0].end == 12.0


def test_apply_llm_cleanup_items_rejects_missing_ids() -> None:
    from pytest import raises
    from video_translate.translate.volcengine import _apply_llm_cleanup_items

    window = [SubtitleCue(1, 0.0, 1.0, "第一句"), SubtitleCue(2, 1.1, 2.0, "第二句")]

    with raises(ValueError):
        _apply_llm_cleanup_items(window, [{"ids": [1], "zh": "第一句"}])


def test_apply_llm_cleanup_items_can_drop_visual_noise() -> None:
    from video_translate.translate.volcengine import _apply_llm_cleanup_items

    window = [
        SubtitleCue(41, 144.811, 145.439, "小不点门店 小不点队长登场"),
        SubtitleCue(42, 145.479, 146.106, "小不点"),
        SubtitleCue(43, 146.146, 147.774, "76정 1098"),
        SubtitleCue(44, 153.153, 154.448, "各位演员们"),
    ]
    items = [
        {"ids": [41, 42], "zh": "小不点队长登场"},
        {"ids": [43], "drop": True},
        {"ids": [44], "zh": "各位演员们"},
    ]

    cleaned = _apply_llm_cleanup_items(window, items)

    assert [cue.text for cue in cleaned] == ["小不点队长登场", "各位演员们"]
    assert cleaned[0].start == 144.811
    assert cleaned[0].end == 146.106


def test_retime_translated_cues_extends_dense_text_without_overlapping_next() -> None:
    from video_translate.translate.volcengine import retime_translated_cues_for_readability

    cues = [
        SubtitleCue(1, 140.474, 141.474, "时间是1月1日，新年一开年就忙拍摄的《黄金乐园》剧组"),
        SubtitleCue(2, 144.811, 145.439, "小不点门店 小不点队长登场"),
    ]

    retimed = retime_translated_cues_for_readability(cues, chars_per_second=7.5, max_extension_seconds=2.5)

    assert retimed[0].end > 141.474
    assert retimed[0].end <= 143.974
    assert retimed[0].end < retimed[1].start


def test_retime_translated_cues_does_not_force_short_text_to_minimum() -> None:
    from video_translate.translate.volcengine import retime_translated_cues_for_readability

    cues = [SubtitleCue(1, 58.058, 58.758, "绝了")]

    retimed = retime_translated_cues_for_readability(cues, chars_per_second=7.5, max_extension_seconds=2.5)

    assert retimed[0].end == 58.758



def test_llm_cleanup_candidate_allows_delayed_ocr_variant_with_wider_gap() -> None:
    left = SubtitleCue(44, 159.159, 160.860, "为什么哈皮和小啵要当罗密欧和朱丽叶啊")
    right = SubtitleCue(45, 163.163, 165.125, "哈皮和小啵也要当罗密欧和朱丽叶")

    assert not _is_llm_cleanup_candidate_pair({}, left, right, max_gap_seconds=1.8)
    assert _is_llm_cleanup_candidate_pair({}, left, right, max_gap_seconds=3.0)



def test_cleanup_residual_fragment_cues_only_drops_hard_visual_noise() -> None:
    full_caption = "各位参演人员\n喊卡之后\n小队长和演员们相处超融洽"
    cues = [
        SubtitleCue(43, 153.153, 154.448, full_caption),
        SubtitleCue(44, 156.156, 156.450, "各位演员"),
        SubtitleCue(45, 158.825, 159.119, "고과출"),
        SubtitleCue(46, 159.159, 160.000, "969모 966모"),
        SubtitleCue(47, 160.159, 165.125, "为什么HappyBee和小啵要演罗密欧与朱丽叶啊？"),
    ]

    cleaned = cleanup_residual_fragment_cues(cues, max_gap_seconds=3.0, short_text_chars=6)

    assert [cue.text for cue in cleaned] == [
        full_caption,
        "各位演员",
        "고과출",
        "为什么HappyBee和小啵要演罗密欧与朱丽叶啊？",
    ]


def test_cleanup_residual_fragment_cues_keeps_standalone_short_subtitle() -> None:
    cues = [SubtitleCue(1, 58.058, 58.758, "绝了")]

    cleaned = cleanup_residual_fragment_cues(cues, max_gap_seconds=3.0, short_text_chars=6)

    assert cleaned == cues



def test_dedupe_uses_source_similarity_for_ocr_variants() -> None:
    translated = [
        SubtitleCue(70, 159.159, 160.120, "凭什么HappyBee和小啵要演罗密欧与朱丽叶啊"),
        SubtitleCue(73, 163.163, 165.125, "HappyBee和小啵就得演罗密欧与朱丽叶"),
    ]
    source = [
        SubtitleCue(70, 159.159, 160.120, "왜 해피비랑 뽀가 로미오 줄리엣이 되어야 하는데"),
        SubtitleCue(73, 163.163, 165.125, "해피비랑 뽀가 로미오 줄리옛이 되어야"),
    ]

    merged = dedupe_adjacent_translated_cues(
        translated,
        similarity_threshold=0.88,
        max_gap_seconds=1.2,
        source_cues=source,
        source_max_gap_seconds=3.5,
    )

    assert len(merged) == 1
    assert merged[0].start == 159.159
    assert merged[0].end == 165.125
    assert merged[0].text == "凭什么HappyBee和小啵要演罗密欧与朱丽叶啊"



def test_source_similarity_dedupe_does_not_merge_long_context_blocks() -> None:
    translated = [
        SubtitleCue(1, 120.0, 132.5, "这是一条已经合并过的较长字幕，包含很多上下文内容"),
        SubtitleCue(2, 133.0, 137.5, "这是另一条较长字幕，不应该继续被源文上下文合并"),
    ]
    source = [
        SubtitleCue(1, 120.0, 124.0, "해피비랑 뽀가 로미오 줄리엣이 되어야 하는데"),
        SubtitleCue(2, 124.1, 128.0, "해피비랑 뽀가 로미오 줄리엣이 되어야 하는데"),
        SubtitleCue(3, 133.0, 137.5, "해피비랑 뽀가 로미오 줄리옛이 되어야"),
    ]

    merged = dedupe_adjacent_translated_cues(
        translated,
        similarity_threshold=0.88,
        max_gap_seconds=1.2,
        source_cues=source,
        source_max_gap_seconds=3.5,
    )

    assert len(merged) == 2


def test_enforce_glossary_translations_replaces_source_name_leak() -> None:
    from video_translate.translate.glossary import Glossary, GlossaryEntry
    from video_translate.translate.volcengine import enforce_glossary_translations

    glossary = Glossary(entries=[GlossaryEntry(source="뽀", zh="小啵", type="nickname", aliases=["뽀가"])])
    source = [SubtitleCue(1, 1.0, 2.0, "뽀가 바로 몰입한다")]
    translated = [SubtitleCue(1, 1.0, 2.0, "뽀马上入戏")]

    cleaned = enforce_glossary_translations(source_cues=source, translated_cues=translated, glossary=glossary)

    assert cleaned[0].text == "小啵马上入戏"


def test_enforce_glossary_translations_replaces_program_alias() -> None:
    from video_translate.translate.glossary import Glossary, GlossaryEntry
    from video_translate.translate.volcengine import enforce_glossary_translations

    glossary = Glossary(
        program=GlossaryEntry(
            source="골드랜드",
            zh="黄金乐园",
            type="show_title",
            aliases=["Gold Land", "<골드랜드>"],
        )
    )
    source = [SubtitleCue(1, 10.0, 11.0, "<골드랜드>팀")]
    translated = [SubtitleCue(1, 10.0, 11.0, "Gold Land剧组")]

    cleaned = enforce_glossary_translations(source_cues=source, translated_cues=translated, glossary=glossary)

    assert cleaned[0].text == "黄金乐园剧组"


def test_cleanup_payload_includes_glossary_context() -> None:
    from video_translate.translate.glossary import Glossary, GlossaryEntry
    from video_translate.translate.volcengine import _build_cleanup_payload

    glossary = Glossary(entries=[GlossaryEntry(source="희주", zh="禧主", type="person", always=True)])
    source_by_index = {1: SubtitleCue(1, 1.0, 2.0, "바로 '희주'로 몰입하는 뽀")}
    window = [SubtitleCue(1, 1.0, 2.0, "立刻进入熙珠状态的小啵")]

    payload = _build_cleanup_payload(source_by_index, window, "model", "简体中文", "", glossary)
    content = payload["messages"][1]["content"]

    assert '"context"' in content
    assert "희주" in content
    assert "禧主" in content


def test_cleanup_payload_tells_llm_to_preserve_intentional_short_repetition() -> None:
    from video_translate.translate.volcengine import _build_cleanup_payload

    source_by_index = {
        1: SubtitleCue(1, 1.0, 2.0, "맞아"),
        2: SubtitleCue(2, 2.1, 3.0, "맞아 맞아"),
    }
    window = [SubtitleCue(1, 1.0, 2.0, "对"), SubtitleCue(2, 2.1, 3.0, "对对")]

    payload = _build_cleanup_payload(source_by_index, window, "model", "简体中文", "")
    content = payload["messages"][1]["content"]

    assert "不要因为字幕短" in content
    assert "故意重复" in content
    assert "不确定" in content


def test_strip_plain_sentence_periods_removes_only_low_value_final_periods() -> None:
    from video_translate.translate.volcengine import strip_plain_sentence_periods

    cues = [
        SubtitleCue(1, 0.0, 1.0, "这是普通陈述句。"),
        SubtitleCue(2, 1.0, 2.0, "真的可以吗？"),
        SubtitleCue(3, 2.0, 3.0, "太好了！"),
        SubtitleCue(4, 3.0, 4.0, "先这样吧……"),
        SubtitleCue(5, 4.0, 5.0, "第一行。\n第二行。"),
        SubtitleCue(6, 5.0, 6.0, "她说“你好。”"),
        SubtitleCue(7, 6.0, 7.0, "版本 1.0。"),
    ]

    cleaned = strip_plain_sentence_periods(cues)

    assert [cue.text for cue in cleaned] == [
        "这是普通陈述句",
        "真的可以吗？",
        "太好了！",
        "先这样吧……",
        "第一行\n第二行",
        "她说“你好”",
        "版本 1.0",
    ]
