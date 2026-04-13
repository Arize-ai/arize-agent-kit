"""Tests for core.installer.collector module."""

import os
import shutil
import stat
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from core.installer.collector import (
    _health_check,
    _is_windows,
    _remove_empty_dir,
    _remove_file,
    _resolve_host_port,
    _write_unix_launcher,
    _write_windows_launcher,
    collector_status,
    install_collector,
    start_collector,
    stop_collector,
    uninstall_collector,
)


# ---------------------------------------------------------------------------
# Fixture: patch path constants in BOTH core.constants AND
# core.installer.collector (which has its own local bindings from
# `from core.constants import ...`).
# ---------------------------------------------------------------------------

@pytest.fixture
def inst_paths(tmp_harness_dir, monkeypatch):
    """Monkeypatch all path constants in core.installer.collector to temp paths.

    The base tmp_harness_dir fixture patches core.constants, but
    core.installer.collector has its own local bindings. This patches those too.
    """
    import core.constants as c
    import core.installer.collector as mod

    monkeypatch.setattr(mod, "BIN_DIR", c.BIN_DIR)
    monkeypatch.setattr(mod, "PID_DIR", c.PID_DIR)
    monkeypatch.setattr(mod, "PID_FILE", c.PID_FILE)
    monkeypatch.setattr(mod, "LOG_DIR", c.LOG_DIR)
    monkeypatch.setattr(mod, "COLLECTOR_LOG_FILE", c.COLLECTOR_LOG_FILE)
    monkeypatch.setattr(mod, "COLLECTOR_BIN", c.COLLECTOR_BIN)
    monkeypatch.setattr(mod, "VENV_DIR", c.VENV_DIR)
    monkeypatch.setattr(mod, "DEFAULT_COLLECTOR_PORT", c.DEFAULT_COLLECTOR_PORT)

    return tmp_harness_dir


# ---------------------------------------------------------------------------
# _is_windows
# ---------------------------------------------------------------------------

class TestIsWindows:
    def test_returns_bool(self):
        result = _is_windows()
        assert isinstance(result, bool)

    def test_matches_os_name(self):
        assert _is_windows() == (os.name == "nt")


# ---------------------------------------------------------------------------
# install_collector
# ---------------------------------------------------------------------------

class TestInstallCollector:
    def test_creates_directories(self, inst_paths):
        """install_collector creates BIN_DIR, PID_DIR, LOG_DIR."""
        import core.constants as c
        # Remove them first to prove install_collector creates them
        for d in (c.BIN_DIR, c.PID_DIR, c.LOG_DIR):
            if d.exists():
                shutil.rmtree(d)

        install_collector("/usr/bin/python3")

        assert c.BIN_DIR.is_dir()
        assert c.PID_DIR.is_dir()
        assert c.LOG_DIR.is_dir()

    def test_creates_directories_idempotent(self, inst_paths):
        """Calling install_collector twice does not raise."""
        install_collector("/usr/bin/python3")
        install_collector("/usr/bin/python3")

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_writes_unix_launcher(self, inst_paths):
        """On Unix, install_collector writes a script with shebang at COLLECTOR_BIN."""
        import core.constants as c
        python_cmd = "/opt/venv/bin/python3"

        install_collector(python_cmd)

        assert c.COLLECTOR_BIN.is_file()
        content = c.COLLECTOR_BIN.read_text()
        assert content.startswith(f"#!{python_cmd}\n")
        assert "runpy.run_module" in content
        assert "core.collector" in content

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_launcher_is_executable(self, inst_paths):
        """The launcher script has execute permissions set."""
        import core.constants as c
        install_collector("/usr/bin/python3")

        mode = c.COLLECTOR_BIN.stat().st_mode
        assert mode & stat.S_IXUSR  # owner execute
        assert mode & stat.S_IXGRP  # group execute
        assert mode & stat.S_IXOTH  # other execute

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_launcher_sets_sys_path(self, inst_paths):
        """The launcher script adds the package root to sys.path."""
        import core.constants as c
        install_collector("/usr/bin/python3")

        content = c.COLLECTOR_BIN.read_text()
        assert "sys.path.insert" in content
        assert "_pkg_root" in content

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_launcher_contains_python_cmd(self, inst_paths):
        """The shebang uses the exact python_cmd provided."""
        import core.constants as c
        custom_python = "/home/user/.arize/harness/venv/bin/python3"
        install_collector(custom_python)

        content = c.COLLECTOR_BIN.read_text()
        assert custom_python in content


