"""Offline adapter contracts; no optional runtime/model is needed for this suite."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

from reibosub import (
    ASR, OCR, Cue, Subtitle, TextRegion, FasterWhisperBackend, PaddleOCRBackend,
    MissingDependencyError, ModelUnavailableError, RecognitionError,
    OperationCancelled, ValidationError,
)
import reibosub.asr as asr
import reibosub.ocr as ocr

_real_model_directory = asr._model_directory


@pytest.fixture(autouse=True)
def fake_model_files_for_inference_tests(monkeypatch):
    # Inference tests replace the native factory; cache resolver tests below
    # explicitly exercise the real resolver with synthetic complete directories.
    monkeypatch.setattr(asr, '_model_directory', lambda model, **kwargs: model)


def region(text='Hello', score=.9):
    return TextRegion(text, score, ((0, 0), (10, 0), (10, 5), (0, 5)))


@pytest.fixture
def media(tmp_path):
    path = tmp_path / 'media.mp4'
    path.touch()
    return path


def test_import_and_construction_never_load_optional_runtimes():
    script = '''
import sys
from reibosub import ASR, OCR
ASR(); OCR()
assert not {'torch', 'numpy', 'paddle', 'paddleocr', 'faster_whisper', 'cv2'} & sys.modules.keys()
assert not any(n.startswith('video_translate') for n in sys.modules)
'''
    subprocess.run([sys.executable, '-c', script], check=True)


def test_custom_backends_without_any_model_runtime(media):
    class Audio:
        def transcribe(self, path, **kwargs):
            assert path == media and kwargs['language'] == 'ko'
            return Subtitle((Cue(1, .1, 1, '안녕'),), language='ko')
    class Image:
        def recognize(self, path):
            return (region(),)
    assert ASR(Audio()).transcribe(media, language='ko')[0].text == '안녕'
    assert OCR(Image()).read_image(media)[0].text == 'Hello'


@pytest.mark.parametrize('value', [None, (), ['bad']])
def test_invalid_asr_backend_result_is_not_accepted(media, value):
    with pytest.raises(RecognitionError):
        ASR(NS(transcribe=lambda *a, **k: value)).transcribe(media)


def test_invalid_ocr_result_and_configuration(media):
    with pytest.raises(RecognitionError):
        OCR(NS(recognize=lambda _: ('bad',))).read_image(media)
    with pytest.raises(RecognitionError):
        OCR(NS(recognize=lambda _: None)).read_image(media)
    with pytest.raises(ValidationError):
        ASR(NS(transcribe=lambda **k: None), model='tiny')
    with pytest.raises(ValidationError):
        OCR(NS(recognize=lambda _: ()), language='en')
    with pytest.raises(FileNotFoundError):
        ASR().transcribe(media.with_name('missing.wav'))


@pytest.mark.parametrize('options', [dict(device='gpu'), dict(beam_size=0), dict(beam_size=True), dict(local_files_only='yes'), dict(model=''), dict(revision='')])
def test_asr_configuration_validation(options):
    with pytest.raises(ValidationError):
        FasterWhisperBackend(**options)


def test_asr_lazy_load_cache_options_thread_reuse_and_close(monkeypatch, tmp_path):
    calls = []
    def factory(model, **kwargs):
        calls.append((model, kwargs))
        return NS()
    monkeypatch.setattr(asr, 'import_module', lambda name: NS(WhisperModel=factory))
    engine = FasterWhisperBackend('tiny', cache_dir=tmp_path, local_files_only=True, revision='commit')
    assert calls == []
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: engine.prepare(), range(8)))
    assert len(calls) == 1
    assert calls[0] == ('tiny', dict(device='cpu', compute_type='int8', download_root=str(tmp_path), local_files_only=True, revision='commit'))
    engine.close()
    engine.prepare()
    assert len(calls) == 2


def test_asr_segments_zero_timing_and_progress(monkeypatch, media):
    segments = [NS(text=' 안녕 ', start=.2, end=1), NS(text='零时长', start=1, end=1), NS(text=' ', start=1, end=2), NS(text=' 세계 ', start=2, end=3)]
    model = NS(transcribe=lambda *a, **k: (iter(segments), NS(duration=4, language='ko')))
    monkeypatch.setattr(asr, 'import_module', lambda _: NS(WhisperModel=lambda *a, **k: model))
    progress = []
    result = ASR().transcribe(media, on_progress=progress.append)
    assert result.cues == (Cue(1, .2, 1, '안녕'), Cue(2, 2, 3, '세계'))
    assert result.language == 'ko' and 'Discarded 2' in result.notices[0]
    assert progress[-1].completed == progress[-1].total == 4000


def test_asr_online_download_only_after_proven_cache_miss(monkeypatch, tmp_path):
    class CacheMiss(Exception):
        pass
    calls = []
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (tmp_path / name).touch()
    def download(model, **kwargs):
        calls.append(kwargs['local_files_only'])
        if kwargs['local_files_only']:
            raise CacheMiss()
        return str(tmp_path)
    monkeypatch.setattr(asr, 'import_module', lambda name: NS(download_model=download) if name == 'faster_whisper.utils' else NS(LocalEntryNotFoundError=CacheMiss))
    assert _real_model_directory('tiny', cache_dir=None, local_files_only=False, revision=None) == str(tmp_path)
    assert calls == [True, False]


def test_asr_cached_online_load_does_not_contact_hub(monkeypatch, tmp_path):
    calls = []
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (tmp_path / name).touch()
    def download(model, **kwargs):
        calls.append(kwargs['local_files_only'])
        return str(tmp_path)
    monkeypatch.setattr(asr, 'import_module', lambda name: NS(download_model=download))
    _real_model_directory('tiny', cache_dir=None, local_files_only=False, revision=None)
    assert calls == [True]


def test_incomplete_local_asr_model_never_fetches_fallback_tokenizer(monkeypatch, tmp_path):
    (tmp_path / 'model.bin').touch()
    (tmp_path / 'config.json').touch()
    monkeypatch.setattr(asr, 'import_module', lambda _: pytest.fail('unexpected download'))
    with pytest.raises(ModelUnavailableError, match='tokenizer.json'):
        _real_model_directory(str(tmp_path), cache_dir=None, local_files_only=True, revision=None)


def test_asr_cancellation_before_model_load(monkeypatch, media):
    monkeypatch.setattr(asr, 'import_module', lambda _: pytest.fail('loaded model'))
    with pytest.raises(OperationCancelled):
        ASR().transcribe(media, cancelled=lambda: True)


def test_asr_cancellation_during_generator(monkeypatch, media):
    stop = []
    def segments():
        yield NS(text='A', start=0, end=1)
        pytest.fail('recognition continued after cancellation')
    model = NS(transcribe=lambda *a, **k: (segments(), NS(duration=1, language='en')))
    monkeypatch.setattr(asr, 'import_module', lambda _: NS(WhisperModel=lambda *a, **k: model))
    with pytest.raises(OperationCancelled):
        ASR().transcribe(media, on_progress=lambda _: stop.append(True), cancelled=lambda: bool(stop))


def test_asr_missing_dependency_and_failed_model_are_distinct(monkeypatch):
    def missing(_):
        raise ImportError('private path')
    monkeypatch.setattr(asr, 'import_module', missing)
    with pytest.raises(MissingDependencyError, match=r'reibosub\[asr\]'):
        ASR().backend.prepare()
    def failure(*a, **k):
        raise RuntimeError('private access token')
    monkeypatch.setattr(asr, 'import_module', lambda _: NS(WhisperModel=failure))
    with pytest.raises(ModelUnavailableError) as exc:
        ASR(local_files_only=True).backend.prepare()
    assert 'private' not in str(exc.value)


@pytest.mark.parametrize('segments', [[NS(text='A', start=-1, end=1)], [NS(text='A', start=2, end=1)], [NS(text='A', start=0, end=float('nan'))]])
def test_asr_bad_timing_not_silently_fixed(monkeypatch, media, segments):
    model = NS(transcribe=lambda *a, **k: (iter(segments), NS(duration=2, language='en')))
    monkeypatch.setattr(asr, 'import_module', lambda _: NS(WhisperModel=lambda *a, **k: model))
    with pytest.raises(RecognitionError, match='timestamps'):
        ASR().transcribe(media)


def fake_paddle(monkeypatch, result=None, gpu=False):
    calls = []
    model = NS(predict=lambda _: iter([result if result is not None else {'rec_texts': ['你好'], 'rec_scores': [.9], 'rec_polys': [[(0, 0), (10, 0), (10, 5), (0, 5)]]}]), close=lambda: calls.append('close'))
    paddle = NS(device=NS(is_compiled_with_cuda=lambda: gpu, cuda=NS(device_count=lambda: 1)))
    def factory(**kwargs):
        calls.append(kwargs)
        return model
    monkeypatch.setattr(ocr, 'import_module', lambda name: paddle if name == 'paddle' else NS(PaddleOCR=factory))
    return calls


def test_paddle_lazy_reuse_model_options_and_regions(monkeypatch, media):
    calls = fake_paddle(monkeypatch)
    engine = OCR(language='ch')
    assert calls == []
    assert engine.read_image(media) == (region('你好'),)
    engine.read_image(media)
    assert len(calls) == 1
    assert calls[0]['device'] == 'cpu'
    assert calls[0]['ocr_version'] == 'PP-OCRv5'
    assert calls[0]['use_doc_orientation_classify'] is False
    assert calls[0]['enable_mkldnn'] is False
    engine.backend.close()
    assert calls[-1] == 'close'
    engine.read_image(media)
    assert len(calls) == 3


def test_paddle_offline_fail_before_import_with_missing_models(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, 'import_module', lambda _: pytest.fail('unexpected import/download'))
    with pytest.raises(ValidationError):
        OCR(local_files_only=True)
    engine = OCR(local_files_only=True, detection_model_dir=tmp_path, recognition_model_dir=tmp_path)
    with pytest.raises(ModelUnavailableError, match='inference'):
        engine.backend.prepare()


def test_paddle_offline_local_paths_and_no_global_env_changes(monkeypatch, tmp_path):
    (tmp_path / 'inference.json').touch()
    (tmp_path / 'inference.pdiparams').touch()
    calls = fake_paddle(monkeypatch)
    monkeypatch.delenv('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', raising=False)
    engine = OCR(local_files_only=True, detection_model_dir=tmp_path, recognition_model_dir=tmp_path)
    with pytest.raises(ModelUnavailableError, match='before starting Python'):
        engine.backend.prepare()
    assert not calls
    monkeypatch.setenv('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    engine.backend.prepare()
    assert calls[0]['text_detection_model_dir'] == str(tmp_path)
    assert calls[0]['text_recognition_model_dir'] == str(tmp_path)


@pytest.mark.parametrize('device', ['gpu', 'gpu:3'])
def test_gpu_request_never_silently_falls_back(monkeypatch, device):
    calls = fake_paddle(monkeypatch, gpu=device != 'gpu')
    with pytest.raises(ModelUnavailableError):
        OCR(device=device).backend.prepare()
    assert not calls


def test_paddle_malformed_arrays_are_not_zipped_silently(monkeypatch, media):
    fake_paddle(monkeypatch, {'rec_texts': ['A', 'B'], 'rec_scores': [.9], 'rec_polys': []})
    with pytest.raises(RecognitionError):
        OCR().read_image(media)


@pytest.mark.parametrize('args', [dict(text=1), dict(confidence=2), dict(polygon=((0, 0),)), dict(polygon=((0, 0), (1, 0), (1, float('nan'))))])
def test_text_region_validation(args):
    values = dict(text='A', confidence=.9, polygon=((0, 0), (1, 0), (1, 1)))
    with pytest.raises(ValidationError):
        TextRegion(**(values | args))


class Frame:
    shape = (100, 200, 3)
    def __init__(self, masks=None):
        self.masks = [] if masks is None else masks
    def __getitem__(self, key):
        return self
    def copy(self):
        return Frame(self.masks)
    def __setitem__(self, key, value):
        self.masks.append((key, value))


def fake_video(monkeypatch, frames=6, declared=None):
    samples = []
    stream = NS(average_rate=3, duration=declared or frames, time_base=1/3, start_time=0)
    source = [NS(time=i/3, to_ndarray=lambda **_: Frame(samples)) for i in range(frames)]
    capture = NS(streams=NS(video=[stream]), decode=lambda _: iter(source), close=lambda: samples.append('released'))
    av = NS(open=lambda _: capture, time_base=1000000)
    monkeypatch.setattr(ocr, 'import_module', lambda name: av)
    return samples


def test_video_merges_adjacent_exact_text_and_applies_masks(monkeypatch, media):
    samples = fake_video(monkeypatch)
    values = iter([(region('A'),), (region('A'),), (), (region('B'),), (region('B'),), (region('B'),)])
    result = OCR(NS(recognize=lambda _: next(values))).extract_subtitles(media, sample_fps=3, crop=(0, .5, 1, 1), exclude=((0, .5, .2, .8),), language='en')
    assert [(r.start, r.end, r.text) for r in result] == [(0, 2/3, 'A'), (1, 2, 'B')]
    assert result.language == 'en' and result.notices
    assert samples[-1] == 'released'
    assert samples[0][1] == 0  # black mask actually applied before recognition


def test_video_range_offsets_are_absolute(monkeypatch, media):
    samples = fake_video(monkeypatch)
    result = OCR(NS(recognize=lambda _: (region(),))).extract_subtitles(media, start=1, end=1.8)
    assert len(result) == 1
    assert (result[0].start, result[0].end) == (1, 1.8)
    assert samples[-1] == 'released'


def test_video_decode_failure_never_returns_fake_complete_subtitle(monkeypatch, media):
    samples = fake_video(monkeypatch, frames=2, declared=6)
    with pytest.raises(RecognitionError, match='declared duration'):
        OCR(NS(recognize=lambda _: (region(),))).extract_subtitles(media)
    assert samples[-1] == 'released'


def test_video_cancellation_releases_decoder(monkeypatch, media):
    samples = fake_video(monkeypatch)
    stop = []
    with pytest.raises(OperationCancelled):
        OCR(NS(recognize=lambda _: (region(),))).extract_subtitles(media, on_progress=lambda _: stop.append(1), cancelled=lambda: bool(stop))
    assert samples[-1] == 'released'


@pytest.mark.parametrize('options', [dict(sample_fps=0), dict(sample_fps=1000), dict(sample_fps=True), dict(start=2, end=1), dict(crop=(0, 1, 1, 0)), dict(exclude=((0, 0, 2, 1),)), dict(min_confidence=2)])
def test_bad_video_arguments_never_load_dependencies(monkeypatch, media, options):
    monkeypatch.setattr(ocr, 'import_module', lambda _: pytest.fail('loaded dependency'))
    with pytest.raises(ValidationError):
        OCR().extract_subtitles(media, **options)
