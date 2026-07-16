from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .app_settings import APP_SETTINGS_PATH, get_app_settings_payload, save_app_settings
from .local_config_lock import LOCAL_CONFIG_WRITE_LOCK
from .provider_profiles import (
    PROVIDER_CONFIG_DIR,
    clear_provider_model_cache,
    get_provider_profile,
    list_provider_profiles,
    normalize_provider_id,
)
from .provider_secrets import (
    PROVIDER_SECRETS_PATH,
    delete_provider_secret_override,
    update_provider_connection_settings,
)


_CREATE_FIELDS = frozenset(
    {
        "id",
        "label",
        "base_url",
        "api_key",
        "default_model",
        "models_url",
        "models",
    }
)
_MAX_LABEL_LENGTH = 128
_MAX_MODEL_LENGTH = 256
_MAX_MODELS = 256
_UPDATE_FIELDS = frozenset({"label", "default_model", "models"})


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    content: bytes = b""
    mode: int = 0o600


def create_provider_profile(
    payload: Mapping[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Create one local OpenAI-compatible provider and its private connection."""

    if not isinstance(payload, Mapping):
        raise ValueError("服务商配置必须是对象")
    unknown = sorted(set(payload) - _CREATE_FIELDS)
    if unknown:
        raise ValueError(f"不支持的服务商字段: {', '.join(unknown)}")

    profile_id = normalize_provider_id(payload.get("id"))
    if profile_id.endswith((".yml", ".yaml")):
        raise ValueError("provider id 不应包含 .yml 或 .yaml 扩展名")
    label = _validated_text(payload.get("label") or profile_id, "label", _MAX_LABEL_LENGTH)
    default_model = _optional_text(payload.get("default_model"), "default_model", _MAX_MODEL_LENGTH)
    models = _validated_models(payload.get("models"))

    if "base_url" not in payload:
        raise ValueError("新服务商必须填写 base_url")
    base_url = payload.get("base_url")
    api_key = payload.get("api_key")
    models_url = payload.get("models_url")

    project_root = _project_root(root)
    with LOCAL_CONFIG_WRITE_LOCK:
        provider_dir = _writable_provider_dir(project_root)
        profile_path = provider_dir / f"{profile_id}.yml"
        alternate_path = provider_dir / f"{profile_id}.yaml"
        if _path_present(profile_path) or _path_present(alternate_path):
            raise ValueError(f"provider 已存在: {profile_id}")
        if get_provider_profile(profile_id, project_root) is not None:
            raise ValueError(f"provider 已存在: {profile_id}")

        # A stale secret must never silently attach itself to a recreated ID.
        delete_provider_secret_override(profile_id, project_root)

        document: dict[str, Any] = {
            "label": label,
            "provider": profile_id,
            "backend": "openai-compatible",
        }
        if default_model:
            document["model_name"] = default_model
        if models:
            document["model_names"] = models
        _atomic_write_yaml(profile_path, document, mode=0o600)

        connection_payload: dict[str, Any] = {"base_url": base_url}
        if api_key is not None and str(api_key).strip():
            connection_payload["api_key"] = api_key
        if models_url is not None and str(models_url).strip():
            connection_payload["models_url"] = models_url

        try:
            connection = update_provider_connection_settings(
                profile_id,
                connection_payload,
                project_root,
            )
        except Exception:
            delete_provider_secret_override(profile_id, project_root)
            profile_path.unlink(missing_ok=True)
            clear_provider_model_cache()
            raise

        profile = get_provider_profile(profile_id, project_root)
        if profile is None:  # Defensive; the atomic profile write completed above.
            raise RuntimeError("新服务商配置创建后无法读取")
        result = get_app_settings_payload(project_root)
        result.update(
            {
                "provider": profile.to_public_dict(),
                "connection": connection,
            }
        )
        return result


def delete_provider_profile(
    profile_id: str,
    replacement_provider_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Delete a provider, its secret, and migrate every saved reference."""

    normalized_id = normalize_provider_id(profile_id)
    replacement_id = normalize_provider_id(replacement_provider_id)
    if replacement_id == normalized_id:
        raise ValueError("替代 provider 不能和待删除 provider 相同")

    project_root = _project_root(root)
    with LOCAL_CONFIG_WRITE_LOCK:
        profiles = list_provider_profiles(project_root)
        by_id = {profile.id: profile for profile in profiles}
        if normalized_id not in by_id:
            raise ValueError(f"未知 provider: {normalized_id}")
        if len(profiles) <= 1:
            raise ValueError("至少需要保留一个 provider；请先新增替代服务商")
        if replacement_id not in by_id:
            raise ValueError(f"未知替代 provider: {replacement_id}")

        profile_path = _find_profile_path(project_root, normalized_id)
        settings_path = project_root / APP_SETTINGS_PATH
        secrets_path = project_root / PROVIDER_SECRETS_PATH
        snapshots = {
            settings_path: _snapshot_file(settings_path),
            secrets_path: _snapshot_file(secrets_path),
            profile_path: _snapshot_file(profile_path),
        }

        current = get_app_settings_payload(project_root)["settings"]
        replacement = by_id[replacement_id]
        updated_settings, affected_tasks, default_replaced = _replace_provider_references(
            current,
            normalized_id,
            replacement_id,
            replacement.default_model or "",
        )

        try:
            save_app_settings(updated_settings, project_root)
            delete_provider_secret_override(normalized_id, project_root)
            profile_path.unlink()
            clear_provider_model_cache()
        except Exception:
            for path, snapshot in snapshots.items():
                _restore_file(path, snapshot)
            clear_provider_model_cache()
            raise

        result = get_app_settings_payload(project_root)
        result.update(
            {
                "deleted_provider_id": normalized_id,
                "replacement_provider_id": replacement_id,
                "default_replaced": default_replaced,
                "affected_tasks": affected_tasks,
            }
        )
        return result


def update_provider_profile(
    profile_id: str,
    payload: Mapping[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Update browser-editable provider metadata without touching credentials."""

    normalized_id = normalize_provider_id(profile_id)
    if not isinstance(payload, Mapping):
        raise ValueError("服务商更新配置必须是对象")
    unknown = sorted(set(payload) - _UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"不支持的服务商更新字段: {', '.join(unknown)}")
    if not payload:
        raise ValueError("没有需要更新的服务商字段")

    project_root = _project_root(root)
    with LOCAL_CONFIG_WRITE_LOCK:
        current = get_provider_profile(normalized_id, project_root)
        if current is None:
            raise ValueError(f"未知 provider: {normalized_id}")
        profile_path = _find_profile_path(project_root, normalized_id)
        snapshot = _snapshot_file(profile_path)
        document = _read_profile_document(profile_path)

        if "label" in payload:
            label = _optional_text(payload.get("label"), "label", _MAX_LABEL_LENGTH)
            document.pop("label", None)
            document.pop("name", None)
            if label:
                document["label"] = label

        default_model_updated = "default_model" in payload
        default_model = current.default_model or ""
        if default_model_updated:
            default_model = _optional_text(
                payload.get("default_model"),
                "default_model",
                _MAX_MODEL_LENGTH,
            )
            had_api_model_name = "api_model_name" in document
            document.pop("api_model_name", None)
            document.pop("model_name", None)
            document.pop("model", None)
            if default_model:
                document["model_name"] = default_model
                if had_api_model_name:
                    document["api_model_name"] = default_model

        if default_model_updated or "models" in payload:
            raw_models: Any
            if "models" in payload:
                raw_models = payload.get("models")
            else:
                raw_models = list(current.static_models)
            models = _validated_models(raw_models)
            document.pop("model_names", None)
            document.pop("models", None)
            if models:
                document["model_names"] = models

        try:
            _atomic_write_yaml(profile_path, document, mode=snapshot.mode)
            updated = get_provider_profile(normalized_id, project_root)
            if updated is None:
                raise RuntimeError("服务商配置更新后无法读取")
            clear_provider_model_cache()
            result = get_app_settings_payload(project_root)
            result["provider"] = updated.to_public_dict()
        except Exception:
            _restore_file(profile_path, snapshot)
            clear_provider_model_cache()
            raise
        return result


def _replace_provider_references(
    settings: Mapping[str, Any],
    removed_id: str,
    replacement_id: str,
    replacement_model: str,
) -> tuple[dict[str, Any], list[str], bool]:
    updated = deepcopy(dict(settings))
    defaults = updated.setdefault("defaults", {})
    tasks = updated.setdefault("tasks", {})
    old_default = str(defaults.get("provider_profile") or "").strip()
    default_replaced = old_default == removed_id
    if default_replaced:
        defaults["provider_profile"] = replacement_id

    affected_tasks: list[str] = []
    for task_key, raw_binding in tasks.items():
        binding = raw_binding if isinstance(raw_binding, dict) else {"model": raw_binding}
        explicit_provider = str(binding.get("provider_profile") or "").strip()
        effective_provider = explicit_provider or old_default
        if effective_provider != removed_id:
            tasks[task_key] = binding
            continue
        affected_tasks.append(str(task_key))
        binding["provider_profile"] = "" if default_replaced else replacement_id
        binding["model"] = replacement_model
        tasks[task_key] = binding
    return updated, affected_tasks, default_replaced


def _project_root(root: Path | None) -> Path:
    return Path(root).expanduser() if root is not None else Path(__file__).resolve().parent.parent


def _writable_provider_dir(project_root: Path) -> Path:
    provider_dir = project_root / PROVIDER_CONFIG_DIR
    if provider_dir.is_symlink():
        raise ValueError("configs/providers 不能是符号链接")
    provider_dir.mkdir(parents=True, exist_ok=True)
    return provider_dir


def _find_profile_path(project_root: Path, profile_id: str) -> Path:
    provider_dir = _writable_provider_dir(project_root)
    candidates = [provider_dir / f"{profile_id}.yml", provider_dir / f"{profile_id}.yaml"]
    matches = [path for path in candidates if _path_present(path)]
    if len(matches) != 1:
        raise ValueError(f"provider 文件状态异常: {profile_id}")
    path = matches[0]
    if path.is_symlink() or not path.is_file():
        raise ValueError("provider 文件必须是普通文件")
    return path


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _validated_text(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    if len(text) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field} 格式不合法")
    return text


def _optional_text(value: Any, field: str, max_length: int) -> str:
    if value in (None, ""):
        return ""
    return _validated_text(value, field, max_length)


def _validated_models(value: Any) -> list[str]:
    if value is None:
        raw_models: list[Any] = []
    elif isinstance(value, str):
        raw_models = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_models = list(value)
    else:
        raise ValueError("models 必须是字符串或数组")
    if len(raw_models) > _MAX_MODELS:
        raise ValueError(f"models 最多允许 {_MAX_MODELS} 项")
    result: list[str] = []
    for raw in raw_models:
        model = _optional_text(raw, "model", _MAX_MODEL_LENGTH)
        if model and model not in result:
            result.append(model)
    return result


def _snapshot_file(path: Path) -> _FileSnapshot:
    if path.is_symlink():
        raise ValueError(f"本地配置不能是符号链接: {path.name}")
    if not path.exists():
        return _FileSnapshot(existed=False)
    if not path.is_file():
        raise ValueError(f"本地配置必须是普通文件: {path.name}")
    return _FileSnapshot(
        existed=True,
        content=path.read_bytes(),
        mode=stat.S_IMODE(path.stat().st_mode),
    )


def _read_profile_document(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeError):
        raise ValueError(f"provider 配置不是有效的 YAML: {path.name}") from None
    if not isinstance(data, dict):
        raise ValueError(f"provider 配置必须是 YAML 对象: {path.name}")
    return dict(data)


def _restore_file(path: Path, snapshot: _FileSnapshot) -> None:
    if not snapshot.existed:
        path.unlink(missing_ok=True)
        return
    _atomic_write_bytes(path, snapshot.content, snapshot.mode)


def _atomic_write_yaml(path: Path, data: Mapping[str, Any], *, mode: int) -> None:
    serialized = yaml.safe_dump(
        dict(data),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).encode("utf-8")
    _atomic_write_bytes(path, serialized, mode)


def _atomic_write_bytes(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, mode)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
