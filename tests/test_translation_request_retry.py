from __future__ import annotations

import requests

from video_translate.translate import volcengine


class _FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def test_request_translation_retries_timeout(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return _FakeResponse()

    monkeypatch.setenv("ARK_REQUEST_TIMEOUT", "5")
    monkeypatch.setenv("ARK_REQUEST_RETRIES", "2")
    monkeypatch.setattr(volcengine.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(volcengine.requests, "post", fake_post)

    assert volcengine._request_translation("https://example.test", "key", {"model": "m"}) == "ok"
    assert len(calls) == 2
    assert calls[0]["timeout"] == 5.0
