from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_CONFIG_PATH = Path("configs") / "llm.yaml"


@dataclass(frozen=True)
class LLMTaskConfig:
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    provider: str = DEFAULT_PROVIDER
    fallback_models: tuple[str, ...] = ()


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
        or defaults.get("env_base_url")
        or ""
    ).strip()
    env_api_key_name = str(
        task_config.get("env_api_key")
        or defaults.get("env_api_key")
        or ""
    ).strip()
    models = defaults.get("models") if isinstance(defaults.get("models"), dict) else {}
    model_role = _clean(task_config.get("model_role"))
    fallback_roles = _clean_list(task_config.get("fallback_roles"))

    model = (
        _clean(explicit_model)
        or _env(env_model_name)
        or _clean(task_config.get("model"))
        or _model_for_role(models, model_role)
        or _env("LLM_MODEL")
        or _env("ARK_MODEL")
        or _clean(defaults.get("model"))
        or _model_for_role(models, "default")
    )
    base_url = (
        _clean(explicit_base_url)
        or _env(env_base_url_name)
        or _clean(task_config.get("base_url"))
        or _env("LLM_BASE_URL")
        or _env("ARK_BASE_URL")
        or _clean(defaults.get("base_url"))
    )
    api_key = (
        _env(env_api_key_name)
        or _env("LLM_API_KEY")
        or _env("ARK_API_KEY")
    )
    provider = (
        _clean(task_config.get("provider"))
        or _clean(defaults.get("provider"))
        or DEFAULT_PROVIDER
    )
    fallback_models = _clean_list(task_config.get("fallback_models") or defaults.get("fallback_models"))
    fallback_models.extend(_model_for_role(models, role) for role in fallback_roles)
    fallback_models = [item for item in fallback_models if item]
    return LLMTaskConfig(model=model, base_url=base_url, api_key=api_key, provider=provider, fallback_models=tuple(fallback_models))



def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"LLM 配置必须是 YAML 对象: {path}")
    return data


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
