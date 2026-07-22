from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml

from video_translate.app_settings import APP_SETTINGS_PATH, save_app_settings
from video_translate.provider_management import (
    create_provider_profile,
    delete_provider_profile,
    update_provider_profile,
)
from video_translate.provider_profiles import PROVIDER_PROFILES_PATH, get_provider_profile
from video_translate.provider_secrets import PROVIDER_SECRETS_PATH, update_provider_connection_settings


def _write_profile(root: Path, profile_id: str, *, model: str) -> Path:
    path = root / "configs" / "providers" / f"{profile_id}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"label: {profile_id}\nprovider: {profile_id}\nmodel_name: {model}\n",
        encoding="utf-8",
    )
    return path


def test_create_provider_keeps_secret_connection_out_of_profile_yaml(tmp_path: Path) -> None:
    result = create_provider_profile(
        {
            "id": "custom-gateway",
            "label": "Custom Gateway",
            "base_url": "https://gateway.example/v1",
            "api_key": "top-secret-key",
            "default_model": "custom-model",
            "models_url": "https://gateway.example/v1/models",
            "models": ["custom-model-2"],
        },
        tmp_path,
    )

    profile_path = tmp_path / PROVIDER_PROFILES_PATH
    profile_text = profile_path.read_text(encoding="utf-8")
    profile_data = yaml.safe_load(profile_text)["providers"]["custom-gateway"]
    secrets_path = tmp_path / PROVIDER_SECRETS_PATH
    secrets_data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    resolved = get_provider_profile("custom-gateway", tmp_path)

    assert profile_data == {
        "label": "Custom Gateway",
        "provider": "custom-gateway",
        "backend": "openai-compatible",
        "default_model": "custom-model",
        "models": ["custom-model-2"],
    }
    assert "top-secret-key" not in profile_text
    assert "gateway.example" not in profile_text
    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(secrets_path.stat().st_mode) == 0o600
    assert secrets_data["providers"]["custom-gateway"] == {
        "api_key": "top-secret-key",
        "base_url": "https://gateway.example/v1",
        "models_url": "https://gateway.example/v1/models",
    }
    assert resolved is not None
    assert resolved.api_key == "top-secret-key"
    assert resolved.base_url == "https://gateway.example/v1"
    assert resolved.models == ("custom-model", "custom-model-2")
    assert resolved.static_models == ("custom-model-2",)
    assert result["provider"]["id"] == "custom-gateway"
    assert "top-secret-key" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"id": "../../escape", "base_url": "https://safe.example/v1"}, "provider id"),
        ({"id": "bad.yml", "base_url": "https://safe.example/v1"}, "扩展名"),
        ({"id": "valid", "base_url": "file:///tmp/api"}, "http/https URL"),
        ({"id": "valid", "base_url": "https://user:pass@example.com/v1"}, "用户信息"),
        ({"id": "valid", "base_url": "https://safe.example/v1", "unexpected": True}, "不支持"),
    ],
)
def test_create_provider_rejects_unsafe_payloads(
    tmp_path: Path,
    payload: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        create_provider_profile(payload, tmp_path)
    assert not (tmp_path / PROVIDER_PROFILES_PATH).exists()


def test_create_rejects_duplicate_and_provider_directory_symlink(tmp_path: Path) -> None:
    _write_profile(tmp_path, "existing", model="model-a")
    with pytest.raises(ValueError, match="已存在"):
        create_provider_profile(
            {"id": "existing", "base_url": "https://safe.example/v1"},
            tmp_path,
        )

    linked_root = tmp_path / "linked-root"
    target = tmp_path / "outside"
    target.mkdir()
    (linked_root / "configs").mkdir(parents=True)
    (linked_root / "configs" / "providers").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        create_provider_profile(
            {"id": "new", "base_url": "https://safe.example/v1"},
            linked_root,
        )


def test_create_clears_orphan_secret_before_reusing_id(tmp_path: Path) -> None:
    secret_path = tmp_path / PROVIDER_SECRETS_PATH
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(
        "version: 1\nproviders:\n  reused:\n    api_key: stale-secret\n",
        encoding="utf-8",
    )

    create_provider_profile(
        {"id": "reused", "base_url": "https://new.example/v1"},
        tmp_path,
    )
    profile = get_provider_profile("reused", tmp_path)
    document = yaml.safe_load(secret_path.read_text(encoding="utf-8"))

    assert profile is not None
    assert profile.api_key is None
    assert document["providers"]["reused"] == {"base_url": "https://new.example/v1"}
    assert "stale-secret" not in secret_path.read_text(encoding="utf-8")


def test_first_management_write_migrates_legacy_connections_without_leaking_them(
    tmp_path: Path,
    monkeypatch,
) -> None:
    literal_path = tmp_path / "configs" / "providers" / "literal.yml"
    literal_path.parent.mkdir(parents=True, exist_ok=True)
    literal_path.write_text(
        """
label: Literal
api_key: literal-secret
base_url: https://literal.example/v1
models_url: https://literal.example/v1/models
model_name: literal-model
""".lstrip(),
        encoding="utf-8",
    )
    env_path = literal_path.with_name("environment.yml")
    env_path.write_text(
        """
label: Environment
api_key: LEGACY_API_KEY
base_url: LEGACY_BASE_URL
models_url: LEGACY_MODELS_URL
model_name: env-model
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEGACY_API_KEY", "environment-secret")
    monkeypatch.setenv("LEGACY_BASE_URL", "https://environment.example/v1")
    monkeypatch.setenv("LEGACY_MODELS_URL", "https://environment.example/v1/models")

    update_provider_profile("literal", {"label": "Literal Updated"}, tmp_path)

    registry_path = tmp_path / PROVIDER_PROFILES_PATH
    registry_text = registry_path.read_text(encoding="utf-8")
    registry = yaml.safe_load(registry_text)
    secrets = yaml.safe_load(
        (tmp_path / PROVIDER_SECRETS_PATH).read_text(encoding="utf-8")
    )
    monkeypatch.delenv("LEGACY_API_KEY")
    monkeypatch.delenv("LEGACY_BASE_URL")
    monkeypatch.delenv("LEGACY_MODELS_URL")

    assert registry["providers"]["literal"]["label"] == "Literal Updated"
    assert registry["providers"]["environment"]["default_model"] == "env-model"
    for sensitive_value in (
        "literal-secret",
        "environment-secret",
        "literal.example",
        "environment.example",
        "LEGACY_API_KEY",
        "LEGACY_BASE_URL",
        "LEGACY_MODELS_URL",
    ):
        assert sensitive_value not in registry_text
    assert secrets["providers"]["literal"] == {
        "api_key": "literal-secret",
        "base_url": "https://literal.example/v1",
        "models_url": "https://literal.example/v1/models",
    }
    assert secrets["providers"]["environment"] == {
        "api_key": "environment-secret",
        "base_url": "https://environment.example/v1",
        "models_url": "https://environment.example/v1/models",
    }
    assert get_provider_profile("literal", tmp_path).api_key == "literal-secret"
    assert get_provider_profile("environment", tmp_path).base_url == "https://environment.example/v1"


def test_delete_provider_migrates_default_tasks_and_removes_secret(tmp_path: Path) -> None:
    first_path = _write_profile(tmp_path, "first", model="first-model")
    _write_profile(tmp_path, "second", model="second-model")
    update_provider_connection_settings(
        "first",
        {"api_key": "first-secret", "base_url": "https://first.example/v1"},
        tmp_path,
    )
    update_provider_connection_settings(
        "second",
        {"api_key": "second-secret", "base_url": "https://second.example/v1"},
        tmp_path,
    )
    save_app_settings(
        {
            "version": 1,
            "defaults": {
                "source_language": "korean",
                "ocr_language": "auto",
                "target_language": "zh",
                "provider_profile": "first",
            },
            "tasks": {
                "subtitle_translation": {"provider_profile": "", "model": "first-special"},
                "glossary": {"provider_profile": "first", "model": "first-glossary"},
            },
        },
        tmp_path,
    )

    result = delete_provider_profile("first", "second", tmp_path)
    saved = yaml.safe_load((tmp_path / APP_SETTINGS_PATH).read_text(encoding="utf-8"))
    secrets = yaml.safe_load((tmp_path / PROVIDER_SECRETS_PATH).read_text(encoding="utf-8"))

    assert first_path.exists()  # Legacy files are left untouched after one-time migration.
    registry = yaml.safe_load((tmp_path / PROVIDER_PROFILES_PATH).read_text(encoding="utf-8"))
    assert "first" not in registry["providers"]
    assert "second" in registry["providers"]
    assert get_provider_profile("first", tmp_path) is None
    assert "first" not in secrets["providers"]
    assert secrets["providers"]["second"]["api_key"] == "second-secret"
    assert saved["defaults"]["provider_profile"] == "second"
    assert saved["tasks"]["subtitle_translation"] == {
        "provider_profile": "",
        "model": "second-model",
    }
    assert saved["tasks"]["glossary"] == {
        "provider_profile": "",
        "model": "second-model",
    }
    assert result["deleted_provider_id"] == "first"
    assert result["replacement_provider_id"] == "second"
    assert result["default_replaced"] is True
    assert "subtitle_translation" in result["affected_tasks"]
    assert "first-secret" not in json.dumps(result, ensure_ascii=False)


def test_delete_explicit_task_reference_uses_replacement_without_changing_default(tmp_path: Path) -> None:
    _write_profile(tmp_path, "default", model="default-model")
    _write_profile(tmp_path, "removed", model="removed-model")
    _write_profile(tmp_path, "replacement", model="replacement-model")
    save_app_settings(
        {
            "version": 1,
            "defaults": {
                "source_language": "korean",
                "ocr_language": "auto",
                "target_language": "zh",
                "provider_profile": "default",
            },
            "tasks": {
                "glossary": {"provider_profile": "removed", "model": "removed-model"},
            },
        },
        tmp_path,
    )

    delete_provider_profile("removed", "replacement", tmp_path)
    saved = yaml.safe_load((tmp_path / APP_SETTINGS_PATH).read_text(encoding="utf-8"))

    assert saved["defaults"]["provider_profile"] == "default"
    assert saved["tasks"]["glossary"] == {
        "provider_profile": "replacement",
        "model": "replacement-model",
    }


def test_delete_rejects_unknown_self_replacement_and_last_provider(tmp_path: Path) -> None:
    _write_profile(tmp_path, "only", model="only-model")
    with pytest.raises(ValueError, match="相同"):
        delete_provider_profile("only", "only", tmp_path)
    with pytest.raises(ValueError, match="未知 provider"):
        delete_provider_profile("missing", "only", tmp_path)

    _write_profile(tmp_path, "temporary", model="temporary-model")
    delete_provider_profile("temporary", "only", tmp_path)
    with pytest.raises(ValueError, match="至少需要保留"):
        delete_provider_profile("only", "missing", tmp_path)


def test_update_provider_metadata_migrates_connection_and_drops_legacy_extras(tmp_path: Path) -> None:
    profile_path = tmp_path / "configs" / "providers" / "editable.yml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        """
api_key: EDITABLE_KEY
base_url: https://profile.example/v1
label: Old Label
api_model_name: old-default
model_name: old-default
model_names:
  - old-default
  - old-extra
temperature: 0.25
timeout: 120
""".lstrip(),
        encoding="utf-8",
    )
    update_provider_connection_settings(
        "editable",
        {"api_key": "local-secret", "base_url": "https://local.example/v1"},
        tmp_path,
    )

    result = update_provider_profile(
        "editable",
        {
            "label": "New Label",
            "default_model": "new-default",
            "models": ["new-extra"],
        },
        tmp_path,
    )
    legacy_document = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    registry_path = tmp_path / PROVIDER_PROFILES_PATH
    document = yaml.safe_load(registry_path.read_text(encoding="utf-8"))["providers"]["editable"]
    secrets = yaml.safe_load((tmp_path / PROVIDER_SECRETS_PATH).read_text(encoding="utf-8"))
    resolved = get_provider_profile("editable", tmp_path)

    assert legacy_document["api_key"] == "EDITABLE_KEY"
    assert legacy_document["base_url"] == "https://profile.example/v1"
    assert legacy_document["temperature"] == 0.25
    assert legacy_document["timeout"] == 120
    assert document["label"] == "New Label"
    assert document["default_model"] == "new-default"
    assert document["models"] == ["new-extra"]
    assert "api_key" not in document
    assert "base_url" not in document
    assert "temperature" not in document
    assert "timeout" not in document
    assert stat.S_IMODE(registry_path.stat().st_mode) == 0o600
    assert secrets["providers"]["editable"]["api_key"] == "local-secret"
    assert resolved is not None
    assert resolved.label == "New Label"
    assert resolved.default_model == "new-default"
    assert resolved.models == ("new-default", "new-extra")
    assert resolved.static_models == ("new-extra",)
    assert result["provider"]["label"] == "New Label"
    assert "local-secret" not in json.dumps(result, ensure_ascii=False)


def test_update_provider_can_clear_optional_metadata_without_touching_secret(tmp_path: Path) -> None:
    _write_profile(tmp_path, "editable", model="old-model")
    update_provider_connection_settings(
        "editable",
        {"api_key": "keep-secret", "base_url": "https://provider.example/v1"},
        tmp_path,
    )

    update_provider_profile(
        "editable",
        {"label": "", "default_model": "", "models": []},
        tmp_path,
    )
    document = yaml.safe_load(
        (tmp_path / PROVIDER_PROFILES_PATH).read_text(encoding="utf-8")
    )["providers"]["editable"]
    resolved = get_provider_profile("editable", tmp_path)

    assert "label" not in document
    assert "default_model" not in document
    assert "models" not in document
    assert resolved is not None
    assert resolved.label == "editable"
    assert resolved.default_model is None
    assert resolved.api_key == "keep-secret"


def test_update_provider_rejects_unknown_profile_and_fields(tmp_path: Path) -> None:
    _write_profile(tmp_path, "known", model="known-model")
    with pytest.raises(ValueError, match="未知 provider"):
        update_provider_profile("missing", {"label": "Missing"}, tmp_path)
    with pytest.raises(ValueError, match="不支持"):
        update_provider_profile("known", {"api_key": "must-use-connection-editor"}, tmp_path)
    with pytest.raises(ValueError, match="没有需要更新"):
        update_provider_profile("known", {}, tmp_path)
