from __future__ import annotations

import json
import requests
from types import SimpleNamespace

from video_translate.translate import volcengine


class _FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def test_request_translation_retries_timeout(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return _FakeResponse()

    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "5")
    monkeypatch.setenv("LLM_REQUEST_RETRIES", "2")
    monkeypatch.setattr(volcengine.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(volcengine.requests, "post", fake_post)

    assert volcengine._request_translation("https://example.test", "key", {"model": "m"}) == "ok"
    assert len(calls) == 2
    assert calls[0]["timeout"] == 5.0


def test_translate_batch_splits_after_timeout(monkeypatch, tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "\n\n".join(
            [
                "1\n00:00:00,000 --> 00:00:01,000\n하나",
                "2\n00:00:01,000 --> 00:00:02,000\n둘",
                "3\n00:00:02,000 --> 00:00:03,000\n셋",
                "4\n00:00:03,000 --> 00:00:04,000\n넷",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.srt"
    calls = []

    def fake_request_mapping(_endpoint, _key, payload, batch_label, **kwargs):
        user = json.loads(payload["messages"][1]["content"])
        ids = [item["id"] for item in user["subtitles"]]
        calls.append((batch_label, ids))
        if ids == [1, 2, 3, 4]:
            raise requests.Timeout("slow batch")
        return {cue_id: f"译文{cue_id}" for cue_id in ids}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(volcengine, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        volcengine,
        "load_llm_task_config",
        lambda *args, **kwargs: SimpleNamespace(model="model", base_url="https://example.test", fallback_models=()),
    )
    monkeypatch.setattr(volcengine, "_request_translation_mapping", fake_request_mapping)

    volcengine.translate_srt_with_volcengine(source, out, batch_size=4)

    assert calls == [("1/1", [1, 2, 3, 4]), ("1/1a", [1, 2]), ("1/1b", [3, 4])]
    text = out.read_text(encoding="utf-8")
    assert "译文1" in text
    assert "译文4" in text


def test_translate_batch_uses_fallback_model_after_timeout(monkeypatch, tmp_path):
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n하나\n", encoding="utf-8")
    out = tmp_path / "out.srt"
    calls = []

    def fake_request_mapping(_endpoint, _key, payload, batch_label, **kwargs):
        model = payload["model"]
        user = json.loads(payload["messages"][1]["content"])
        ids = [item["id"] for item in user["subtitles"]]
        calls.append((batch_label, model, ids, kwargs))
        if model == "doubao-seed-2.0-pro":
            raise requests.Timeout("slow primary")
        return {cue_id: f"备用译文{cue_id}" for cue_id in ids}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(volcengine, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        volcengine,
        "load_llm_task_config",
        lambda *args, **kwargs: SimpleNamespace(
            model="doubao-seed-2.0-pro",
            base_url="https://example.test",
            fallback_models=("doubao-seed-2.0-lite",),
        ),
    )
    monkeypatch.setattr(volcengine, "_request_translation_mapping", fake_request_mapping)

    volcengine.translate_srt_with_volcengine(source, out, batch_size=1)

    assert calls == [
        ("1/1", "doubao-seed-2.0-pro", [1], {"max_attempts": 1}),
        ("1/1 fallback doubao-seed-2.0-lite", "doubao-seed-2.0-lite", [1], {"max_attempts": 1}),
    ]
    assert "备用译文1" in out.read_text(encoding="utf-8")


def test_translate_merges_exact_adjacent_duplicates_when_enabled(monkeypatch, tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "\n\n".join(
            [
                "1\n00:04:05,912 --> 00:04:07,207\n간단하게",
                "2\n00:04:07,247 --> 00:04:07,541\n간단하게",
                "3\n00:04:07,581 --> 00:04:09,182\n간단하게",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.srt"

    def fake_request_mapping(_endpoint, _key, payload, batch_label, **kwargs):
        user = json.loads(payload["messages"][1]["content"])
        return {item["id"]: "简单对台词的禧主&小昱" for item in user["subtitles"]}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(volcengine, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        volcengine,
        "load_llm_task_config",
        lambda *args, **kwargs: SimpleNamespace(model="model", base_url="https://example.test", fallback_models=()),
    )
    monkeypatch.setattr(volcengine, "_request_translation_mapping", fake_request_mapping)

    volcengine.translate_srt_with_volcengine(source, out, batch_size=3, dedupe_translated=False)

    text = out.read_text(encoding="utf-8")
    assert text.count("简单对台词的禧主&小昱") == 1
    assert "00:04:05,912 --> 00:04:09,182" in text


def test_translate_only_preserves_source_cue_structure(monkeypatch, tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "\n\n".join(
            [
                "1\n00:04:05,912 --> 00:04:07,207\n간단하게",
                "2\n00:04:07,247 --> 00:04:07,541\n간단하게",
                "3\n00:04:07,581 --> 00:04:09,182\n간단하게",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.srt"

    def fake_request_mapping(_endpoint, _key, payload, batch_label, **kwargs):
        user = json.loads(payload["messages"][1]["content"])
        return {item["id"]: "简单对台词的禧主&小昱" for item in user["subtitles"]}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(volcengine, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        volcengine,
        "load_llm_task_config",
        lambda *args, **kwargs: SimpleNamespace(model="model", base_url="https://example.test", fallback_models=()),
    )
    monkeypatch.setattr(volcengine, "_request_translation_mapping", fake_request_mapping)

    source_cues = volcengine.read_srt(source)
    volcengine.translate_srt_with_volcengine(
        source,
        out,
        batch_size=3,
        dedupe_translated=False,
        dedupe_exact_translated=False,
    )
    translated_cues = volcengine.read_srt(out)

    assert [(cue.index, cue.start, cue.end) for cue in translated_cues] == [
        (cue.index, cue.start, cue.end) for cue in source_cues
    ]
    assert [cue.text for cue in translated_cues] == ["简单对台词的禧主&小昱"] * 3


def test_translate_srt_strips_plain_sentence_periods_before_write(monkeypatch, tmp_path):
    from video_translate.translate import volcengine

    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    out = tmp_path / "zh.srt"

    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_MODEL", "model")
    monkeypatch.setattr(volcengine, "_request_translation", lambda endpoint, key, payload, **kwargs: '[{"id":1,"zh":"你好。"}]')

    volcengine.translate_srt_with_volcengine(source, out, batch_size=1)

    assert "你好\n" in out.read_text(encoding="utf-8")
    assert "你好。" not in out.read_text(encoding="utf-8")
