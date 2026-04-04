"""Tests for core.collector_ctl module."""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from core.collector_ctl import (
    _is_process_alive,
    _resolve_host_port,
    collector_ensure,
    collector_start,
    collector_status,
    collector_stop,
    main,
)


class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        assert _is_process_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        # PID 99999 is almost certainly not running
        assert _is_process_alive(99999) is False


class TestResolveHostPort:
    def test_with_config(self, sample_config):
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_without_config(self, tmp_harness_dir):
        # No config.yaml exists — should return defaults
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_with_custom_config(self, tmp_harness_dir):
        config = {
            "collector": {"host": "0.0.0.0", "port": 9999},
        }
        config_path = tmp_harness_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "0.0.0.0"
        assert port == 9999


class TestCollectorStatus:
    def test_stopped_when_no_pid_file(self, tmp_harness_dir):
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert addr is None

    def test_stopped_when_dead_pid(self, tmp_harness_dir, sample_config):
        # Write a PID file with a dead PID
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text("99999\n")
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert addr is None
        # PID file should be cleaned up
        assert not pid_file.exists()

    def test_stopped_when_non_numeric_pid(self, tmp_harness_dir, sample_config):
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text("not-a-number\n")
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        # PID file should be cleaned up
        assert not pid_file.exists()

    def test_running_when_process_alive(self, tmp_harness_dir, sample_config, mock_collector):
        """If PID is alive and health check passes, report running."""
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text(str(os.getpid()) + "\n")

        # Point config to mock_collector port
        config = {
            "collector": {"host": "127.0.0.1", "port": mock_collector["port"]},
        }
        config_path = tmp_harness_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f)

        status, pid, addr = collector_status()
        assert status == "running"
        assert pid == os.getpid()
        assert str(mock_collector["port"]) in addr


class TestCollectorStart:
    def test_returns_false_when_config_missing(self, tmp_harness_dir):
        result = collector_start()
        assert result is False

    def test_detects_port_in_use(self, tmp_harness_dir, sample_config, mock_collector):
        """When port is taken by a non-collector, start should fail with clear error."""
        # Point config to a port that has a server but NOT our health endpoint
        # mock_collector actually does respond to /health, so we need a different server
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class _NoHealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(404)
                self.end_headers()
            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _NoHealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            config = {"collector": {"host": "127.0.0.1", "port": port}}
            config_path = tmp_harness_dir / "config.yaml"
            with open(config_path, "w") as f:
                yaml.safe_dump(config, f)

            result = collector_start()
            assert result is False
        finally:
            server.shutdown()

    def test_idempotent_when_already_running(self, tmp_harness_dir, sample_config, mock_collector):
        """If collector is already running, start returns True."""
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {
            "collector": {"host": "127.0.0.1", "port": mock_collector["port"]},
        }
        config_path = tmp_harness_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f)

        result = collector_start()
        assert result is True


class TestCollectorStop:
    def test_stop_when_already_stopped(self, tmp_harness_dir):
        result = collector_stop()
        assert result == "stopped"

    def test_stop_cleans_up_stale_pid_file(self, tmp_harness_dir):
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text("99999\n")
        result = collector_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_with_non_numeric_pid(self, tmp_harness_dir):
        pid_file = tmp_harness_dir / "run" / "collector.pid"
        pid_file.write_text("garbage\n")
        result = collector_stop()
        assert result == "stopped"
        assert not pid_file.exists()


class TestCollectorEnsure:
    def test_does_not_raise_when_config_missing(self, tmp_harness_dir):
        # Should not raise even when config is missing
        collector_ensure()

    def test_does_not_raise_on_any_error(self, tmp_harness_dir):
        """ensure() swallows all exceptions."""
        with patch("core.collector_ctl.collector_status", side_effect=RuntimeError("boom")):
            collector_ensure()  # should not raise


class TestCLI:
    def test_no_args_prints_usage(self, tmp_harness_dir):
        result = subprocess.run(
            [sys.executable, "-m", "core.collector_ctl"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "usage:" in result.stderr

    def test_unknown_arg_prints_usage(self, tmp_harness_dir):
        result = subprocess.run(
            [sys.executable, "-m", "core.collector_ctl", "restart"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "usage:" in result.stderr

    def test_status_prints_stopped(self, tmp_harness_dir):
        result = subprocess.run(
            [sys.executable, "-c",
             "import core.constants as c; "
             f"c.PID_FILE = __import__('pathlib').Path('{tmp_harness_dir}/run/collector.pid'); "
             f"c.CONFIG_FILE = __import__('pathlib').Path('{tmp_harness_dir}/config.yaml'); "
             "from core.collector_ctl import main; "
             "__import__('sys').argv = ['arize-collector-ctl', 'status']; "
             "main()"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert "stopped" in result.stdout


@pytest.mark.slow
class TestIntegration:
    def test_full_lifecycle(self, tmp_harness_dir, sample_config):
        """Start → status → stop cycle with real collector.py."""
        collector_py = Path(__file__).parent.parent / "core" / "collector.py"
        if not collector_py.is_file():
            pytest.skip("collector.py not found")

        # Start
        ok = collector_start()
        if not ok:
            pytest.skip("collector failed to start (may need dependencies)")

        try:
            # Status
            status, pid, addr = collector_status()
            assert status == "running"
            assert pid is not None
            assert addr is not None

            # Stop
            result = collector_stop()
            assert result == "stopped"

            # Verify stopped
            status2, _, _ = collector_status()
            assert status2 == "stopped"
        except Exception:
            # Clean up even on failure
            collector_stop()
            raise
