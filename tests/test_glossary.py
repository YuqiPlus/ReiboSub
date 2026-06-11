from pathlib import Path

from video_translate.translate.glossary import load_glossary


def test_glossary_matches_aliases_and_always_entries(tmp_path: Path) -> None:
    path = tmp_path / "glossary.yaml"
    path.write_text(
        '''program:
  source: "골드랜드"
  zh: "黄金乐园"
  always: true
characters:
  - source: "희주"
    zh: "禧主"
    aliases: ["'희주'", "히주"]
    always: true
terms:
  - source: "쪼꼬미대장"
    zh: "小不点队长"
    aliases: ["쪼꼬미매장"]
''',
        encoding="utf-8",
    )

    glossary = load_glossary(path)
    context = glossary.to_context(["바로 '희주' 로 몰입하는 뽀", "쪼꼬미 매장 등장"])

    assert context["program"]["zh"] == "黄金乐园"
    translations = {entry["source"]: entry["zh"] for entry in context["glossary"]}
    assert translations["희주"] == "禧主"
    assert translations["쪼꼬미대장"] == "小不点队长"


def test_glossary_skips_unfilled_draft_entries(tmp_path: Path) -> None:
    path = tmp_path / "draft_glossary.yaml"
    path.write_text(
        '''program:
  source: "제주삼다수"
  zh: ""
  suggested_zh: "济州三多水"
characters:
  - source: "박보영"
    zh: ""
    suggested_zh: "朴宝英"
    always: true
terms:
  - source: "광고 비하인드"
    zh: "广告花絮"
''',
        encoding="utf-8",
    )

    glossary = load_glossary(path)
    context = glossary.to_context(["박보영 제주삼다수 광고 비하인드"])

    assert "program" not in context
    translations = {entry["source"]: entry["zh"] for entry in context["glossary"]}
    assert "박보영" not in translations
    assert translations["광고 비하인드"] == "广告花絮"
