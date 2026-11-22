"""Toolkit setup is independent of the web product and its extras."""
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import subprocess
import threading

import pytest

from reibosub import DependencyInstallError, MissingDependencyError, ValidationError
from reibosub import dependencies as deps


@pytest.fixture
def env(monkeypatch, tmp_path):
    meta = Message()
    dist = SimpleNamespace(metadata=meta, requires=['opencc-python-reimplemented>=0.1.7,<0.2', 'packaging>=24'])
    monkeypatch.setattr(deps.metadata, 'distribution', lambda name: dist)
    versions = {}
    monkeypatch.setattr(deps, '_installed', lambda name: versions.get(name))
    monkeypatch.setattr(deps, '_module_available', lambda name: True)
    monkeypatch.setattr(deps, '_managed_environment', lambda: True)
    monkeypatch.setattr(deps, '_loaded_frameworks', lambda: ())
    monkeypatch.setattr(deps, '_INSTALL_LOCK', threading.Lock())
    monkeypatch.setattr(deps.sys, 'prefix', str(tmp_path))
    return versions


def test_only_toolkit_features_are_public(env):
    assert deps.FEATURES == ('core', 'asr', 'ocr', 'ocr-cpu', 'video')
    for feature in ('web', 'download', 'database'):
        with pytest.raises(ValidationError):
            deps.check_feature(feature)


def test_optional_framework_install_is_never_implicit(env, monkeypatch):
    def status(feature):
        return deps.FeatureStatus(feature, ('faster-whisper>=1.1,<2',), ('faster-whisper>=1.1,<2',), ('faster_whisper',), ())
    monkeypatch.setattr(deps, 'check_feature', status)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('unexpected install'))
    with pytest.raises(MissingDependencyError, match='reibosub\\[asr\\]'):
        deps.ensure_feature('asr')
    with pytest.raises(DependencyInstallError, match='explicitly before runtime'):
        deps.ensure_feature('asr', install=True)


def test_diagnostics_never_install(env, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('unexpected install'))
    assert not deps.check_feature().ready
    with pytest.raises(MissingDependencyError):
        deps.ensure_feature()


def test_explicit_repair_only_installs_lightweight_requirements(env, monkeypatch):
    calls = []
    def pip(command, **kwargs):
        calls.append(command)
        env.update({'opencc-python-reimplemented': '0.1.7', 'packaging': '26.3'})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', pip)
    assert deps.ensure_feature(install=True).ready
    assert calls[0][:4] == (deps.sys.executable, '-m', 'pip', 'install')
    assert len(calls[0]) == 6
    assert not (Path(deps.sys.prefix) / '.reibosub-install.lock').exists()


@pytest.mark.parametrize('reason', ['system', 'loaded', 'pip', 'lock'])
def test_install_guards(env, monkeypatch, reason):
    if reason == 'system':
        monkeypatch.setattr(deps, '_managed_environment', lambda: False)
    elif reason == 'loaded':
        monkeypatch.setattr(deps, '_loaded_frameworks', lambda: ('numpy',))
    elif reason == 'pip':
        monkeypatch.setattr(deps, '_module_available', lambda name: name != 'pip')
    else:
        (Path(deps.sys.prefix) / '.reibosub-install.lock').write_text('test lock')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('unsafe install'))
    with pytest.raises(DependencyInstallError):
        deps.ensure_feature(install=True)


def test_install_errors_do_not_leak_index_credentials(env, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stderr='private-index-password'))
    with pytest.raises(DependencyInstallError) as error:
        deps.ensure_feature(install=True)
    assert 'private-index-password' not in str(error.value)
