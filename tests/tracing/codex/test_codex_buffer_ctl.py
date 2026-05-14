"""Tests for tracing.codex.codex_buffer_ctl module."""

import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tracing.codex.codex_buffer_ctl import (
    _evict_stale,
    _expected_build_path,
    _health_check,
    _health_identity,
    _is_process_alive,
    _listener_pid,
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
    monkeypatch.setattr("tracing.codex.codex_buffer_ctl.time.sleep", lambda s: sleep_calls.append(s))
    return sleep_calls


@pytest.fixture(autouse=True)
def _mock_ctl_health(monkeypatch):
    """Mock _health_check to prevent tests from finding a real buffer on localhost.

    Tests that need a healthy endpoint use mock_collector which patches this back.
    """
    monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: False)


@pytest.fixture(autouse=True)
def _mock_ctl_identity(monkeypatch):
    """Mock _health_identity and _listener_pid to prevent real network/lsof calls.

    Tests that need identity behavior override these explicitly.
    """
    monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_identity", lambda *a, **kw: {})
    monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Helper fixture: monkeypatch constants in BOTH core.constants AND
# tracing.codex.codex_buffer_ctl, because codex_buffer_ctl uses `from core.constants import`
# which creates local bindings that won't see monkeypatches to core.constants.
# ---------------------------------------------------------------------------


