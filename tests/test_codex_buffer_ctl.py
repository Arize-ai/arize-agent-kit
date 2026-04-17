"""Tests for core.codex_buffer_ctl module."""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core.codex_buffer_ctl import (
    _health_check,
    _is_process_alive,
    _resolve_host_port,
    buffer_ensure,
    buffer_start,
    buffer_status,
    buffer_stop,
    main,
)


@pytest.fixture(autouse=True)
def _mock_ctl_sleep(monkeypatch):
    """Mock time.sleep in codex_buffer_ctl to prevent real delays in retry/poll loops."""
    sleep_calls = []
    monkeypatch.setattr("core.codex_buffer_ctl.time.sleep", lambda s: sleep_calls.append(s))
    return sleep_calls


@pytest.fixture(autouse=True)
def _mock_ctl_health(monkeypatch):
    """Mock _health_check to prevent tests from finding a real buffer on localhost.

    Tests that need a healthy endpoint use mock_collector which patches this back.
    """
    monkeypatch.setattr("core.codex_buffer_ctl._health_check", lambda *a, **kw: False)


# ---------------------------------------------------------------------------
# Helper fixture: monkeypatch constants in BOTH core.constants AND
# core.codex_buffer_ctl, because codex_buffer_ctl uses `from core.constants import`
# which creates local bindings that won't see monkeypatches to core.constants.
# ---------------------------------------------------------------------------


@pytest.fixture
def ctl_paths(tmp_harness_dir, monkeypatch):
    """Monkeypatch all path constants in core.codex_buffer_ctl to use temp paths.

    The base tmp_harness_dir fixture patches core.constants, but codex_buffer_ctl
    has its own local bindings from `from core.constants import ...`.
    This fixture patches those too.
    """
    import core.codex_buffer_ctl as ctl
    import core.constants as c

    monkeypatch.setattr(ctl, "CODEX_BUFFER_PID_FILE", c.CODEX_BUFFER_PID_FILE)
    monkeypatch.setattr(ctl, "PID_DIR", c.PID_DIR)
    monkeypatch.setattr(ctl, "CONFIG_FILE", c.CONFIG_FILE)
    monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", c.CODEX_BUFFER_BIN)
    monkeypatch.setattr(ctl, "CODEX_BUFFER_LOG_FILE", c.CODEX_BUFFER_LOG_FILE)
    monkeypatch.setattr(ctl, "LOG_DIR", c.LOG_DIR)
    monkeypatch.setattr(ctl, "DEFAULT_BUFFER_HOST", c.DEFAULT_BUFFER_HOST)
    monkeypatch.setattr(ctl, "DEFAULT_BUFFER_PORT", c.DEFAULT_BUFFER_PORT)

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

    def test_buffer_config_takes_priority(self, ctl_paths):
        """buffer.host/port takes priority over collector.host/port."""
        import core.constants as c

        config = {
            "collector": {"host": "10.0.0.1", "port": 9999},
            "buffer": {"host": "192.168.1.1", "port": 7777},
        }
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "192.168.1.1"
        assert port == 7777

    def test_buffer_partial_falls_back_to_collector(self, ctl_paths):
        """If buffer only has host, port falls back to collector.port."""
        import core.constants as c

        config = {
            "collector": {"host": "10.0.0.1", "port": 9999},
            "buffer": {"host": "192.168.1.1"},
        }
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "192.168.1.1"
        assert port == 9999


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
# buffer_status tests
# ---------------------------------------------------------------------------


class TestBufferStatus:
    def test_stopped_when_no_pid_file_and_no_health(self, ctl_paths):
        """No PID file and no healthy service means stopped."""
        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert pid is None

    def test_stopped_when_dead_pid(self, ctl_paths, sample_config):
        """PID file with dead PID is cleaned up and reports stopped."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("99999\n")
        assert pid_file.exists()

        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert pid is None
        # PID file should be cleaned up
        assert not pid_file.exists()

    def test_stopped_when_non_numeric_pid(self, ctl_paths, sample_config):
        """Non-numeric PID file content is cleaned up."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("not-a-number\n")

        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert pid is None
        assert not pid_file.exists()

    def test_stopped_when_empty_pid_file(self, ctl_paths, sample_config):
        """Empty PID file is cleaned up."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("")

        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert pid is None
        assert not pid_file.exists()

    def test_running_when_process_alive_and_healthy(self, ctl_paths, mock_collector):
        """Process alive + health OK = running."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        status, pid, addr = buffer_status()
        assert status == "running"
        assert pid == os.getpid()
        assert str(mock_collector["port"]) in addr

    def test_running_when_process_alive_but_health_fails(self, ctl_paths):
        """Process alive but health fails = still reports running (benefit of the doubt)."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        # Config points to a port with nothing listening
        config = {"collector": {"host": "127.0.0.1", "port": 19998}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        status, pid, addr = buffer_status()
        assert status == "running"
        assert pid == os.getpid()
        assert "19998" in addr

    def test_pid_file_with_extra_whitespace(self, ctl_paths, sample_config):
        """PID file with extra whitespace/newlines is parsed correctly."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(f"  {os.getpid()}  \n\n")

        status, pid, addr = buffer_status()
        assert status == "running"
        assert pid == os.getpid()


