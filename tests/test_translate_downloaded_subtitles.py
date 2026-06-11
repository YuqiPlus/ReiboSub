from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "translate_downloaded_subtitles.py"
    spec = importlib.util.spec_from_file_location("translate_downloaded_subtitles_1_linux", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_output_path_uses_zh_suffix():
    module = _load_module()

    assert module.default_output_path(Path("video.ko.srt")) == Path("video.ko.zh.srt")


def test_translate_downloaded_subtitles_rejects_non_srt(tmp_path):
    module = _load_module()
    source = tmp_path / "video.ko.vtt"
    source.write_text("WEBVTT\n", encoding="utf-8")

    with pytest.raises(ValueError):
        module.translate_downloaded_subtitles(source)


def test_translate_downloaded_subtitles_preserves_timing_mode(monkeypatch, tmp_path):
    module = _load_module()
    source = tmp_path / "video.ko.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\n박보영\n", encoding="utf-8")
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text("characters: []\n", encoding="utf-8")
    calls = {}

    def fake_translate_srt_with_volcengine(source_srt, out_srt, **kwargs):
        calls["source_srt"] = source_srt
        calls["out_srt"] = out_srt
        calls.update(kwargs)
        return out_srt

    monkeypatch.setattr(module, "translate_srt_with_volcengine", fake_translate_srt_with_volcengine)

    out = module.translate_downloaded_subtitles(source, glossary=glossary)

    assert out == tmp_path / "video.ko.zh.srt"
    assert calls["source_srt"] == source.resolve()
    assert calls["glossary_path"] == glossary
    assert calls["dedupe_translated"] is False
    assert calls["llm_cleanup_translated"] is False
    assert calls["cleanup_residual_fragments"] is False
    assert calls["retime_translated"] is False
