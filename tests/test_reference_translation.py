from types import SimpleNamespace

import pytest

from video_translate import web_agent as app


@pytest.fixture
def configured(monkeypatch):
    calls = []
    def config(task, **kwargs):
        assert task == 'subtitle_translation'
        assert kwargs['root'] == app.ROOT
        return SimpleNamespace(model='doubao-seed-2-1-lite', api_key='test-only-key', base_url='https://example.invalid/v1')
    def request(url, key, payload, **kwargs):
        calls.append((url, key, payload, kwargs))
        return ' Hello!\nGood morning. '
    monkeypatch.setattr(app, 'load_llm_task_config', config)
    monkeypatch.setattr(app, '_request_translation', request)
    return calls


def test_reference_translation_uses_shared_translation_model_and_explicit_languages(configured):
    result = app.translate_reference_text({'text': '안녕!\n좋은 아침.', 'source_language': 'ko', 'target_language': 'en'})
    assert result['translation'] == 'Hello!\nGood morning.'
    assert result['source_language'] == 'ko' and result['target_language'] == 'en'
    url, key, payload, options = configured[0]
    assert url == 'https://example.invalid/v1/chat/completions'
    assert '韩语' in payload['messages'][0]['content']
    assert '英语' in payload['messages'][0]['content']
    assert payload['messages'][1]['content'] == '안녕!\n좋은 아침.'
    assert payload['thinking']['type'] == 'disabled'
    assert options == {'max_attempts': 1, 'timeout_seconds': 45}
    assert 'test-only-key' not in str(result)


def test_auto_detect_source_and_japanese_target(configured):
    app.translate_reference_text({'text': '你好', 'target_language': 'ja'})
    prompt = configured[0][2]['messages'][0]['content']
    assert '自动识别' in prompt and '日语' in prompt


def test_same_language_returns_original_without_model_request(configured):
    result = app.translate_reference_text({'text': ' Hello! ', 'source_language': 'en', 'target_language': 'en'})
    assert result['translation'] == ' Hello! '
    assert configured == []


@pytest.mark.parametrize('payload', [
    {}, {'text': ' '}, {'text': 123}, {'text': 'a' * 4001},
    {'text': 'hello', 'source_language': 'invalid'}, {'text': 'hello', 'target_language': 'invalid'},
])
def test_invalid_request_does_not_call_model(configured, payload):
    with pytest.raises(ValueError):
        app.translate_reference_text(payload)
    assert configured == []


def test_unconfigured_service_has_actionable_message(monkeypatch):
    monkeypatch.setattr(app, 'load_llm_task_config', lambda *a, **k: SimpleNamespace(model=None, api_key=None))
    with pytest.raises(ValueError, match='设置'):
        app.translate_reference_text({'text': 'hello'})


def test_provider_failure_does_not_expose_upstream_details(configured, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('upstream error: test-only-key https://private.invalid')
    monkeypatch.setattr(app, '_request_translation', fail)
    with pytest.raises(RuntimeError) as error:
        app.translate_reference_text({'text': 'hello'})
    assert '暂不可用' in str(error.value)
    assert 'test-only-key' not in str(error.value)
    assert 'private.invalid' not in str(error.value)


def test_empty_response_is_not_success(configured, monkeypatch):
    monkeypatch.setattr(app, '_request_translation', lambda *a, **k: '  ')
    with pytest.raises(RuntimeError, match='空结果'):
        app.translate_reference_text({'text': 'hello'})
