from __future__ import annotations

from pathlib import Path

from video_translate.llm_config import LLMTaskConfig, load_llm_task_config


def test_load_llm_task_config_reads_task_specific_model(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  provider: volcengine
  base_url: https://ark.cn-beijing.volces.com/api/coding/v3
  model: doubao-seed-2.0-pro
tasks:
  asr_correction:
    model: doubao-seed-2.0-lite
  subtitle_translation:
    model: minimax-m2.7
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("ARK_MODEL", raising=False)
    monkeypatch.delenv("ASR_CORRECTION_MODEL", raising=False)

    task = load_llm_task_config("asr_correction", root=tmp_path)

    assert task == LLMTaskConfig(
        model="doubao-seed-2.0-lite",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        provider="volcengine",
    )


def test_load_llm_task_config_falls_back_to_default_then_ark_model(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text("defaults:\n  model: glm-latest\n", encoding="utf-8")
    monkeypatch.setenv("ARK_MODEL", "env-model")

    known = load_llm_task_config("glossary", root=tmp_path)
    missing_file = load_llm_task_config("title_translation", root=tmp_path / "missing")

    assert known.model == "glm-latest"
    assert missing_file.model == "env-model"


def test_load_llm_task_config_uses_task_env_override(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  model: default-model
tasks:
  asr_correction:
    model: configured-lite
    env_model: ASR_CORRECTION_MODEL
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ASR_CORRECTION_MODEL", "override-model")

    task = load_llm_task_config("asr_correction", root=tmp_path)

    assert task.model == "override-model"


def test_load_llm_task_config_reads_fallback_models(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  model: default-model
tasks:
  subtitle_translation:
    model: doubao-seed-2.0-pro
    fallback_models:
      - doubao-seed-2.0-lite
      - minimax-m2.7
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("ARK_MODEL", raising=False)

    task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task == LLMTaskConfig(
        model="doubao-seed-2.0-pro",
        fallback_models=("doubao-seed-2.0-lite", "minimax-m2.7"),
    )
