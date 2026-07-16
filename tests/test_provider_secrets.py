from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import yaml

from video_translate.provider_profiles import fetch_provider_models, get_provider_profile
from video_translate.provider_secrets import (
    PROVIDER_SECRETS_PATH,
    get_provider_connection_settings,
    update_provider_connection_settings,
)


def _write_profile(root: Path, name: str, content: str) -> Path:
    path = root / "configs" / "providers" / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_local_connection_has_priority_and_public_result_never_leaks_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "ark",
        """
api_key: TEST_ARK_KEY
base_url: TEST_ARK_BASE
models_url: https://profile.example/v1/models
model_name: model-a
""",
    )
    monkeypatch.setenv("TEST_ARK_KEY", "environment-secret")
    monkeypatch.setenv("TEST_ARK_BASE", "https://environment.example/v1")

    public = update_provider_connection_settings(
        "ark",
        {
            "api_key": "local-secret",
            "base_url": "https://local.example/v1/",
            "models_url": "https://local.example/catalog/models",
        },
        tmp_path,
    )
    profile = get_provider_profile("ark", tmp_path)

    assert profile is not None
    assert profile.api_key == "local-secret"
    assert profile.base_url == "https://local.example/v1"
    assert profile.models_url == "https://local.example/catalog/models"
    assert profile.api_key_source == "local"
    assert profile.base_url_source == "local"
    assert profile.models_url_source == "local"
    assert public == get_provider_connection_settings("ark", tmp_path)
    assert public["key_configured"] is True
    assert public["local_key_configured"] is True
    assert public["key_source"] == "local"
    assert public["base_url_source"] == "local"
    assert public["storage_path"] == "configs/provider_secrets.yaml"
    serialized = json.dumps(public, ensure_ascii=False)
    assert "local-secret" not in serialized
    assert "environment-secret" not in serialized
    assert "api_key" not in public


def test_write_is_atomic_private_and_preserves_other_providers(tmp_path: Path) -> None:
    _write_profile(tmp_path, "one", "model_name: one\n")
    _write_profile(tmp_path, "two", "model_name: two\n")

    update_provider_connection_settings(
        "one",
        {"api_key": "secret-one", "base_url": "https://one.example/v1"},
        tmp_path,
    )
    update_provider_connection_settings(
        "two",
        {
            "api_key": "secret-two",
            "base_url": "http://localhost:9000/v1",
            "models_url": "http://localhost:9000/models",
        },
        tmp_path,
    )

    storage = tmp_path / PROVIDER_SECRETS_PATH
    document = yaml.safe_load(storage.read_text(encoding="utf-8"))
    assert document == {
        "version": 1,
        "providers": {
            "one": {"api_key": "secret-one", "base_url": "https://one.example/v1"},
            "two": {
                "api_key": "secret-two",
                "base_url": "http://localhost:9000/v1",
                "models_url": "http://localhost:9000/models",
            },
        },
    }
    assert stat.S_IMODE(storage.stat().st_mode) == 0o600
    assert not list(storage.parent.glob(f".{storage.name}.*.tmp"))


def test_import_current_copies_environment_values_then_works_without_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "imported",
        """
api_key_env: IMPORT_KEY
base_url_env: IMPORT_BASE
models_url_env: IMPORT_MODELS
model_name: imported-model
""",
    )
    monkeypatch.setenv("IMPORT_KEY", "secret-from-env")
    monkeypatch.setenv("IMPORT_BASE", "https://env.example/v1")
    monkeypatch.setenv("IMPORT_MODELS", "https://env.example/v1/catalog")

    public = update_provider_connection_settings(
        "imported",
        {"import_current": True},
        tmp_path,
    )
    assert public["key_source"] == "local"
    assert "secret-from-env" not in json.dumps(public)

    monkeypatch.delenv("IMPORT_KEY")
    monkeypatch.delenv("IMPORT_BASE")
    monkeypatch.delenv("IMPORT_MODELS")
    profile = get_provider_profile("imported", tmp_path)

    assert profile is not None
    assert profile.api_key == "secret-from-env"
    assert profile.base_url == "https://env.example/v1"
    assert profile.models_url == "https://env.example/v1/catalog"
    assert profile.api_key_source == "local"
    assert profile.base_url_source == "local"
    assert profile.models_url_source == "local"


def test_clear_flags_remove_only_local_values_and_restore_fallbacks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "fallback",
        """
api_key: FALLBACK_KEY
base_url: https://profile.example/v1
models_url: https://profile.example/v1/models
model_name: fallback-model
""",
    )
    monkeypatch.setenv("FALLBACK_KEY", "fallback-secret")
    update_provider_connection_settings(
        "fallback",
        {
            "api_key": "local-secret",
            "base_url": "https://profile.example/local-v1",
            "models_url": "https://profile.example/local-models",
        },
        tmp_path,
    )

    public = update_provider_connection_settings(
        "fallback",
        {
            "clear_api_key": True,
            "clear_base_url": True,
            "clear_models_url": True,
        },
        tmp_path,
    )

    assert public["key_configured"] is True
    assert public["local_key_configured"] is False
    assert public["key_source"] == "environment"
    assert public["base_url"] == "https://profile.example/v1"
    assert public["base_url_source"] == "profile"
    assert public["models_url_source"] == "profile"
    document = yaml.safe_load((tmp_path / PROVIDER_SECRETS_PATH).read_text(encoding="utf-8"))
    assert document == {"version": 1, "providers": {}}


