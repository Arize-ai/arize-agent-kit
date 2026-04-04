"""Shared pytest fixtures for arize-agent-kit tests."""
import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import pytest
import yaml

# Ensure repo root is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_harness_dir(tmp_path, monkeypatch):
    """Create the full ~/.arize/harness directory tree in a temp location.

    Monkeypatches core.constants so all code sees the temp paths.
    Returns the base directory Path.
    """
    base = tmp_path / ".arize" / "harness"
    for subdir in ["bin", "run", "logs",
                    "state/claude-code", "state/codex", "state/cursor"]:
        (base / subdir).mkdir(parents=True)

    import core.constants as c
    monkeypatch.setattr(c, "BASE_DIR", base)
    monkeypatch.setattr(c, "CONFIG_FILE", base / "config.yaml")
    monkeypatch.setattr(c, "PID_DIR", base / "run")
    monkeypatch.setattr(c, "PID_FILE", base / "run" / "collector.pid")
    monkeypatch.setattr(c, "LOG_DIR", base / "logs")
    monkeypatch.setattr(c, "COLLECTOR_LOG_FILE", base / "logs" / "collector.log")
    monkeypatch.setattr(c, "BIN_DIR", base / "bin")
    monkeypatch.setattr(c, "COLLECTOR_BIN", base / "bin" / "arize-collector")
    monkeypatch.setattr(c, "VENV_DIR", base / "venv")
    monkeypatch.setattr(c, "STATE_BASE_DIR", base / "state")
    return base


@pytest.fixture
def sample_config(tmp_harness_dir):
    """Write a known-good config.yaml into the temp harness dir.

    Returns the config dict.
    """
    config = {
        "collector": {"host": "127.0.0.1", "port": 4318},
        "backend": {
            "target": "phoenix",
            "phoenix": {"endpoint": "http://localhost:6006", "api_key": ""},
            "arize": {"endpoint": "otlp.arize.com:443", "api_key": "", "space_id": ""},
        },
        "harnesses": {
            "claude-code": {"project_name": "claude-code"},
            "codex": {"project_name": "codex"},
            "cursor": {"project_name": "cursor"},
        },
    }
    config_path = tmp_harness_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    return config


class _CollectorHandler(BaseHTTPRequestHandler):
    """Minimal mock HTTP handler that records POSTed spans."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server._received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence request logging in test output


@pytest.fixture
def mock_collector():
    """Start a real HTTP server on a random port.

    Accepts POST /v1/spans (records body) and GET /health (returns 200).
    Yields dict: {"url": "http://127.0.0.1:{port}", "received": [...], "port": int}
    Server is torn down after the test.
    """
    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    server._received = []
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{port}", "received": server._received, "port": port}
    server.shutdown()


@pytest.fixture
def capture_log(tmp_path):
    """Provide a temp log file and a reader function.

    Returns (log_file_path, read_log_fn). read_log_fn() returns list of lines.
    """
    log_file = tmp_path / "test.log"
    def read_log():
        return log_file.read_text().splitlines() if log_file.exists() else []
    return log_file, read_log


def load_fixture(name: str):
    """Load a JSON fixture file from tests/fixtures/ by filename.

    Returns parsed dict/list.
    """
    fixture_path = Path(__file__).parent / "fixtures" / name
    return json.loads(fixture_path.read_text())