# ---------------------------------------------------------------------------
# buffer_start tests
# ---------------------------------------------------------------------------


class TestBufferStart:
    def test_returns_false_when_config_missing(self, ctl_paths):
        """No config.yaml means start fails."""
        result = buffer_start()
        assert result is False

    def test_idempotent_when_already_running(self, ctl_paths, mock_collector):
        """If buffer is already running, start returns True without launching."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        result = buffer_start()
        assert result is True

    def test_detects_port_in_use_by_non_buffer(self, ctl_paths):
        """When port is taken by a non-buffer process, start fails with clear error."""
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

            result = buffer_start()
            assert result is False
        finally:
            server.shutdown()

    def test_detects_existing_buffer_on_port(self, ctl_paths, mock_collector, monkeypatch):
        """If port has a healthy buffer already, start returns True."""
        import core.codex_buffer_ctl as ctl
        import core.constants as c

        # Restore real _health_check for this test (overrides autouse mock)
        monkeypatch.setattr("core.codex_buffer_ctl._health_check", _health_check)

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        # Create a fake codex_buffer.py so the runtime check passes
        fake_core = ctl_paths / "fake_core_detect"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake buffer\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # No PID file, but the port has a healthy buffer
        result = buffer_start()
        assert result is True

    def test_returns_false_when_no_buffer_runtime(self, ctl_paths, sample_config, monkeypatch):
        """If neither CODEX_BUFFER_BIN nor codex_buffer.py exist, start fails."""
        import core.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent path
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Point __file__ to a dir that has no codex_buffer.py
        fake_core = ctl_paths / "fake_core"
        fake_core.mkdir(exist_ok=True)
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        result = buffer_start()
        assert result is False

    def test_start_launches_subprocess(self, ctl_paths, sample_config, monkeypatch):
        """Successful launch via codex_buffer.py calls Popen with correct args."""
        import core.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create a fake codex_buffer.py at the expected path
        fake_core = ctl_paths / "fake_core"
        fake_core.mkdir(exist_ok=True)
        buffer_py = fake_core / "codex_buffer.py"
        buffer_py.write_text("# fake buffer\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock socket to raise (port is free)
        monkeypatch.setattr(
            "core.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("core.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Mock _health_check: fail first calls (status + start pre-check), succeed after launch
        call_count = {"n": 0}

        def fake_health_check(host, port, timeout=2.0):
            call_count["n"] += 1
            return call_count["n"] >= 4  # 1=status, 2=start pre-check, 3=port-check, 4+=poll

        monkeypatch.setattr("core.codex_buffer_ctl._health_check", fake_health_check)

        result = buffer_start()
        assert result is True

        # Verify Popen was called with the right command
        popen_args, popen_kwargs = mock_popen.call_args
        assert popen_args[0] == [sys.executable, str(buffer_py)]
        assert popen_kwargs.get("start_new_session") is True

    def test_start_uses_buffer_bin_when_available(self, ctl_paths, sample_config, monkeypatch):
        """When CODEX_BUFFER_BIN exists and is executable, it is preferred over codex_buffer.py."""
        import core.codex_buffer_ctl as ctl

        # Create a fake CODEX_BUFFER_BIN
        buffer_bin = ctl_paths / "arize-codex-buffer"
        buffer_bin.write_text("#!/bin/sh\n")
        buffer_bin.chmod(0o755)
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", buffer_bin)

        # Mock socket to raise (port is free)
        monkeypatch.setattr(
            "core.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("core.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Mock _health_check: False for status + start pre-checks, True after launch
        health_calls = iter([False, False, True])
        monkeypatch.setattr("core.codex_buffer_ctl._health_check", lambda h, p, timeout=2.0: next(health_calls))

        result = buffer_start()
        assert result is True

        popen_args, _ = mock_popen.call_args
        assert popen_args[0] == [str(buffer_bin)]

    def test_start_returns_true_if_process_alive_but_unhealthy(self, ctl_paths, sample_config, monkeypatch):
        """If health check never passes but process is alive, returns True (benefit of the doubt)."""
        import core.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create fake codex_buffer.py
        fake_core = ctl_paths / "fake_core_alive"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock socket (port is free)
        monkeypatch.setattr(
            "core.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("core.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Health check always fails
        monkeypatch.setattr("core.codex_buffer_ctl._health_check", lambda h, p, timeout=2.0: False)

        # Process is alive
        monkeypatch.setattr("core.codex_buffer_ctl._is_process_alive", lambda pid: pid == 54321)

        result = buffer_start()
        assert result is True

    def test_start_returns_false_on_popen_failure(self, ctl_paths, sample_config, monkeypatch):
        """If Popen raises OSError, buffer_start returns False."""
        import core.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create fake codex_buffer.py
        fake_core = ctl_paths / "fake_core_oserr"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock socket (port is free)
        monkeypatch.setattr(
            "core.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen to raise OSError
        monkeypatch.setattr(
            "core.codex_buffer_ctl.subprocess.Popen",
            MagicMock(side_effect=OSError("Permission denied")),
        )

        result = buffer_start()
        assert result is False


# ---------------------------------------------------------------------------
# buffer_stop tests
# ---------------------------------------------------------------------------


class TestBufferStop:
    def test_stop_when_already_stopped(self, ctl_paths):
        """Stop when no PID file returns 'stopped'."""
        result = buffer_stop()
        assert result == "stopped"

    def test_stop_cleans_up_stale_pid_file(self, ctl_paths):
        """Stop with dead PID removes PID file."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("99999\n")

        result = buffer_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_with_non_numeric_pid(self, ctl_paths):
        """Stop with garbage PID file removes it."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("garbage\n")

        result = buffer_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_with_empty_pid_file(self, ctl_paths):
        """Stop with empty PID file removes it."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text("")

        result = buffer_stop()
        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_sends_sigterm_to_alive_process(self, ctl_paths, _mock_ctl_sleep):
        """Stop sends SIGTERM to a live process and waits for it to die."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE

        # Start a subprocess that we can kill
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_file.write_text(str(proc.pid) + "\n")

        try:
            result = buffer_stop()
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

        pid_file = c.CODEX_BUFFER_PID_FILE

        # Use our own PID — we won't die from SIGTERM during test
        # but the function should still remove the PID file
        pid_file.write_text(str(os.getpid()) + "\n")

        # Mock os.kill to do nothing (simulate process that ignores SIGTERM)
        with patch("core.codex_buffer_ctl.os.kill"):
            with patch("core.codex_buffer_ctl._is_process_alive", return_value=True):
                result = buffer_stop()

        assert result == "stopped"
        assert not pid_file.exists()

    def test_stop_is_idempotent(self, ctl_paths):
        """Calling stop twice returns 'stopped' both times."""
        assert buffer_stop() == "stopped"
        assert buffer_stop() == "stopped"


# ---------------------------------------------------------------------------
# buffer_ensure tests
# ---------------------------------------------------------------------------


class TestBufferEnsure:
    def test_does_not_raise_when_config_missing(self, ctl_paths):
        """ensure() does not raise even when config is missing."""
        buffer_ensure()  # should not raise

    def test_does_not_raise_on_status_error(self, ctl_paths):
        """ensure() swallows exceptions from buffer_status."""
        with patch("core.codex_buffer_ctl.buffer_status", side_effect=RuntimeError("boom")):
            buffer_ensure()  # should not raise

    def test_does_not_raise_on_start_error(self, ctl_paths):
        """ensure() swallows exceptions from buffer_start."""
        with patch("core.codex_buffer_ctl.buffer_status", return_value=("stopped", None, None)):
            with patch("core.codex_buffer_ctl.buffer_start", side_effect=RuntimeError("boom")):
                buffer_ensure()  # should not raise

    def test_skips_start_when_running(self, ctl_paths, mock_collector):
        """ensure() does not call start if status is running."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        with patch("core.codex_buffer_ctl.buffer_start") as mock_start:
            buffer_ensure()
            mock_start.assert_not_called()

    def test_calls_start_when_stopped(self, ctl_paths):
        """ensure() calls start when buffer is stopped."""
        with patch("core.codex_buffer_ctl.buffer_start") as mock_start:
            buffer_ensure()
            mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# CLI entrypoint tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_no_args_prints_usage_and_exits_1(self, ctl_paths):
        """No args prints usage to stderr, exits 1."""
        with patch("sys.argv", ["arize-codex-buffer"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_unknown_command_prints_usage(self, ctl_paths):
        """Unknown command prints usage to stderr, exits 1."""
        with patch("sys.argv", ["arize-codex-buffer", "restart"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_status_prints_stopped(self, ctl_paths, capsys):
        """'status' command prints 'stopped' when no buffer running."""
        with patch("sys.argv", ["arize-codex-buffer", "status"]):
            main()
        captured = capsys.readouterr()
        assert "stopped" in captured.out

    def test_status_prints_running(self, ctl_paths, mock_collector, capsys):
        """'status' command prints 'running' with PID and address."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        with patch("sys.argv", ["arize-codex-buffer", "status"]):
            main()
        captured = capsys.readouterr()
        assert "running" in captured.out
        assert str(os.getpid()) in captured.out
        assert str(mock_collector["port"]) in captured.out

    def test_stop_prints_stopped(self, ctl_paths, capsys):
        """'stop' command prints 'stopped'."""
        with patch("sys.argv", ["arize-codex-buffer", "stop"]):
            main()
        captured = capsys.readouterr()
        assert "stopped" in captured.out

    def test_start_fails_without_config(self, ctl_paths):
        """'start' command exits 1 when config is missing."""
        with patch("sys.argv", ["arize-codex-buffer", "start"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_valid_commands_accepted(self, ctl_paths):
        """All three valid commands are accepted (don't exit 1 for usage)."""
        for cmd in ["start", "stop", "status"]:
            # Just verify they don't print usage; they may fail for other reasons
            with patch("sys.argv", ["arize-codex-buffer", cmd]):
                try:
                    main()
                except SystemExit:
                    # start may exit 1 due to no config, that's fine
                    # but it shouldn't be a usage error
                    pass


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_pid_file_with_float(self, ctl_paths, sample_config):
        """PID file with float value is handled (ValueError on int())."""
        import core.constants as c

        c.CODEX_BUFFER_PID_FILE.write_text("123.456\n")
        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert not c.CODEX_BUFFER_PID_FILE.exists()

    def test_pid_file_with_negative_pid(self, ctl_paths, sample_config):
        """PID file with negative PID is handled — treated as dead."""
        import core.constants as c

        c.CODEX_BUFFER_PID_FILE.write_text("-1\n")
        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert not c.CODEX_BUFFER_PID_FILE.exists()

    def test_pid_file_with_zero(self, ctl_paths, sample_config):
        """PID file with 0 — always treated as dead (guarded)."""
        import core.constants as c

        c.CODEX_BUFFER_PID_FILE.write_text("0\n")
        status, pid, addr = buffer_status()
        assert status == "stopped"
        assert not c.CODEX_BUFFER_PID_FILE.exists()

    def test_status_then_stop_then_status(self, ctl_paths):
        """Verify status->stop->status cycle is clean."""
        s1, _, _ = buffer_status()
        assert s1 == "stopped"
        assert buffer_stop() == "stopped"
        s2, _, _ = buffer_status()
        assert s2 == "stopped"

    def test_log_output_goes_to_stderr(self, ctl_paths, capsys):
        """_log() writes to stderr, not stdout."""
        from core.codex_buffer_ctl import _log

        _log("test message")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test message" in captured.err
        assert "[arize-codex-buffer]" in captured.err

    def test_buffer_start_with_config_but_no_runtime(self, ctl_paths, sample_config, monkeypatch):
        """Start with config but no buffer binary or codex_buffer.py fails gracefully."""
        import core.codex_buffer_ctl as ctl

        # Point both runtime locations to nonexistent paths
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))
        fake_parent = ctl_paths / "fake_core2"
        fake_parent.mkdir(exist_ok=True)
        monkeypatch.setattr(ctl, "__file__", str(fake_parent / "codex_buffer_ctl.py"))

        result = buffer_start()
        assert result is False
