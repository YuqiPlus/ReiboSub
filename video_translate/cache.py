from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_cache_dir() -> Path:
    configured = os.environ.get("VIDEO_TRANSLATE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / ".cache"


def configure_model_cache(cache_dir: Path | None = None) -> Path:
    root = (cache_dir or default_cache_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)

    paths = {
        "PADDLE_PDX_CACHE_HOME": root / "paddlex",
        "PADDLE_HOME": root / "paddle",
        "XDG_CACHE_HOME": root,
        "HF_HOME": root / "huggingface",
        "MODELSCOPE_CACHE": root / "modelscope",
    }
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
    for env_name, path in paths.items():
        os.environ.setdefault(env_name, str(path))
        Path(os.environ[env_name]).mkdir(parents=True, exist_ok=True)

    return root
