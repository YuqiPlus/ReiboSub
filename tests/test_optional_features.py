from __future__ import annotations

import email.message
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from reibosub import DependencyInstallError, MissingDependencyError, ValidationError
from video_translate import dependencies as dependencies
from video_translate.dependencies import main

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
VERSIONS = {'opencc-python-reimplemented': '0.1.7', 'packaging': '26.3', 'requests': '2.34.0', 'pyyaml': '6.0.3', 'yt-dlp': '2026.8.19', 'pillow': '12.0.0', 'opencv-python': '4.12.0', 'paddleocr': '3.5.0', 'paddlepaddle': '3.3.0', 'faster-whisper': '1.2.0', 'pyannote-audio': '4.0.0'}


VERSIONS['reibosub'] = '0.1.0'


@pytest.fixture
def feature_env(monkeypatch, tmp_path):
    headers = email.message.Message()
    for extra in PROJECT['optional-dependencies']:
        headers['Provides-Extra'] = extra
    requires = list(PROJECT['dependencies'])
    for extra, rows in PROJECT['optional-dependencies'].items():
        for row in rows:
            requirement = Requirement(row)
            marker = f'({requirement.marker}) and ' if requirement.marker else ''
            requirement.marker = None
            requires.append(f'{requirement}; {marker}extra == "{extra}"')
    distribution = SimpleNamespace(metadata=headers, requires=requires)
    monkeypatch.setattr(dependencies.metadata, 'distribution', lambda _: distribution)
    versions = {}
    monkeypatch.setattr(dependencies, '_installed', lambda name: versions.get(canonicalize_name(name)))
    monkeypatch.setattr(dependencies, '_module_available', lambda name: True)
    monkeypatch.setattr(dependencies.shutil, 'which', lambda name: '/tools/' + name)
    monkeypatch.setattr(dependencies, '_managed_environment', lambda: True)
    monkeypatch.setattr(dependencies, '_loaded_frameworks', lambda: ())
    monkeypatch.setattr(dependencies, '_INSTALL_LOCK', threading.Lock())
    monkeypatch.setattr(dependencies.sys, 'prefix', str(tmp_path))
    return versions


def names(rows):
    return {canonicalize_name(Requirement(row).name) for row in rows}


def test_legacy_running_environment_metadata_is_read_without_reinstall(monkeypatch):
    headers = email.message.Message()
    headers['Provides-Extra'] = 'ocr-cpu'
    headers['Provides-Extra'] = 'asr'
    legacy = SimpleNamespace(metadata=headers, requires=['requests>=2.31,<3', 'paddleocr>=3,<4'])
    def distribution(name):
        if name == 'reibosub-web':
            raise dependencies.metadata.PackageNotFoundError(name)
        return legacy
    monkeypatch.setattr(dependencies.metadata, 'distribution', distribution)
    assert names(dependencies._requirements('ocr')) == {'requests', 'paddleocr'}


def test_pure_toolkit_metadata_is_not_mistaken_for_web_install(monkeypatch):
    headers = email.message.Message()
    headers['Provides-Extra'] = 'dev'
    def distribution(name):
        if name == 'reibosub-web':
            raise dependencies.metadata.PackageNotFoundError(name)
        return SimpleNamespace(metadata=headers, requires=['packaging>=24'])
    monkeypatch.setattr(dependencies.metadata, 'distribution', distribution)
    with pytest.raises(MissingDependencyError, match='separate web project'):
        dependencies._requirements('web')


def test_minimal_base_and_recursive_feature_boundaries(feature_env):
    assert names(dependencies.check_feature('core').requirements) == {'reibosub', 'packaging'}
    web = names(dependencies.check_feature('web').requirements)
    assert {'yt-dlp', 'requests', 'pyyaml', 'pillow'} <= web
    assert not {'paddleocr', 'opencv-python', 'paddlepaddle', 'faster-whisper'} & web
    ocr = names(dependencies.check_feature('ocr').requirements)
    assert {'paddleocr', 'opencv-python'} <= ocr
    assert not {'paddlepaddle', 'paddlepaddle-gpu', 'faster-whisper'} & ocr
    assert 'paddlepaddle' in names(dependencies.check_feature('ocr-cpu').requirements)
    assert 'faster-whisper' in names(dependencies.check_feature('asr').requirements)
    assert 'paddlepaddle' not in names(dependencies.check_feature('asr').requirements)
    assert 'pyannote-audio' not in names(dependencies.check_feature('all-cpu').requirements)


def test_diagnostics_and_default_ensure_never_install(feature_env, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('diagnostics must not install'))
    status = dependencies.check_feature('asr')
    assert not status.ready and status.missing_requirements
    with pytest.raises(MissingDependencyError, match='setup asr --yes'):
        dependencies.ensure_feature('asr')
    with pytest.raises(ValidationError):
        dependencies.check_feature('not-a-feature')
    with pytest.raises(ValidationError):
        dependencies.check_feature([])


