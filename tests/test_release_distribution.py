from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import re
import subprocess
import sys
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
    prefix = '' if wheel else 'src/'
    data = {prefix + name: b"# public Python\n" for name in ("reibosub/__init__.py", "reibosub/py.typed", "reibosub/models.py", "reibosub/dependencies.py")}
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
    assert audit.inspect_archive(archive(tmp_path, files(wheel), wheel), version=VERSION) == 5


@pytest.mark.parametrize("name", [".env", "configs/provider_secrets.yaml", "outputs/job.json", "tests/input.srt", "video_translate/cli.py", "video_translate/web_agent.py", "video_translate/storage.py", "video_translate/storage_migration.py", "reibosub/secret.key", "../escaped.py", "reibosub/../../escaped.py", "frontend/dist/index.html"])
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


def test_website_dependency_cannot_leak_into_toolkit_metadata(tmp_path):
    data = files(True)
    data[f"reibosub-{VERSION}.dist-info/METADATA"] = INFO.replace(b"\n\n", b"\nRequires-Dist: paddleocr>=3\n\n")
    with pytest.raises(ValueError, match="approved optional extra"):
        audit.inspect_archive(archive(tmp_path, data), version=VERSION)


@pytest.mark.parametrize('name,extra', [('faster-whisper', 'asr'), ('paddleocr', 'ocr'), ('paddleocr', 'ocr-cpu'), ('paddlepaddle', 'ocr-cpu'), ('av', 'video'), ('numpy', 'video')])
def test_recognition_dependencies_must_be_explicit_extras(tmp_path, name, extra):
    data = files(True)
    data[f"reibosub-{VERSION}.dist-info/METADATA"] = INFO.replace(b'\n\n', f'\nProvides-Extra: {extra}\nRequires-Dist: {name}; extra == "{extra}"\n\n'.encode())
    assert audit.inspect_archive(archive(tmp_path, data), version=VERSION) == 5


@pytest.mark.parametrize('marker', ['', '; extra == "dev"', '; extra == "asr" or python_version > "3.0"'])
def test_recognition_cannot_become_a_default_dependency(tmp_path, marker):
    data = files(True)
    data[f"reibosub-{VERSION}.dist-info/METADATA"] = INFO.replace(b'\n\n', f'\nRequires-Dist: faster-whisper{marker}\n\n'.encode())
    with pytest.raises(ValueError, match='approved optional extra'):
        audit.inspect_archive(archive(tmp_path, data), version=VERSION)


def test_publish_workflow_is_tag_guarded_and_separates_oidc_from_build():
    workflow = yaml.load((ROOT / ".github/workflows/publish.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow['on']['push'] == {'tags': ['publish/v*']}
    assert "workflow_dispatch" in workflow["on"]
    assert workflow['on']['workflow_dispatch']['inputs']['publish']['default'] == 'false'
    jobs = workflow["jobs"]
    assert "permissions" not in jobs["build"]
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert jobs["publish"]["environment"]["name"] == "pypi"
    assert "github.event_name == 'workflow_dispatch'" in jobs["publish"]["if"]
    assert "inputs.publish" in jobs['publish']['if']
    assert "startsWith(github.ref, 'refs/tags/publish/v')" in jobs['publish']['if']
    assert "github.ref_type == 'tag'" in jobs["publish"]["if"]
    assert jobs["publish"]["needs"] == ["build", "test"]
    assert all("run" not in step for step in jobs["publish"]["steps"])
    for job in jobs.values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])


@pytest.mark.parametrize('source_version,ref_type,ref,publish,ok', [
    ('0.1.0', 'branch', 'main', 'false', True),
    ('0.1.0', 'tag', 'v0.1.0', 'true', True),
    ('0.1.1', 'tag', 'v0.1.0', 'true', False),
    ('0.1.0', 'tag', 'v0.1.1', 'true', False),
    ('0.1.0', 'branch', 'main', 'true', False),
    ('0.1.0', 'tag', 'publish/v0.1.0', 'false', True),
    ('0.1.0', 'tag', 'publish/v0.1.1', 'false', False),
    ('0.1.0', 'tag', 'publish/v0.1.0-extra', 'false', False),
])
def test_real_workflow_version_guard(tmp_path, source_version, ref_type, ref, publish, ok):
    workflow = yaml.load((ROOT / '.github/workflows/publish.yml').read_text(), Loader=yaml.BaseLoader)
    step = next(step for step in workflow['jobs']['build']['steps'] if step.get('name') == 'Validate release version')
    script = step['run'].split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    project = tmp_path / 'packages/subtitles'
    (project / 'src/reibosub').mkdir(parents=True)
    (project / 'pyproject.toml').write_text('[project]\nversion="0.1.0"\n')
    (project / 'src/reibosub/__init__.py').write_text(f'__version__ = "{source_version}"\n')
    env = {**os.environ, 'GITHUB_REF_TYPE': ref_type, 'GITHUB_REF_NAME': ref, 'PUBLISH_REQUESTED': publish}
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is ok, result.stderr
