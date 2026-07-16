from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

from .provider_secrets import _get_provider_secret_override


ROOT = Path(__file__).resolve().parent.parent
PROVIDER_CONFIG_DIR = Path("configs") / "providers"
MODEL_CACHE_TTL_SECONDS = 300.0

_PROFILE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")
_MODEL_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    label: str
    base_url: str | None
    api_key: str | None = field(repr=False)
    api_key_env: str | None
    backend: str
    models: tuple[str, ...]
    provider: str
    static_models: tuple[str, ...] = ()
    default_model: str | None = None
    models_url: str | None = None
    api_key_source: str = "unconfigured"
    base_url_source: str = "unconfigured"
    models_url_source: str = "unconfigured"

    def to_public_dict(self) -> dict[str, Any]:
        """Return browser-safe metadata without credentials or resolved URLs."""

        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "backend": self.backend,
            "default_model": self.default_model,
            "models": list(self.models),
            "static_models": list(self.static_models),
            "api_key_env": self.api_key_env,
            "key_configured": bool(self.api_key),
            "base_url_configured": bool(self.base_url),
            "model_discovery_configured": bool(self.models_url or self.base_url),
        }


@dataclass(frozen=True)
class _ModelCacheEntry:
    expires_at: float
    result: dict[str, Any]


_MODEL_CACHE: dict[tuple[str, str], _ModelCacheEntry] = {}


def list_provider_profiles(
    root: Path | None = None,
    *,
    include_local: bool = True,
) -> list[ProviderProfile]:
    """Load all trusted provider profiles under ``root/configs/providers``."""

    provider_dir = _provider_dir(root)
    if not provider_dir.is_dir():
        return []

    profiles: dict[str, ProviderProfile] = {}
    paths = sorted(
        (*provider_dir.glob("*.yml"), *provider_dir.glob("*.yaml")),
        key=lambda item: item.name.casefold(),
    )
    for path in paths:
        resolved = path.resolve()
        try:
            resolved.relative_to(provider_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"provider 配置不能位于 configs/providers 之外: {path.name}") from exc
        profile_id = normalize_provider_id(path.stem)
        if profile_id in profiles:
            raise ValueError(f"provider id 重复: {profile_id}")
        profiles[profile_id] = _load_provider_profile(
            resolved,
            profile_id,
            root,
            include_local=include_local,
        )
    return [profiles[key] for key in sorted(profiles, key=str.casefold)]


def get_provider_profile(
    profile_id: str,
    root: Path | None = None,
    *,
    include_local: bool = True,
) -> ProviderProfile | None:
    """Return a trusted local profile, or ``None`` when a valid id is unknown."""

    normalized = normalize_provider_id(profile_id)
    return next(
        (
            profile
            for profile in list_provider_profiles(root, include_local=include_local)
            if profile.id == normalized
        ),
        None,
    )