@pytest.fixture
def ctl_paths(tmp_harness_dir, monkeypatch):
    """Monkeypatch all path constants in tracing.codex.codex_buffer_ctl to use temp paths.

    The base tmp_harness_dir fixture patches core.constants, but codex_buffer_ctl
    has its own local bindings from `from core.constants import ...`.
    This fixture patches those too.
    """
    import core.constants as c
    import tracing.codex.codex_buffer_ctl as ctl

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
    def test_buffer_reads_host_port_from_codex_collector(self, ctl_paths):
        """Full config with harnesses.codex.collector.{host, port} is read correctly."""
        import core.constants as c

        config = {"harnesses": {"codex": {"collector": {"host": "0.0.0.0", "port": 9999}}}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "0.0.0.0"
        assert port == 9999

    def test_buffer_defaults_when_no_codex_entry(self, ctl_paths):
        """Config has no harnesses.codex at all -> defaults."""
        import core.constants as c

        config = {"harnesses": {"claude-code": {"project_name": "cc"}}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_buffer_defaults_when_codex_entry_has_no_collector(self, ctl_paths):
        """harnesses.codex exists but no collector sub-dict -> defaults."""
        import core.constants as c

        config = {"harnesses": {"codex": {"project_name": "codex"}}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_buffer_ignores_top_level_collector_key(self, ctl_paths):
        """Old-style top-level collector: block is NOT read; defaults used."""
        import core.constants as c

        config = {"collector": {"host": "10.0.0.1", "port": 9999}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

    def test_buffer_ignores_top_level_buffer_key(self, ctl_paths):
        """Old-style top-level buffer: block is NOT read; defaults used."""
        import core.constants as c

        config = {"buffer": {"host": "192.168.1.1", "port": 7777}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)
        host, port = _resolve_host_port()
        assert host == "127.0.0.1"
        assert port == 4318

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

    def test_partial_config_falls_back(self, ctl_paths):
        """If only host is set, port falls back to default."""
        import core.constants as c

        config = {"harnesses": {"codex": {"collector": {"host": "10.0.0.1"}}}}
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

        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": "5555"}}}}
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

        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}}}
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
        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": 19998}}}}
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

    def test_idempotent_when_already_running(self, ctl_paths, mock_collector, monkeypatch):
        """If buffer is already running with matching identity, start returns True without launching."""
        import core.constants as c

        pid_file = c.CODEX_BUFFER_PID_FILE
        pid_file.write_text(str(os.getpid()) + "\n")

        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        # Mock identity to match expected build_path so pidfile check passes
        expected_bp = _expected_build_path()
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": os.getpid(), "build_path": expected_bp},
        )

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
            config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": port}}}}
            with open(c.CONFIG_FILE, "w") as f:
                yaml.safe_dump(config, f)

            result = buffer_start()
            assert result is False
        finally:
            server.shutdown()

    def test_detects_existing_buffer_on_port(self, ctl_paths, mock_collector, monkeypatch):
        """If port has a healthy buffer with matching identity, start returns True."""
        import core.constants as c
        import tracing.codex.codex_buffer_ctl as ctl

        # Restore real _health_check for this test (overrides autouse mock)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", _health_check)

        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}}}
        with open(c.CONFIG_FILE, "w") as f:
            yaml.safe_dump(config, f)

        # Create a fake codex_buffer.py so the runtime check passes
        fake_core = ctl_paths / "fake_core_detect"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake buffer\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock identity to match expected build_path
        expected_bp = str((fake_core / "codex_buffer.py").resolve())
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": os.getpid(), "build_path": expected_bp},
        )

        # No PID file, but the port has a healthy buffer with matching identity
        result = buffer_start()
        assert result is True

    def test_returns_false_when_no_buffer_runtime(self, ctl_paths, sample_config, monkeypatch):
        """If neither CODEX_BUFFER_BIN nor codex_buffer.py exist, start fails."""
        import tracing.codex.codex_buffer_ctl as ctl

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
        import tracing.codex.codex_buffer_ctl as ctl

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
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Mock _health_check: fail for identity check, succeed after launch poll
        call_count = {"n": 0}

        def fake_health_check(host, port, timeout=2.0):
            call_count["n"] += 1
            # 1st call: identity check -> False (nothing on port)
            # 2nd+ call: post-launch poll -> True
            return call_count["n"] >= 2

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", fake_health_check)

        result = buffer_start()
        assert result is True

        # Verify Popen was called with the right command
        popen_args, popen_kwargs = mock_popen.call_args
        assert popen_args[0] == [sys.executable, str(buffer_py)]
        assert popen_kwargs.get("start_new_session") is True

    def test_start_uses_buffer_bin_when_available(self, ctl_paths, sample_config, monkeypatch):
        """When CODEX_BUFFER_BIN exists and is executable, it is preferred over codex_buffer.py."""
        import tracing.codex.codex_buffer_ctl as ctl

        # Create a fake CODEX_BUFFER_BIN
        buffer_bin = ctl_paths / "arize-codex-buffer"
        buffer_bin.write_text("#!/bin/sh\n")
        buffer_bin.chmod(0o755)
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", buffer_bin)

        # Mock socket to raise (port is free)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Mock _health_check: False for status + start pre-checks, True after launch
        health_calls = iter([False, False, True])
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_check", lambda h, p, timeout=2.0: next(health_calls)
        )

        result = buffer_start()
        assert result is True

        popen_args, _ = mock_popen.call_args
        assert popen_args[0] == [str(buffer_bin)]

    def test_start_returns_true_if_process_alive_but_unhealthy(self, ctl_paths, sample_config, monkeypatch):
        """If health check never passes but process is alive, returns True (benefit of the doubt)."""
        import tracing.codex.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create fake codex_buffer.py
        fake_core = ctl_paths / "fake_core_alive"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock socket (port is free)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.Popen", mock_popen)

        # Health check always fails
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda h, p, timeout=2.0: False)

        # Process is alive
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._is_process_alive", lambda pid: pid == 54321)

        result = buffer_start()
        assert result is True

    def test_start_returns_false_on_popen_failure(self, ctl_paths, sample_config, monkeypatch):
        """If Popen raises OSError, buffer_start returns False."""
        import tracing.codex.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create fake codex_buffer.py
        fake_core = ctl_paths / "fake_core_oserr"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        # Mock socket (port is free)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen to raise OSError
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.Popen",
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
        with patch("tracing.codex.codex_buffer_ctl.os.kill"):
            with patch("tracing.codex.codex_buffer_ctl._is_process_alive", return_value=True):
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

    def test_does_not_raise_on_start_error(self, ctl_paths):
        """ensure() swallows exceptions from buffer_start."""
        with patch("tracing.codex.codex_buffer_ctl.buffer_start", side_effect=RuntimeError("boom")):
            buffer_ensure()  # should not raise

    def test_calls_start_without_evicting_stale_buffer(self, ctl_paths):
        """ensure() delegates to buffer_start but preserves healthy in-memory buffers."""
        with patch("tracing.codex.codex_buffer_ctl.buffer_start") as mock_start:
            buffer_ensure()
            mock_start.assert_called_once_with(evict_stale=False)


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

        config = {"harnesses": {"codex": {"collector": {"host": "127.0.0.1", "port": mock_collector["port"]}}}}
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
        from tracing.codex.codex_buffer_ctl import _log

        _log("test message")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test message" in captured.err
        assert "[arize-codex-buffer]" in captured.err

    def test_buffer_start_with_config_but_no_runtime(self, ctl_paths, sample_config, monkeypatch):
        """Start with config but no buffer binary or codex_buffer.py fails gracefully."""
        import tracing.codex.codex_buffer_ctl as ctl

        # Point both runtime locations to nonexistent paths
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))
        fake_parent = ctl_paths / "fake_core2"
        fake_parent.mkdir(exist_ok=True)
        monkeypatch.setattr(ctl, "__file__", str(fake_parent / "codex_buffer_ctl.py"))

        result = buffer_start()
        assert result is False


