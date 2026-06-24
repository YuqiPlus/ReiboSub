from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PROVIDER = "volcengine"
DEFAULT_CONFIG_PATH = Path("configs") / "llm.yaml"


@dataclass(frozen=True)
class LLMTaskConfig:
    model: str | None = None
    base_url: str | None = None
    provider: str = DEFAULT_PROVIDER
    fallback_models: tuple[str, ...] = ()


def load_llm_task_config(task: str, *, root: Path | None = None, explicit_model: str | None = None, explicit_base_url: str | None = None) -> LLMTaskConfig:
    root = root or Path(__file__).resolve().parent.parent
    data = _load_config(root / DEFAULT_CONFIG_PATH)
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    task_config = tasks.get(task) if isinstance(tasks.get(task), dict) else {}
    env_model_name = str(task_config.get("env_model") or "").strip()
    env_base_url_name = str(task_config.get("env_base_url") or "").strip()

    model = (
        _clean(explicit_model)
        or _env(env_model_name)
        or _clean(task_config.get("model"))
        or _clean(defaults.get("model"))
        or _env("ARK_MODEL")
    )
    base_url = (
        _clean(explicit_base_url)
        or _env(env_base_url_name)
        or _clean(task_config.get("base_url"))
        or _clean(defaults.get("base_url"))
        or _env("ARK_BASE_URL")
    )
    provider = _clean(task_config.get("provider")) or _clean(defaults.get("provider")) or DEFAULT_PROVIDER
    fallback_models = _clean_list(task_config.get("fallback_models") or defaults.get("fallback_models"))
    return LLMTaskConfig(model=model, base_url=base_url, provider=provider, fallback_models=tuple(fallback_models))


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
