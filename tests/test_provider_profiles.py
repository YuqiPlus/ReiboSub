from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
import yaml

from video_translate.provider_profiles import (
    PROVIDER_PROFILES_PATH,
    clear_provider_model_cache,
    fetch_provider_models,
    get_provider_profile,
    list_provider_profiles,
)


def _write_profile(root: Path, name: str, content: str) -> Path:
    path = root / "configs" / "providers" / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_registry(root: Path, providers: dict) -> Path:
    path = root / PROVIDER_PROFILES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"version": 1, "providers": providers},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_loads_legacy_env_references_and_never_exposes_api_key(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "volcano",
        """
api_key: TEST_ARK_KEY
base_url: TEST_ARK_BASE_URL
model_name: doubao-seed-2-0-lite
model_names:
  - doubao-seed-2-0-pro
  - doubao-seed-2-0-lite
""",
    )
    monkeypatch.setenv("TEST_ARK_KEY", "secret-provider-key")
    monkeypatch.setenv("TEST_ARK_BASE_URL", "https://ark.example/v3")

    profile = get_provider_profile("VOLCANO", tmp_path)

    assert profile is not None
    assert profile.id == "volcano"
    assert profile.provider == "volcano"
    assert profile.base_url == "https://ark.example/v3"
    assert profile.api_key == "secret-provider-key"
    assert profile.api_key_env == "TEST_ARK_KEY"
    assert profile.backend == "openai-compatible"
    assert profile.default_model == "doubao-seed-2-0-lite"
    assert profile.models == ("doubao-seed-2-0-lite", "doubao-seed-2-0-pro")
    public_json = json.dumps(profile.to_public_dict(), ensure_ascii=False)
    assert "secret-provider-key" not in public_json
    assert "secret-provider-key" not in repr(profile)
    assert profile.to_public_dict()["key_configured"] is True


def test_supports_canonical_env_fields_inline_values_and_common_model_fields(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "custom-provider",
        """
provider: custom
label: Custom Gateway
backend: official_api
api_key_env:
  - MISSING_CUSTOM_KEY
  - CUSTOM_KEY
base_url_env: CUSTOM_BASE_URL
models_url: https://catalog.example/v1/models
api_model_name: model-api
models:
  pro: model-pro
  lite: model-lite
""",
    )
    _write_profile(
        tmp_path,
        "inline",
        """
api_key: inline-secret
base_url: https://inline.example/v1
model_name: inline-model
""",
    )
    monkeypatch.setenv("CUSTOM_KEY", "custom-secret")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://custom.example/v1")

    profiles = list_provider_profiles(tmp_path)
    custom = next(profile for profile in profiles if profile.id == "custom-provider")
    inline = next(profile for profile in profiles if profile.id == "inline")

    assert custom.api_key == "custom-secret"
    assert custom.api_key_env == "CUSTOM_KEY"
    assert custom.base_url == "https://custom.example/v1"
    assert custom.models_url == "https://catalog.example/v1/models"
    assert custom.backend == "official-api"
    assert custom.models == ("model-api", "model-lite", "model-pro")
    assert inline.api_key == "inline-secret"
    assert inline.base_url == "https://inline.example/v1"


def test_unified_registry_takes_precedence_over_legacy_profiles(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "legacy-only",
        "api_key: must-not-load\nbase_url: https://legacy.example/v1\nmodel_name: old\n",
    )
    _write_registry(
        tmp_path,
        {
            "unified": {
                "label": "Unified Provider",
                "provider": "gateway",
                "backend": "openai-compatible",
                "default_model": "model-a",
                "models": ["model-b"],
            }
        },
    )
    secrets_path = tmp_path / "configs" / "provider_secrets.yaml"
    secrets_path.write_text(
        """
version: 1
providers:
  unified:
    api_key: unified-secret
    base_url: https://unified.example/v1
""".lstrip(),
        encoding="utf-8",
    )

    profiles = list_provider_profiles(tmp_path)

    assert [profile.id for profile in profiles] == ["unified"]
    profile = profiles[0]
    assert profile.label == "Unified Provider"
    assert profile.provider == "gateway"
    assert profile.default_model == "model-a"
    assert profile.models == ("model-a", "model-b")
    assert profile.api_key == "unified-secret"
    assert profile.base_url == "https://unified.example/v1"
    assert get_provider_profile("legacy-only", tmp_path) is None


@pytest.mark.parametrize(
    "document",
    [
        {"version": 2, "providers": {}},
        {"version": 1, "providers": {"unsafe": {"api_key": "secret"}}},
        {"version": 1, "providers": {"unsafe": {"base_url": "https://example.com"}}},
    ],
)
def test_unified_registry_rejects_invalid_or_connection_fields(
    tmp_path: Path,
    document: dict,
) -> None:
    path = tmp_path / PROVIDER_PROFILES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="version|连接配置"):
        list_provider_profiles(tmp_path)


def test_unknown_and_illegal_profile_ids_cannot_escape_provider_directory(tmp_path: Path) -> None:
    _write_profile(tmp_path, "known", "model_name: known-model\n")

    assert get_provider_profile("missing", tmp_path) is None
    with pytest.raises(ValueError, match="provider id"):
        get_provider_profile("../../.env", tmp_path)
    with pytest.raises(ValueError, match="provider id"):
        fetch_provider_models("known/models", tmp_path)


