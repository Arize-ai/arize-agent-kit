"""Tests for gemini_tracing constants and hook handler contract.

Parallels tests/test_copilot_hook.py. This file tests:
1. The gemini_tracing.constants module values (EVENTS, HARNESS_NAME, paths, etc.)
2. The core.constants HARNESSES["gemini"] entry
3. Package importability
4. Handler function signatures (once handlers exist)
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# gemini_tracing package importability
# ---------------------------------------------------------------------------


class TestPackageImportable:
    """gemini_tracing package and subpackages are importable."""

    def test_import_gemini_tracing(self):
        import gemini_tracing  # noqa: F401

    def test_import_gemini_tracing_constants(self):
        import gemini_tracing.constants  # noqa: F401

    def test_import_gemini_tracing_hooks(self):
        import gemini_tracing.hooks  # noqa: F401


# ---------------------------------------------------------------------------
# gemini_tracing.constants contract
# ---------------------------------------------------------------------------


class TestGeminiConstants:
    """Verify all constants in gemini_tracing.constants match the spec."""

    def test_harness_name(self):
        from gemini_tracing.constants import HARNESS_NAME

        assert HARNESS_NAME == "gemini"

    def test_settings_dir_is_path(self):
        from gemini_tracing.constants import SETTINGS_DIR

        assert isinstance(SETTINGS_DIR, Path)

    def test_settings_dir_ends_with_dot_gemini(self):
        from gemini_tracing.constants import SETTINGS_DIR

        assert SETTINGS_DIR.name == ".gemini"

    def test_settings_file_is_path(self):
        from gemini_tracing.constants import SETTINGS_FILE

        assert isinstance(SETTINGS_FILE, Path)

    def test_settings_file_name(self):
        from gemini_tracing.constants import SETTINGS_FILE

        assert SETTINGS_FILE.name == "settings.json"

    def test_settings_file_under_settings_dir(self):
        from gemini_tracing.constants import SETTINGS_DIR, SETTINGS_FILE

        assert SETTINGS_FILE.parent == SETTINGS_DIR

    def test_hook_name(self):
        from gemini_tracing.constants import HOOK_NAME

        assert HOOK_NAME == "arize-tracing"

    def test_hook_timeout_ms(self):
        from gemini_tracing.constants import HOOK_TIMEOUT_MS

        assert HOOK_TIMEOUT_MS == 30000

    def test_events_is_dict(self):
        from gemini_tracing.constants import EVENTS

        assert isinstance(EVENTS, dict)

    def test_events_has_exactly_8_entries(self):
        from gemini_tracing.constants import EVENTS

        assert len(EVENTS) == 8, f"Expected 8 events, got {len(EVENTS)}: {list(EVENTS.keys())}"

    def test_events_keys(self):
        from gemini_tracing.constants import EVENTS

        expected_keys = {
            "SessionStart",
            "SessionEnd",
            "BeforeAgent",
            "AfterAgent",
            "BeforeModel",
            "AfterModel",
            "BeforeTool",
            "AfterTool",
        }
        assert set(EVENTS.keys()) == expected_keys

    def test_events_values_are_strings(self):
        from gemini_tracing.constants import EVENTS

        for event, script in EVENTS.items():
            assert isinstance(script, str), f"EVENTS['{event}'] should be str, got {type(script)}"

    def test_events_values_have_gemini_prefix(self):
        """All entry-point script names should start with 'arize-hook-gemini-'."""
        from gemini_tracing.constants import EVENTS

        for event, script in EVENTS.items():
            assert script.startswith("arize-hook-gemini-"), (
                f"EVENTS['{event}'] = '{script}' should start with 'arize-hook-gemini-'"
            )

    @pytest.mark.parametrize(
        "event,expected_script",
        [
            ("SessionStart", "arize-hook-gemini-session-start"),
            ("SessionEnd", "arize-hook-gemini-session-end"),
            ("BeforeAgent", "arize-hook-gemini-before-agent"),
            ("AfterAgent", "arize-hook-gemini-after-agent"),
            ("BeforeModel", "arize-hook-gemini-before-model"),
            ("AfterModel", "arize-hook-gemini-after-model"),
            ("BeforeTool", "arize-hook-gemini-before-tool"),
            ("AfterTool", "arize-hook-gemini-after-tool"),
        ],
    )
    def test_event_script_mapping(self, event, expected_script):
        from gemini_tracing.constants import EVENTS

        assert EVENTS[event] == expected_script

    def test_events_order_preserved(self):
        """EVENTS dict preserves insertion order (Session, Agent, Model, Tool)."""
        from gemini_tracing.constants import EVENTS

        keys = list(EVENTS.keys())
        assert keys == [
            "SessionStart",
            "SessionEnd",
            "BeforeAgent",
            "AfterAgent",
            "BeforeModel",
            "AfterModel",
            "BeforeTool",
            "AfterTool",
        ]

    def test_no_excluded_events(self):
        """Intentionally omitted events should not be present."""
        from gemini_tracing.constants import EVENTS

        excluded = {"BeforeToolSelection", "PreCompress", "Notification"}
        for name in excluded:
            assert name not in EVENTS, f"Event '{name}' should not be in EVENTS (intentionally omitted from v1)"


# ---------------------------------------------------------------------------
# core.constants HARNESSES["gemini"] contract
# ---------------------------------------------------------------------------


class TestCoreHarnessesGeminiEntry:
    """Verify core.constants.HARNESSES contains a correct 'gemini' entry."""

    def test_gemini_in_harnesses(self):
        from core.constants import HARNESSES

        assert "gemini" in HARNESSES, "HARNESSES dict should contain a 'gemini' key"

    def test_service_name(self):
        from core.constants import HARNESSES

        assert HARNESSES["gemini"]["service_name"] == "gemini"

    def test_scope_name(self):
        from core.constants import HARNESSES

        assert HARNESSES["gemini"]["scope_name"] == "arize-gemini-plugin"

    def test_default_project_name(self):
        from core.constants import HARNESSES

        assert HARNESSES["gemini"]["default_project_name"] == "gemini"

    def test_state_subdir(self):
        from core.constants import HARNESSES

        assert HARNESSES["gemini"]["state_subdir"] == "gemini"

    def test_default_log_file_is_path(self):
        from core.constants import HARNESSES

        assert isinstance(HARNESSES["gemini"]["default_log_file"], Path)

    def test_default_log_file_name(self):
        from core.constants import HARNESSES

        log_file = HARNESSES["gemini"]["default_log_file"]
        assert log_file.name == "arize-gemini.log"

    def test_default_log_file_in_tmp(self):
        from core.constants import HARNESSES

        log_file = HARNESSES["gemini"]["default_log_file"]
        assert str(log_file).startswith("/tmp")

    def test_has_all_required_keys(self):
        from core.constants import HARNESSES

        required_keys = {"service_name", "scope_name", "default_project_name", "state_subdir", "default_log_file"}
        entry = HARNESSES["gemini"]
        missing = required_keys - set(entry.keys())
        assert not missing, f"HARNESSES['gemini'] missing keys: {missing}"

    def test_state_subdir_matches_key(self):
        """state_subdir should match the harness key, consistent with other harnesses."""
        from core.constants import HARNESSES

        assert HARNESSES["gemini"]["state_subdir"] == "gemini"

    def test_total_harness_count(self):
        """After adding gemini, HARNESSES should have 5 entries."""
        from core.constants import HARNESSES

        assert len(HARNESSES) == 5, f"Expected 5 harnesses, got {len(HARNESSES)}: {list(HARNESSES.keys())}"


# ---------------------------------------------------------------------------
# Handler entry points (will fail until handlers.py is created)
# ---------------------------------------------------------------------------


class TestHandlerEntryPoints:
    """Verify that the 8 handler entry-point functions exist and are callable."""

    def test_session_start_importable(self):
        from gemini_tracing.hooks.handlers import session_start

        assert callable(session_start)

    def test_session_end_importable(self):
        from gemini_tracing.hooks.handlers import session_end

        assert callable(session_end)

    def test_before_agent_importable(self):
        from gemini_tracing.hooks.handlers import before_agent

        assert callable(before_agent)

    def test_after_agent_importable(self):
        from gemini_tracing.hooks.handlers import after_agent

        assert callable(after_agent)

    def test_before_model_importable(self):
        from gemini_tracing.hooks.handlers import before_model

        assert callable(before_model)

    def test_after_model_importable(self):
        from gemini_tracing.hooks.handlers import after_model

        assert callable(after_model)

    def test_before_tool_importable(self):
        from gemini_tracing.hooks.handlers import before_tool

        assert callable(before_tool)

    def test_after_tool_importable(self):
        from gemini_tracing.hooks.handlers import after_tool

        assert callable(after_tool)
