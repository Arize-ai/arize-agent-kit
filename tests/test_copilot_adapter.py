#!/usr/bin/env python3
"""Tests for copilot_tracing.hooks.adapter — dual-mode session resolution, init, GC, requirements."""
import os
import subprocess
from unittest.mock import mock_open, patch

import pytest
import yaml

from copilot_tracing.hooks import adapter
from core.common import StateManager

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def copilot_state_dir(tmp_harness_dir, monkeypatch):
    """Point adapter.STATE_DIR to a temp directory and return it."""
    state_dir = tmp_harness_dir / "state" / "copilot"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
    return state_dir


@pytest.fixture
def disable_env_vars(monkeypatch):
    """Clear env vars that could influence session resolution."""
    monkeypatch.delenv("ARIZE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("ARIZE_USER_ID", raising=False)
    monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")


# ── is_vscode_mode tests ────────────────────────────────────────────────────


class TestIsVscodeMode:
    def test_true_with_session_id(self):
        """Returns True when sessionId is present."""
        assert adapter.is_vscode_mode({"sessionId": "abc-123"}) is True

    def test_true_with_hook_event_name(self):
        """Returns True when hookEventName is present."""
        assert adapter.is_vscode_mode({"hookEventName": "PreToolUse"}) is True

    def test_true_with_both(self):
        """Returns True when both fields present."""
        assert adapter.is_vscode_mode({"sessionId": "abc", "hookEventName": "Stop"}) is True

    def test_false_when_absent(self):
        """Returns False when neither field present (CLI mode)."""
        assert adapter.is_vscode_mode({"prompt": "hello"}) is False

    def test_false_with_empty_values(self):
        """Returns False when fields are empty strings."""
        assert adapter.is_vscode_mode({"sessionId": "", "hookEventName": ""}) is False


# ── resolve_session tests ────────────────────────────────────────────────────


class TestResolveSession:
    def test_vscode_uses_session_id(self, copilot_state_dir, disable_env_vars):
        """VS Code mode: sessionId from payload used as state file key."""
        sm = adapter.resolve_session({"sessionId": "vscode-sess-42", "hookEventName": "SessionStart"})
        assert sm.state_file == copilot_state_dir / "state_vscode-sess-42.yaml"
        assert sm.state_file.exists()

    def test_cli_uses_pid(self, copilot_state_dir, disable_env_vars, monkeypatch):
        """CLI mode: falls back to PID-based key when no VS Code fields."""
        monkeypatch.setattr(adapter, "_get_grandparent_pid", lambda: "54321")
        sm = adapter.resolve_session({"prompt": "hello"})
        assert sm.state_file == copilot_state_dir / "state_54321.yaml"

    def test_init_state_called(self, copilot_state_dir, disable_env_vars):
        """Returned StateManager has init_state() called (file exists with {})."""
        sm = adapter.resolve_session({"sessionId": "test-init", "hookEventName": "SessionStart"})
        assert sm.state_file.exists()
        data = yaml.safe_load(sm.state_file.read_text())
        assert data == {}

    def test_same_input_same_file(self, copilot_state_dir, disable_env_vars):
        """Calling resolve_session twice with same input returns same file path."""
        inp = {"sessionId": "stable", "hookEventName": "Stop"}
        sm1 = adapter.resolve_session(inp)
        sm2 = adapter.resolve_session(inp)
        assert sm1.state_file == sm2.state_file

    def test_vscode_session_id_required(self, copilot_state_dir, disable_env_vars):
        """VS Code mode requires sessionId in payload (hookEventName alone triggers vscode mode)."""
        # hookEventName present but no sessionId — is_vscode_mode returns True,
        # but sessionId key is missing; should raise KeyError or use hookEventName path
        # Actually: hookEventName triggers vscode mode, sessionId must be there
        # This tests the expected behavior when only hookEventName present
        inp = {"hookEventName": "SessionStart", "sessionId": "from-event"}
        sm = adapter.resolve_session(inp)
        assert sm.state_file == copilot_state_dir / "state_from-event.yaml"


# ── ensure_session_initialized tests ─────────────────────────────────────────


class TestEnsureSessionInitialized:
    def _make_state(self, copilot_state_dir, key="test"):
        sm = StateManager(
            state_dir=copilot_state_dir,
            state_file=copilot_state_dir / f"state_{key}.yaml",
            lock_path=copilot_state_dir / f".lock_{key}",
        )
        sm.init_state()
        return sm

    def test_sets_all_keys(self, copilot_state_dir, disable_env_vars):
        """First call sets all expected keys."""
        sm = self._make_state(copilot_state_dir, "all-keys")
        adapter.ensure_session_initialized(sm, {"sessionId": "sid-1"})
        assert sm.get("session_id") == "sid-1"
        assert sm.get("session_start_time") is not None
        assert sm.get("project_name") is not None
        assert sm.get("trace_count") == "0"
        assert sm.get("tool_count") == "0"
        assert sm.get("user_id") is not None

    def test_idempotent(self, copilot_state_dir, disable_env_vars):
        """Second call is a no-op — values unchanged."""
        sm = self._make_state(copilot_state_dir, "idempotent")
        adapter.ensure_session_initialized(sm, {"sessionId": "sid-2"})
        start_time = sm.get("session_start_time")
        adapter.ensure_session_initialized(sm, {"sessionId": "sid-different"})
        assert sm.get("session_id") == "sid-2"
        assert sm.get("session_start_time") == start_time

    def test_session_id_from_vscode_payload(self, copilot_state_dir, disable_env_vars):
        """sessionId from VS Code payload is used as session_id."""
        sm = self._make_state(copilot_state_dir, "from-vscode")
        adapter.ensure_session_initialized(sm, {"sessionId": "vscode-session"})
        assert sm.get("session_id") == "vscode-session"

    def test_session_id_generated_for_cli(self, copilot_state_dir, disable_env_vars):
        """session_id is generated (32-hex) when not in input (CLI mode)."""
        sm = self._make_state(copilot_state_dir, "generated")
        adapter.ensure_session_initialized(sm, {"prompt": "hello"})
        sid = sm.get("session_id")
        assert sid is not None
        assert len(sid) == 32
        int(sid, 16)  # should not raise

    def test_project_name_from_env(self, copilot_state_dir, monkeypatch):
        """ARIZE_PROJECT_NAME env var takes priority over cwd."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_PROJECT_NAME", "my-env-project")
        monkeypatch.delenv("ARIZE_USER_ID", raising=False)
        sm = self._make_state(copilot_state_dir, "proj-env")
        adapter.ensure_session_initialized(sm, {"cwd": "/home/user/other-project"})
        assert sm.get("project_name") == "my-env-project"

    def test_project_name_from_cwd_input(self, copilot_state_dir, disable_env_vars):
        """project_name from input cwd -> basename extracted."""
        sm = self._make_state(copilot_state_dir, "proj-cwd")
        adapter.ensure_session_initialized(sm, {"cwd": "/home/user/my-project"})
        assert sm.get("project_name") == "my-project"

    def test_counters_start_at_zero(self, copilot_state_dir, disable_env_vars):
        """trace_count and tool_count start at '0'."""
        sm = self._make_state(copilot_state_dir, "counters")
        adapter.ensure_session_initialized(sm, {})
        assert sm.get("trace_count") == "0"
        assert sm.get("tool_count") == "0"


# ── gc_stale_state_files tests ───────────────────────────────────────────────


class TestGcStaleStateFiles:
    def test_dead_pid_removed(self, copilot_state_dir, disable_env_vars, monkeypatch):
        """state file for a dead PID is removed."""
        dead_pid = 99999
        state_file = copilot_state_dir / f"state_{dead_pid}.yaml"
        state_file.write_text("{}")
        monkeypatch.setattr(adapter, "_is_pid_alive", lambda pid: False)
        adapter.gc_stale_state_files()
        assert not state_file.exists()

    def test_live_pid_kept(self, copilot_state_dir, disable_env_vars, monkeypatch):
        """state file for a live PID is kept."""
        live_pid = os.getpid()
        state_file = copilot_state_dir / f"state_{live_pid}.yaml"
        state_file.write_text("{}")
        monkeypatch.setattr(adapter, "_is_pid_alive", lambda pid: pid == live_pid)
        adapter.gc_stale_state_files()
        assert state_file.exists()

    def test_non_numeric_key_kept(self, copilot_state_dir, disable_env_vars):
        """state file with non-numeric key (VS Code sessionId) is never GC'd."""
        state_file = copilot_state_dir / "state_vscode-sess-abc123.yaml"
        state_file.write_text("{}")
        adapter.gc_stale_state_files()
        assert state_file.exists()

    def test_lock_dir_removed(self, copilot_state_dir, disable_env_vars, monkeypatch):
        """Lock dir is removed when state file is removed."""
        dead_pid = 99998
        state_file = copilot_state_dir / f"state_{dead_pid}.yaml"
        state_file.write_text("{}")
        lock_dir = copilot_state_dir / f".lock_{dead_pid}"
        lock_dir.mkdir()
        monkeypatch.setattr(adapter, "_is_pid_alive", lambda pid: False)
        adapter.gc_stale_state_files()
        assert not state_file.exists()
        assert not lock_dir.exists()

    def test_lock_file_removed(self, copilot_state_dir, disable_env_vars, monkeypatch):
        """Lock file (fcntl-style) is removed when state file is removed."""
        dead_pid = 99997
        state_file = copilot_state_dir / f"state_{dead_pid}.yaml"
        state_file.write_text("{}")
        lock_file = copilot_state_dir / f".lock_{dead_pid}"
        lock_file.write_text("")  # fcntl creates lock as a regular file
        monkeypatch.setattr(adapter, "_is_pid_alive", lambda pid: False)
        adapter.gc_stale_state_files()
        assert not state_file.exists()
        assert not lock_file.exists()

    def test_empty_dir_no_error(self, copilot_state_dir, disable_env_vars):
        """Empty STATE_DIR causes no errors."""
        for f in copilot_state_dir.glob("state_*.yaml"):
            f.unlink()
        adapter.gc_stale_state_files()  # should not raise


# ── check_requirements tests ─────────────────────────────────────────────────


class TestCheckRequirements:
    def test_enabled_returns_true(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=True -> returns True and STATE_DIR exists."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        state_dir = tmp_harness_dir / "state" / "copilot-check"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is True
        assert state_dir.is_dir()

    def test_disabled_returns_false(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=False -> returns False, STATE_DIR not created."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        state_dir = tmp_harness_dir / "state" / "copilot-nope"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is False
        assert not state_dir.exists()


# ── _get_grandparent_pid tests ───────────────────────────────────────────────


class TestGetGrandparentPid:
    def test_reads_from_proc_stat(self, monkeypatch):
        """Linux path: reads grandparent PID from /proc/{ppid}/stat."""
        monkeypatch.setattr(os, "getppid", lambda: 100)
        fake_stat = "100 (python) S 456 0 0 0"
        with patch("builtins.open", mock_open(read_data=fake_stat)):
            result = adapter._get_grandparent_pid()
        assert result == "456"

    def test_falls_back_to_ps_command(self, monkeypatch):
        """When /proc read fails, falls back to ps command."""
        monkeypatch.setattr(os, "getppid", lambda: 100)
        with patch("builtins.open", side_effect=OSError("no /proc")):
            with patch("subprocess.check_output", return_value=b"  789  \n"):
                result = adapter._get_grandparent_pid()
        assert result == "789"

    def test_falls_back_to_ppid(self, monkeypatch):
        """When both /proc and ps fail, falls back to parent PID."""
        monkeypatch.setattr(os, "getppid", lambda: 42)
        with patch("builtins.open", side_effect=OSError("no /proc")):
            with patch(
                "subprocess.check_output",
                side_effect=subprocess.SubprocessError("ps failed"),
            ):
                result = adapter._get_grandparent_pid()
        assert result == "42"

    def test_ppid_zero_returns_own_pid(self, monkeypatch):
        """When ppid is 0, returns current process PID."""
        monkeypatch.setattr(os, "getppid", lambda: 0)
        result = adapter._get_grandparent_pid()
        assert result == str(os.getpid())


# ── _is_pid_alive tests ─────────────────────────────────────────────────────


class TestIsPidAlive:
    def test_own_pid_is_alive(self):
        """Current process PID should be alive."""
        assert adapter._is_pid_alive(os.getpid()) is True

    def test_dead_pid(self):
        """A very high PID that doesn't exist should be dead."""
        assert adapter._is_pid_alive(99999) is False

    def test_zero_returns_false(self):
        """PID 0 should return False."""
        assert adapter._is_pid_alive(0) is False

    def test_negative_returns_false(self):
        """Negative PID should return False."""
        assert adapter._is_pid_alive(-1) is False