def test_clear_key_cannot_reuse_fallback_key_when_base_origin_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "guarded",
        """
api_key: GUARDED_KEY
base_url: https://fallback.example/v1
model_name: guarded-model
""",
    )
    monkeypatch.setenv("GUARDED_KEY", "fallback-secret")
    update_provider_connection_settings(
        "guarded",
        {"api_key": "local-secret", "base_url": "https://local.example/v1"},
        tmp_path,
    )

    with pytest.raises(ValueError, match="必须同时填写新的 api_key"):
        update_provider_connection_settings(
            "guarded",
            {"clear_api_key": True, "clear_base_url": True},
            tmp_path,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"api_key": ""}, "api_key 不能为空"),
        ({"base_url": "file:///tmp/socket"}, "http/https URL"),
        ({"models_url": "provider.example/models"}, "http/https URL"),
        ({"base_url": "https://secret@example.com/v1"}, "不能包含用户信息"),
        ({"models_url": "https://example.com/models#secret"}, "URL 片段"),
        ({"clear_api_key": "yes"}, "必须是布尔值"),
        ({"api_key": "secret", "clear_api_key": True}, "同时设置和清除"),
        ({"import_current": True, "clear_base_url": True}, "不能和 clear"),
        ({"unexpected": True}, "不支持"),
    ],
)
def test_update_rejects_ambiguous_or_unsafe_values(
    tmp_path: Path,
    payload: dict,
    message: str,
) -> None:
    _write_profile(tmp_path, "safe", "model_name: safe\n")

    with pytest.raises(ValueError, match=message):
        update_provider_connection_settings("safe", payload, tmp_path)


def test_update_requires_a_trusted_profile_id(tmp_path: Path) -> None:
    _write_profile(tmp_path, "known", "model_name: known\n")

    with pytest.raises(ValueError, match="未知 provider"):
        update_provider_connection_settings("missing", {"api_key": "secret"}, tmp_path)
    with pytest.raises(ValueError, match="provider id"):
        get_provider_connection_settings("../../.env", tmp_path)


def test_invalid_yaml_error_never_echoes_secret_source_lines(tmp_path: Path) -> None:
    _write_profile(tmp_path, "known", "model_name: known\n")
    storage = tmp_path / PROVIDER_SECRETS_PATH
    storage.parent.mkdir(parents=True, exist_ok=True)
    storage.write_text("version: 1\nproviders: [secret-value\n", encoding="utf-8")

    with pytest.raises(ValueError) as error:
        get_provider_connection_settings("known", tmp_path)

    assert str(error.value) == "provider_secrets.yaml 不是有效的 YAML"
    assert "secret-value" not in str(error.value)


def test_origin_change_requires_new_key_but_same_origin_path_change_does_not(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "origin",
        """
api_key: ORIGIN_KEY
base_url: https://one.example/v1
model_name: origin-model
""",
    )
    monkeypatch.setenv("ORIGIN_KEY", "old-secret")

    same_origin = update_provider_connection_settings(
        "origin",
        {"base_url": "https://one.example/v2"},
        tmp_path,
    )
    assert same_origin["base_url"] == "https://one.example/v2"

    with pytest.raises(ValueError, match="必须同时填写新的 api_key"):
        update_provider_connection_settings(
            "origin",
            {"base_url": "https://two.example/v1"},
            tmp_path,
        )

    moved = update_provider_connection_settings(
        "origin",
        {"base_url": "https://two.example/v1", "api_key": "new-secret"},
        tmp_path,
    )
    assert moved["base_url"] == "https://two.example/v1"
    assert "new-secret" not in json.dumps(moved)


def test_explicit_models_url_must_share_effective_base_origin(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "catalog",
        "base_url: https://provider.example/v1\nmodel_name: model\n",
    )

    with pytest.raises(ValueError, match="相同来源"):
        update_provider_connection_settings(
            "catalog",
            {"models_url": "https://catalog.example/models"},
            tmp_path,
        )

    public = update_provider_connection_settings(
        "catalog",
        {"models_url": "https://provider.example/catalog/models"},
        tmp_path,
    )
    assert public["models_url"] == "https://provider.example/catalog/models"


def test_model_discovery_uses_local_connection_and_cache_is_cleared(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "gateway",
        """
api_key: ORIGINAL_KEY
base_url: https://original.example/v1
model_name: static-model
""",
    )
    monkeypatch.setenv("ORIGINAL_KEY", "original-secret")
    calls: list[tuple[str, str]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "remote-model"}]}

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["headers"]["Authorization"]))
        return Response()

    monkeypatch.setattr("video_translate.provider_profiles.requests.get", fake_get)
    fetch_provider_models("gateway", tmp_path)
    update_provider_connection_settings(
        "gateway",
        {"api_key": "local-secret", "base_url": "https://local.example/v2"},
        tmp_path,
    )
    fetch_provider_models("gateway", tmp_path)

    assert calls == [
        ("https://original.example/v1/models", "Bearer original-secret"),
        ("https://local.example/v2/models", "Bearer local-secret"),
    ]