class TestWriteWindowsLauncher:
    def test_writes_cmd_file(self, inst_paths):
        """_write_windows_launcher creates a .cmd file next to COLLECTOR_BIN."""
        import core.constants as c
        import core.installer.collector as mod

        # Ensure bin dir exists
        c.BIN_DIR.mkdir(parents=True, exist_ok=True)

        _write_windows_launcher("C:\\Python39\\python.exe")

        cmd_path = c.COLLECTOR_BIN.with_suffix(".cmd")
        assert cmd_path.is_file()
        content = cmd_path.read_text()
        assert "@echo off" in content
        assert "C:\\Python39\\python.exe" in content
        assert "-m core.collector" in content


class TestWriteUnixLauncher:
    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_writes_script(self, inst_paths):
        """_write_unix_launcher creates the script file."""
        import core.constants as c
        c.BIN_DIR.mkdir(parents=True, exist_ok=True)

        _write_unix_launcher("/usr/bin/python3")

        assert c.COLLECTOR_BIN.is_file()
        content = c.COLLECTOR_BIN.read_text()
        assert content.startswith("#!/usr/bin/python3\n")


# ---------------------------------------------------------------------------
# start_collector
# ---------------------------------------------------------------------------

class TestStartCollector:
    def test_delegates_to_collector_ctl(self, inst_paths, monkeypatch):
        """start_collector calls core.collector_ctl.collector_start."""
        mock_start = MagicMock(return_value=True)
        monkeypatch.setattr("core.collector_ctl.collector_start", mock_start)

        result = start_collector()
        assert result is True
        mock_start.assert_called_once()

    def test_returns_false_on_failure(self, inst_paths, monkeypatch):
        """start_collector returns False when collector_start returns False."""
        mock_start = MagicMock(return_value=False)
        monkeypatch.setattr("core.collector_ctl.collector_start", mock_start)

        result = start_collector()
        assert result is False


# ---------------------------------------------------------------------------
# stop_collector
# ---------------------------------------------------------------------------

class TestStopCollector:
    def test_delegates_to_collector_ctl(self, inst_paths, monkeypatch):
        """stop_collector calls core.collector_ctl.collector_stop."""
        mock_stop = MagicMock(return_value="stopped")
        monkeypatch.setattr("core.collector_ctl.collector_stop", mock_stop)
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )

        result = stop_collector()
        assert result is True
        mock_stop.assert_called_once()

    def test_returns_true_when_stopped(self, inst_paths, monkeypatch):
        """stop_collector returns True when the process is confirmed stopped."""
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock(return_value="stopped"))
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )

        assert stop_collector() is True

    def test_returns_false_when_still_running(self, inst_paths, monkeypatch):
        """stop_collector returns False when the process is still alive after stop."""
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock(return_value="stopped"))
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("running", 12345, "127.0.0.1:4318")),
        )

        assert stop_collector() is False


# ---------------------------------------------------------------------------
# collector_status
# ---------------------------------------------------------------------------

