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
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from reibosub.errors import DependencyInstallError, MissingDependencyError, ValidationError


@dataclass(frozen=True, slots=True)
class _Feature:
    extra: str | None
    modules: tuple[str, ...]
    tools: tuple[str, ...] = ()


_FEATURES = {
    "core": _Feature(None, ("opencc", "packaging")),
    "translate": _Feature("translate", ("requests", "yaml")),
    "download": _Feature("download", ("yt_dlp", "yt_dlp_ejs", "PIL", "requests", "yaml"), ("ffmpeg", "ffprobe", "node")),
    "video": _Feature("video", ("cv2", "PIL"), ("ffmpeg", "ffprobe")),
    "ocr": _Feature("ocr", ("cv2", "paddleocr", "PIL", "requests", "yaml")),
    "ocr-cpu": _Feature("ocr-cpu", ("cv2", "paddleocr", "paddle", "PIL", "requests", "yaml")),
    "asr": _Feature("asr", ("faster_whisper",), ("ffmpeg", "ffprobe")),
    "diarization": _Feature("diarization", ("pyannote.audio",), ("ffmpeg", "ffprobe")),
    "web": _Feature("web", ("yt_dlp", "yt_dlp_ejs", "PIL", "requests", "yaml")),
    "all-cpu": _Feature("all-cpu", ("yt_dlp", "yt_dlp_ejs", "PIL", "requests", "yaml", "cv2", "paddleocr", "paddle", "faster_whisper"), ("ffmpeg", "ffprobe", "node")),
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
        distribution = metadata.distribution("reibosub-web")
        distribution_name = "reibosub-web"
    except metadata.PackageNotFoundError:
        # Existing source deployments still have the pre-split distribution
        # metadata. Read it without reinstalling or changing a running service.
        try:
            distribution = metadata.distribution("reibosub")
        except metadata.PackageNotFoundError:
            raise MissingDependencyError("Install the web project: python -m pip install -e ./packages/subtitles -e '.[web]'") from None
        legacy_extras = set(distribution.metadata.get_all("Provides-Extra") or ())
        if not {"ocr-cpu", "asr"} <= legacy_extras:
            raise MissingDependencyError("Only the subtitle toolkit is installed. Install the separate web project with -e '.[web]'") from None
        distribution_name = "reibosub"
    extras = set(distribution.metadata.get_all("Provides-Extra") or ())
    extra = _FEATURES[feature].extra
    if distribution_name == "reibosub" and extra is not None and extra not in extras:
        # Before extras were split, these dependencies lived in the base group.
        extra = None
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
            if canonicalize_name(requirement.name) == distribution_name:
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
    if "yt_dlp_ejs" in modules:
        # yt-dlp itself may already exist without its explicitly requested extra.
        # Re-requesting [default] lets pip install the missing challenge component.
        missing.extend(raw for raw in requirements if Requirement(raw).name == "yt-dlp" and raw not in missing)
    tools = tuple(name for name in descriptor.tools if shutil.which(name) is None)
    manual, conflicts = [], []
    if feature == "ocr" and not _module_available("paddle"):
        manual.append("Choose a Paddle engine: select ocr-cpu explicitly, or install a matching paddlepaddle-gpu manually")
    if feature in {"ocr-cpu", "all-cpu"} and _installed("paddlepaddle-gpu") is not None:
        conflicts.append("GPU Paddle is installed; refusing to install CPU Paddle over it. Use the ocr extra and keep your GPU engine")
    elif feature in {"ocr-cpu", "all-cpu"} and _module_available("paddle") and _installed("paddlepaddle") is None:
        conflicts.append("An unclassified Paddle engine is present; choose/repair its CPU or GPU distribution manually before installing CPU Paddle")
    notes = ("Diagnostics check package versions and tool paths, not CUDA compatibility, model weights, authorization or remote API access.",)
    if feature == "web":
        notes += ("Web dependencies do not include OCR/ASR; existing source checkout and a frontend build are still needed.",)
    return FeatureStatus(feature, requirements, tuple(missing), modules, tools, tuple(manual), tuple(conflicts), notes)


def _managed_environment() -> bool:
    return sys.prefix != sys.base_prefix or (Path(sys.prefix) / "conda-meta").is_dir()


def _loaded_frameworks() -> tuple[str, ...]:
    return tuple(name for name in ("numpy", "cv2", "paddle", "paddleocr", "torch", "faster_whisper", "pyannote.audio", "video_translate.web_agent") if name in sys.modules)


def _failure_message(status: FeatureStatus) -> str:
    parts = [f"Feature '{status.feature}' is not ready."]
    if status.missing_requirements:
        parts.append("Missing/incompatible Python packages: " + ", ".join(status.missing_requirements))
    if status.missing_modules:
        parts.append("Unavailable imports: " + ", ".join(status.missing_modules))
    if status.missing_external:
        parts.append("External tools missing: " + ", ".join(status.missing_external) + '. Install separately with conda-forge (ffmpeg / "nodejs>=22.12"); no automatic OS installation.')
    parts.extend(status.conflicts + status.manual_steps)
    parts.append(f"Inspect with: python -m video_translate.dependencies doctor {status.feature}; opt in with: python -m video_translate.dependencies setup {status.feature} --yes")
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
        return replace(result, installation_performed=True, restart_recommended=feature in {"video", "ocr", "ocr-cpu", "asr", "diarization", "all-cpu"})
    finally:
        if created:
            lock.unlink(missing_ok=True)
        _INSTALL_LOCK.release()


def main(argv=None):
    import argparse
    from dataclasses import asdict
    parser = argparse.ArgumentParser(description="Web application dependency diagnosis; never installs without --yes")
    parser.add_argument("command", choices=("doctor", "setup"))
    parser.add_argument("feature", nargs="?", default="web", choices=FEATURES)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        status = check_feature(args.feature)
        print(json.dumps(asdict(status) | {"ready": status.ready}, ensure_ascii=False, indent=2))
        if args.command == "setup" and not args.dry_run and not status.ready:
            if not args.yes:
                parser.error("No installation performed; --yes is required")
            status = ensure_feature(args.feature, install=True)
            print(json.dumps(asdict(status) | {"ready": status.ready}, ensure_ascii=False, indent=2))
    except (DependencyInstallError, MissingDependencyError, ValidationError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
