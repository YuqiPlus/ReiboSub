import pytest

from video_translate.translate import volcengine
from video_translate.translate.volcengine import _parse_translation_mapping
from video_translate.translate.volcengine import _request_translation_mapping


def test_parse_translation_mapping_extracts_json_from_wrapped_text() -> None:
    content = '好的，结果如下：\n[{"id": 1, "zh": "你好"}]\n完成。'

    assert _parse_translation_mapping(content) == {1: "你好"}


def test_request_translation_mapping_repairs_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_request_translation(url, api_key, payload):
        calls.append(payload)
        if len(calls) == 1:
            return '[{"id": 1, "zh": "你好"} {"id": 2, "zh": "世界"}]'
        return '[{"id": 1, "zh": "你好"}, {"id": 2, "zh": "世界"}]'

    monkeypatch.setattr(volcengine, "_request_translation", fake_request_translation)

    mapping = _request_translation_mapping(
        "https://example.test/chat/completions",
        "key",
        {"messages": [{"role": "user", "content": "translate"}], "temperature": 0.2},
        "1/1",
    )

    assert mapping == {1: "你好", 2: "世界"}
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0
    assert "不是合法 JSON" in calls[1]["messages"][-1]["content"]
