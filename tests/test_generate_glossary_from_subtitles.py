from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


def _load_module():
    path = Path(__file__).resolve().parents[1] / "generate_glossary_from_subtitles.py"
    spec = importlib.util.spec_from_file_location("generate_glossary_from_subtitles_1_linux", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_candidate_response_accepts_fenced_json():
    module = _load_module()

    parsed = module.parse_candidate_response(
        '```json\n{"program": null, "characters": [{"source": "박보영", "suggested_zh": "朴宝英"}], "terms": []}\n```'
    )

    assert parsed["characters"][0]["source"] == "박보영"
    assert parsed["characters"][0]["suggested_zh"] == "朴宝英"


def test_merge_candidate_drafts_dedupes_aliases_and_evidence_ids():
    module = _load_module()
    left = {
        "program": None,
        "characters": [
            {"source": "박보영", "suggested_zh": "朴宝英", "aliases": ["보영"], "evidence_ids": [1], "confidence": 0.7}
        ],
        "terms": [],
    }
    right = {
        "program": None,
        "characters": [
            {"source": "박 보영", "aliases": ["Park Bo-young", "보영"], "evidence_ids": [1, 4], "confidence": 0.6}
        ],
        "terms": [],
    }

    merged = module.merge_candidate_drafts(left, right)

    item = merged["characters"][0]
    assert item["suggested_zh"] == "朴宝英"
    assert item["aliases"] == ["보영", "Park Bo-young"]
    assert item["evidence_ids"] == [1, 4]


def test_normalize_draft_for_yaml_leaves_zh_empty_by_default():
    module = _load_module()
    draft = {
        "program": None,
        "characters": [
            {"source": "박보영", "suggested_zh": "朴宝英", "aliases": ["보영"], "confidence": 0.9}
        ],
        "terms": [],
    }

    data = module.normalize_draft_for_yaml(draft)

    assert data["characters"][0]["zh"] == ""
    assert data["characters"][0]["suggested_zh"] == "朴宝英"
    assert data["characters"][0]["always"] is True


def test_write_glossary_yaml_roundtrip(tmp_path):
    module = _load_module()
    out = tmp_path / "draft.yaml"
    data = {"characters": [{"source": "박보영", "zh": "", "suggested_zh": "朴宝英", "type": "person", "always": True}]}

    module.write_glossary_yaml(data, out, source_srt=tmp_path / "source.srt")
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert loaded["characters"][0]["source"] == "박보영"
    assert loaded["characters"][0]["zh"] == ""
    assert loaded["characters"][0]["suggested_zh"] == "朴宝英"


def test_merge_candidate_drafts_accepts_list_fields_from_llm():
    module = _load_module()
    left = {
        "program": None,
        "characters": [],
        "terms": [
            {"source": "Hong Kong Disneyland", "suggested_zh": "香港迪士尼乐园", "note": "place", "confidence": 0.5}
        ],
    }
    right = {
        "program": None,
        "characters": [],
        "terms": [
            {
                "source": "Hong Kong Disneyland",
                "suggested_zh": "香港迪士尼乐园",
                "note": ["place", "20th anniversary"],
                "aliases": ["HK Disneyland"],
                "evidence_ids": [9],
                "confidence": 0.9,
            }
        ],
    }

    merged = module.merge_candidate_drafts(left, right)

    item = merged["terms"][0]
    assert item["suggested_zh"] == "香港迪士尼乐园"
    assert item["note"] == ["place", "20th anniversary"]
    assert item["aliases"] == ["HK Disneyland"]


def test_filter_low_value_candidates_drops_common_known_terms():
    module = _load_module()
    draft = {
        "program": None,
        "characters": [{"source": "박보영", "suggested_zh": "朴宝英"}],
        "terms": [
            {"source": "Hong Kong Disneyland", "suggested_zh": "香港迪士尼乐园"},
            {"source": "뽀블리", "suggested_zh": "啵宝莉"},
            {"source": "배우", "suggested_zh": "演员"},
        ],
    }

    filtered = module.filter_low_value_candidates(draft)

    terms = [item["source"] for item in filtered["terms"]]
    assert "Hong Kong Disneyland" not in terms
    assert "배우" not in terms
    assert terms == ["뽀블리"]
    assert filtered["characters"][0]["source"] == "박보영"


def test_filter_low_value_candidates_keeps_common_term_when_hint_mentions_it():
    module = _load_module()
    draft = {
        "program": None,
        "characters": [],
        "terms": [{"source": "Hong Kong Disneyland", "suggested_zh": "香港迪士尼"}],
    }

    filtered = module.filter_low_value_candidates(draft, extra_hint="Hong Kong Disneyland 固定译为港迪")

    assert filtered["terms"][0]["source"] == "Hong Kong Disneyland"


def test_parse_candidate_response_extracts_json_object_from_surrounding_text():
    module = _load_module()

    parsed = module.parse_candidate_response('说明文字 {"program": null, "characters": [], "terms": [{"source": "희주"}]} trailing')

    assert parsed["terms"][0]["source"] == "희주"


def test_parse_or_repair_candidate_response_repairs_invalid_json(monkeypatch):
    module = _load_module()
    calls = []

    def fake_request(endpoint, api_key, payload):
        calls.append((endpoint, api_key, payload))
        return '{"program": null, "characters": [{"source": "박보영", "suggested_zh": "朴宝英"}], "terms": []}'

    monkeypatch.setattr(module, "_request_chat_completion", fake_request)

    parsed = module.parse_or_repair_candidate_response(
        '{"program": null, "characters": [{"source": "박보영" "suggested_zh": "朴宝英"}], "terms": []}',
        endpoint="endpoint",
        api_key="key",
        model="model",
        batch_index=9,
        total_batches=10,
    )

    assert calls
    assert calls[0][2]["temperature"] == 0.0
    assert parsed["characters"][0]["source"] == "박보영"


def test_parse_or_repair_candidate_response_skips_unrepairable_json(monkeypatch):
    module = _load_module()

    def fake_request(endpoint, api_key, payload):
        return 'still not json'

    monkeypatch.setattr(module, "_request_chat_completion", fake_request)

    parsed = module.parse_or_repair_candidate_response(
        '{bad json',
        endpoint="endpoint",
        api_key="key",
        model="model",
        batch_index=9,
        total_batches=10,
    )

    assert parsed == {"program": None, "characters": [], "terms": []}
