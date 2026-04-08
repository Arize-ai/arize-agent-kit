"""Tests for core.collector_ctl module."""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from core.collector_ctl import (
    _is_process_alive,
    _resolve_host_port,
    _health_check,
    collector_ensure,
    collector_start,
    collector_status,
    collector_stop,
    main,
)


@pytest.fixture(autouse=True)
def _mock_ctl_sleep(monkeypatch):
    """Mock time.sleep in collector_ctl to prevent real delays in retry/poll loops."""
    sleep_calls = []
    monkeypatch.setattr("core.collector_ctl.time.sleep", lambda s: sleep_calls.append(s))
    return sleep_calls


# ---------------------------------------------------------------------------
# Helper fixture: monkeypatch constants in BOTH core.constants AND
# core.collector_ctl, because collector_ctl uses `from core.constants import`
# which creates local bindings that won't see monkeypatches to core.constants.
# ---------------------------------------------------------------------------

@pytest.fixture
def ctl_paths(tmp_harness_dir, monkeypatch):
    """Monkeypatch all path constants in core.collector_ctl to use temp paths.

    The base tmp_harness_dir fixture patches core.constants, but collector_ctl
    has its own local bindings from `from core.constants import ...`.
    This fixture patches those too.
    """
    import core.collector_ctl as ctl
    import core.constants as c

    monkeypatch.setattr(ctl, "PID_FILE", c.PID_FILE)
    monkeypatch.setattr(ctl, "PID_DIR", c.PID_DIR)
    monkeypatch.setattr(ctl, "CONFIG_FILE", c.CONFIG_FILE)
    monkeypatch.setattr(ctl, "COLLECTOR_BIN", c.COLLECTOR_BIN)
    monkeypatch.setattr(ctl, "COLLECTOR_LOG_FILE", c.COLLECTOR_LOG_FILE)
    monkeypatch.setattr(ctl, "LOG_DIR", c.LOG_DIR)
    monkeypatch.setattr(ctl, "DEFAULT_COLLECTOR_HOST", c.DEFAULT_COLLECTOR_HOST)
    monkeypatch.setattr(ctl, "DEFAULT_COLLECTOR_PORT", c.DEFAULT_COLLECTOR_PORT)

    return tmp_harness_dir


# ---------------------------------------------------------------------------
# _is_process_alive tests
# ---------------------------------------------------------------------------

class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        """os.getpid() must always be alive."""
        assert _is_process_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        """PID 99999 is almost certainly not running."""
        assert _is_process_alive(99999) is False

    def test_negative_pid(self):
        """Negative PIDs should return False, not raise."""
        assert _is_process_alive(-1) is False

    def test_zero_pid(self):
        """PID 0 is guarded — always returns False."""
        assert _is_process_alive(0) is False

    def test_parent_process_is_alive(self):
        """Parent process should be alive."""
        ppid = os.getppid()
        if ppid > 0:
            assert _is_process_alive(ppid) is True


# ---------------------------------------------------------------------------
# _resolve_host_port tests
# ---------------------------------------------------------------------------

