from __future__ import annotations

import os
import re
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .local_config_lock import LOCAL_CONFIG_WRITE_LOCK


ROOT = Path(__file__).resolve().parent.parent
PROVIDER_SECRETS_PATH = Path("configs") / "provider_secrets.yaml"

_PROFILE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_STORED_FIELDS = frozenset({"api_key", "base_url", "models_url"})
_UPDATE_FIELDS = frozenset(
    {
        *_STORED_FIELDS,
        "clear_api_key",
        "clear_base_url",
        "clear_models_url",
        "import_current",
    }
)
_WRITE_LOCK = threading.Lock()


def get_provider_connection_settings(
    profile_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return browser-safe connection settings for a trusted provider profile.

    The API key itself is never included. ``key_source`` and URL source fields
    are one of ``local``, ``environment``, ``profile`` or ``unconfigured``.
    """

    from .provider_profiles import get_provider_profile

    profile = get_provider_profile(profile_id, root)
    if profile is None:
        raise ValueError(f"未知 provider: {_normalize_provider_id(profile_id)}")
    local = _get_provider_secret_override(profile.id, root)
    return {
        "provider_id": profile.id,
        "provider": profile.provider,
        "label": profile.label,
        "key_configured": bool(profile.api_key),
        "local_key_configured": bool(local.get("api_key")),
        "key_source": profile.api_key_source,
        "base_url": profile.base_url or "",
        "base_url_configured": bool(profile.base_url),
        "local_base_url_configured": bool(local.get("base_url")),
        "base_url_source": profile.base_url_source,
        "models_url": profile.models_url or "",
        "models_url_configured": bool(profile.models_url),
        "local_models_url_configured": bool(local.get("models_url")),
        "models_url_source": profile.models_url_source,
        "storage_path": PROVIDER_SECRETS_PATH.as_posix(),
    }


def update_provider_connection_settings(
    profile_id: str,
    payload: Mapping[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Persist a local provider connection override and return public state.

    Supported fields are ``api_key``, ``base_url``, ``models_url``, matching
    ``clear_*`` flags, and ``import_current``. Empty values are rejected so a
    caller must use an explicit clear flag to reveal the environment/profile
    fallback again.
    """

    from .provider_profiles import clear_provider_model_cache, get_provider_profile

    normalized_id = _normalize_provider_id(profile_id)
    profile = get_provider_profile(normalized_id, root)
    if profile is None:
        raise ValueError(f"未知 provider: {normalized_id}")
    fallback_profile = get_provider_profile(normalized_id, root, include_local=False)
    if fallback_profile is None:  # Defensive: the trusted profile was present immediately above.
        raise ValueError(f"未知 provider: {normalized_id}")
    if not isinstance(payload, Mapping):
        raise ValueError("provider 连接配置必须是对象")

    unknown = sorted(set(payload) - _UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"不支持的 provider 连接配置字段: {', '.join(unknown)}")

    flags = {
        name: _read_bool(payload, name)
        for name in ("clear_api_key", "clear_base_url", "clear_models_url", "import_current")
    }
    for field in _STORED_FIELDS:
        if field in payload and flags[f"clear_{field}"]:
            raise ValueError(f"不能同时设置和清除 {field}")
    if flags["import_current"] and any(flags[f"clear_{field}"] for field in _STORED_FIELDS):
        raise ValueError("import_current 不能和 clear_* 同时使用")

    explicit: dict[str, str] = {}
    if "api_key" in payload:
        explicit["api_key"] = _validate_api_key(payload["api_key"])
    for field in ("base_url", "models_url"):
        if field in payload:
            explicit[field] = _validate_url(payload[field], field)

    with LOCAL_CONFIG_WRITE_LOCK, _WRITE_LOCK:
        document = _read_document(root)
        providers = dict(document["providers"])
        record = dict(providers.get(normalized_id) or {})

        if flags["import_current"]:
            if profile.api_key:
                record["api_key"] = profile.api_key
            if profile.base_url:
                record["base_url"] = profile.base_url
            if profile.models_url:
                record["models_url"] = profile.models_url

        for field in _STORED_FIELDS:
            if flags[f"clear_{field}"]:
                record.pop(field, None)
        record.update(explicit)

        resulting_base_url = record.get("base_url") or fallback_profile.base_url
        resulting_api_key = record.get("api_key") or fallback_profile.api_key
        if _url_origin(profile.base_url) != _url_origin(resulting_base_url) and resulting_api_key:
            if "api_key" not in explicit:
                raise ValueError("更换 base_url 服务地址时，若仍有可用密钥，必须同时填写新的 api_key")

        if "models_url" in explicit:
            if not resulting_base_url or _url_origin(explicit["models_url"]) != _url_origin(resulting_base_url):
                raise ValueError("models_url 必须和当前 base_url 使用相同来源")

        if record:
            providers[normalized_id] = record
        else:
            providers.pop(normalized_id, None)
        _write_document({"version": 1, "providers": providers}, root)

    clear_provider_model_cache()
    return get_provider_connection_settings(normalized_id, root)


def delete_provider_secret_override(
    profile_id: str,
    root: Path | None = None,
) -> bool:
    """Delete one complete local provider record without exposing its values."""

    from .provider_profiles import clear_provider_model_cache

    normalized_id = _normalize_provider_id(profile_id)
    with LOCAL_CONFIG_WRITE_LOCK, _WRITE_LOCK:
        document = _read_document(root)
        providers = dict(document["providers"])
        existed = normalized_id in providers
        providers.pop(normalized_id, None)
        if existed:
            _write_document({"version": 1, "providers": providers}, root)
    if existed:
        clear_provider_model_cache()
    return existed


def _get_provider_secret_override(profile_id: str, root: Path | None = None) -> dict[str, str]:
    """Load one validated local override for provider profile resolution."""

    normalized_id = _normalize_provider_id(profile_id)
    return dict(_read_document(root)["providers"].get(normalized_id) or {})


def _read_document(root: Path | None = None) -> dict[str, Any]:
    path = _storage_path(root)
    if not path.exists():
        return {"version": 1, "providers": {}}
    if path.is_symlink():
        raise ValueError("provider_secrets.yaml 不能是符号链接")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise ValueError("provider_secrets.yaml 不是有效的 YAML") from None
    if not isinstance(data, dict):
        raise ValueError("provider_secrets.yaml 必须是 YAML 对象")
    if data.get("version") != 1:
        raise ValueError("provider_secrets.yaml 仅支持 version: 1")
    raw_providers = data.get("providers")
    if not isinstance(raw_providers, dict):
        raise ValueError("provider_secrets.yaml 的 providers 必须是对象")

    providers: dict[str, dict[str, str]] = {}
    for raw_id, raw_record in raw_providers.items():
        profile_id = _normalize_provider_id(raw_id)
        if not isinstance(raw_record, dict):
            raise ValueError(f"provider {profile_id} 的连接配置必须是对象")
        unknown = sorted(set(raw_record) - _STORED_FIELDS)
        if unknown:
            raise ValueError(f"provider {profile_id} 含有不支持的字段: {', '.join(unknown)}")
        record: dict[str, str] = {}
        if "api_key" in raw_record:
            record["api_key"] = _validate_api_key(raw_record["api_key"])
        for field in ("base_url", "models_url"):
            if field in raw_record:
                record[field] = _validate_url(raw_record[field], field)
        if record:
            providers[profile_id] = record
    return {"version": 1, "providers": providers}


def _write_document(document: dict[str, Any], root: Path | None = None) -> None:
    path = _storage_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            yaml.safe_dump(
                document,
                handle,
                allow_unicode=True,
                sort_keys=True,
                default_flow_style=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)


def _storage_path(root: Path | None = None) -> Path:
    project_root = Path(root).expanduser() if root is not None else ROOT
    return project_root / PROVIDER_SECRETS_PATH


def _normalize_provider_id(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not _PROFILE_ID_RE.fullmatch(normalized):
        raise ValueError("provider id 只能包含小写字母、数字、点、下划线和连字符")
    return normalized


def _validate_api_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("api_key 必须是非空字符串")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("api_key 不能为空；如需删除请使用 clear_api_key")
    if len(cleaned) > 16384 or "\x00" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError("api_key 格式不合法")
    return cleaned


def _validate_url(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是 http/https URL")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} 不能为空；如需删除请使用 clear_{field}")
    if len(cleaned) > 4096 or "\x00" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{field} 格式不合法")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} 必须是 http/https URL")
    try:
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError(f"{field} 必须是有效的 http/https URL") from None
    if not hostname:
        raise ValueError(f"{field} 必须是有效的 http/https URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError(f"{field} 不能包含用户信息或 URL 片段")
    return cleaned.rstrip("/")


def _read_bool(payload: Mapping[str, Any], field: str) -> bool:
    value = payload.get(field, False)
    if not isinstance(value, bool):
        raise ValueError(f"{field} 必须是布尔值")
    return value


def _url_origin(value: str | None) -> tuple[str, str, int | None] | None:
    if not value:
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
    return parsed.scheme.lower(), hostname, port
