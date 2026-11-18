from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from video_translate import web_agent


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_agent.AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    server_address,
    method: str,
    target: str,
    payload: dict | None = None,
    *,
    content_type: str = "application/json",
):
    connection = HTTPConnection(*server_address, timeout=5)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": content_type} if body is not None else {}
    try:
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data
    finally:
        connection.close()


def test_get_settings_returns_browser_safe_payload(monkeypatch, http_server):
    expected = {
        "settings": {"version": 1, "defaults": {"source_language": "korean"}, "tasks": {}},
        "providers": [{"id": "volcano", "key_configured": True}],
    }
    seen = {}

    def fake_get(*, root):
        seen["root"] = root
        return expected

    monkeypatch.setattr(web_agent, "get_app_settings_payload", fake_get)

    status, payload = _request(http_server, "GET", "/api/settings")

    assert status == 200
    assert {key: payload[key] for key in expected} == expected
    assert payload["capabilities"] == {"provider_management_allowed": True}
    assert seen["root"] == web_agent.ROOT


def test_create_provider_returns_public_payload_for_local_or_remote_page(monkeypatch, http_server):
    seen = {}

    def fake_create(payload, *, root):
        seen.update(payload=payload, root=root)
        return {
            "provider": {"id": payload["id"], "key_configured": True},
            "providers": [{"id": payload["id"], "key_configured": True}],
            "settings": {"version": 1},
        }

    monkeypatch.setattr(web_agent, "create_provider_profile", fake_create)
    status, payload = _request(
        http_server,
        "POST",
        "/api/settings/providers",
        {
            "id": "custom",
            "base_url": "https://provider.example/v1",
            "api_key": "write-only-key",
        },
    )

    assert status == 201
    assert payload["provider"]["id"] == "custom"
    assert "api_key" not in payload["provider"]
    assert payload["capabilities"]["provider_management_allowed"] is True
    assert seen["root"] == web_agent.ROOT

    monkeypatch.setattr(web_agent, "_is_loopback_address", lambda _value: False)
    remote_status, remote_payload = _request(
        http_server,
        "POST",
        "/api/settings/providers",
        {"id": "remote-custom", "base_url": "https://remote.example/v1"},
    )
    assert remote_status == 201
    assert remote_payload["provider"]["id"] == "remote-custom"


def test_delete_provider_requires_replacement_and_supports_remote_page(monkeypatch, http_server):
    seen = {}

    def fake_delete(provider_id, replacement_provider_id, *, root):
        seen.update(
            provider_id=provider_id,
            replacement_provider_id=replacement_provider_id,
            root=root,
        )
        return {
            "deleted_provider_id": provider_id,
            "replacement_provider_id": replacement_provider_id,
            "providers": [{"id": replacement_provider_id}],
            "settings": {"version": 1},
        }

    monkeypatch.setattr(web_agent, "delete_provider_profile", fake_delete)
    status, payload = _request(
        http_server,
        "DELETE",
        "/api/settings/providers/old-provider",
        {"replacement_provider_id": "new-provider"},
    )

    assert status == 200
    assert payload["deleted_provider_id"] == "old-provider"
    assert seen == {
        "provider_id": "old-provider",
        "replacement_provider_id": "new-provider",
        "root": web_agent.ROOT,
    }

    missing_status, missing_payload = _request(
        http_server,
        "DELETE",
        "/api/settings/providers/old-provider",
        {},
    )
    assert missing_status == 400
    assert "replacement_provider_id" in missing_payload["error"]

    monkeypatch.setattr(web_agent, "_is_loopback_address", lambda _value: False)
    remote_status, remote_payload = _request(
        http_server,
        "DELETE",
        "/api/settings/providers/remote-old",
        {"replacement_provider_id": "new-provider"},
    )
    assert remote_status == 200
    assert remote_payload["deleted_provider_id"] == "remote-old"


