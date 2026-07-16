from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_CONFIG_PATH = Path("configs") / "llm.yaml"
DEFAULT_APP_SETTINGS_PATH = Path("configs") / "app_settings.yaml"


@dataclass(frozen=True)
class LLMTaskConfig:
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    provider: str = DEFAULT_PROVIDER
    fallback_models: tuple[str, ...] = ()
    provider_profile: str | None = None


def load_llm_task_config(task: str, *, root: Path | None = None, explicit_model: str | None = None, explicit_base_url: str | None = None) -> LLMTaskConfig:
    root = root or Path(__file__).resolve().parent.parent
    config_path = root / DEFAULT_CONFIG_PATH
    data = _load_config(config_path)
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    task_config = tasks.get(task) if isinstance(tasks.get(task), dict) else {}
    env_model_name = str(task_config.get("env_model") or "").strip()
    env_base_url_name = str(
        task_config.get("env_base_url")
        or task_config.get("base_url_env")
        or defaults.get("env_base_url")
        or defaults.get("base_url_env")
        or ""
    ).strip()
    env_api_key_name = str(
        task_config.get("env_api_key")
        or task_config.get("api_key_env")
        or defaults.get("env_api_key")
        or defaults.get("api_key_env")
        or ""
    ).strip()
    models = defaults.get("models") if isinstance(defaults.get("models"), dict) else {}
    model_role = _clean(task_config.get("model_role"))
    fallback_roles = _clean_list(task_config.get("fallback_roles"))

    legacy_model = (
        _env(env_model_name)
        or _clean(task_config.get("model"))
        or _model_for_role(models, model_role)
        or _env("LLM_MODEL")
        or _env("ARK_MODEL")
        or _clean(defaults.get("model"))
        or _model_for_role(models, "default")
    )
    legacy_base_url = (
        _env(env_base_url_name)
        or _clean(task_config.get("base_url"))
        or _env("LLM_BASE_URL")
        or _env("ARK_BASE_URL")
        or _clean(defaults.get("base_url"))
    )
    legacy_api_key = (
        _env(env_api_key_name)
        or _env("LLM_API_KEY")
        or _env("ARK_API_KEY")
    )
    legacy_provider = (
        _clean(task_config.get("provider"))
        or _clean(defaults.get("provider"))
        or DEFAULT_PROVIDER
    )
    legacy_fallback_models = _clean_list(task_config.get("fallback_models") or defaults.get("fallback_models"))
    legacy_fallback_models.extend(_model_for_role(models, role) for role in fallback_roles)
    legacy_fallback_models = [item for item in legacy_fallback_models if item]

    app_defaults, app_task = _load_app_task_settings(root, task)
    overlay_model = _clean(app_task.get("model"))
    profile_id, profile = _resolve_app_provider_profile(root, app_defaults, app_task)

    model = _clean(explicit_model) or overlay_model or legacy_model
    base_url = _clean(explicit_base_url) or _profile_value(profile, "base_url") or legacy_base_url
    api_key = _profile_api_key(profile) or legacy_api_key
    # ``provider`` is the legacy transport/protocol field used by run config
    # validation.  The selected vendor/profile has its own dedicated field and
    # must not turn values such as ``openai-compatible`` into a profile id.
    provider = legacy_provider

    has_overlay_fallbacks = "fallback_models" in app_task
    if has_overlay_fallbacks:
        fallback_models = _clean_list(app_task.get("fallback_models"))
    elif overlay_model:
        # A legacy fallback generally belongs to the legacy provider.  Carrying
        # it across a Settings-selected model can send an invalid model ID to
        # the newly selected provider, so an overlay model opts out by default.
        fallback_models = []
    else:
        fallback_models = legacy_fallback_models
    fallback_models = [
        item
        for item in fallback_models
        if item and (not has_overlay_fallbacks or item != model)
    ]
    return LLMTaskConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        provider=provider,
        fallback_models=tuple(fallback_models),
        provider_profile=profile_id,
    )



def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"LLM 配置必须是 YAML 对象: {path}")
    return data


def _load_app_task_settings(root: Path, task: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = _load_config(root / DEFAULT_APP_SETTINGS_PATH)
    if data.get("version") != 1:
        return {}, {}
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    task_config = tasks.get(task) if isinstance(tasks.get(task), dict) else {}
    return defaults, task_config


def _resolve_app_provider_profile(
    root: Path,
    app_defaults: dict[str, Any],
    app_task: dict[str, Any],
) -> tuple[str | None, Any]:
    candidates = [
        _clean(app_task.get("provider_profile")),
        _clean(app_defaults.get("provider_profile")),
    ]
    seen: set[str] = set()
    for profile_id in candidates:
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        profile = _get_provider_profile(profile_id, root)
        if profile is not None:
            return profile_id, profile
    return None, None


def _get_provider_profile(profile_id: str, root: Path) -> Any:
    try:
        from video_translate.provider_profiles import get_provider_profile
    except ModuleNotFoundError as exc:
        if exc.name != "video_translate.provider_profiles":
            raise
        return None
    try:
        return get_provider_profile(profile_id, root=root)
    except (FileNotFoundError, KeyError, ValueError):
        return None


def _profile_value(profile: Any, name: str) -> str | None:
    if profile is None:
        return None
    value = profile.get(name) if isinstance(profile, dict) else getattr(profile, name, None)
    return _clean(value)


def _profile_api_key(profile: Any) -> str | None:
    api_key = _profile_value(profile, "api_key")
    if api_key:
        return api_key
    return _env(_profile_value(profile, "api_key_env") or "")


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _env(name: str) -> str | None:
    if not name:
        return None
    return _clean(os.environ.get(name))


def _model_for_role(models: dict[str, Any], role: str | None) -> str | None:
    if not role:
        return None
    return _clean(models.get(role))


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    result: list[str] = []
    for item in values:
        cleaned = _clean(item)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result
