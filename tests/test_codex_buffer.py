"""Tests for the /health endpoint identity fields in codex_tracing.codex_buffer."""

import json
import os
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import codex_tracing.codex_buffer as buffer_mod
from codex_tracing.codex_buffer import CodexBufferHandler


@pytest.fixture()
def health_server():
    """Start a buffer HTTP server on an ephemeral port and yield its base URL."""
    # Set _start_time so the handler has a meaningful value
    old_start = buffer_mod._start_time
    buffer_mod._start_time = time.time()

    server = ThreadingHTTPServer(("127.0.0.1", 0), CodexBufferHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        buffer_mod._start_time = old_start


def _get_health(base_url: str) -> dict:
    """GET /health and return parsed JSON."""
    req = urllib.request.Request(f"{base_url}/health")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_health_returns_identity_fields(health_server):
    payload = _get_health(health_server)
    for key in ("status", "pid", "build_path", "started_at"):
        assert key in payload, f"missing key {key!r} in /health response"
    assert payload["status"] == "ok"


def test_health_pid_matches_process(health_server):
    payload = _get_health(health_server)
    assert payload["pid"] == os.getpid()


def test_health_build_path_is_absolute_and_exists(health_server):
    payload = _get_health(health_server)
    build_path = payload["build_path"]
    assert os.path.isabs(build_path)
    assert build_path.endswith("codex_buffer.py")
    assert os.path.isfile(build_path)


def test_health_started_at_is_float(health_server):
    payload = _get_health(health_server)
    assert isinstance(payload["started_at"], (int, float))
    # Should be within a few seconds of now
    assert abs(time.time() - payload["started_at"]) < 10