def test_fetches_openai_compatible_models_merges_static_and_uses_cache(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "ark",
        """
api_key: ARK_TEST_KEY
base_url: https://ark.example/api/coding/v3
model_name: configured-alias
model_names:
  - static-only
""",
    )
    monkeypatch.setenv("ARK_TEST_KEY", "ark-secret")
    clear_provider_model_cache()
    calls: list[dict] = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "object": "list",
                "data": [
                    {"id": "remote-z"},
                    {"id": "configured-alias"},
                    {"name": "remote-a"},
                ],
            }

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("video_translate.provider_profiles.requests.get", fake_get)

    first = fetch_provider_models("ark", tmp_path)
    cached = fetch_provider_models("ark", tmp_path)
    refreshed = fetch_provider_models("ark", tmp_path, refresh=True)

    assert first["models"] == ["configured-alias", "remote-a", "remote-z", "static-only"]
    assert first["remote_models"] == ["configured-alias", "remote-a", "remote-z"]
    assert first["static_models"] == ["configured-alias", "static-only"]
    assert first["source"] == "remote"
    assert first["warning"] == ""
    assert first["cached"] is False
    assert cached["cached"] is True
    assert refreshed["cached"] is False
    assert len(calls) == 2
    assert calls[0]["url"] == "https://ark.example/api/coding/v3/models"
    assert calls[0]["headers"]["Authorization"] == "Bearer ark-secret"
    assert calls[0]["allow_redirects"] is False


def test_fetch_parses_common_models_array_shape(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "gateway",
        """
api_key: GATEWAY_KEY
base_url: https://gateway.example/v1/chat/completions
model_name: fallback-model
""",
    )
    monkeypatch.setenv("GATEWAY_KEY", "secret")
    clear_provider_model_cache()

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"models": ["model-b", {"model_name": "model-a"}]}

    monkeypatch.setattr("video_translate.provider_profiles.requests.get", lambda *args, **kwargs: Response())

    result = fetch_provider_models("gateway", tmp_path)

    assert result["models"] == ["fallback-model", "model-a", "model-b"]
    assert result["remote_models"] == ["model-a", "model-b"]


@pytest.mark.parametrize(
    ("base_url", "expected_models_url"),
    [
        ("https://gateway.example/v1", "https://gateway.example/v1/models"),
        ("https://gateway.example/api/coding/v3", "https://gateway.example/api/coding/v3/models"),
        ("https://gateway.example/v1/models", "https://gateway.example/v1/models"),
        ("https://gateway.example/v1/models/", "https://gateway.example/v1/models"),
        ("https://gateway.example/v1/chat/completions", "https://gateway.example/v1/models"),
        ("https://gateway.example/v1/responses", "https://gateway.example/v1/models"),
        ("https://gateway.example/v1/completions", "https://gateway.example/v1/models"),
    ],
)
def test_fetch_normalizes_common_openai_compatible_base_urls(
    tmp_path: Path,
    monkeypatch,
    base_url: str,
    expected_models_url: str,
) -> None:
    _write_profile(
        tmp_path,
        "normalized",
        f"api_key: secret\nbase_url: {base_url}\nmodel_name: fallback-model\n",
    )
    clear_provider_model_cache()
    calls: list[str] = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "remote-model"}]}

    def fake_get(url, **_kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("video_translate.provider_profiles.requests.get", fake_get)

    result = fetch_provider_models("normalized", tmp_path)

    assert calls == [expected_models_url]
    assert result["models"] == ["fallback-model", "remote-model"]


def test_upstream_failure_returns_only_static_models_and_sanitized_warning(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "failed",
        """
api_key: FAILED_KEY
base_url: https://private-workspace.example/v1
model_name: safe-static-model
""",
    )
    monkeypatch.setenv("FAILED_KEY", "top-secret-value")
    clear_provider_model_cache()

    def fail(*args, **kwargs):
        raise requests.ConnectionError("top-secret-value https://private-workspace.example/v1/models")

    monkeypatch.setattr("video_translate.provider_profiles.requests.get", fail)

    result = fetch_provider_models("failed", tmp_path)
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["models"] == ["safe-static-model"]
    assert result["source"] == "static"
    assert "连接失败" in result["warning"]
    assert "top-secret-value" not in serialized
    assert "private-workspace" not in result["warning"]


def test_missing_key_does_not_make_an_upstream_request(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "no-key",
        """
api_key_env: NOT_CONFIGURED_KEY
base_url: https://provider.example/v1
model_name: static-model
""",
    )
    monkeypatch.delenv("NOT_CONFIGURED_KEY", raising=False)
    clear_provider_model_cache()
    monkeypatch.setattr(
        "video_translate.provider_profiles.requests.get",
        lambda *args, **kwargs: pytest.fail("missing key must not trigger a request"),
    )

    result = fetch_provider_models("no-key", tmp_path)

    assert result["models"] == ["static-model"]
    assert "未配置" in result["warning"]


def test_cross_origin_models_url_never_receives_provider_key(tmp_path: Path, monkeypatch) -> None:
    _write_profile(
        tmp_path,
        "unsafe-catalog",
        """
api_key: CATALOG_KEY
base_url: https://provider.example/v1
models_url: https://other.example/models
model_name: static-model
""",
    )
    monkeypatch.setenv("CATALOG_KEY", "must-not-leak")
    clear_provider_model_cache()
    monkeypatch.setattr(
        "video_translate.provider_profiles.requests.get",
        lambda *args, **kwargs: pytest.fail("cross-origin catalog must not receive a request"),
    )

    result = fetch_provider_models("unsafe-catalog", tmp_path)

    assert result["models"] == ["static-model"]
    assert result["source"] == "static"
    assert "不同源" in result["warning"]
    assert "密钥安全" in result["warning"]