class TestCollectorStatus:
    def test_returns_dict_with_expected_keys(self, inst_paths, monkeypatch):
        """collector_status returns a dict with running, pid, port, healthy keys."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        monkeypatch.setattr(
            "core.installer.collector._health_check",
            MagicMock(return_value=False),
        )

        result = collector_status()
        assert set(result.keys()) == {"running", "pid", "port", "healthy"}

    def test_stopped_status(self, inst_paths, monkeypatch):
        """When collector is stopped, returns running=False, pid=None, healthy=False."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        monkeypatch.setattr(
            "core.installer.collector._health_check",
            MagicMock(return_value=False),
        )

        result = collector_status()
        assert result["running"] is False
        assert result["pid"] is None
        assert result["port"] == 4318
        assert result["healthy"] is False

    def test_running_and_healthy(self, inst_paths, monkeypatch):
        """When collector is running and healthy, returns appropriate values."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("running", 12345, "127.0.0.1:4318")),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        monkeypatch.setattr(
            "core.installer.collector._health_check",
            MagicMock(return_value=True),
        )

        result = collector_status()
        assert result["running"] is True
        assert result["pid"] == 12345
        assert result["port"] == 4318
        assert result["healthy"] is True

    def test_running_but_unhealthy(self, inst_paths, monkeypatch):
        """When collector is running but health check fails."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("running", 12345, "127.0.0.1:4318")),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        monkeypatch.setattr(
            "core.installer.collector._health_check",
            MagicMock(return_value=False),
        )

        result = collector_status()
        assert result["running"] is True
        assert result["pid"] == 12345
        assert result["healthy"] is False

    def test_stopped_skips_health_check(self, inst_paths, monkeypatch):
        """When collector is stopped, health check is NOT called."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        mock_health = MagicMock(return_value=False)
        monkeypatch.setattr("core.installer.collector._health_check", mock_health)

        result = collector_status()
        assert result["healthy"] is False
        mock_health.assert_not_called()

    def test_pid_is_none_when_stopped(self, inst_paths, monkeypatch):
        """Even if ctl_status returns a pid with 'stopped', pid should be None."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", 999, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )

        result = collector_status()
        assert result["pid"] is None

    def test_custom_port(self, inst_paths, monkeypatch):
        """Status returns whatever port _resolve_host_port gives."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("0.0.0.0", 9999)),
        )

        result = collector_status()
        assert result["port"] == 9999

    def test_value_types(self, inst_paths, monkeypatch):
        """Verify return value types match the docstring contract."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("running", 42, "127.0.0.1:4318")),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )
        monkeypatch.setattr(
            "core.installer.collector._health_check",
            MagicMock(return_value=True),
        )

        result = collector_status()
        assert isinstance(result["running"], bool)
        assert isinstance(result["pid"], int)
        assert isinstance(result["port"], int)
        assert isinstance(result["healthy"], bool)


# ---------------------------------------------------------------------------
# uninstall_collector
# ---------------------------------------------------------------------------

