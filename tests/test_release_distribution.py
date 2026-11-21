from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import re
import tarfile
import zipfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_distribution", ROOT / "scripts/check_distribution.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
VERSION = "0.1.0"
INFO = b"Name: reibosub\nVersion: 0.1.0\nLicense-Expression: Apache-2.0\n\nPublic toolkit"


def files(wheel):
    data = {name: b"# public Python\n" for name in ("reibosub/__init__.py", "reibosub/py.typed", "reibosub/models.py", "reibosub/dependencies.py", "video_translate/cli.py")}
    data[f"reibosub-{VERSION}.dist-info/METADATA" if wheel else "PKG-INFO"] = INFO
    return data


def archive(tmp_path, data, wheel=True):
    path = tmp_path / (f"reibosub-{VERSION}-py3-none-any.whl" if wheel else f"reibosub-{VERSION}.tar.gz")
    if wheel:
        with zipfile.ZipFile(path, "w") as target:
            for name, content in data.items():
                target.writestr(name, content)
    else:
        with tarfile.open(path, "w:gz") as target:
            for name, content in data.items():
                member = tarfile.TarInfo(f"reibosub-{VERSION}/{name}")
                member.size = len(content)
                target.addfile(member, io.BytesIO(content))
    return path


@pytest.mark.parametrize("wheel", [True, False])
def test_public_archive_is_accepted(tmp_path, wheel):
    assert audit.inspect_archive(archive(tmp_path, files(wheel), wheel), version=VERSION) == 6


@pytest.mark.parametrize("name", [".env", "configs/provider_secrets.yaml", "outputs/job.json", "tests/input.srt", "video_translate/storage.py", "video_translate/storage_migration.py", "reibosub/secret.key", "../escaped.py", "reibosub/../../escaped.py", "frontend/dist/index.html"])
@pytest.mark.parametrize("wheel", [True, False])
def test_unexpected_and_private_files_are_rejected(tmp_path, name, wheel):
    data = files(wheel)
    data[name] = b"not permitted"
    with pytest.raises(ValueError):
        audit.inspect_archive(archive(tmp_path, data, wheel), version=VERSION)


@pytest.mark.parametrize("private", [b"from video_translate.storage import get_store", b"sk-" + b"A" * 30, b"pypi-" + b"a" * 30, b"/data/wjq/secret", b"-----BEGIN PRIVATE KEY-----"])
def test_private_content_in_python_is_rejected(tmp_path, private):
    data = files(True)
    data["reibosub/models.py"] = private
    with pytest.raises(ValueError, match="Private credential"):
        audit.inspect_archive(archive(tmp_path, data), version=VERSION)


def test_database_extra_is_rejected(tmp_path):
    data = files(True)
    data[f"reibosub-{VERSION}.dist-info/METADATA"] = INFO.replace(b"\n\n", b"\nProvides-Extra: database\n\n")
    with pytest.raises(ValueError, match="database extra"):
        audit.inspect_archive(archive(tmp_path, data), version=VERSION)


def test_missing_core_files_are_rejected(tmp_path):
    data = files(True)
    del data["reibosub/models.py"]
    with pytest.raises(ValueError, match="missing required"):
        audit.inspect_archive(archive(tmp_path, data), version=VERSION)


def test_publish_workflow_is_tag_guarded_and_separates_oidc_from_build():
    workflow = yaml.load((ROOT / ".github/workflows/publish.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["push"]["tags"] == ["v*"]
    assert "workflow_dispatch" in workflow["on"]
    jobs = workflow["jobs"]
    assert "permissions" not in jobs["build"]
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["publish"]["environment"]["name"] == "pypi"
    assert "github.event_name == 'push'" in jobs["publish"]["if"]
    assert "github.ref_type == 'tag'" in jobs["publish"]["if"]
    assert jobs["publish"]["needs"] == ["build", "test"]
    assert all("run" not in step for step in jobs["publish"]["steps"])
    for job in jobs.values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