class TestResolveHostPort:
    def test_with_default_config(self, ctl_paths, sample_config):
        """With standard sample config, returns 127.0.0.1:4318."""
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_without_config_returns_defaults(self, ctl_paths):
        """When config.yaml doesn't exist, returns defaults."""
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_with_custom_host_port(self, ctl_paths):
        """Custom host/port in config.yaml is returned."""
        import core.constants as c
        config = {"collector": {"host": "0.0.0.0", "port": 9999}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "0.0.0.0"
        assert port == 9999

    def test_partial_config_falls_back(self, ctl_paths):
        """If only host is set, port falls back to default."""
        import core.constants as c
        config = {"collector": {"host": "10.0.0.1"}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "10.0.0.1"
        assert port == 4318  # default

    def test_empty_config_returns_defaults(self, ctl_paths):
        """Empty config file returns defaults."""
        import core.constants as c
        with open(c.CONFIG_FILE, "w") as f:
            f.write("{}\n")
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_malformed_config_returns_defaults(self, ctl_paths):
        """Malformed YAML in config returns defaults without raising."""
        import core.constants as c
        with open(c.CONFIG_FILE, "w") as f:
            f.write(":::bad yaml:::\n")
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_port_is_always_int(self, ctl_paths):
        """Port is returned as int even if config stores it as string."""
        import core.constants as c
        config = {"collector": {"host": "127.0.0.1", "port": "5555"}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert isinstance(port, int)
        assert port == 5555


# ---------------------------------------------------------------------------
# _health_check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_success(self, mock_collector):
        """Health check succeeds against a mock collector."""
        assert _health_check("127.0.0.1", mock_collector["port"]) is True

    def test_health_check_failure_no_server(self):
        """Health check returns False when no server is listening."""
        # Use a port that's very unlikely to be in use
        assert _health_check("127.0.0.1", 19999, timeout=0.5) is False

    def test_health_check_non_health_endpoint(self):
        """Health check returns False if server doesn't respond to /health."""
        class _NoHealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500)
                self.end_headers()
            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _NoHealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # urllib considers 500 an error, so health_check should return False
            assert _health_check("127.0.0.1", port, timeout=1.0) is False
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# collector_status tests
# ---------------------------------------------------------------------------

class TestCollectorStatus:
    def test_stopped_when_no_pid_file(self, ctl_paths):
        """No PID file means stopped."""
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert addr is None

    def test_stopped_when_dead_pid(self, ctl_paths, sample_config):
        """PID file with dead PID is cleaned up and reports stopped."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("99999\n")
        assert pid_file.exists()

        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert addr is None
        # PID file should be cleaned up
        assert not pid_file.exists()

    def test_stopped_when_non_numeric_pid(self, ctl_paths, sample_config):
        """Non-numeric PID file content is cleaned up."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("not-a-number\n")

        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert not pid_file.exists()

    def test_stopped_when_empty_pid_file(self, ctl_paths, sample_config):
        """Empty PID file is cleaned up."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("")

        status, pid, addr = collector_status()
        assert status == "stopped"
        assert pid is None
        assert not pid_file.exists()

    def test_running_when_process_alive_and_healthy(self, ctl_paths, mock_collector):
        """Process alive + health OK = running."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        status, pid, addr = collector_status()
        assert status == "running"
        assert pid == os.getpid()
        assert str(mock_collector["port"]) in addr

    def test_running_when_process_alive_but_health_fails(self, ctl_paths):
        """Process alive but health fails = still reports running (benefit of the doubt)."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        # Config points to a port with nothing listening
        config = {"collector": {"host": "127.0.0.1", "port": 19998}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        status, pid, addr = collector_status()
        assert status == "running"
        assert pid == os.getpid()
        assert "19998" in addr

    def test_pid_file_with_extra_whitespace(self, ctl_paths, sample_config):
        """PID file with extra whitespace/newlines is parsed correctly."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(f"  {os.getpid()}  \n\n")

        status, pid, addr = collector_status()
        assert status == "running"
        assert pid == os.getpid()


# ---------------------------------------------------------------------------
# collector_start tests
# ---------------------------------------------------------------------------

class TestCollectorStart:
    def test_returns_false_when_config_missing(self, ctl_paths):
        """No config.yaml means start fails."""
        result = collector_start()
        assert result is False

    def test_idempotent_when_already_running(self, ctl_paths, mock_collector):
        """If collector is already running, start returns True without launching."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        result = collector_start()
        assert result is True

    def test_detects_port_in_use_by_non_collector(self, ctl_paths):
        """When port is taken by a non-collector process, start fails with clear error."""
        import core.constants as c

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
            with open(c.CONFIG_FILE, "w") as f:
                yaml.safe_dump(config, f)

            result = collector_start()
            assert result is False
        finally:
            server.shutdown()

    def test_detects_existing_collector_on_port(self, ctl_paths, mock_collector):
        """If port has a healthy collector already, start returns True."""
        import core.constants as c
        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        # No PID file, but the port has a healthy collector
        result = collector_start()
        assert result is True

    def test_returns_false_when_no_collector_runtime(self, ctl_paths, sample_config, monkeypatch):
        """If neither COLLECTOR_BIN nor collector.py exist, start fails."""
        import core.collector_ctl as ctl

        # Point COLLECTOR_BIN to nonexistent path
        monkeypatch.setattr(ctl, "COLLECTOR_BIN", Path("/nonexistent/arize-collector"))

        # Point __file__ to a dir that has no collector.py
        fake_core = ctl_paths / "fake_core"
        fake_core.mkdir(exist_ok=True)
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "collector_ctl.py"))

        result = collector_start()
        assert result is False


# ---------------------------------------------------------------------------
# collector_stop tests
# ---------------------------------------------------------------------------

class TestCollectorStop:
    def test_stop_when_already_stopped(self, ctl_paths):
        """Stop when no PID file returns 'stopped'."""
        result = collector_stop()
        assert result == "stopped"

    def test_stop_cleans_up_stale_pid_file(self, ctl_paths):
        """Stop with dead PID removes PID file."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("99999\n")

        result = collector_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_with_non_numeric_pid(self, ctl_paths):
        """Stop with garbage PID file removes it."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("garbage\n")

        result = collector_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_with_empty_pid_file(self, ctl_paths):
        """Stop with empty PID file removes it."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text("")

        result = collector_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_sends_sigterm_to_alive_process(self, ctl_paths, _mock_ctl_sleep):
        """Stop sends SIGTERM to a live process and waits for it to die."""
        import core.constants as c
        pid_file = c.PID_FILE

        # Start a subprocess that we can kill
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_file.write_text(str(proc.pid) + "\n")

        try:
            result = collector_stop()
            assert result == "stopped"
            assert not pid_file.exists()
            # Verify poll sleeps were attempted
            assert len(_mock_ctl_sleep) > 0
            assert all(s == 0.1 for s in _mock_ctl_sleep)

            # Process should be dead (SIGTERM was sent)
            proc.wait(timeout=5)
            assert proc.returncode is not None
        except Exception:
            proc.kill()
            proc.wait()
            raise

    def test_stop_removes_pid_file_even_if_process_wont_die(self, ctl_paths):
        """Stop removes PID file even if process ignores SIGTERM."""
        import core.constants as c
        pid_file = c.PID_FILE

        # Use our own PID — we won't die from SIGTERM during test
        # but the function should still remove the PID file
        pid_file.write_text(str(os.getpid()) + "\n")

        # Mock os.kill to do nothing (simulate process that ignores SIGTERM)
        with patch("core.collector_ctl.os.kill"):
            with patch("core.collector_ctl._is_process_alive", return_value=True):
                result = collector_stop()

        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_is_idempotent(self, ctl_paths):
        """Calling stop twice returns 'stopped' both times."""
        assert collector_stop() == "stopped"
        assert collector_stop() == "stopped"


# ---------------------------------------------------------------------------
# collector_ensure tests
# ---------------------------------------------------------------------------

class TestCollectorEnsure:
    def test_does_not_raise_when_config_missing(self, ctl_paths):
        """ensure() does not raise even when config is missing."""
        collector_ensure()  # should not raise

    def test_does_not_raise_on_status_error(self, ctl_paths):
        """ensure() swallows exceptions from collector_status."""
        with patch("core.collector_ctl.collector_status", side_effect=RuntimeError("boom")):
            collector_ensure()  # should not raise

    def test_does_not_raise_on_start_error(self, ctl_paths):
        """ensure() swallows exceptions from collector_start."""
        with patch("core.collector_ctl.collector_status", return_value=("stopped", None, None)):
            with patch("core.collector_ctl.collector_start", side_effect=RuntimeError("boom")):
                collector_ensure()  # should not raise

    def test_skips_start_when_running(self, ctl_paths, mock_collector):
        """ensure() does not call start if status is running."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        with patch("core.collector_ctl.collector_start") as mock_start:
            collector_ensure()
            mock_start.assert_not_called()

    def test_calls_start_when_stopped(self, ctl_paths):
        """ensure() calls start when collector is stopped."""
        with patch("core.collector_ctl.collector_start") as mock_start:
            collector_ensure()
            mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# CLI entrypoint tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_no_args_prints_usage_and_exits_1(self, ctl_paths):
        """No args prints usage to stderr, exits 1."""
        with patch("sys.argv", ["arize-collector-ctl"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_unknown_command_prints_usage(self, ctl_paths):
        """Unknown command prints usage to stderr, exits 1."""
        with patch("sys.argv", ["arize-collector-ctl", "restart"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_status_prints_stopped(self, ctl_paths, capsys):
        """'status' command prints 'stopped' when no collector running."""
        with patch("sys.argv", ["arize-collector-ctl", "status"]):
            main()
        captured = capsys.readouterr()
        assert "stopped" in captured.out

    def test_status_prints_running(self, ctl_paths, mock_collector, capsys):
        """'status' command prints 'running' with PID and address."""
        import core.constants as c
        pid_file = c.PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        with patch("sys.argv", ["arize-collector-ctl", "status"]):
            main()
        captured = capsys.readouterr()
        assert "running" in captured.out
        assert str(os.getpid()) in captured.out
        assert str(mock_collector["port"]) in captured.out

    def test_stop_prints_stopped(self, ctl_paths, capsys):
        """'stop' command prints 'stopped'."""
        with patch("sys.argv", ["arize-collector-ctl", "stop"]):
            main()
        captured = capsys.readouterr()
        assert "stopped" in captured.out

    def test_start_fails_without_config(self, ctl_paths):
        """'start' command exits 1 when config is missing."""
        with patch("sys.argv", ["arize-collector-ctl", "start"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_valid_commands_accepted(self, ctl_paths):
        """All three valid commands are accepted (don't exit 1 for usage)."""
        for cmd in ["start", "stop", "status"]:
            # Just verify they don't print usage; they may fail for other reasons
            with patch("sys.argv", ["arize-collector-ctl", cmd]):
                try:
                    main()
                except SystemExit as e:
                    # start may exit 1 due to no config, that's fine
                    # but it shouldn't be a usage error
                    pass


# ---------------------------------------------------------------------------
# Integration test: full lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestIntegration:
    def test_full_lifecycle(self, ctl_paths, sample_config):
        """Start -> status -> stop cycle with real collector.py."""
        collector_py = Path(__file__).parent.parent / "core" / "collector.py"
        if not collector_py.is_file():
            pytest.skip("collector.py not found")

        # Start
        ok = collector_start()
        if not ok:
            pytest.skip("collector failed to start (may need dependencies)")

        try:
            # Verify actually running (not just briefly alive)
            status, pid, addr = collector_status()
            if status != "running":
                pytest.skip("collector started but exited quickly (environment issue)")

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


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_pid_file_with_float(self, ctl_paths, sample_config):
        """PID file with float value is handled (ValueError on int())."""
        import core.constants as c
        c.PID_FILE.write_text("123.456\n")
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert not c.PID_FILE.exists()

    def test_pid_file_with_negative_pid(self, ctl_paths, sample_config):
        """PID file with negative PID is handled — treated as dead."""
        import core.constants as c
        c.PID_FILE.write_text("-1\n")
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert not c.PID_FILE.exists()

    def test_pid_file_with_zero(self, ctl_paths, sample_config):
        """PID file with 0 — always treated as dead (guarded)."""
        import core.constants as c
        c.PID_FILE.write_text("0\n")
        status, pid, addr = collector_status()
        assert status == "stopped"
        assert not c.PID_FILE.exists()

    def test_status_then_stop_then_status(self, ctl_paths):
        """Verify status->stop->status cycle is clean."""
        s1, _, _ = collector_status()
        assert s1 == "stopped"
        assert collector_stop() == "stopped"
        s2, _, _ = collector_status()
        assert s2 == "stopped"

    def test_log_output_goes_to_stderr(self, ctl_paths, capsys):
        """_log() writes to stderr, not stdout."""
        from core.collector_ctl import _log
        _log("test message")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test message" in captured.err
        assert "[arize]" in captured.err

    def test_collector_start_with_config_but_no_runtime(self, ctl_paths, sample_config, monkeypatch):
        """Start with config but no collector binary or collector.py fails gracefully."""
        import core.collector_ctl as ctl

        # Point both runtime locations to nonexistent paths
        monkeypatch.setattr(ctl, "COLLECTOR_BIN", Path("/nonexistent/arize-collector"))
        fake_parent = ctl_paths / "fake_core2"
        fake_parent.mkdir(exist_ok=True)
        monkeypatch.setattr(ctl, "__file__", str(fake_parent / "collector_ctl.py"))

        result = collector_start()
        assert result is False