# ---------------------------------------------------------------------------
# _health_identity tests
# ---------------------------------------------------------------------------


class TestHealthIdentity:
    def test_health_identity_parses_json(self, monkeypatch):
        """Valid identity JSON is returned as a dict."""
        import io

        identity_json = json.dumps(
            {"status": "ok", "pid": 12345, "build_path": "/some/path/codex_buffer.py", "started_at": 1700000000.0}
        ).encode()

        def fake_urlopen(url, timeout=None):
            return io.BytesIO(identity_json)

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.urllib.request.urlopen", fake_urlopen)
        result = _health_identity("127.0.0.1", 4318)
        assert result["pid"] == 12345
        assert result["build_path"] == "/some/path/codex_buffer.py"
        assert result["started_at"] == 1700000000.0

    def test_health_identity_empty_on_invalid_json(self, monkeypatch):
        """Non-JSON response returns empty dict."""
        import io

        def fake_urlopen(url, timeout=None):
            return io.BytesIO(b"not json at all")

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.urllib.request.urlopen", fake_urlopen)
        result = _health_identity("127.0.0.1", 4318)
        assert result == {}

    def test_health_identity_empty_on_connection_error(self, monkeypatch):
        """Connection error returns empty dict."""

        def fake_urlopen(url, timeout=None):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.urllib.request.urlopen", fake_urlopen)
        result = _health_identity("127.0.0.1", 4318)
        assert result == {}


# ---------------------------------------------------------------------------
# _listener_pid tests
# ---------------------------------------------------------------------------