def test_patch_provider_updates_only_public_metadata(monkeypatch, http_server):
    submitted = {
        "label": "Updated Provider",
        "default_model": "model-new",
        "models": ["model-new", "model-extra"],
    }
    seen = {}

    def fake_update(provider_id, payload, *, root):
        seen.update(provider_id=provider_id, payload=payload, root=root)
        return {
            "provider": {
                "id": provider_id,
                "label": payload["label"],
                "default_model": payload["default_model"],
                "models": payload["models"],
            },
            "providers": [],
            "settings": {"version": 1},
        }

    monkeypatch.setattr(web_agent, "update_provider_profile", fake_update)
    status, payload = _request(
        http_server,
        "PATCH",
        "/api/settings/providers/existing",
        submitted,
    )

    assert status == 200
    assert payload["provider"]["label"] == "Updated Provider"
    assert payload["capabilities"]["provider_management_allowed"] is True
    assert seen == {
        "provider_id": "existing",
        "payload": submitted,
        "root": web_agent.ROOT,
    }


def test_get_provider_models_uses_trusted_profile_id_and_refresh(monkeypatch, http_server):
    seen = {}

    def fake_fetch(provider_id, *, root, refresh):
        seen.update(provider_id=provider_id, root=root, refresh=refresh)
        return {"provider_id": provider_id, "models": ["model-a"], "warning": ""}

    monkeypatch.setattr(web_agent, "fetch_provider_models", fake_fetch)

    status, payload = _request(
        http_server,
        "GET",
        "/api/settings/providers/demo-provider/models?refresh=1",
    )

    assert status == 200
    assert payload["models"] == ["model-a"]
    assert seen == {
        "provider_id": "demo-provider",
        "root": web_agent.ROOT,
        "refresh": True,
    }


def test_get_provider_models_returns_400_for_unknown_profile(monkeypatch, http_server):
    def fake_fetch(provider_id, *, root, refresh):
        raise ValueError(f"未知 provider: {provider_id}")

    monkeypatch.setattr(web_agent, "fetch_provider_models", fake_fetch)

    status, payload = _request(http_server, "GET", "/api/settings/providers/missing/models")

    assert status == 400
    assert payload == {"error": "未知 provider: missing"}


def test_post_settings_persists_public_settings(monkeypatch, http_server):
    submitted = {
        "version": 1,
        "defaults": {
            "source_language": "japanese",
            "ocr_language": "auto",
            "target_language": "zh",
            "provider_profile": "volcano",
        },
        "tasks": {"subtitle_translation": {"model": "doubao-seed-2-0-lite"}},
    }
    seen = {}

    def fake_save(payload, *, root):
        seen.update(payload=payload, root=root)
        return {"settings": payload, "providers": []}

    monkeypatch.setattr(web_agent, "save_app_settings", fake_save)

    status, payload = _request(http_server, "POST", "/api/settings", submitted)

    assert status == 200
    assert payload["settings"] == submitted
    assert seen == {"payload": submitted, "root": web_agent.ROOT}


def test_get_provider_connection_returns_only_public_state(monkeypatch, http_server):
    expected = {
        "provider_id": "volcano",
        "key_configured": True,
        "local_key_configured": True,
        "key_source": "local",
        "base_url": "https://provider.example/v1",
    }

    monkeypatch.setattr(
        web_agent,
        "get_provider_connection_settings",
        lambda provider_id, *, root: expected,
    )

    status, payload = _request(
        http_server,
        "GET",
        "/api/settings/providers/volcano/connection",
    )

    assert status == 200
    assert {key: payload[key] for key in expected} == expected
    assert payload["key_write_allowed"] is True
    assert payload["endpoint_origin_change_allowed"] is True
    assert "api_key" not in payload


def test_post_provider_connection_updates_local_override(monkeypatch, http_server):
    submitted = {
        "api_key": "new-key",
        "base_url": "https://provider.example/v1",
    }
    seen = {}

    def fake_update(provider_id, payload, *, root):
        seen.update(provider_id=provider_id, payload=payload, root=root)
        return {
            "provider_id": provider_id,
            "key_configured": True,
            "local_key_configured": True,
            "key_source": "local",
            "base_url": payload["base_url"],
        }

    # This HTTP contract test must also work on a fresh clone with no local
    # provider registry or credentials configured.
    monkeypatch.setattr(
        web_agent,
        "get_provider_connection_settings",
        lambda provider_id, *, root: {"provider_id": provider_id, "base_url": "https://provider.example/v1"},
    )
    monkeypatch.setattr(web_agent, "update_provider_connection_settings", fake_update)

    status, payload = _request(
        http_server,
        "POST",
        "/api/settings/providers/volcano/connection",
        submitted,
    )

    assert status == 200
    assert payload["key_source"] == "local"
    assert "api_key" not in payload
    assert payload["key_write_allowed"] is True
    assert seen == {
        "provider_id": "volcano",
        "payload": submitted,
        "root": web_agent.ROOT,
    }


