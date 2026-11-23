from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from video_translate.app_settings import (
    LLM_TASK_KEYS,
    get_app_settings_payload,
    save_app_settings,
)


def _write_provider(root: Path, name: str, content: str = "") -> Path:
    path = root / "configs" / "providers" / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or f"model_name: {name}-model\n", encoding="utf-8")
    return path


def _valid_payload(provider: str = "volcano") -> dict:
    return {
        "version": 1,
        "defaults": {
            "source_language": "korean",
            "ocr_language": "auto",
            "target_language": "zh",
            "provider_profile": provider,
        },
        "tasks": {
            task: {"provider_profile": "", "model": f"{task}-model"}
            for task in LLM_TASK_KEYS
        },
    }


def test_missing_settings_use_korean_defaults_volcano_and_effective_models(tmp_path: Path) -> None:
    _write_provider(tmp_path, "alpha")
    _write_provider(tmp_path, "volcano", "model_name: configured-volcano-model\n")
    config = tmp_path / "configs" / "llm.yaml"
    config.write_text(
        "defaults:\n  model: legacy-effective-model\n",
        encoding="utf-8",
    )

    payload = get_app_settings_payload(tmp_path)

    assert payload["settings"]["defaults"] == {
        "source_language": "korean",
        "ocr_language": "auto",
        "target_language": "zh",
        "provider_profile": "volcano",
        "model": "",
    }
    assert tuple(payload["settings"]["tasks"]) == LLM_TASK_KEYS
    assert all(
        binding == {"provider_profile": "", "model": "legacy-effective-model"}
        for binding in payload["settings"]["tasks"].values()
    )
    assert [provider["id"] for provider in payload["providers"]] == ["alpha", "volcano"]


def test_missing_settings_fall_back_to_first_provider_or_blank(tmp_path: Path) -> None:
    _write_provider(tmp_path, "zeta")
    _write_provider(tmp_path, "alpha")

    with_providers = get_app_settings_payload(tmp_path)
    without_providers = get_app_settings_payload(tmp_path / "empty")

    assert with_providers["settings"]["defaults"]["provider_profile"] == "alpha"
    assert without_providers["settings"]["defaults"]["provider_profile"] == ""


def test_shared_model_roundtrip_inherits_missing_task_bindings(tmp_path: Path) -> None:
    _write_provider(tmp_path, "volcano")
    payload = {"defaults": {"provider_profile": "volcano", "model": " shared-text-model "}, "tasks": {}}
    saved = save_app_settings(payload, tmp_path)["settings"]
    assert saved["defaults"]["model"] == "shared-text-model"
    assert all(row == {"provider_profile": "", "model": ""} for row in saved["tasks"].values())
    assert get_app_settings_payload(tmp_path)["settings"] == saved


def test_delivery_preference_roundtrip_and_old_client_does_not_disable_it(tmp_path):
    from video_translate.app_settings import get_delivery_settings
    assert get_delivery_settings(tmp_path) == {'youtube_bcc': False}
    saved = save_app_settings({'delivery': {'youtube_bcc': True}}, tmp_path)
    assert saved['settings']['delivery'] == {'youtube_bcc': True}
    assert get_delivery_settings(tmp_path) == {'youtube_bcc': True}
    save_app_settings({'defaults': {'source_language': 'japanese'}}, tmp_path)
    assert get_delivery_settings(tmp_path) == {'youtube_bcc': True}
    save_app_settings({'delivery': {'youtube_bcc': False}}, tmp_path)
    assert get_delivery_settings(tmp_path) == {'youtube_bcc': False}
    for value in ['true', 1, None]:
        with pytest.raises(ValueError, match='布尔值'):
            save_app_settings({'delivery': {'youtube_bcc': value}}, tmp_path)


@pytest.mark.parametrize("model", [123, "x\nbad", "x" * 257])
def test_shared_model_validated_like_task_models(tmp_path: Path, model) -> None:
    _write_provider(tmp_path, "volcano")
    with pytest.raises(ValueError):
        save_app_settings({"defaults": {"provider_profile": "volcano", "model": model}}, tmp_path)


def test_load_normalizes_missing_fields_but_preserves_explicit_task_override(tmp_path: Path) -> None:
    _write_provider(tmp_path, "alpha")
    _write_provider(tmp_path, "volcano")
    settings_path = tmp_path / "configs" / "app_settings.yaml"
    settings_path.write_text(
        """
version: 1
defaults:
  source_language: japanese
  ocr_language: broken
  provider_profile: alpha
tasks:
  subtitle_translation:
    provider_profile: volcano
    model: custom-model
  glossary: compact-model
  asr_correction:
    provider_profile: missing-provider
""",
        encoding="utf-8",
    )

    payload = get_app_settings_payload(tmp_path)["settings"]

    assert payload["defaults"] == {
        "source_language": "japanese",
        "ocr_language": "auto",
        "target_language": "zh",
        "provider_profile": "alpha",
        "model": "",
    }
    assert payload["tasks"]["subtitle_translation"] == {
        "provider_profile": "volcano",
        "model": "custom-model",
    }
    assert payload["tasks"]["glossary"]["model"] == "compact-model"
    assert payload["tasks"]["asr_correction"]["provider_profile"] == ""


