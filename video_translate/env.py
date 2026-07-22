from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


REBOSUB_CONFIG_PATH = Path("configs") / "reibosub.yaml"
REBOSUB_CONFIG_KEYS = frozenset({"media_dir", "youtube_proxy", "host", "port"})
REBOSUB_ENV_MAP = {
    "youtube_proxy": ("YTDLP_PROXY",),
    "host": ("VIDEO_TRANSLATE_HOST",),
    "port": ("VIDEO_TRANSLATE_PORT",),
    # Keep the Agent asset library and the standalone YouTube commands on the
    # same root. Older installations may still override either variable from
    # local_runtime.yaml or .env.
    "media_dir": ("VIDEO_TRANSLATE_DOWNLOAD_DIR", "YTDLP_OUTPUT_DIR"),
}

# Compatibility-only configuration. New installations use reibosub.yaml, but
# this loader stays in place so existing advanced overrides (OCR device, cache
# paths, and similar settings) continue to work unchanged.
LOCAL_RUNTIME_CONFIG_PATH = Path("configs") / "local_runtime.yaml"
LOCAL_RUNTIME_ENV_KEYS = frozenset(
    {
        "VIDEO_TRANSLATE_HOST",
        "VIDEO_TRANSLATE_PORT",
        "VIDEO_TRANSLATE_DOWNLOAD_DIR",
        "VIDEO_TRANSLATE_GLOSSARY_DIR",
        "VIDEO_TRANSLATE_JOB_DIR",
        "VIDEO_TRANSLATE_TASK_DIR",
        "VIDEO_TRANSLATE_CACHE_DIR",
        "VIDEO_TRANSLATE_OCR_DEVICE",
        "YTDLP_PROXY",
        "YTDLP_OUTPUT_DIR",
        "YTDLP_SUB_LANGS",
        "YTDLP_THUMBNAIL_FORMAT",
        "LLM_REQUEST_TIMEOUT",
        "LLM_REQUEST_RETRIES",
        "ASR_DEVICE",
        "ASR_COMPUTE_TYPE",
        "ASR_MODEL_SIZE",
        "ASR_PROBE_MODEL_SIZE",
    }
)


def load_dotenv(anchor: Path | str | None = None, *, override: bool = False) -> None:
    roots: list[Path] = [Path.cwd()]
    if anchor is not None:
        anchor_path = Path(anchor).expanduser().resolve()
        roots.append(anchor_path if anchor_path.is_dir() else anchor_path.parent)

    seen: set[Path] = set()
    for root in roots:
        reibosub_config = root / REBOSUB_CONFIG_PATH
        if reibosub_config not in seen and reibosub_config.exists():
            seen.add(reibosub_config)
            _apply_environment(_read_reibosub_config(reibosub_config), override=override)

        runtime_config = root / LOCAL_RUNTIME_CONFIG_PATH
        if runtime_config not in seen and runtime_config.exists():
            seen.add(runtime_config)
            _apply_environment(_read_local_runtime(runtime_config), override=override)

        dotenv = root / ".env"
        if dotenv in seen or not dotenv.exists():
            continue
        seen.add(dotenv)
        values: dict[str, str] = {}
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
        _apply_environment(values, override=override)


def _read_reibosub_config(path: Path) -> dict[str, str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError("reibosub.yaml 不是有效的 YAML") from None

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("reibosub.yaml 必须是 YAML 对象")

    unknown = sorted(str(key) for key in data if str(key) not in REBOSUB_CONFIG_KEYS)
    if unknown:
        raise ValueError(f"reibosub.yaml 含有不支持的配置项: {', '.join(unknown)}")

    result: dict[str, str] = {}
    for key, value in data.items():
        name = str(key)
        if name == "port":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError("reibosub.yaml 的 port 必须是 1 到 65535 之间的整数")
            text = str(value)
        else:
            if not isinstance(value, str):
                raise ValueError(f"reibosub.yaml 的 {name} 必须是字符串")
            text = value.strip()
            if name in {"media_dir", "host"} and not text:
                raise ValueError(f"reibosub.yaml 的 {name} 不能为空")

        for env_key in REBOSUB_ENV_MAP[name]:
            result[env_key] = text
    return result


def _read_local_runtime(path: Path) -> dict[str, str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise ValueError("local_runtime.yaml 不是有效的 YAML") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("local_runtime.yaml 必须是 version: 1 的 YAML 对象")
    raw_environment = data.get("environment")
    if not isinstance(raw_environment, dict):
        raise ValueError("local_runtime.yaml 的 environment 必须是对象")

    unknown = sorted(str(key) for key in raw_environment if str(key) not in LOCAL_RUNTIME_ENV_KEYS)
    if unknown:
        raise ValueError(f"local_runtime.yaml 含有不支持的配置项: {', '.join(unknown)}")

    result: dict[str, str] = {}
    for key, value in raw_environment.items():
        if value is None:
            result[str(key)] = ""
        elif isinstance(value, (str, int, float, bool)):
            result[str(key)] = str(value)
        else:
            raise ValueError(f"local_runtime.yaml 的 {key} 必须是标量值")
    return result


def _apply_environment(values: dict[str, Any], *, override: bool) -> None:
    for key, value in values.items():
        text = str(value)
        if override:
            os.environ[key] = text
        else:
            os.environ.setdefault(key, text)
