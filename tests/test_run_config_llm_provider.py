from __future__ import annotations

from pathlib import Path

from video_translate import run_config as run_config_mod


def test_run_config_accepts_openai_compatible_translation_provider(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        f"""
mode: translate
source_srt: {source}
output_dir: {tmp_path / 'out'}
target_language: 简体中文
translation:
  provider: openai-compatible
  batch_size: 1
""",
        encoding="utf-8",
    )
    called = {}

    def fake_translate(source_srt, zh_srt, **kwargs):
        called["source_srt"] = source_srt
        called["zh_srt"] = zh_srt
        Path(zh_srt).parent.mkdir(parents=True, exist_ok=True)
        Path(zh_srt).write_text("translated", encoding="utf-8")

    monkeypatch.setattr(run_config_mod, "translate_srt_with_volcengine", fake_translate)

    run_config_mod.run_config(config_path)

    assert called["source_srt"] == source
    assert called["zh_srt"] == tmp_path / "out" / "zh.srt"
