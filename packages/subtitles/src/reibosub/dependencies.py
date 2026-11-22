"""Read-only feature diagnostics and explicit, guarded environment installation.

No installation takes place on import or during check_feature(). Package/version
constraints come from this installed distribution's metadata, not a second list.
"""
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import DependencyInstallError, MissingDependencyError, ValidationError


@dataclass(frozen=True, slots=True)
class _Feature:
    extra: str | None
    modules: tuple[str, ...]
    tools: tuple[str, ...] = ()


_FEATURES = {
    "core": _Feature(None, ("opencc", "packaging")),
    "asr": _Feature("asr", ("faster_whisper",)),
    "ocr": _Feature("ocr", ("paddleocr", "paddle")),
    "ocr-cpu": _Feature("ocr-cpu", ("paddleocr", "paddle")),
    "video": _Feature("video", ("av", "numpy")),
}
FEATURES = tuple(_FEATURES)
_INSTALL_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class FeatureStatus:
    feature: str
    requirements: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    missing_modules: tuple[str, ...]
    missing_external: tuple[str, ...]
    manual_steps: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    installation_performed: bool = False
    restart_recommended: bool = False

    @property
    def python_ready(self) -> bool:
        return not (self.missing_requirements or self.missing_modules or self.conflicts)

    @property
    def ready(self) -> bool:
        return self.python_ready and not (self.missing_external or self.manual_steps)

    @property
    def install_command(self) -> tuple[str, ...]:
        return (sys.executable, "-m", "pip", "install", *self.missing_requirements)


def _requirements(feature: str) -> tuple[str, ...]:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    try:
        distribution = metadata.distribution("reibosub")
    except metadata.PackageNotFoundError:
        raise MissingDependencyError("Install the current ReiboSub source first: python -m pip install -e ./packages/subtitles") from None
    extras = set(distribution.metadata.get_all("Provides-Extra") or ())
    extra = _FEATURES[feature].extra
    if extra is not None and extra not in extras:
        raise MissingDependencyError(f"Installed metadata does not provide [{extra}]; reinstall the current source before dependency setup")
    requirements, visited = set(), set()

    def visit(selected):
        if selected in visited:
            return
        visited.add(selected)
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if requirement.marker is not None and not requirement.marker.evaluate({"extra": selected or ""}):
                continue
            if canonicalize_name(requirement.name) == "reibosub":
                for child in requirement.extras:
                    if child not in extras:
                        raise MissingDependencyError(f"Incomplete installed metadata for [{child}]")
                    visit(child)
                continue
            if requirement.url is not None:
                raise DependencyInstallError("Direct-URL dependencies require manual installation")
            requirement.marker = None
            requirements.add(str(requirement))
    visit(extra)
    return tuple(sorted(requirements))


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def check_feature(feature: str = "core") -> FeatureStatus:
    """Inspect metadata/module paths/tool paths without importing model runtimes."""
    if not isinstance(feature, str) or feature not in _FEATURES:
        raise ValidationError(f"unknown feature: {feature}; choose from {', '.join(FEATURES)}")
    try:
        from packaging.requirements import Requirement
    except ImportError:
        raise MissingDependencyError("Install the lightweight packaging dependency first: python -m pip install packaging") from None
    requirements = _requirements(feature)
    missing = []
    for raw in requirements:
        requirement = Requirement(raw)
        version = _installed(requirement.name)
        if version is None or (requirement.specifier and not requirement.specifier.contains(version, prereleases=True)):
            missing.append(raw)
    descriptor = _FEATURES[feature]
    modules = tuple(name for name in descriptor.modules if not _module_available(name))
    tools = ()
    manual, conflicts = [], []
    notes = ("Toolkit diagnostics never load/download models or change the environment. Website setup remains separate.",)
    if feature in {"ocr", "ocr-cpu"}:
        if feature == "ocr" and not _module_available("paddle"):
            manual.append('Select a Paddle engine explicitly: CPU via reibosub[ocr-cpu], or a GPU wheel matching your CUDA runtime')
        if _installed("paddlepaddle") and _installed("paddlepaddle-gpu"):
            conflicts.append("Both CPU and GPU Paddle distributions are installed; repair in a separate environment")
    return FeatureStatus(feature, requirements, tuple(missing), modules, tools, tuple(manual), tuple(conflicts), notes)


