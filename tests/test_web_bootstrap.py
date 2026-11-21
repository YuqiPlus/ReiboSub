from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import reibosub

ROOT = Path(__file__).resolve().parents[1]


def bootstrap():
    spec = importlib.util.spec_from_file_location('bootstrap_under_test', ROOT / 'run_agent_ui.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('arguments,expected', [([], ('configured-host', 8000)), (['--host', '127.0.0.1', '--port', '0'], ('127.0.0.1', 0))])
def test_default_startup_never_installs_and_keeps_configured_defaults(monkeypatch, arguments, expected):
    calls = []
    fake = SimpleNamespace(DEFAULT_HOST='configured-host', DEFAULT_PORT=8000, serve=lambda *args: calls.append(args))
    monkeypatch.setitem(sys.modules, 'video_translate.web_agent', fake)
    monkeypatch.setattr(reibosub, 'ensure_feature', lambda *a, **kw: pytest.fail('no installation without flag'))
    monkeypatch.setattr(sys, 'argv', ['run_agent_ui.py', *arguments])
    bootstrap().main()
    assert calls == [expected]


def test_explicit_install_runs_before_serve(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'video_translate.web_agent', SimpleNamespace(DEFAULT_HOST='host', DEFAULT_PORT=8000, serve=lambda *a: calls.append('serve')))
    monkeypatch.setattr(reibosub, 'ensure_feature', lambda feature, **kwargs: calls.append((feature, kwargs)))
    monkeypatch.setattr(sys, 'argv', ['run_agent_ui.py', '--install-missing'])
    bootstrap().main()
    assert calls == [('web', {'install': True}), 'serve']


def test_missing_web_dependency_has_actionable_message_without_install(monkeypatch, capsys):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'video_translate.web_agent':
            raise ModuleNotFoundError('missing web package', name='requests')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    monkeypatch.setattr(sys, 'argv', ['run_agent_ui.py'])
    with pytest.raises(SystemExit) as error:
        bootstrap().main()
    assert error.value.code == 2
    assert '.[web]' in capsys.readouterr().err