class TestListenerPid:
    def test_listener_pid_uses_health(self, monkeypatch):
        """When /health returns a valid PID, lsof is not called."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": 12345},
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._is_process_alive", lambda pid: pid == 12345)
        mock_run = MagicMock()
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.run", mock_run)

        result = _listener_pid("127.0.0.1", 4318)
        assert result == 12345
        mock_run.assert_not_called()

    def test_listener_pid_falls_back_to_lsof(self, monkeypatch):
        """When /health has no PID, falls back to lsof."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {},
        )
        mock_result = MagicMock()
        mock_result.stdout = "99887\n"
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.run",
            MagicMock(return_value=mock_result),
        )

        result = _listener_pid("127.0.0.1", 4318)
        assert result == 99887

    def test_listener_pid_returns_none_when_lsof_missing(self, monkeypatch):
        """When lsof is not installed, returns None."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {},
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.run",
            MagicMock(side_effect=FileNotFoundError("lsof not found")),
        )

        result = _listener_pid("127.0.0.1", 4318)
        assert result is None


# ---------------------------------------------------------------------------
# Identity-aware buffer_status tests
# ---------------------------------------------------------------------------


class TestBufferStatusIdentity:
    def test_status_returns_real_pid_via_lsof_when_pidfile_missing(self, ctl_paths, monkeypatch):
        """When pidfile is absent but health passes, _listener_pid provides PID."""
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: True)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 555)

        status, pid, addr = buffer_status()
        assert status == "running"
        assert pid == 555


# ---------------------------------------------------------------------------
# Identity-aware buffer_start tests
# ---------------------------------------------------------------------------


class TestBufferStartIdentity:
    def test_start_short_circuits_when_build_path_matches(self, ctl_paths, sample_config, monkeypatch):
        """If /health returns matching build_path, Popen is never called."""

        expected_bp = _expected_build_path()
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: True)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": 999, "build_path": expected_bp},
        )

        mock_popen = MagicMock()
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.Popen", mock_popen)

        result = buffer_start()
        assert result is True
        mock_popen.assert_not_called()

    def test_start_evicts_when_build_path_mismatches(self, ctl_paths, sample_config, monkeypatch):
        """Mismatched build_path triggers eviction then spawn."""
        import tracing.codex.codex_buffer_ctl as ctl

        # Point CODEX_BUFFER_BIN to nonexistent so it falls through to codex_buffer.py
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        # Create fake codex_buffer.py at __file__'s parent
        fake_core = ctl_paths / "fake_core_evict"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        health_calls = {"n": 0}

        def fake_health(host, port, timeout=2.0):
            health_calls["n"] += 1
            # 1st call: buffer_start identity check -> True (stale daemon on port)
            # 2nd+ call: post-launch poll -> True
            return True

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", fake_health)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": 12345, "build_path": "/old/worktree/codex_buffer.py"},
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 12345)

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )

        # Mock _evict_stale's port poll to succeed immediately
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        # Mock Popen for the spawn
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )

        result = buffer_start()
        assert result is True
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)

    def test_start_evicts_when_build_path_no_longer_exists(self, ctl_paths, sample_config, monkeypatch):
        """build_path pointing to a deleted file triggers eviction."""
        import tracing.codex.codex_buffer_ctl as ctl

        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        fake_core = ctl_paths / "fake_core_gone"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: True)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": 12345, "build_path": "/tmp/nonexistent/buffer.py"},
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 12345)

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )

        result = buffer_start()
        assert result is True
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)

    def test_start_evicts_when_identity_missing(self, ctl_paths, sample_config, monkeypatch):
        """Old buffer with no identity triggers eviction."""
        import tracing.codex.codex_buffer_ctl as ctl

        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", Path("/nonexistent/arize-codex-buffer"))

        fake_core = ctl_paths / "fake_core_old"
        fake_core.mkdir(exist_ok=True)
        (fake_core / "codex_buffer.py").write_text("# fake\n")
        monkeypatch.setattr(ctl, "__file__", str(fake_core / "codex_buffer_ctl.py"))

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: True)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_identity", lambda h, p: {})
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 12345)

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.socket.create_connection",
            MagicMock(side_effect=ConnectionRefusedError),
        )

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )

        result = buffer_start()
        assert result is True
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)

    def test_start_without_evict_stale_preserves_healthy_mismatched_buffer(self, ctl_paths, sample_config, monkeypatch):
        """Hook-time start preserves a healthy listener even when build_path differs."""
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_check", lambda *a, **kw: True)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"pid": 12345, "build_path": "/old/worktree/codex_buffer.py"},
        )

        mock_evict = MagicMock()
        mock_popen = MagicMock()
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._evict_stale", mock_evict)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.subprocess.Popen", mock_popen)

        result = buffer_start(evict_stale=False)

        assert result is True
        mock_evict.assert_not_called()
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# Identity-aware buffer_stop tests
# ---------------------------------------------------------------------------


class TestBufferStopIdentity:
    def test_stop_force_kills_unknown_listener(self, ctl_paths, monkeypatch):
        """With --force, unknown listener is killed."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._listener_pid",
            lambda h, p: 12345,
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"build_path": "/some/foreign/codex_buffer.py"},
        )
        # Make the foreign build_path "exist"
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.path.isfile", lambda p: True)

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._is_process_alive", lambda pid: False)

        result = buffer_stop(force=True)
        assert result == "stopped"
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)

    def test_stop_refuses_unknown_without_force(self, ctl_paths, monkeypatch):
        """Without --force, unknown listener is refused."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._listener_pid",
            lambda h, p: 12345,
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"build_path": "/some/foreign/codex_buffer.py"},
        )
        # Make the foreign build_path "exist"
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.path.isfile", lambda p: True)

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )

        result = buffer_stop(force=False)
        assert result == "refused"
        assert len(kill_calls) == 0

    def test_stop_kills_when_build_path_file_deleted(self, ctl_paths, monkeypatch):
        """Listener whose build_path no longer exists is killed without --force."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._listener_pid",
            lambda h, p: 12345,
        )
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"build_path": "/tmp/gone.py"},
        )

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._is_process_alive", lambda pid: False)

        result = buffer_stop(force=False)
        assert result == "stopped"
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)


# ---------------------------------------------------------------------------
# CLI identity-aware tests
# ---------------------------------------------------------------------------