def test_load_preserves_explicit_empty_model_instead_of_restoring_legacy_model(tmp_path: Path) -> None:
    _write_provider(tmp_path, "volcano", "model_name: provider-default\n")
    config_dir = tmp_path / "configs"
    (config_dir / "llm.yaml").write_text(
        "defaults:\n  model: stale-legacy-model\n",
        encoding="utf-8",
    )
    (config_dir / "app_settings.yaml").write_text(
        """
version: 1
defaults:
  provider_profile: volcano
tasks:
  subtitle_translation:
    provider_profile: ''
    model: ''
""",
        encoding="utf-8",
    )

    settings = get_app_settings_payload(tmp_path)["settings"]

    assert settings["tasks"]["subtitle_translation"] == {
        "provider_profile": "",
        "model": "",
    }


def test_save_round_trip_is_normalized_atomic_and_drops_unknown_secret_fields(
    tmp_path: Path,
) -> None:
    _write_provider(tmp_path, "volcano")
    payload = _valid_payload()
    payload["defaults"]["source_language"] = " JAPANESE "
    payload["defaults"]["api_key"] = "must-never-be-written"
    payload["tasks"]["subtitle_translation"] = {
        "provider_profile": "volcano",
        "model": "  doubao-seed-2-0-lite  ",
        "api_key": "task-secret",
    }

    returned = save_app_settings(payload, tmp_path)
    stored_text = (tmp_path / "configs" / "app_settings.yaml").read_text(encoding="utf-8")
    stored = yaml.safe_load(stored_text)

    assert stored["defaults"]["source_language"] == "japanese"
    assert stored["tasks"]["subtitle_translation"] == {
        "provider_profile": "volcano",
        "model": "doubao-seed-2-0-lite",
    }
    assert returned["settings"] == stored
    assert "must-never-be-written" not in stored_text
    assert "task-secret" not in stored_text
    assert not list((tmp_path / "configs").glob(".app_settings.yaml.*.tmp"))


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value.update(version=2), "version"),
        (
            lambda value: value["defaults"].update(source_language="klingon"),
            "source_language",
        ),
        (
            lambda value: value["defaults"].update(ocr_language="thai"),
            "ocr_language",
        ),
        (
            lambda value: value["defaults"].update(target_language="en"),
            "target_language",
        ),
        (
            lambda value: value["defaults"].update(provider_profile="unknown"),
            "未知 provider",
        ),
        (
            lambda value: value["tasks"].update(unknown_task={"model": "x"}),
            "未知的模型任务",
        ),
        (
            lambda value: value["tasks"]["glossary"].update(provider_profile="unknown"),
            "未知 provider",
        ),
        (
            lambda value: value["tasks"]["glossary"].update(model=123),
            "model 必须是字符串",
        ),
        (
            lambda value: value["tasks"]["glossary"].update(model="x\nsecret"),
            "控制字符",
        ),
        (
            lambda value: value["tasks"]["glossary"].update(model="x" * 257),
            "不能超过",
        ),
    ],
)
def test_save_rejects_invalid_public_settings(tmp_path: Path, mutate, error: str) -> None:
    _write_provider(tmp_path, "volcano")
    payload = _valid_payload()
    mutate(payload)

    with pytest.raises(ValueError, match=error):
        save_app_settings(payload, tmp_path)

    assert not (tmp_path / "configs" / "app_settings.yaml").exists()


def test_browser_payload_never_contains_resolved_credentials_or_urls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_provider(
        tmp_path,
        "volcano",
        """
api_key: SAFE_SETTINGS_TEST_KEY
base_url: SAFE_SETTINGS_TEST_URL
model_name: safe-model
""",
    )
    monkeypatch.setenv("SAFE_SETTINGS_TEST_KEY", "super-secret-token")
    monkeypatch.setenv("SAFE_SETTINGS_TEST_URL", "https://private-gateway.example/v1")

    serialized = json.dumps(get_app_settings_payload(tmp_path), ensure_ascii=False)

    assert "super-secret-token" not in serialized
    assert "private-gateway.example" not in serialized
    assert "api_key\"" not in serialized
    assert "base_url\"" not in serialized
    assert "key_configured" in serialized
