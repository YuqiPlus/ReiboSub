from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_cache_dir() -> Path:
    configured = os.environ.get("VIDEO_TRANSLATE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "models"


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


def cuda_library_dirs() -> list[Path]:
    roots = [Path(site_path) for site_path in site.getsitepackages()]
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site))
    roots.append(Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")

    dirs: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        nvidia_root = root / "nvidia"
        if not nvidia_root.exists():
            continue
        for lib_dir in nvidia_root.glob("*/lib"):
            if not lib_dir.is_dir():
                continue
            if not any(lib_dir.glob("lib*.so*")):
                continue
            resolved = lib_dir.resolve()
            if resolved not in seen:
                dirs.append(resolved)
                seen.add(resolved)
    return dirs


def prepend_library_path(env: dict[str, str], paths: list[Path], *, variable: str = "LD_LIBRARY_PATH") -> None:
    existing = [item for item in env.get(variable, "").split(":") if item]
    prefix = [str(path) for path in paths if str(path) not in existing]
    if prefix:
        env[variable] = ":".join([*prefix, *existing])