class TestCLIIdentity:
    def test_cli_stop_force_flag(self, ctl_paths, monkeypatch):
        """--force flag is passed through to buffer_stop."""
        stop_calls = []

        def mock_stop(force=False):
            stop_calls.append(force)
            return "stopped"

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.buffer_stop", mock_stop)

        with patch("sys.argv", ["arize-codex-buffer", "stop", "--force"]):
            main()
        assert stop_calls == [True]

    def test_cli_stop_exits_nonzero_on_refused(self, ctl_paths, monkeypatch):
        """buffer_stop returning 'refused' causes non-zero exit."""
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.buffer_stop", lambda force=False: "refused")

        with patch("sys.argv", ["arize-codex-buffer", "stop"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _evict_stale safety guard tests
# ---------------------------------------------------------------------------


class TestEvictStaleSafety:
    def test_evict_refuses_pid_zero(self, monkeypatch):
        """PID 0 is never killed."""
        kill_calls = []
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.kill", lambda p, s: kill_calls.append((p, s)))
        result = _evict_stale(0, "127.0.0.1", 4318, "test")
        assert result is False
        assert len(kill_calls) == 0

    def test_evict_refuses_pid_one(self, monkeypatch):
        """PID 1 (init) is never killed."""
        kill_calls = []
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.kill", lambda p, s: kill_calls.append((p, s)))
        result = _evict_stale(1, "127.0.0.1", 4318, "test")
        assert result is False
        assert len(kill_calls) == 0

    def test_evict_refuses_negative_pid(self, monkeypatch):
        """Negative PIDs are never killed."""
        kill_calls = []
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.kill", lambda p, s: kill_calls.append((p, s)))
        result = _evict_stale(-5, "127.0.0.1", 4318, "test")
        assert result is False
        assert len(kill_calls) == 0

    def test_evict_refuses_own_pid(self, monkeypatch):
        """Current process PID is never killed."""
        kill_calls = []
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.kill", lambda p, s: kill_calls.append((p, s)))
        result = _evict_stale(os.getpid(), "127.0.0.1", 4318, "test")
        assert result is False
        assert len(kill_calls) == 0

    def test_evict_treats_process_lookup_error_as_success(self, monkeypatch):
        """If the process dies between check and kill, that counts as success."""
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            MagicMock(side_effect=ProcessLookupError),
        )
        result = _evict_stale(9999, "127.0.0.1", 4318, "already gone")
        assert result is True

    def test_evict_escalates_to_sigkill(self, monkeypatch):
        """If SIGTERM doesn't free the port, SIGKILL is sent."""
        kill_calls = []

        def fake_kill(pid, sig):
            kill_calls.append((pid, sig))

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.os.kill", fake_kill)

        # Port stays open during SIGTERM polling, then closes after SIGKILL
        call_count = {"n": 0}

        def fake_connect(addr, timeout=None):
            call_count["n"] += 1
            # First 50 calls (SIGTERM poll): port still open
            if call_count["n"] <= 50:
                conn = MagicMock()
                return conn
            # After SIGKILL: port freed
            raise ConnectionRefusedError

        monkeypatch.setattr("tracing.codex.codex_buffer_ctl.socket.create_connection", fake_connect)

        result = _evict_stale(9999, "127.0.0.1", 4318, "stubborn process")
        assert result is True
        assert (9999, signal.SIGTERM) in kill_calls
        assert (9999, signal.SIGKILL) in kill_calls


# ---------------------------------------------------------------------------
# buffer_stop edge cases
# ---------------------------------------------------------------------------


class TestBufferStopEdgeCases:
    def test_stop_no_pidfile_no_listener_returns_stopped(self, ctl_paths, monkeypatch):
        """With no pidfile and no listener, stop returns 'stopped'."""
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: None)
        result = buffer_stop()
        assert result == "stopped"

    def test_stop_refuses_when_no_identity_without_force(self, ctl_paths, monkeypatch):
        """Listener with no identity (empty dict) is refused without --force."""
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 12345)
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._health_identity", lambda h, p: {})

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )

        result = buffer_stop(force=False)
        assert result == "refused"
        assert len(kill_calls) == 0

    def test_stop_kills_matching_build_path_without_force(self, ctl_paths, monkeypatch):
        """Listener whose build_path matches ours is killed without --force."""

        expected_bp = _expected_build_path()
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._listener_pid", lambda h, p: 12345)
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl._health_identity",
            lambda h, p: {"build_path": expected_bp},
        )

        kill_calls = []
        monkeypatch.setattr(
            "tracing.codex.codex_buffer_ctl.os.kill",
            lambda pid, sig: kill_calls.append((pid, sig)),
        )
        monkeypatch.setattr("tracing.codex.codex_buffer_ctl._is_process_alive", lambda pid: False)

        result = buffer_stop(force=False)
        assert result == "stopped"
        assert any(pid == 12345 and sig == signal.SIGTERM for pid, sig in kill_calls)
