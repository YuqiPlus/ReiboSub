from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import video_translate.llm_config as llm_config
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


def test_load_llm_task_config_accepts_both_env_field_spellings(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """
defaults:
  model: default-model
  base_url_env: DEFAULT_BASE_URL
  api_key_env: DEFAULT_API_KEY
tasks:
  title_translation:
    env_base_url: TASK_BASE_URL
    env_api_key: TASK_API_KEY
  glossary: {}
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("DEFAULT_BASE_URL", "https://default.example/v1")
    monkeypatch.setenv("DEFAULT_API_KEY", "default-key")
    monkeypatch.setenv("TASK_BASE_URL", "https://task.example/v1")
    monkeypatch.setenv("TASK_API_KEY", "task-key")

    title = load_llm_task_config("title_translation", root=tmp_path)
    glossary = load_llm_task_config("glossary", root=tmp_path)

    assert title.base_url == "https://task.example/v1"
    assert title.api_key == "task-key"
    assert glossary.base_url == "https://default.example/v1"
    assert glossary.api_key == "default-key"


def test_app_settings_task_overlay_selects_profile_and_clears_legacy_fallbacks(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """
defaults:
  provider: openai-compatible
  base_url: https://legacy.example/v1
tasks:
  subtitle_translation:
    model: legacy-model
    fallback_models:
      - legacy-fallback
""",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
defaults:
  provider_profile: default-profile
tasks:
  subtitle_translation:
    provider_profile: selected-profile
    model: selected-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("SELECTED_API_KEY", "selected-key")
    profiles = {
        "default-profile": SimpleNamespace(
            base_url="https://default-profile.example/v1",
            api_key_env="DEFAULT_PROFILE_API_KEY",
            provider="openai-compatible",
        ),
        "selected-profile": SimpleNamespace(
            base_url="https://selected-profile.example/v1",
            api_key_env="SELECTED_API_KEY",
            provider="openai-compatible",
        ),
    }
    monkeypatch.setattr(llm_config, "_get_provider_profile", lambda profile_id, root: profiles.get(profile_id))

    task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task == LLMTaskConfig(
        model="selected-model",
        base_url="https://selected-profile.example/v1",
        api_key="selected-key",
        provider="openai-compatible",
        provider_profile="selected-profile",
    )


def test_app_settings_explicit_values_override_overlay_and_overlay_fallbacks_are_kept(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        "defaults:\n  model: legacy-model\n  base_url: https://legacy.example/v1\n",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
tasks:
  glossary:
    provider_profile: selected-profile
    model: selected-model
    fallback_models:
      - selected-fallback
      - explicit-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_get_provider_profile",
        lambda profile_id, root: {
            "base_url": "https://profile.example/v1",
            "api_key": "profile-key",
            "provider": "openai-compatible",
        } if profile_id == "selected-profile" else None,
    )

    task = load_llm_task_config(
        "glossary",
        root=tmp_path,
        explicit_model="explicit-model",
        explicit_base_url="https://explicit.example/v1",
    )

    assert task == LLMTaskConfig(
        model="explicit-model",
        base_url="https://explicit.example/v1",
        api_key="profile-key",
        provider="openai-compatible",
        fallback_models=("selected-fallback",),
        provider_profile="selected-profile",
    )


def test_invalid_task_profile_falls_back_to_default_profile_but_keeps_task_model(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        "defaults:\n  model: legacy-model\n  base_url: https://legacy.example/v1\n",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
defaults:
  provider_profile: working-profile
tasks:
  glossary:
    provider_profile: missing-profile
    model: overlay-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_get_provider_profile",
        lambda profile_id, root: {
            "base_url": "https://working.example/v1",
            "api_key": "working-key",
            "provider": "openai-compatible",
        } if profile_id == "working-profile" else None,
    )

    task = load_llm_task_config("glossary", root=tmp_path)

    assert task.model == "overlay-model"
    assert task.base_url == "https://working.example/v1"
    assert task.api_key == "working-key"
    assert task.provider_profile == "working-profile"


def test_missing_profiles_fall_back_to_legacy_connection_and_keep_overlay_model(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """
defaults:
  model: legacy-model
  base_url: https://legacy.example/v1
  api_key_env: LEGACY_API_KEY
""",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
defaults:
  provider_profile: also-missing
tasks:
  glossary:
    provider_profile: missing-profile
    model: overlay-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LEGACY_API_KEY", "legacy-key")
    monkeypatch.setattr(llm_config, "_get_provider_profile", lambda profile_id, root: None)

    task = load_llm_task_config("glossary", root=tmp_path)

    assert task == LLMTaskConfig(
        model="overlay-model",
        base_url="https://legacy.example/v1",
        api_key="legacy-key",
        provider="openai-compatible",
    )


def test_app_settings_overlay_integrates_with_provider_profile_files(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configs"
    provider_dir = config_dir / "providers"
    provider_dir.mkdir(parents=True)
    (config_dir / "llm.yaml").write_text(
        "defaults:\n  provider: openai-compatible\n  model: legacy-model\n",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
defaults:
  provider_profile: selected-profile
tasks:
  subtitle_translation:
    model: provider-model
""",
        encoding="utf-8",
    )
    (provider_dir / "selected-profile.yml").write_text(
        """
api_key: SELECTED_PROFILE_API_KEY
base_url: SELECTED_PROFILE_BASE_URL
model_name: provider-model
""",
        encoding="utf-8",
    )
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("SELECTED_PROFILE_API_KEY", "provider-key")
    monkeypatch.setenv("SELECTED_PROFILE_BASE_URL", "https://provider.example/v1")

    task = load_llm_task_config("subtitle_translation", root=tmp_path)

    assert task == LLMTaskConfig(
        model="provider-model",
        base_url="https://provider.example/v1",
        api_key="provider-key",
        provider="openai-compatible",
        provider_profile="selected-profile",
    )