def fetch_provider_models(
    profile_id: str,
    root: Path | None = None,
    refresh: bool = False,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Discover models from a trusted profile and merge its static model list.

    Upstream response bodies and exception messages are intentionally never
    included in the returned warning.
    """

    profile = get_provider_profile(profile_id, root)
    if profile is None:
        raise ValueError(f"未知 provider: {normalize_provider_id(profile_id)}")

    cache_key = (str(_project_root(root).resolve()), profile.id)
    now = time.monotonic()
    if not refresh:
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(cache_key)
        if cached and cached.expires_at > now:
            result = _copy_model_result(cached.result)
            result["cached"] = True
            return result

    static_models = list(profile.models)
    remote_models: list[str] = []
    warning = ""
    models_url = _model_discovery_url(profile)

    if not models_url:
        warning = "服务商没有配置模型列表地址，已显示配置文件中的静态模型。"
    elif not profile.api_key:
        warning = "服务商 API Key 未配置，已显示配置文件中的静态模型。"
    else:
        try:
            response = requests.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {profile.api_key}",
                    "Accept": "application/json",
                },
                timeout=max(0.1, float(timeout)),
                allow_redirects=False,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if not 200 <= status < 300:
                warning = f"模型列表请求失败（HTTP {status or 'unknown'}），已显示配置文件中的静态模型。"
            else:
                try:
                    remote_models = _parse_model_ids(response.json())
                except (TypeError, ValueError):
                    warning = "服务商返回的模型列表格式无法解析，已显示配置文件中的静态模型。"
                if not remote_models and not warning:
                    warning = "服务商没有返回可用模型，已显示配置文件中的静态模型。"
        except requests.RequestException:
            warning = "模型列表请求连接失败，已显示配置文件中的静态模型。"

    models = _sorted_unique([*static_models, *remote_models])
    result = {
        "provider_id": profile.id,
        "provider": profile.provider,
        "profile": profile.to_public_dict(),
        "models": models,
        "default_model": profile.default_model,
        "source": "remote" if remote_models else "static",
        "warning": warning,
        "cached": False,
    }
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE[cache_key] = _ModelCacheEntry(
            expires_at=now + MODEL_CACHE_TTL_SECONDS,
            result=_copy_model_result(result),
        )
    return result


def clear_provider_model_cache() -> None:
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


def normalize_provider_id(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not _PROFILE_ID_RE.fullmatch(normalized):
        raise ValueError("provider id 只能包含小写字母、数字、点、下划线和连字符")
    return normalized


def _project_root(root: Path | None) -> Path:
    return Path(root).expanduser() if root is not None else ROOT


def _provider_dir(root: Path | None) -> Path:
    return _project_root(root) / PROVIDER_CONFIG_DIR


def _load_provider_profile(
    path: Path,
    profile_id: str,
    root: Path | None,
    *,
    include_local: bool,
) -> ProviderProfile:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError):
        raise ValueError(f"provider 配置不是有效的 YAML: {path.name}") from None
    if not isinstance(data, dict):
        raise ValueError(f"provider 配置必须是 YAML 对象: {path.name}")

    api_key, api_key_env, api_key_source = _resolve_secret(data, "api_key")
    base_url, base_url_source = _resolve_config_value(data, "base_url")
    models_url, models_url_source = _resolve_config_value(data, "models_url")
    local = _get_provider_secret_override(profile_id, root) if include_local else {}
    if "api_key" in local:
        api_key = local["api_key"]
        api_key_source = "local"
    if "base_url" in local:
        base_url = local["base_url"]
        base_url_source = "local"
    if "models_url" in local:
        models_url = local["models_url"]
        models_url_source = "local"
    default_model = _clean(data.get("api_model_name") or data.get("model_name") or data.get("model"))
    static_models = _configured_static_models(data)
    models = _sorted_unique([default_model, *static_models])
    backend = _normalize_backend(data.get("backend") or data.get("interface") or "openai-compatible")
    provider = _clean(data.get("provider")) or profile_id
    label = _clean(data.get("label") or data.get("name")) or profile_id

    return ProviderProfile(
        id=profile_id,
        provider=provider,
        label=label,
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        default_model=default_model,
        models=tuple(models),
        static_models=tuple(static_models),
        models_url=models_url,
        api_key_source=api_key_source,
        base_url_source=base_url_source,
        models_url_source=models_url_source,
    )


def _resolve_secret(
    data: dict[str, Any],
    key: str,
) -> tuple[str | None, str | None, str]:
    env_names = _env_names(data.get(f"{key}_env"))
    for env_name in env_names:
        value = _clean(os.environ.get(env_name))
        if value:
            return value, env_name, "environment"

    raw = _clean(data.get(key))
    if not raw:
        return None, env_names[0] if env_names else None, "unconfigured"
    if _ENV_NAME_RE.fullmatch(raw):
        value = _clean(os.environ.get(raw))
        return value, raw, "environment" if value else "unconfigured"
    return raw, env_names[0] if env_names else None, "profile"


def _resolve_config_value(data: dict[str, Any], key: str) -> tuple[str | None, str]:
    env_names = _env_names(data.get(f"{key}_env"))
    for env_name in env_names:
        value = _clean(os.environ.get(env_name))
        if value:
            return value, "environment"

    raw = _clean(data.get(key))
    if not raw:
        return None, "unconfigured"
    if _ENV_NAME_RE.fullmatch(raw):
        value = _clean(os.environ.get(raw))
        return value, "environment" if value else "unconfigured"
    return raw, "profile"


def _env_names(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in values:
        name = _clean(item)
        if not name:
            continue
        if not _ENV_NAME_RE.fullmatch(name):
            raise ValueError(f"环境变量名称不合法: {name}")
        if name not in result:
            result.append(name)
    return result


def _configured_static_models(data: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    for key in ("model_names", "models"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            candidates.extend(value)
        elif value is not None:
            candidates.append(value)
    return _sorted_unique(candidates)


def _normalize_backend(value: Any) -> str:
    return (_clean(value) or "openai-compatible").lower().replace("_", "-")


def _model_discovery_url(profile: ProviderProfile) -> str | None:
    raw = _clean(profile.models_url or profile.base_url)
    if not raw:
        return None
    if profile.models_url and _url_origin(profile.models_url) != _url_origin(profile.base_url):
        # The same Bearer token is used for discovery. Never send it to a
        # catalog hosted on a different origin than the configured API.
        return None
    base = raw.rstrip("/")
    if not profile.models_url and base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    url = base if profile.models_url else f"{base}/models"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _url_origin(value: str | None) -> tuple[str, str, int | None] | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def _parse_model_ids(payload: Any) -> list[str]:
    rows = payload
    if isinstance(payload, dict):
        rows = next(
            (
                payload[key]
                for key in ("data", "models", "items", "results")
                if isinstance(payload.get(key), (list, tuple))
            ),
            [],
        )
    if not isinstance(rows, (list, tuple)):
        return []

    models: list[Any] = []
    for row in rows:
        if isinstance(row, str):
            models.append(row)
            continue
        if not isinstance(row, dict):
            continue
        models.append(row.get("id") or row.get("model") or row.get("model_name") or row.get("name"))
    return _sorted_unique(models)


def _sorted_unique(values: list[Any]) -> list[str]:
    result: dict[str, str] = {}
    for value in values:
        cleaned = _clean(value)
        if not cleaned or len(cleaned) > 256:
            continue
        result.setdefault(cleaned, cleaned)
    return sorted(result.values(), key=str.casefold)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _copy_model_result(result: dict[str, Any]) -> dict[str, Any]:
    copied = dict(result)
    copied["models"] = list(result.get("models") or [])
    copied["profile"] = dict(result.get("profile") or {})
    copied["profile"]["models"] = list(copied["profile"].get("models") or [])
    copied["profile"]["static_models"] = list(
        copied["profile"].get("static_models") or []
    )
    return copied
