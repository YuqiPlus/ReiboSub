from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from video_translate.llm_config import load_llm_task_config
from video_translate.local_config_lock import LOCAL_CONFIG_WRITE_LOCK
from video_translate.provider_profiles import ProviderProfile, list_provider_profiles


ROOT = Path(__file__).resolve().parent.parent
APP_SETTINGS_PATH = Path("configs") / "app_settings.yaml"
APP_SETTINGS_VERSION = 1

LLM_TASK_KEYS = (
    "title_translation",
    "glossary",
    "subtitle_translation",
    "asr_correction",
    "hybrid_source_reconstruction",
    "ocr_source_refinement",
    "ocr_geometry_refinement",
    "ocr_source_cleanup",
    "video_analysis",
)

SOURCE_LANGUAGES = frozenset({"auto", "korean", "japanese", "english", "chinese"})
OCR_LANGUAGES = SOURCE_LANGUAGES
TARGET_LANGUAGES = frozenset({"zh"})
MAX_MODEL_LENGTH = 256


def get_app_settings_payload(root: Path | None = None) -> dict[str, Any]:
    """Return normalized settings and browser-safe provider metadata."""

    project_root = _project_root(root)
    providers = list_provider_profiles(project_root)
    raw = _read_settings(project_root / APP_SETTINGS_PATH)
    settings = _normalize_loaded_settings(raw, providers, project_root)
    return {
        "settings": settings,
        "providers": [provider.to_public_dict() for provider in providers],
    }


