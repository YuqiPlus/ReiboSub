from __future__ import annotations

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlencode

import pytest

from video_translate import web_agent


@pytest.mark.parametrize(
    ("header", "file_size", "expected"),
    [
        ("bytes=2-5", 10, (2, 5)),
        ("bytes=7-", 10, (7, 9)),
        ("bytes=-3", 10, (7, 9)),
        ("bytes=0-999", 10, (0, 9)),
        ("bytes=-999", 10, (0, 9)),
        ("BYTES=1-2", 10, (1, 2)),
    ],
)
def test_parse_single_byte_range(header, file_size, expected):
    assert web_agent._parse_single_byte_range(header, file_size) == expected


@pytest.mark.parametrize(
    ("header", "file_size"),
    [
        ("", 10),
        ("items=0-1", 10),
        ("bytes=-", 10),
        ("bytes=-0", 10),
        ("bytes=5-4", 10),
        ("bytes=10-", 10),
        ("bytes=0-1,4-5", 10),
        ("bytes=0-0", 0),
    ],
)
def test_parse_single_byte_range_rejects_invalid_or_unsatisfiable_ranges(header, file_size):
    with pytest.raises(ValueError):
        web_agent._parse_single_byte_range(header, file_size)


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


def request(server_address, target, *, range_header=None):
    connection = HTTPConnection(*server_address, timeout=5)
    headers = {"Range": range_header} if range_header is not None else {}
    try:
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, body
    finally:
        connection.close()


def file_target(path: Path) -> str:
    return f"/api/file?{urlencode({'path': str(path)})}"


def test_api_file_streams_full_response_without_read_bytes(monkeypatch, tmp_path, http_server):
    content = b"0123456789"
    path = tmp_path / "sample.mp4"
    path.write_bytes(content)
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(web_agent, "_FILE_STREAM_CHUNK_SIZE", 3)

    def fail_read_bytes(_path):
        raise AssertionError("/api/file must not use Path.read_bytes()")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    status, headers, body = request(http_server, file_target(path))

    assert status == 200
    assert body == content
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-length"] == str(len(content))
    assert "content-range" not in headers


@pytest.mark.parametrize(
    ("range_header", "expected_body", "expected_content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=7-", b"789", "bytes 7-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
    ],
)
def test_api_file_returns_single_partial_range(
    monkeypatch,
    tmp_path,
    http_server,
    range_header,
    expected_body,
    expected_content_range,
):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"0123456789")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)

    status, headers, body = request(http_server, file_target(path), range_header=range_header)

    assert status == 206
    assert body == expected_body
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-range"] == expected_content_range
    assert headers["content-length"] == str(len(expected_body))


@pytest.mark.parametrize("range_header", ["bytes=99-", "bytes=bad", "bytes=0-1,4-5"])
def test_api_file_returns_416_for_invalid_or_unsatisfiable_range(
    monkeypatch,
    tmp_path,
    http_server,
    range_header,
):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"0123456789")
    monkeypatch.setattr(web_agent, "DOWNLOAD_DIR", tmp_path)

    status, headers, body = request(http_server, file_target(path), range_header=range_header)

    assert status == 416
    assert body == b""
    assert headers["accept-ranges"] == "bytes"
    assert headers["content-range"] == "bytes */10"
    assert headers["content-length"] == "0"


def test_frontend_asset_ignores_range_and_keeps_full_200_response(monkeypatch, tmp_path, http_server):
    dist = tmp_path / "dist"
    asset = dist / "assets" / "app.js"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"frontend-asset")
    monkeypatch.setattr(web_agent, "FRONTEND_DIST", dist)

    status, headers, body = request(http_server, "/assets/app.js", range_header="bytes=0-2")

    assert status == 200
    assert body == b"frontend-asset"
    assert headers["content-length"] == str(len(body))
    assert "accept-ranges" not in headers
    assert "content-range" not in headers
