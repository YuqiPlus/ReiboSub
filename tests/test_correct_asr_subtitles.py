from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import requests

from video_translate.tools import correct_asr


def test_correct_asr_subtitles_preserves_timing_and_replaces_text(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n릴 짱이에요\n\n"
        "2\n00:00:01,000 --> 00:00:02,500\n다이브 안녕\n",
        encoding="utf-8",
    )
    out = tmp_path / "source.corrected.srt"

    def fake_request(*args, **kwargs):
        return {1: "렐짱이에요", 2: "다이브 안녕"}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setenv("ARK_MODEL", "model")
    monkeypatch.setattr(correct_asr, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(correct_asr, "_request_correction_mapping", fake_request)

    result = correct_asr.correct_asr_srt(source, out, source_language="korean", extra_prompt="아이브 멤버 레이의 브이로그")

    assert result == out
    assert out.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,000\n렐짱이에요\n\n"
        "2\n00:00:01,000 --> 00:00:02,500\n다이브 안녕\n"
    )


def test_build_correction_payload_keeps_task_in_source_language():
    payload = correct_asr.build_correction_payload(
        [
            correct_asr.SubtitleCue(index=1, start=0.0, end=1.0, text="릴 짱이에요"),
        ],
        model="model-id",
        source_language="korean",
        glossary_context={"glossary": [{"source": "렐짱", "zh": "怜酱"}]},
        extra_prompt="人物是 Rei",
    )

    content = payload["messages"][1]["content"]
    assert payload["model"] == "model-id"
    assert "不要翻译成中文" in content
    assert "릴 짱이에요" in content
    assert "렐짱" in content
    assert "人物是 Rei" in content


def test_correct_asr_subtitles_splits_batch_after_timeout(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.srt"
    source.write_text(
        "\n\n".join(
            [
                "1\n00:00:00,000 --> 00:00:01,000\n릴 짱",
                "2\n00:00:01,000 --> 00:00:02,000\n다이브",
                "3\n00:00:02,000 --> 00:00:03,000\n롬유",
                "4\n00:00:03,000 --> 00:00:04,000\n버니 핑크",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "source.corrected.srt"
    calls = []

    def fake_request(_endpoint, _key, payload):
        user = correct_asr.json.loads(payload["messages"][1]["content"])
        ids = [item["id"] for item in user["subtitles"]]
        calls.append(ids)
        if ids == [1, 2, 3, 4]:
            raise requests.Timeout("slow correction")
        return {cue_id: f"교정{cue_id}" for cue_id in ids}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setenv("ARK_MODEL", "model")
    monkeypatch.setattr(correct_asr, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(correct_asr, "_request_correction_mapping", fake_request)

    correct_asr.correct_asr_srt(source, out, batch_size=4)

    assert calls == [[1, 2, 3, 4], [1, 2], [3, 4]]
    text = out.read_text(encoding="utf-8")
    assert "교정1" in text
    assert "교정4" in text


def test_correct_asr_subtitles_uses_configured_task_model(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n릴 짱\n", encoding="utf-8")
    out = tmp_path / "source.corrected.srt"
    seen_models = []

    def fake_request(_endpoint, _key, payload):
        seen_models.append(payload["model"])
        return {1: "렐짱"}

    monkeypatch.setattr(correct_asr, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(correct_asr, "_request_correction_mapping", fake_request)
    monkeypatch.setattr(
        correct_asr,
        "load_llm_task_config",
        lambda *args, **kwargs: SimpleNamespace(
            model="configured-asr-lite",
            base_url="https://example.test/v1",
            api_key="key",
        ),
    )

    correct_asr.correct_asr_srt(source, out)

    assert seen_models == ["configured-asr-lite"]


def test_correct_asr_subtitles_allows_model_override(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n릴 짱\n", encoding="utf-8")
    out = tmp_path / "source.corrected.srt"
    seen_models = []

    def fake_request(_endpoint, _key, payload):
        seen_models.append(payload["model"])
        return {1: "렐짱"}

    monkeypatch.setenv("ARK_API_KEY", "key")
    monkeypatch.setattr(correct_asr, "_load_dotenv", lambda _path: None)
    monkeypatch.setattr(correct_asr, "_request_correction_mapping", fake_request)

    correct_asr.correct_asr_srt(source, out, model="minimax-m2.7")

    assert seen_models == ["minimax-m2.7"]


def test_build_correction_payload_includes_ocr_reference():
    payload = correct_asr.build_correction_payload(
        [correct_asr.SubtitleCue(index=10, start=5.0, end=7.0, text="박봉열 선생님")],
        model="model-id",
        source_language="korean",
        glossary_context={},
        reference_cues=[
            correct_asr.SubtitleCue(index=1, start=4.8, end=6.8, text="박보영 선생님"),
            correct_asr.SubtitleCue(index=2, start=20.0, end=22.0, text="멀리 있는 자막"),
        ],
    )

    content = payload["messages"][1]["content"]
    data = correct_asr.json.loads(content)
    assert data["subtitles"][0]["ocr_reference"][0]["text"] == "박보영 선생님"
    assert "멀리 있는 자막" not in content
    assert "OCR" in content
    assert "ASR" in content