class TestUninstallCollector:
    def test_stops_collector(self, inst_paths, monkeypatch):
        """uninstall_collector calls stop_collector."""
        mock_stop = MagicMock(return_value="stopped")
        monkeypatch.setattr("core.collector_ctl.collector_stop", mock_stop)
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        uninstall_collector()
        mock_stop.assert_called_once()

    def test_removes_launcher_scripts(self, inst_paths, monkeypatch):
        """uninstall_collector removes COLLECTOR_BIN and .cmd variant."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        # Create both launcher scripts
        c.COLLECTOR_BIN.write_text("#!/usr/bin/env python3\n")
        c.COLLECTOR_BIN.with_suffix(".cmd").write_text("@echo off\n")

        uninstall_collector()

        assert not c.COLLECTOR_BIN.exists()
        assert not c.COLLECTOR_BIN.with_suffix(".cmd").exists()

    def test_removes_pid_file(self, inst_paths, monkeypatch):
        """uninstall_collector removes PID file."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        c.PID_FILE.write_text("12345\n")
        uninstall_collector()
        assert not c.PID_FILE.exists()

    def test_removes_log_file(self, inst_paths, monkeypatch):
        """uninstall_collector removes collector log file."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        c.COLLECTOR_LOG_FILE.write_text("some log\n")
        uninstall_collector()
        assert not c.COLLECTOR_LOG_FILE.exists()

    def test_removes_venv_directory(self, inst_paths, monkeypatch):
        """uninstall_collector removes venv directory."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        venv = c.VENV_DIR
        venv.mkdir(parents=True, exist_ok=True)
        (venv / "bin").mkdir()
        (venv / "bin" / "python3").write_text("fake")

        uninstall_collector()
        assert not venv.exists()

    def test_cleans_empty_directories(self, inst_paths, monkeypatch):
        """uninstall_collector removes empty PID_DIR, LOG_DIR, BIN_DIR."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        # Ensure dirs exist and are empty (remove pre-created files)
        for d in (c.PID_DIR, c.LOG_DIR, c.BIN_DIR):
            d.mkdir(parents=True, exist_ok=True)
            # Remove any files in the dirs
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()

        uninstall_collector()

        assert not c.PID_DIR.exists()
        assert not c.LOG_DIR.exists()
        assert not c.BIN_DIR.exists()

    def test_preserves_nonempty_directories(self, inst_paths, monkeypatch):
        """uninstall_collector does NOT remove dirs that contain other files."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        # Put an unrelated file in BIN_DIR
        (c.BIN_DIR / "other-tool").write_text("keep me")

        uninstall_collector()

        # BIN_DIR should still exist because it has other-tool
        assert c.BIN_DIR.is_dir()
        assert (c.BIN_DIR / "other-tool").exists()

    def test_idempotent(self, inst_paths, monkeypatch):
        """Calling uninstall_collector twice does not raise."""
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        uninstall_collector()
        uninstall_collector()  # should not raise

    def test_handles_missing_venv(self, inst_paths, monkeypatch):
        """uninstall_collector does not fail if venv doesn't exist."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        assert not c.VENV_DIR.exists()
        uninstall_collector()  # should not raise


# ---------------------------------------------------------------------------
# _remove_file helper
# ---------------------------------------------------------------------------

class TestRemoveFile:
    def test_removes_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        _remove_file(f)
        assert not f.exists()

    def test_ignores_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.txt"
        _remove_file(f)  # should not raise

    def test_ignores_oserror(self, tmp_path, monkeypatch):
        """_remove_file catches OSError from unlink."""
        f = tmp_path / "test.txt"
        f.write_text("hello")
        monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=OSError("perm")))
        _remove_file(f)  # should not raise


# ---------------------------------------------------------------------------
# _remove_empty_dir helper
# ---------------------------------------------------------------------------

class TestRemoveEmptyDir:
    def test_removes_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        _remove_empty_dir(d)
        assert not d.exists()

    def test_preserves_nonempty_dir(self, tmp_path):
        d = tmp_path / "notempty"
        d.mkdir()
        (d / "file.txt").write_text("keep")
        _remove_empty_dir(d)
        assert d.is_dir()

    def test_ignores_nonexistent_dir(self, tmp_path):
        d = tmp_path / "nope"
        _remove_empty_dir(d)  # should not raise

    def test_ignores_oserror(self, tmp_path, monkeypatch):
        d = tmp_path / "locked"
        d.mkdir()
        monkeypatch.setattr(Path, "rmdir", MagicMock(side_effect=OSError("busy")))
        _remove_empty_dir(d)  # should not raise


# ---------------------------------------------------------------------------
# Integration: install then uninstall lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.skipif(os.name == "nt", reason="Unix-only test")
    def test_install_then_uninstall(self, inst_paths, monkeypatch):
        """Full lifecycle: install creates launcher, uninstall cleans it up."""
        import core.constants as c
        monkeypatch.setattr("core.collector_ctl.collector_stop", MagicMock())
        monkeypatch.setattr("core.collector_ctl.collector_status", MagicMock(return_value=("stopped", None, None)))

        # Install
        install_collector("/usr/bin/python3")
        assert c.COLLECTOR_BIN.is_file()
        assert c.COLLECTOR_BIN.stat().st_mode & stat.S_IXUSR

        # Uninstall
        uninstall_collector()
        assert not c.COLLECTOR_BIN.exists()

    def test_status_when_not_running(self, inst_paths, monkeypatch):
        """collector_status returns sensible dict even when nothing is running."""
        monkeypatch.setattr(
            "core.collector_ctl.collector_status",
            MagicMock(return_value=("stopped", None, None)),
        )
        monkeypatch.setattr(
            "core.installer.collector._resolve_host_port",
            MagicMock(return_value=("127.0.0.1", 4318)),
        )

        result = collector_status()
        assert result == {
            "running": False,
            "pid": None,
            "port": 4318,
            "healthy": False,
        }
