"""Cache policy and per-instance routing without importing an inference runtime."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from reibosub import ASR, OCR, ModelUnavailableError, MissingDependencyError, ValidationError
import reibosub.ocr as ocr


def complete(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('inference.json', 'inference.pdiparams'):
        (directory / name).touch()
    return directory


def fake_runtime(monkeypatch):
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return NS(close=lambda: None)
    factory._get_ocr_model_names = lambda _, lang, version: ('PP-OCRv5_server_det', f'{lang}_PP-OCRv5_mobile_rec')
    paddle = NS(device=NS(is_compiled_with_cuda=lambda: True, cuda=NS(device_count=lambda: 2)))
    monkeypatch.setattr(ocr, 'import_module', lambda name: paddle if name == 'paddle' else NS(PaddleOCR=factory))
    return calls, factory


def test_construction_has_no_cache_or_network_side_effects(monkeypatch, tmp_path):
    cache = tmp_path / 'not-created'
    monkeypatch.setattr(ocr, 'import_module', lambda _: pytest.fail('unexpected import'))
    engine = OCR(cache_dir=cache)
    assert engine.backend._cache_dir == cache
    assert not cache.exists()


@pytest.mark.parametrize('value', ['', ' ', True, 123, []])
def test_invalid_cache_paths(value):
    with pytest.raises(ValidationError, match='cache_dir'):
        OCR(cache_dir=value)
    with pytest.raises(ValidationError, match='cache_dir'):
        ASR(cache_dir=value)


def test_relative_cache_is_anchored_at_construction(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = OCR(cache_dir='./weights')
    speech = ASR(cache_dir='./weights')
    monkeypatch.chdir(tmp_path.parent)
    assert engine.backend._cache_dir == tmp_path / 'weights'
    assert speech.backend._options['download_root'] == str(tmp_path / 'weights')


def test_tilde_cache_expands_without_creation(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert OCR(cache_dir='~/weights').backend._cache_dir == tmp_path / 'weights'
    assert not (tmp_path / 'weights').exists()


def test_default_cache_defers_to_hub_without_a_repository_path(monkeypatch, tmp_path):
    directory = complete(tmp_path / 'snapshot')
    calls = []
    def snapshot(**kwargs):
        calls.append(kwargs)
        return str(directory)
    monkeypatch.setattr(ocr, 'import_module', lambda name: NS(snapshot_download=snapshot))
    assert ocr._cached_model('model', None, local_files_only=False) == directory
    assert len(calls) == 1
    assert calls[0]['cache_dir'] is None and calls[0]['local_files_only'] is True
    assert calls[0]['repo_id'] == 'PaddlePaddle/model'
    assert '*.py' not in calls[0]['allow_patterns']


def test_first_download_then_disk_reuse_without_repeated_online_requests(monkeypatch, tmp_path):
    class CacheMiss(Exception):
        pass
    directory, calls = tmp_path / 'snapshot', []
    def snapshot(**kwargs):
        calls.append(kwargs)
        if not directory.exists():
            if kwargs['local_files_only']:
                raise CacheMiss('private token must not leak')
            complete(directory)
        return str(directory)
    monkeypatch.setattr(ocr, 'import_module', lambda name: NS(snapshot_download=snapshot) if name == 'huggingface_hub' else NS(LocalEntryNotFoundError=CacheMiss))
    assert ocr._cached_model('model', tmp_path, local_files_only=False) == directory
    assert ocr._cached_model('model', tmp_path, local_files_only=False) == directory
    assert [row['local_files_only'] for row in calls] == [True, False, True]
    assert all(row['cache_dir'] == str(tmp_path) for row in calls)


def test_offline_cache_miss_never_falls_back_online(monkeypatch, tmp_path):
    calls = []
    def snapshot(**kwargs):
        calls.append(kwargs['local_files_only'])
        raise FileNotFoundError('private credentials')
    monkeypatch.setattr(ocr, 'import_module', lambda _: NS(snapshot_download=snapshot))
    with pytest.raises(ModelUnavailableError) as exc:
        ocr._cached_model('model', tmp_path, local_files_only=True)
    assert calls == [True]
    assert 'private' not in str(exc.value)


def test_incomplete_cached_snapshot_is_resumed_only_when_online(monkeypatch, tmp_path):
    directory = tmp_path / 'snapshot'
    directory.mkdir()
    calls = []
    def snapshot(**kwargs):
        calls.append(kwargs['local_files_only'])
        if not kwargs['local_files_only']:
            complete(directory)
        return str(directory)
    monkeypatch.setattr(ocr, 'import_module', lambda _: NS(snapshot_download=snapshot))
    with pytest.raises(ModelUnavailableError):
        ocr._cached_model('model', tmp_path, local_files_only=True)
    assert calls == [True]
    assert ocr._cached_model('model', tmp_path, local_files_only=False) == directory
    assert calls == [True, True, False]


def test_cache_permission_failure_does_not_try_another_location(monkeypatch, tmp_path):
    calls = []
    def snapshot(**kwargs):
        calls.append(kwargs)
        raise PermissionError('private mount')
    monkeypatch.setattr(ocr, 'import_module', lambda name: NS(snapshot_download=snapshot) if name == 'huggingface_hub' else NS())
    with pytest.raises(ModelUnavailableError):
        ocr._cached_model('model', tmp_path, local_files_only=False)
    assert len(calls) == 1 and calls[0]['cache_dir'] == str(tmp_path)


def test_optional_hub_missing_has_an_installation_hint(monkeypatch, tmp_path):
    def missing(_):
        raise ImportError()
    monkeypatch.setattr(ocr, 'import_module', missing)
    with pytest.raises(MissingDependencyError, match='huggingface-hub'):
        ocr._cached_model('model', tmp_path, local_files_only=False)


def test_per_instance_caches_and_device_are_isolated(monkeypatch, tmp_path):
    calls, _ = fake_runtime(monkeypatch)
    locations = []
    def cached(name, cache, **kwargs):
        locations.append((name, cache, kwargs))
        return cache / name
    monkeypatch.setattr(ocr, '_cached_model', cached)
    before = dict(ocr.os.environ)
    cpu = OCR(cache_dir=tmp_path / 'cpu', device='cpu')
    cuda = OCR(cache_dir=tmp_path / 'gpu', device='gpu:1')
    cpu.backend.prepare()
    cuda.backend.prepare()
    assert calls[0]['text_detection_model_dir'] == str(tmp_path / 'cpu/PP-OCRv5_server_det')
    assert calls[1]['text_detection_model_dir'] == str(tmp_path / 'gpu/PP-OCRv5_server_det')
    assert calls[0]['device'] == 'cpu' and calls[1]['device'] == 'gpu:1'
    cpu.backend.prepare()
    assert len(locations) == 4 and len(calls) == 2  # already-loaded instance reuses weights
    assert dict(ocr.os.environ) == before


def test_explicit_model_directories_override_cache_and_never_download(monkeypatch, tmp_path):
    calls, _ = fake_runtime(monkeypatch)
    detection = complete(tmp_path / 'local-det')
    recognition = complete(tmp_path / 'local-rec')
    monkeypatch.setattr(ocr, '_cached_model', lambda *a, **k: pytest.fail('unexpected cache download'))
    engine = OCR(cache_dir=tmp_path / 'unused', detection_model_dir=detection, recognition_model_dir=recognition)
    engine.backend.prepare()
    assert calls[0]['text_detection_model_dir'] == str(detection)
    assert calls[0]['text_recognition_model_dir'] == str(recognition)
    assert not (tmp_path / 'unused').exists()


def test_partial_override_keeps_correct_recognition_language(monkeypatch, tmp_path):
    calls, _ = fake_runtime(monkeypatch)
    downloads = []
    def cached(name, cache, **kwargs):
        downloads.append(name)
        return tmp_path / name
    monkeypatch.setattr(ocr, '_cached_model', cached)
    OCR(language='korean', detection_model_name='custom-det', detection_model_dir=complete(tmp_path / 'det')).backend.prepare()
    assert downloads == ['korean_PP-OCRv5_mobile_rec']
    assert calls[0]['text_detection_model_name'] == 'custom-det'
    assert calls[0]['text_recognition_model_name'] == 'korean_PP-OCRv5_mobile_rec'


def test_offline_can_use_just_cache_dir_without_explicit_model_paths(monkeypatch, tmp_path):
    calls, _ = fake_runtime(monkeypatch)
    policies = []
    def cached(name, cache, **kwargs):
        policies.append(kwargs['local_files_only'])
        return cache / name
    monkeypatch.setattr(ocr, '_cached_model', cached)
    monkeypatch.setenv('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    OCR(cache_dir=tmp_path, local_files_only=True).backend.prepare()
    assert policies == [True, True] and len(calls) == 1


def test_selector_compatibility_failure_is_clear_and_does_not_download(monkeypatch):
    calls, factory = fake_runtime(monkeypatch)
    del factory._get_ocr_model_names
    monkeypatch.setattr(ocr, '_cached_model', lambda *a, **k: pytest.fail('unexpected download'))
    with pytest.raises(ModelUnavailableError, match='explicit detection_model_name'):
        OCR().backend.prepare()
    assert not calls


@pytest.mark.parametrize('name', ['../model', '/model', 'model/../../escape', 'https://somewhere/model'])
def test_cache_download_only_accepts_official_model_names(monkeypatch, tmp_path, name):
    monkeypatch.setattr(ocr, 'import_module', lambda _: pytest.fail('unexpected import'))
    with pytest.raises(ModelUnavailableError, match='Invalid official OCR model name'):
        ocr._cached_model(name, tmp_path, local_files_only=False)