def _managed_environment() -> bool:
    return sys.prefix != sys.base_prefix or (Path(sys.prefix) / "conda-meta").is_dir()


def _loaded_frameworks() -> tuple[str, ...]:
    return tuple(name for name in ("numpy", "cv2", "paddle", "paddleocr", "torch", "faster_whisper", "pyannote.audio") if name in sys.modules)


def _failure_message(status: FeatureStatus) -> str:
    parts = [f"Feature '{status.feature}' is not ready."]
    if status.missing_requirements:
        parts.append("Missing/incompatible Python packages: " + ", ".join(status.missing_requirements))
    if status.missing_modules:
        parts.append("Unavailable imports: " + ", ".join(status.missing_modules))
    parts.extend(status.conflicts + status.manual_steps)
    if status.feature == "core":
        parts.append("Inspect with: reibosub doctor core; opt in with: reibosub setup core --yes")
    else:
        parts.append(f'Install explicitly in an independent environment: python -m pip install "reibosub[{status.feature}]"')
    return " ".join(parts)


def ensure_feature(feature: str = "core", *, install: bool = False) -> FeatureStatus:
    """Validate a feature; install missing Python requirements only with opt-in.

    Installation is limited to the current venv/Conda environment and rejected
    if a model/native framework is already loaded. No GPU/OS/model installation.
    """
    status = check_feature(feature)
    if status.ready:
        return status
    if not install:
        raise MissingDependencyError(_failure_message(status))
    if feature != "core":
        raise DependencyInstallError("Recognition/media dependencies must be installed explicitly before runtime; no packages were installed. " + _failure_message(status))
    if status.conflicts or status.missing_external:
        raise DependencyInstallError(_failure_message(status))
    if not status.missing_requirements:
        raise MissingDependencyError(_failure_message(status) + " Restart or repair imports manually; no forced reinstall was attempted.")
    if not _managed_environment():
        raise DependencyInstallError("Automatic installation requires an activated venv or Conda environment; system Python is never modified")
    if _loaded_frameworks():
        raise DependencyInstallError("Model/native libraries are already loaded. Install in a fresh CLI process before loading OCR/ASR; do not modify a running server")
    if not _module_available("pip"):
        raise DependencyInstallError("pip is unavailable in this interpreter; install pip in the environment manually")
    if not _INSTALL_LOCK.acquire(blocking=False):
        raise DependencyInstallError("Another dependency install is already running")
    lock = Path(sys.prefix) / ".reibosub-install.lock"
    created = False
    try:
        try:
            with lock.open("x", encoding="utf-8") as handle:
                created = True
                json.dump({"pid": os.getpid(), "feature": feature}, handle)
        except FileExistsError:
            raise DependencyInstallError("Another install holds .reibosub-install.lock; inspect its PID before removing a stale lock") from None
        except OSError:
            raise DependencyInstallError("Cannot lock this environment for installation; install dependencies manually") from None
        try:
            process = subprocess.run(status.install_command, capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired):
            raise DependencyInstallError("Dependency installation could not finish; inspect the environment and retry manually") from None
        if process.returncode:
            raise DependencyInstallError(f"pip failed with exit code {process.returncode}; run the reported install command in a terminal. Provider/index output is not exposed")
        importlib.invalidate_caches()
        result = check_feature(feature)
        if not result.ready:
            raise MissingDependencyError(_failure_message(result) + " Python packages may have been installed; additional manual setup is still needed.")
        return replace(result, installation_performed=True, restart_recommended=False)
    finally:
        if created:
            lock.unlink(missing_ok=True)
        _INSTALL_LOCK.release()
