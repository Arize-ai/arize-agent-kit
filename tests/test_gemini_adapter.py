"""Tests for gemini_tracing.hooks.adapter — session resolution, init, and requirements.

Parallels tests/test_copilot_adapter.py. Gemini is simpler than Copilot: no
dual-mode (VS Code vs CLI), no PID-based session keys. Gemini provides
GEMINI_SESSION_ID as an env var on every hook invocation.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Adapter module importability
# ---------------------------------------------------------------------------


class TestAdapterImportable:
    """gemini_tracing.hooks.adapter is importable."""

    def test_import_adapter(self):
        from gemini_tracing.hooks import adapter  # noqa: F401


# ---------------------------------------------------------------------------
# resolve_session tests
# ---------------------------------------------------------------------------


class TestResolveSession:
    """Session resolution uses GEMINI_SESSION_ID env var."""

    def test_resolve_session_exists(self):
        from gemini_tracing.hooks.adapter import resolve_session

        assert callable(resolve_session)

    def test_uses_gemini_session_id_env(self, tmp_harness_dir, monkeypatch):
        """resolve_session should use GEMINI_SESSION_ID for the state file key."""
        from gemini_tracing.hooks import adapter

        state_dir = tmp_harness_dir / "state" / "gemini"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("GEMINI_SESSION_ID", "gemini-sess-abc123")
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")

        sm = adapter.resolve_session({})
        assert "gemini-sess-abc123" in str(sm.state_file)
        assert sm.state_file.exists()

    def test_same_session_id_same_file(self, tmp_harness_dir, monkeypatch):
        """Calling resolve_session twice with same GEMINI_SESSION_ID returns same file."""
        from gemini_tracing.hooks import adapter

        state_dir = tmp_harness_dir / "state" / "gemini"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("GEMINI_SESSION_ID", "stable-session")
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")

        sm1 = adapter.resolve_session({})
        sm2 = adapter.resolve_session({})
        assert sm1.state_file == sm2.state_file


# ---------------------------------------------------------------------------
# check_requirements tests
# ---------------------------------------------------------------------------


class TestCheckRequirements:
    """check_requirements gates handler execution."""

    def test_check_requirements_exists(self):
        from gemini_tracing.hooks.adapter import check_requirements

        assert callable(check_requirements)

    def test_enabled_returns_true(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=True -> returns True and STATE_DIR is created."""
        from gemini_tracing.hooks import adapter

        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        state_dir = tmp_harness_dir / "state" / "gemini"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is True
        assert state_dir.is_dir()

    def test_disabled_returns_false(self, tmp_harness_dir, monkeypatch):
        """trace_enabled=False -> returns False, STATE_DIR not created."""
        from gemini_tracing.hooks import adapter

        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        state_dir = tmp_harness_dir / "state" / "gemini-nope"
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        assert adapter.check_requirements() is False
        assert not state_dir.exists()


# ---------------------------------------------------------------------------
# ensure_session_initialized tests
# ---------------------------------------------------------------------------


class TestEnsureSessionInitialized:
    """Session initialization sets expected state keys."""

    def test_ensure_session_initialized_exists(self):
        from gemini_tracing.hooks.adapter import ensure_session_initialized

        assert callable(ensure_session_initialized)
