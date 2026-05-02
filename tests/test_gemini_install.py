"""Tests for Gemini entry points in pyproject.toml.

Parallels tests/test_copilot_install.py — verifies that pyproject.toml declares
the correct entry-point scripts for all 8 Gemini hook events, and that the
referenced handler functions are importable.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


# ---------------------------------------------------------------------------
# pyproject.toml entry point tests
# ---------------------------------------------------------------------------


class TestGeminiEntryPoints:
    """Verify all 8 Gemini hook entry points in pyproject.toml."""

    @pytest.fixture(autouse=True)
    def _load_pyproject(self):
        self.text = PYPROJECT.read_text()

    def test_session_start_entry_point(self):
        assert 'arize-hook-gemini-session-start = "gemini_tracing.hooks.handlers:session_start"' in self.text

    def test_session_end_entry_point(self):
        assert 'arize-hook-gemini-session-end = "gemini_tracing.hooks.handlers:session_end"' in self.text

    def test_before_agent_entry_point(self):
        assert 'arize-hook-gemini-before-agent = "gemini_tracing.hooks.handlers:before_agent"' in self.text

    def test_after_agent_entry_point(self):
        assert 'arize-hook-gemini-after-agent = "gemini_tracing.hooks.handlers:after_agent"' in self.text

    def test_before_model_entry_point(self):
        assert 'arize-hook-gemini-before-model = "gemini_tracing.hooks.handlers:before_model"' in self.text

    def test_after_model_entry_point(self):
        assert 'arize-hook-gemini-after-model = "gemini_tracing.hooks.handlers:after_model"' in self.text

    def test_before_tool_entry_point(self):
        assert 'arize-hook-gemini-before-tool = "gemini_tracing.hooks.handlers:before_tool"' in self.text

    def test_after_tool_entry_point(self):
        assert 'arize-hook-gemini-after-tool = "gemini_tracing.hooks.handlers:after_tool"' in self.text

    def test_setup_entry_point(self):
        assert 'arize-setup-gemini = "core.setup.gemini:main"' in self.text

    def test_exactly_8_hook_entry_points(self):
        """There should be exactly 8 gemini hook entry points."""
        count = self.text.count("arize-hook-gemini-")
        assert count == 8, f"Expected 8 gemini hook entries, got {count}"

    def test_entry_points_match_constants_events(self):
        """Each entry point script name in pyproject.toml should match EVENTS values."""
        from gemini_tracing.constants import EVENTS

        for event_name, script_name in EVENTS.items():
            assert script_name in self.text, (
                f"Entry point script '{script_name}' for event '{event_name}' not found in pyproject.toml"
            )

    def test_entry_points_importable(self):
        """All referenced handler functions should be importable."""
        from gemini_tracing.hooks.handlers import (
            after_agent,
            after_model,
            after_tool,
            before_agent,
            before_model,
            before_tool,
            session_end,
            session_start,
        )

        for fn in [
            session_start,
            session_end,
            before_agent,
            after_agent,
            before_model,
            after_model,
            before_tool,
            after_tool,
        ]:
            assert callable(fn)