def test_remote_provider_connection_can_read_public_state_and_write_only_key(
    monkeypatch,
    http_server,
):
    monkeypatch.setattr(web_agent, "_is_loopback_address", lambda _value: False)
    current = {
        "provider_id": "volcano",
        "key_configured": True,
        "base_url": "https://provider.example/v1",
    }
    seen = {}
    monkeypatch.setattr(
        web_agent,
        "get_provider_connection_settings",
        lambda provider_id, *, root: dict(current),
    )

    def fake_update(provider_id, payload, *, root):
        seen.update(provider_id=provider_id, payload=payload)
        return dict(current, local_key_configured=True, key_source="local")

    monkeypatch.setattr(web_agent, "update_provider_connection_settings", fake_update)

    get_status, get_payload = _request(
        http_server,
        "GET",
        "/api/settings/providers/volcano/connection",
    )
    post_status, post_payload = _request(
        http_server,
        "POST",
        "/api/settings/providers/volcano/connection",
        {"api_key": "write-only-value"},
    )

    assert get_status == 200
    assert get_payload["endpoint_origin_change_allowed"] is False
    assert post_status == 200
    assert post_payload["local_key_configured"] is True
    assert "api_key" not in post_payload
    assert seen["payload"] == {"api_key": "write-only-value"}


def test_remote_provider_connection_rejects_cross_origin_endpoint_change(
    monkeypatch,
    http_server,
):
    monkeypatch.setattr(web_agent, "_is_loopback_address", lambda _value: False)
    monkeypatch.setattr(
        web_agent,
        "get_provider_connection_settings",
        lambda provider_id, *, root: {
            "provider_id": provider_id,
            "key_configured": True,
            "base_url": "https://trusted.example/v1",
        },
    )
    monkeypatch.setattr(
        web_agent,
        "update_provider_connection_settings",
        lambda *_args, **_kwargs: pytest.fail("cross-origin updates must not reach the updater"),
    )

    status, payload = _request(
        http_server,
        "POST",
        "/api/settings/providers/volcano/connection",
        {
            "api_key": "replacement-key",
            "base_url": "https://attacker.example/v1",
        },
    )

    assert status == 403
    assert "跨服务地址" in payload["error"]


def test_provider_connection_requires_json_and_limits_body_size(monkeypatch, http_server):
    monkeypatch.setattr(
        web_agent,
        "update_provider_connection_settings",
        lambda *_args, **_kwargs: pytest.fail("invalid requests must not reach the updater"),
    )

    wrong_type_status, wrong_type_payload = _request(
        http_server,
        "POST",
        "/api/settings/providers/volcano/connection",
        {"api_key": "x"},
        content_type="text/plain",
    )
    large_status, large_payload = _request(
        http_server,
        "POST",
        "/api/settings/providers/volcano/connection",
        {"api_key": "x" * (web_agent._SECRET_SETTINGS_MAX_BODY_BYTES + 1)},
    )

    assert wrong_type_status == 400
    assert "application/json" in wrong_type_payload["error"]
    assert large_status == 400
    assert large_payload == {"error": "请求体过大"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("::1%lo", True),
        ("10.0.0.2", False),
        ("not-an-ip", False),
    ],
)
def test_loopback_address_detection(value, expected):
    assert web_agent._is_loopback_address(value) is expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"api_key": "new"}, True),
        ({"import_current": True}, True),
        ({"base_url": "https://provider.example/v2"}, True),
        ({"models_url": "https://provider.example/models"}, True),
        ({"base_url": "https://other.example/v1", "api_key": "new"}, False),
        ({"models_url": "https://other.example/models"}, False),
        ({"clear_base_url": True}, False),
    ],
)
def test_remote_provider_connection_update_policy(payload, expected):
    current = {"base_url": "https://provider.example/v1"}
    assert web_agent._remote_provider_connection_update_allowed(payload, current) is expected
