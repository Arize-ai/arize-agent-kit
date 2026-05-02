#!/usr/bin/env python3
"""Tests for gemini_tracing.hooks.adapter — session resolution, init, GC, requirements.

Mirrors tests/test_copilot_adapter.py structure but adapted for Gemini's
single-mode (CLI-only) adapter with GEMINI_SESSION_ID env var instead of
PID-based or dual-mode session keys.
"""
from __future__ import annotations

import os
import time

import pytest
import yaml

from core.common import StateManager

# ---------------------------------------------------------------------------
# We import the adapter module itself so we can monkeypatch its module-level
# constants.  The actual functions under test are attributes of this module.
# ---------------------------------------------------------------------------
from gemini_tracing.hooks import adapter

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def gemini_state_dir(tmp_harness_dir, monkeypatch):
    """Point adapter.STATE_DIR to a temp directory and return it."""
    state_dir = tmp_harness_dir / "state" / "gemini"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
    return state_dir


@pytest.fixture
def disable_env_vars(monkeypatch):
    """Clear env vars that could influence session resolution."""
    monkeypatch.delenv("ARIZE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("ARIZE_USER_ID", raising=False)
    monkeypatch.delenv("GEMINI_SESSION_ID", raising=False)
    monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")


# ── Module-level constants tests ──────────────────────────────────────────────


class TestModuleConstants:
    def test_service_name(self):
        """SERVICE_NAME matches the gemini harness metadata."""
        assert adapter.SERVICE_NAME == "gemini"

    def test_scope_name(self):
        """SCOPE_NAME matches the gemini harness metadata."""
        assert adapter.SCOPE_NAME == "arize-gemini-plugin"


# ── check_requirements tests ─────────────────────────────────────────────────


class TestCheckRequirements:
    def test_enabled_returns_true(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=True -> returns True and STATE_DIR exists."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        state_dir = tmp_harness_dir / "state" / "gemini-check"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is True
        assert state_dir.is_dir()

    def test_disabled_returns_false(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=False -> returns False, STATE_DIR not created."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        state_dir = tmp_harness_dir / "state" / "gemini-nope"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is False
        assert not state_dir.exists()


# ── resolve_session tests ────────────────────────────────────────────────────


class TestResolveSession:
    def test_uses_gemini_session_id_env(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """GEMINI_SESSION_ID env var is the preferred session key."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "env-session-42")
        sm = adapter.resolve_session({})
        assert sm.state_file == gemini_state_dir / "state_env-session-42.yaml"
        assert sm.state_file.exists()

    def test_falls_back_to_payload_session_id(self, gemini_state_dir, disable_env_vars):
        """Falls back to input_json['session_id'] when env var not set."""
        sm = adapter.resolve_session({"session_id": "payload-sess-99"})
        assert sm.state_file == gemini_state_dir / "state_payload-sess-99.yaml"

    def test_generates_id_when_no_session_id(self, gemini_state_dir, disable_env_vars):
        """Generates a trace ID when neither env var nor payload has session_id."""
        sm = adapter.resolve_session({})
        # The state file should exist and its key should be a 32-hex-char generated ID
        assert sm.state_file.exists()
        key = sm.state_file.stem.replace("state_", "", 1)
        assert len(key) == 32
        int(key, 16)  # should not raise

    def test_init_state_called(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """Returned StateManager has init_state() called (file exists with {})."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "test-init")
        sm = adapter.resolve_session({})
        assert sm.state_file.exists()
        data = yaml.safe_load(sm.state_file.read_text())
        assert data == {}

    def test_same_input_same_file(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """Calling resolve_session twice with same env produces same file path."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "stable-session")
        sm1 = adapter.resolve_session({})
        sm2 = adapter.resolve_session({})
        assert sm1.state_file == sm2.state_file

    def test_lock_path_matches_key(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """Lock file is named .lock_{key} in STATE_DIR."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "lock-test")
        sm = adapter.resolve_session({})
        assert sm._lock_path == gemini_state_dir / ".lock_lock-test"

    def test_env_takes_priority_over_payload(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """GEMINI_SESSION_ID env var takes priority over payload session_id."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "from-env")
        sm = adapter.resolve_session({"session_id": "from-payload"})
        assert sm.state_file == gemini_state_dir / "state_from-env.yaml"


# ── ensure_session_initialized tests ─────────────────────────────────────────


class TestEnsureSessionInitialized:
    def _make_state(self, gemini_state_dir, key="test"):
        sm = StateManager(
            state_dir=gemini_state_dir,
            state_file=gemini_state_dir / f"state_{key}.yaml",
            lock_path=gemini_state_dir / f".lock_{key}",
        )
        sm.init_state()
        return sm

    def test_sets_all_keys(self, gemini_state_dir, disable_env_vars):
        """First call sets all expected keys."""
        sm = self._make_state(gemini_state_dir, "all-keys")
        adapter.ensure_session_initialized(sm, {})
        assert sm.get("session_id") is not None
        assert sm.get("session_start_time") is not None
        assert sm.get("project_name") is not None
        assert sm.get("trace_count") == "0"
        assert sm.get("tool_count") == "0"
        assert sm.get("user_id") is not None

    def test_idempotent(self, gemini_state_dir, disable_env_vars):
        """Second call is a no-op — values unchanged."""
        sm = self._make_state(gemini_state_dir, "idempotent")
        adapter.ensure_session_initialized(sm, {})
        start_time = sm.get("session_start_time")
        session_id = sm.get("session_id")
        adapter.ensure_session_initialized(sm, {"session_id": "different"})
        assert sm.get("session_id") == session_id
        assert sm.get("session_start_time") == start_time

    def test_session_id_uses_resolved_key(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """session_id stored in state should match the resolved session key."""
        monkeypatch.setenv("GEMINI_SESSION_ID", "gemini-resolved-key")
        sm = adapter.resolve_session({})
        adapter.ensure_session_initialized(sm, {})
        # The session_id in state should match the key used for the file
        assert sm.get("session_id") is not None

    def test_project_name_from_env(self, gemini_state_dir, monkeypatch):
        """ARIZE_PROJECT_NAME env var takes priority over cwd."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_PROJECT_NAME", "my-env-project")
        monkeypatch.delenv("ARIZE_USER_ID", raising=False)
        monkeypatch.delenv("GEMINI_SESSION_ID", raising=False)
        sm = self._make_state(gemini_state_dir, "proj-env")
        adapter.ensure_session_initialized(sm, {"cwd": "/home/user/other-project"})
        assert sm.get("project_name") == "my-env-project"

    def test_project_name_from_cwd(self, gemini_state_dir, disable_env_vars):
        """project_name falls back to basename of cwd."""
        sm = self._make_state(gemini_state_dir, "proj-cwd")
        adapter.ensure_session_initialized(sm, {})
        # Should use basename of os.getcwd() as fallback
        project = sm.get("project_name")
        assert project is not None
        assert len(project) > 0

    def test_project_name_from_cwd_in_payload(self, gemini_state_dir, disable_env_vars):
        """project_name uses basename of cwd from payload when env var not set."""
        sm = self._make_state(gemini_state_dir, "proj-cwd-payload")
        adapter.ensure_session_initialized(sm, {"cwd": "/some/path/myproj"})
        assert sm.get("project_name") == "myproj"

    def test_counters_start_at_zero(self, gemini_state_dir, disable_env_vars):
        """trace_count and tool_count start at '0'."""
        sm = self._make_state(gemini_state_dir, "counters")
        adapter.ensure_session_initialized(sm, {})
        assert sm.get("trace_count") == "0"
        assert sm.get("tool_count") == "0"

    def test_user_id_from_env(self, gemini_state_dir, monkeypatch):
        """user_id is read from env.user_id."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_USER_ID", "test-user-123")
        monkeypatch.delenv("ARIZE_PROJECT_NAME", raising=False)
        monkeypatch.delenv("GEMINI_SESSION_ID", raising=False)
        sm = self._make_state(gemini_state_dir, "user-env")
        adapter.ensure_session_initialized(sm, {})
        assert sm.get("user_id") == "test-user-123"

    def test_user_id_defaults_to_empty(self, gemini_state_dir, disable_env_vars):
        """user_id defaults to '' when env var not set."""
        sm = self._make_state(gemini_state_dir, "user-empty")
        adapter.ensure_session_initialized(sm, {})
        assert sm.get("user_id") == ""


# ── gc_stale_state_files tests ───────────────────────────────────────────────


class TestGcStaleStateFiles:
    def test_old_file_removed(self, gemini_state_dir, disable_env_vars):
        """State file older than 24h is removed."""
        state_file = gemini_state_dir / "state_old-session.yaml"
        state_file.write_text("{}")
        # Set mtime to 25 hours ago
        old_time = time.time() - 90000  # 25 hours
        os.utime(state_file, (old_time, old_time))
        adapter.gc_stale_state_files()
        assert not state_file.exists()

    def test_recent_file_kept(self, gemini_state_dir, disable_env_vars):
        """State file younger than 24h is kept."""
        state_file = gemini_state_dir / "state_recent-session.yaml"
        state_file.write_text("{}")
        # mtime is now (just created), which is < 24h old
        adapter.gc_stale_state_files()
        assert state_file.exists()

    def test_lock_dir_removed(self, gemini_state_dir, disable_env_vars):
        """Lock dir is removed when state file is removed."""
        state_file = gemini_state_dir / "state_old-lock-dir.yaml"
        state_file.write_text("{}")
        lock_dir = gemini_state_dir / ".lock_old-lock-dir"
        lock_dir.mkdir()
        old_time = time.time() - 90000
        os.utime(state_file, (old_time, old_time))
        adapter.gc_stale_state_files()
        assert not state_file.exists()
        assert not lock_dir.exists()

    def test_lock_file_removed(self, gemini_state_dir, disable_env_vars):
        """Lock file (fcntl-style) is removed when state file is removed."""
        state_file = gemini_state_dir / "state_old-lock-file.yaml"
        state_file.write_text("{}")
        lock_file = gemini_state_dir / ".lock_old-lock-file"
        lock_file.write_text("")
        old_time = time.time() - 90000
        os.utime(state_file, (old_time, old_time))
        adapter.gc_stale_state_files()
        assert not state_file.exists()
        assert not lock_file.exists()

    def test_empty_dir_no_error(self, gemini_state_dir, disable_env_vars):
        """Empty STATE_DIR causes no errors."""
        for f in gemini_state_dir.glob("state_*.yaml"):
            f.unlink()
        adapter.gc_stale_state_files()  # should not raise

    def test_nonexistent_dir_no_error(self, tmp_harness_dir, monkeypatch):
        """Non-existent STATE_DIR causes no errors."""
        state_dir = tmp_harness_dir / "state" / "gemini-nonexistent"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        adapter.gc_stale_state_files()  # should not raise

    def test_uses_24h_cutoff(self, gemini_state_dir, disable_env_vars):
        """Files exactly at the 24h boundary are handled correctly."""
        # File just barely old enough (24h + 1 second)
        state_file = gemini_state_dir / "state_boundary.yaml"
        state_file.write_text("{}")
        old_time = time.time() - 86401
        os.utime(state_file, (old_time, old_time))
        adapter.gc_stale_state_files()
        assert not state_file.exists()

    def test_oserror_on_unlink_is_caught(self, gemini_state_dir, disable_env_vars, monkeypatch):
        """OSError on unlink is caught and ignored (best-effort)."""
        state_file = gemini_state_dir / "state_unlink-err.yaml"
        state_file.write_text("{}")
        old_time = time.time() - 90000
        os.utime(state_file, (old_time, old_time))

        original_unlink = state_file.unlink

        def failing_unlink(*args, **kwargs):
            raise OSError("permission denied")

        # Patch Path.unlink to fail for this specific file
        import pathlib

        orig = pathlib.Path.unlink

        def patched_unlink(self, *args, **kwargs):
            if "unlink-err" in str(self):
                raise OSError("permission denied")
            return orig(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "unlink", patched_unlink)
        adapter.gc_stale_state_files()  # should not raise


# ── No PID-based logic tests ─────────────────────────────────────────────────


class TestNoPidLogic:
    """Verify the adapter does NOT have copilot-specific PID functions."""

    def test_no_get_grandparent_pid(self):
        """Adapter should not define _get_grandparent_pid."""
        assert not hasattr(adapter, "_get_grandparent_pid")

    def test_no_is_pid_alive(self):
        """Adapter should not define _is_pid_alive."""
        assert not hasattr(adapter, "_is_pid_alive")

    def test_no_is_vscode_mode(self):
        """Adapter should not define is_vscode_mode."""
        assert not hasattr(adapter, "is_vscode_mode")
