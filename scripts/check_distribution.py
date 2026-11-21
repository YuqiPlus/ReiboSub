"""Fail closed on unexpected files or private persistence code in a release.

Run on both the wheel and sdist built from a clean, committed checkout. This is
not a replacement for reviewing the source or checking real private credentials.
Only the standard library is used, so this also runs before package installation.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile


FORBIDDEN_TEXT = (
    b"from video_translate.storage import", b"storage_read_file(",
    b"storage_write_file(", b"get_store(", b"/api/storage/status",
    b"/data/wjq/", b"10.112.246.255",
)
SECRET = re.compile(rb"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bpypi-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,})")


def check_member(name: str, data: bytes, *, wheel: bool, version: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    parts = path.parts
    allowed = False
    code = parts if wheel else parts[1:] if parts[:1] == ("src",) else ()
    if len(code) >= 2 and code[0] == "reibosub":
        allowed = path.suffix == ".py" or code == ("reibosub", "py.typed")
    dist_info = f"reibosub-{version}.dist-info"
    if wheel and len(parts) == 2 and parts[0] == dist_info:
        allowed = parts[1] in {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt"}
    if wheel and name == f"{dist_info}/licenses/LICENSE":
        allowed = True
    if not wheel:
        allowed |= name in {"pyproject.toml", "MANIFEST.in", "LICENSE", "README.md", "CHANGELOG.md", "PKG-INFO", "setup.cfg", "docs/python-api.md"}
        info = parts[1:] if parts[:1] == ("src",) else parts
        allowed |= len(info) == 2 and info[0] == "reibosub.egg-info" and info[1] in {"PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"}
        allowed |= len(parts) == 3 and parts[:2] == ("examples", "python_api") and path.suffix == ".py"
    if not allowed:
        raise ValueError(f"File outside release allowlist: {name}")
    if SECRET.search(data) or any(token in data for token in FORBIDDEN_TEXT):
        raise ValueError(f"Private credential, local path or persistence code in: {name}")
    if path.name in {"METADATA", "PKG-INFO"}:
        meta = BytesParser().parsebytes(data)
        if meta["Name"] != "reibosub" or meta["Version"] != version:
            raise ValueError("Release metadata name/version mismatch")
        if "database" in (meta.get_all("Provides-Extra") or []):
            raise ValueError("Local database extra entered release metadata")
        for requirement in meta.get_all("Requires-Dist") or []:
            name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0].lower()
            if name not in {"opencc-python-reimplemented", "packaging", "pytest", "tomli"}:
                raise ValueError("Application dependency entered toolkit metadata")
        if set(meta.get_all("Provides-Extra") or []) - {"dev"}:
            raise ValueError("Application extra entered toolkit metadata")
        if meta["License-Expression"] != "Apache-2.0":
            raise ValueError("Missing Apache-2.0 license expression")


def inspect_archive(path: Path, *, version: str) -> int:
    wheel = path.suffix == ".whl"
    expected = f"reibosub-{version}-py3-none-any.whl" if wheel else f"reibosub-{version}.tar.gz"
    if path.name != expected:
        raise ValueError(f"Unexpected release filename: {path.name}")
    entries = {}
    if wheel:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                if entry.filename in entries or entry.file_size > 5_000_000:
                    raise ValueError("Duplicate or oversized archive member")
                entries[entry.filename] = archive.read(entry)
    else:
        with tarfile.open(path, "r:gz") as archive:
            root = f"reibosub-{version}/"
            for entry in archive.getmembers():
                if entry.isdir():
                    continue
                if not entry.isfile() or not entry.name.startswith(root) or entry.size > 5_000_000:
                    raise ValueError("Unsafe source archive member")
                name = entry.name[len(root):]
                if name in entries:
                    raise ValueError("Duplicate source archive member")
                entries[name] = archive.extractfile(entry).read()
    for name, data in entries.items():
        check_member(name, data, wheel=wheel, version=version)
    prefix = "" if wheel else "src/"
    required = {prefix + name for name in ("reibosub/__init__.py", "reibosub/py.typed", "reibosub/models.py", "reibosub/dependencies.py")}
    required.add(f"reibosub-{version}.dist-info/METADATA" if wheel else "PKG-INFO")
    if not required <= entries.keys():
        raise ValueError("Release is missing required package files")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version")
    args = parser.parse_args()
    version = args.version
    if version is None:
        import tomllib  # Release tools run on Python 3.11+, package supports 3.10+.
        metadata = Path(__file__).resolve().parents[1] / "packages/subtitles/pyproject.toml"
        version = tomllib.loads(metadata.read_text())["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        parser.error("Expected a stable x.y.z version")
    files = sorted(args.directory.iterdir())
    if len(files) != 2 or {p.suffix for p in files} != {".whl", ".gz"}:
        parser.error("Expected exactly one wheel and one source archive")
    for path in files:
        print(f"PASS {path.name}: {inspect_archive(path, version=version)} public files")


if __name__ == "__main__":
    main()