def test_explicit_install_uses_current_python_and_only_missing_declared_requirements(feature_env, monkeypatch, tmp_path):
    calls = []
    def pip(command, **kwargs):
        calls.append((command, kwargs))
        feature_env.update(VERSIONS)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', pip)
    status = dependencies.ensure_feature('core', install=True)
    assert status.ready and status.installation_performed
    command, options = calls[0]
    assert command[:4] == (dependencies.sys.executable, '-m', 'pip', 'install')
    assert names(command[4:]) == {'reibosub', 'packaging'}
    assert '--user' not in command and '--break-system-packages' not in command
    assert options['timeout'] == 900 and options['capture_output']
    assert not (tmp_path / '.reibosub-install.lock').exists()
    dependencies.ensure_feature('core', install=True)
    assert len(calls) == 1


@pytest.mark.parametrize('condition', ['system', 'framework', 'no-pip', 'gpu', 'tool', 'lock'])
def test_unsafe_installs_are_rejected_without_pip(feature_env, monkeypatch, tmp_path, condition):
    feature = 'core'
    if condition == 'system':
        monkeypatch.setattr(dependencies, '_managed_environment', lambda: False)
    elif condition == 'framework':
        monkeypatch.setattr(dependencies, '_loaded_frameworks', lambda: ('torch',))
    elif condition == 'no-pip':
        monkeypatch.setattr(dependencies, '_module_available', lambda name: name != 'pip')
    elif condition == 'gpu':
        feature, feature_env['paddlepaddle-gpu'] = 'ocr-cpu', '3.3.0'
    elif condition == 'tool':
        feature = 'asr'
        monkeypatch.setattr(dependencies.shutil, 'which', lambda _: None)
    else:
        (tmp_path / '.reibosub-install.lock').write_text('{"pid":123}')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('unsafe pip call'))
    with pytest.raises(DependencyInstallError):
        dependencies.ensure_feature(feature, install=True)
    if condition == 'lock':
        assert (tmp_path / '.reibosub-install.lock').exists()


def test_pip_error_is_sanitized_and_lock_is_cleaned(feature_env, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stderr='private-index-password'))
    with pytest.raises(DependencyInstallError) as error:
        dependencies.ensure_feature('core', install=True)
    assert 'private-index-password' not in str(error.value)
    assert not (tmp_path / '.reibosub-install.lock').exists()
    assert not dependencies._INSTALL_LOCK.locked()


def test_missing_engine_and_cpu_gpu_conflict_are_explicit(feature_env, monkeypatch):
    feature_env.update(VERSIONS)
    monkeypatch.setattr(dependencies, '_module_available', lambda name: name != 'paddle')
    status = dependencies.check_feature('ocr')
    assert status.python_ready and not status.ready and 'Choose a Paddle engine' in status.manual_steps[0]
    feature_env['paddlepaddle-gpu'] = '3.3.0'
    assert dependencies.check_feature('ocr-cpu').conflicts


def test_existing_downloader_without_challenge_extra_is_not_falsely_ready(feature_env, monkeypatch):
    feature_env.update(VERSIONS)
    monkeypatch.setattr(dependencies, '_module_available', lambda name: name != 'yt_dlp_ejs')
    status = dependencies.check_feature('web')
    assert not status.ready
    assert names(status.missing_requirements) == {'yt-dlp'}
    assert '[default]' in status.missing_requirements[0]


def test_unknown_paddle_engine_is_not_overwritten(feature_env):
    # The fixture has a discoverable paddle module but no registered CPU/GPU dist.
    assert 'unclassified' in dependencies.check_feature('ocr-cpu').conflicts[0]


def test_cli_dry_run_and_missing_consent_do_not_install(feature_env, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('CLI did not authorize installation'))
    main(['setup', 'ocr-cpu', '--dry-run'])
    assert 'paddlepaddle' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(['setup', 'core'])
    assert error.value.code == 2
    main(['doctor', 'asr', '--json'])
    output = capsys.readouterr().out
    # setup printed diagnostics before refusing; JSON is the last standalone doctor output.
    assert 'missing_requirements' in output and 'faster-whisper' in output


def test_cli_subtitle_commands_do_not_need_legacy_modules(tmp_path, monkeypatch, capsys):
    from reibosub.cli import main
    source = tmp_path / 'a.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n')
    out = tmp_path / 'a.vtt'
    main(['convert', str(source), str(out)])
    assert out.read_text().startswith('WEBVTT')
    main(['text', str(source)])
    assert 'Hello' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(['convert', str(source), str(out)])
