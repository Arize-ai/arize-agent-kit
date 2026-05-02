"""Tests for Gemini entry points in pyproject.toml.

Mirrors tests/test_copilot_install.py — verifies that all required
Gemini hook entry points and the setup wizard entry point are declared
in pyproject.toml [project.scripts].
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


# ---------------------------------------------------------------------------
# pyproject.toml entry point tests
# ---------------------------------------------------------------------------


class TestGeminiEntryPoints:
    """Verify all 9 Gemini entry points (8 hooks + 1 setup) in pyproject.toml."""

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

    def test_install_module_importable(self):
        """The install module should be importable."""
        from gemini_tracing.install import install, main, uninstall

        assert callable(install)
        assert callable(uninstall)
        assert callable(main)
