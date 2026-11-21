from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from reibosub import Cue, Subtitle, TranslationError, Translator, ValidationError


@pytest.fixture
def service():
    state = SimpleNamespace(calls=[], status=200, content=None, finish_reason="stop", redirect=False)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append((self.path, body, self.headers.get("Authorization")))
            self.send_response(302 if state.redirect else state.status)
            if state.redirect:
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/steal")
            self.end_headers()
            if state.status != 200 or state.redirect:
                self.wfile.write(b"private-provider-detail test-only-secret")
                return
            items = json.loads(body["messages"][1]["content"])["items"]
            content = state.content if state.content is not None else json.dumps({"translations": [{"id": item["id"], "text": f"English {item['text']}"} for item in reversed(items)]})
            self.wfile.write(json.dumps({"choices": [{"finish_reason": state.finish_reason, "message": {"content": content}}]}).encode())
        def do_GET(self):
            state.calls.append((self.path, None, self.headers.get("Authorization")))
            self.send_response(200); self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        yield state
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def client(service, **kwargs):
    return Translator(base_url=service.url, api_key="test-only-secret", model="local-test-model", **kwargs)


def test_configured_service_batches_by_id_and_preserves_source(service):
    glossary = {"數據": "data"}
    translator = client(service, glossary=glossary, extra_prompt="Keep technical terms.")
    glossary["數據"] = "mutated"
    source = Subtitle((Cue(9, 0, 2, "數據"), Cue(20, 3, 5, "Hello\nthere")), language="zh")
    output = translator.translate(source, target_language="en")
    assert [cue.text for cue in output] == ["English 數據", "English Hello\nthere"]
    path, payload, authorization = service.calls[0]
    assert path == "/v1/chat/completions"
    assert payload["model"] == "local-test-model"
    assert authorization == "Bearer test-only-secret"
    assert '"數據": "data"' in payload["messages"][0]["content"]
    assert "Keep technical terms." in payload["messages"][0]["content"]
    assert "mutated" not in payload["messages"][0]["content"]
    assert [(cue.index, cue.start, cue.end) for cue in output] == [(9, 0, 2), (20, 3, 5)]
    assert "test-only-secret" not in repr(translator)
    assert source[0].text == "數據"


@pytest.mark.parametrize("content", [
    "not JSON", '{"translations":[]}',
    '{"translations":[{"id":true,"text":"bad"}]}',
    '{"translations":[{"id":0,"text":""}]}',
    '{"translations":[{"id":3,"text":"wrong id"}]}',
    '{"translations":[{"id":0,"text":null}]}',
    '{"translations":["bad"]}',
])
def test_invalid_provider_output_is_rejected_without_content_leak(service, content):
    service.content = content
    with pytest.raises(TranslationError, match="malformed"):
        client(service).translate_batch(["hello"], source_language="auto", target_language="zh")
    assert len(service.calls) == 1  # No retries, unexpected costs, or provider switching.


def test_fenced_json_works_but_duplicate_ids_and_truncation_do_not(service):
    service.content = '```json\n{"translations":[{"id":0,"text":"你好"}]}\n```'
    assert client(service).translate_batch(["hello"], source_language="en", target_language="zh") == ["你好"]
    service.content = '{"translations":[{"id":0,"text":"one"},{"id":0,"text":"two"}]}'
    with pytest.raises(TranslationError):
        client(service).translate_batch(["a", "b"], source_language="auto", target_language="en")
    service.content, service.finish_reason = '{"translations":[{"id":0,"text":"partial"}]}', "length"
    with pytest.raises(TranslationError):
        client(service).translate_batch(["a"], source_language="auto", target_language="en")


def test_http_errors_are_sanitized_and_redirects_never_receive_credentials(service):
    service.status = 401
    with pytest.raises(TranslationError, match="HTTP 401") as error:
        client(service).translate_batch(["hello"], source_language="en", target_language="zh")
    trace = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "test-only-secret" not in trace and "private-provider-detail" not in trace
    service.redirect = True
    with pytest.raises(TranslationError, match="HTTP 302"):
        client(service).translate_batch(["hello"], source_language="en", target_language="zh")
    assert all(path != "/steal" for path, _, _ in service.calls)


@pytest.mark.parametrize("kwargs", [
    {"base_url": "file:///tmp/a"}, {"base_url": "http://user:secret@example.test"},
    {"base_url": "https://example.test?key=secret"}, {"base_url": "http://["},
    {"api_key": ""}, {"api_key": "secret\r\nInjected: x"}, {"model": ""},
    {"timeout": 0}, {"timeout": float("inf")}, {"glossary": {"name": ""}},
])
def test_constructor_requires_explicit_valid_configuration(kwargs):
    with pytest.raises(ValidationError):
        Translator(**({"base_url": "http://localhost/v1", "api_key": "test", "model": "test"} | kwargs))


def test_network_failure_is_sanitized_and_empty_batch_makes_no_request(service, monkeypatch):
    translator = client(service)
    assert translator.translate_batch([], source_language="auto", target_language="zh") == []
    assert not service.calls
    def fail(*args, **kwargs):
        raise URLError("test-only-secret")
    monkeypatch.setattr(translator._opener, "open", fail)
    with pytest.raises(TranslationError) as error:
        translator.translate_batch(["a"], source_language="auto", target_language="zh")
    assert "secret" not in str(error.value)
