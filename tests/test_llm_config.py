from __future__ import annotations

from pathlib import Path

from video_translate.llm_config import LLMTaskConfig, load_llm_task_config


def _clear_llm_env(monkeypatch):
    for name in [
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_MODEL",
        "ASR_CORRECTION_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_load_llm_task_config_reads_task_specific_model(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  provider: openai-compatible
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
    _clear_llm_env(monkeypatch)

    task = load_llm_task_config("asr_correction", root=tmp_path)

    assert task == LLMTaskConfig(
        model="doubao-seed-2.0-lite",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        provider="openai-compatible",
    )


def test_load_llm_task_config_falls_back_to_env_default_before_config_default(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text("defaults:\n  model: glm-latest\n", encoding="utf-8")
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "env-default-model")
    monkeypatch.setenv("ARK_MODEL", "ark-env-model")

    known = load_llm_task_config("glossary", root=tmp_path)
    missing_file = load_llm_task_config("title_translation", root=tmp_path / "missing")

    assert known.model == "env-default-model"
    assert missing_file.model == "env-default-model"


def test_load_llm_task_config_task_model_overrides_env_default(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  model: default-model
tasks:
  title_translation:
    model: small-task-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "global-env-model")

    task = load_llm_task_config("title_translation", root=tmp_path)
    missing_task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task.model == "small-task-model"
    assert missing_task.model == "global-env-model"


def test_load_llm_task_config_reads_generic_openai_compatible_env(tmp_path: Path, monkeypatch):
    config = tmp_path / "configs" / "llm.yaml"
    config.parent.mkdir()
    config.write_text(
        """
defaults:
  base_url: https://example.invalid/should-not-win
tasks: {}
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://openai-compatible.example/v1")
    monkeypatch.setenv("LLM_MODEL", "global-model")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example")
    monkeypatch.setenv("ARK_MODEL", "ark-model")

    task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task.api_key == "generic-key"
    assert task.base_url == "https://openai-compatible.example/v1"
    assert task.model == "global-model"


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
    _clear_llm_env(monkeypatch)
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
    _clear_llm_env(monkeypatch)

    task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task == LLMTaskConfig(
        model="doubao-seed-2.0-pro",
        fallback_models=("doubao-seed-2.0-lite", "minimax-m2.7"),
    )


def test_load_llm_task_config_resolves_roles_from_generic_defaults(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """
defaults:
  provider: openai-compatible
  base_url: https://ark.cn-beijing.volces.com/api/coding/v3
  api_key_env: LLM_API_KEY
  models:
    default: doubao-seed-2.0-pro
    pro: doubao-seed-2.0-pro
    lite: doubao-seed-2.0-lite
tasks:
  title_translation:
    model_role: lite
  subtitle_translation:
    model_role: pro
    fallback_roles:
      - lite
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "generic-key")

    title = load_llm_task_config("title_translation", root=tmp_path)
    subtitles = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert title == LLMTaskConfig(
        model="doubao-seed-2.0-lite",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        api_key="generic-key",
        provider="openai-compatible",
    )
    assert subtitles == LLMTaskConfig(
        model="doubao-seed-2.0-pro",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        api_key="generic-key",
        provider="openai-compatible",
        fallback_models=("doubao-seed-2.0-lite",),
    )


def test_load_llm_task_config_can_use_generic_base_url_env_name(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """
defaults:
  provider: openai-compatible
  base_url_env: LLM_BASE_URL
  api_key_env: LLM_API_KEY
  models:
    lite: doubao-seed-2.0-lite
tasks:
  asr_correction:
    model_role: lite
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://generic.example/v1")

    task = load_llm_task_config("asr_correction", root=tmp_path)

    assert task == LLMTaskConfig(
        model="doubao-seed-2.0-lite",
        base_url="https://generic.example/v1",
        api_key="generic-key",
        provider="openai-compatible",
    )