def save_app_settings(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Validate and atomically persist the public settings schema.

    Provider credentials never belong to this file.  Only trusted profile IDs
    from ``configs/providers`` are accepted.
    """

    if not isinstance(payload, dict):
        raise ValueError("设置内容必须是 JSON 对象")

    with LOCAL_CONFIG_WRITE_LOCK:
        project_root = _project_root(root)
        providers = list_provider_profiles(project_root)
        provider_ids = {provider.id for provider in providers}
        if 'delivery' not in payload:
            payload = {**payload, 'delivery': _read_settings(project_root / APP_SETTINGS_PATH).get('delivery', {})}
        normalized = _validate_settings(payload, providers, provider_ids)
        _atomic_write_yaml(project_root / APP_SETTINGS_PATH, normalized)
        return get_app_settings_payload(project_root)


def _project_root(root: Path | None) -> Path:
    return Path(root).expanduser() if root is not None else ROOT


def get_delivery_settings(root: Path | None = None) -> dict[str, bool]:
    """Local-only delivery preferences; no model/provider discovery required."""
    raw = _read_settings(_project_root(root) / APP_SETTINGS_PATH)
    delivery = raw.get('delivery') if isinstance(raw.get('delivery'), dict) else {}
    return {'youtube_bcc': delivery.get('youtube_bcc') is True}


def _read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"应用设置必须是 YAML 对象: {path}")
    version = data.get("version")
    if version not in (None, APP_SETTINGS_VERSION):
        raise ValueError(f"不支持的应用设置版本: {version}")
    return data


def _normalize_loaded_settings(
    raw: dict[str, Any],
    providers: list[ProviderProfile],
    root: Path,
) -> dict[str, Any]:
    provider_ids = {provider.id for provider in providers}
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    tasks = raw.get("tasks") if isinstance(raw.get("tasks"), dict) else {}

    default_provider = _default_provider_id(providers)
    configured_provider = _clean_text(defaults.get("provider_profile"))
    if configured_provider in provider_ids:
        default_provider = configured_provider

    normalized_tasks: dict[str, dict[str, str]] = {}
    for task_key in LLM_TASK_KEYS:
        binding_is_configured = task_key in tasks
        raw_binding = tasks.get(task_key)
        if isinstance(raw_binding, str):
            binding: dict[str, Any] = {"model": raw_binding}
        elif isinstance(raw_binding, dict):
            binding = raw_binding
        else:
            binding = {}

        provider_override = _clean_text(binding.get("provider_profile"))
        if provider_override not in provider_ids:
            provider_override = ""
        model = _clean_text(binding.get("model"))
        # Once the Settings UI has written a task binding, an empty model is
        # intentional: it means "use the selected provider's default".  Do
        # not resurrect a model from legacy llm.yaml/.env after the user
        # switches providers and clears the old model selection.
        if not model and not binding_is_configured and "model" not in defaults:
            model = _clean_text(load_llm_task_config(task_key, root=root).model)

        normalized_tasks[task_key] = {
            # An empty value is meaningful to the UI: inherit the global
            # provider rather than pinning this task to it.
            "provider_profile": provider_override,
            "model": model,
        }

    return {
        "version": APP_SETTINGS_VERSION,
        "delivery": {'youtube_bcc': (raw.get('delivery') or {}).get('youtube_bcc') is True} if isinstance(raw.get('delivery'), dict) else {'youtube_bcc': False},
        "defaults": {
            "source_language": _choice_or_default(
                defaults.get("source_language"), SOURCE_LANGUAGES, "korean"
            ),
            "ocr_language": _choice_or_default(
                defaults.get("ocr_language"), OCR_LANGUAGES, "auto"
            ),
            "target_language": _choice_or_default(
                defaults.get("target_language"), TARGET_LANGUAGES, "zh"
            ),
            "provider_profile": default_provider,
            "model": _clean_text(defaults.get("model")) if not configured_provider or configured_provider in provider_ids else "",
        },
        "tasks": normalized_tasks,
    }


def _validate_settings(
    payload: dict[str, Any],
    providers: list[ProviderProfile],
    provider_ids: set[str],
) -> dict[str, Any]:
    version = payload.get("version", APP_SETTINGS_VERSION)
    if version != APP_SETTINGS_VERSION:
        raise ValueError(f"设置 version 必须是 {APP_SETTINGS_VERSION}")

    defaults = payload.get("defaults", {})
    delivery = payload.get('delivery', {})
    if not isinstance(delivery, dict) or type(delivery.get('youtube_bcc', False)) is not bool:
        raise ValueError('delivery.youtube_bcc 必须为布尔值')
    tasks = payload.get("tasks", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults 必须是对象")
    if not isinstance(tasks, dict):
        raise ValueError("tasks 必须是对象")

    unknown_tasks = sorted(set(tasks) - set(LLM_TASK_KEYS))
    if unknown_tasks:
        raise ValueError(f"未知的模型任务: {', '.join(unknown_tasks)}")

    source_language = _required_choice(
        defaults.get("source_language", "korean"), SOURCE_LANGUAGES, "source_language"
    )
    ocr_language = _required_choice(
        defaults.get("ocr_language", "auto"), OCR_LANGUAGES, "ocr_language"
    )
    target_language = _required_choice(
        defaults.get("target_language", "zh"), TARGET_LANGUAGES, "target_language"
    )

    default_provider = _clean_text(defaults.get("provider_profile")) or _default_provider_id(providers)
    default_model = _validate_model(defaults.get("model", ""), "defaults")
    if default_provider and default_provider not in provider_ids:
        raise ValueError(f"未知 provider: {default_provider}")
    if provider_ids and not default_provider:
        raise ValueError("必须选择一个默认 provider")

    normalized_tasks: dict[str, dict[str, str]] = {}
    for task_key in LLM_TASK_KEYS:
        raw_binding = tasks.get(task_key, {})
        if isinstance(raw_binding, str):
            binding: dict[str, Any] = {"model": raw_binding}
        elif isinstance(raw_binding, dict):
            binding = raw_binding
        else:
            raise ValueError(f"任务 {task_key} 的配置必须是对象")

        provider_override = _clean_text(binding.get("provider_profile"))
        if provider_override and provider_override not in provider_ids:
            raise ValueError(f"任务 {task_key} 使用了未知 provider: {provider_override}")
        model = _validate_model(binding.get("model", ""), task_key)
        normalized_tasks[task_key] = {
            "provider_profile": provider_override,
            "model": model,
        }

    return {
        "version": APP_SETTINGS_VERSION,
        "delivery": {'youtube_bcc': delivery.get('youtube_bcc', False)},
        "defaults": {
            "source_language": source_language,
            "ocr_language": ocr_language,
            "target_language": target_language,
            "provider_profile": default_provider,
            "model": default_model,
        },
        "tasks": normalized_tasks,
    }


def _default_provider_id(providers: list[ProviderProfile]) -> str:
    if any(provider.id == "volcano" for provider in providers):
        return "volcano"
    return providers[0].id if providers else ""


def _choice_or_default(value: Any, allowed: frozenset[str], fallback: str) -> str:
    cleaned = _clean_text(value).lower()
    return cleaned if cleaned in allowed else fallback


def _required_choice(value: Any, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    cleaned = value.strip().lower()
    if cleaned not in allowed:
        raise ValueError(f"不支持的 {field}: {value}")
    return cleaned


def _validate_model(value: Any, task_key: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"任务 {task_key} 的 model 必须是字符串")
    model = value.strip()
    if len(model) > MAX_MODEL_LENGTH:
        raise ValueError(f"任务 {task_key} 的 model 不能超过 {MAX_MODEL_LENGTH} 个字符")
    if any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ValueError(f"任务 {task_key} 的 model 包含非法控制字符")
    return model


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
