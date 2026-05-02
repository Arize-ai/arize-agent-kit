"""Tests for gemini_tracing install/uninstall logic against a fake home.

Parallels tests/test_install_copilot.py. Gemini hooks are configured in
~/.gemini/settings.json (not .github/hooks like Copilot), so install() writes
to settings.json and uninstall() removes arize entries from it.
"""

from __future__ import annotations

import json

import pytest
import yaml


# ---------------------------------------------------------------------------
# Install module importability
# ---------------------------------------------------------------------------


class TestInstallModuleImportable:
    """gemini_tracing.install is importable with install/uninstall functions."""

    def test_import_install_module(self):
        import gemini_tracing.install  # noqa: F401

    def test_install_function_exists(self):
        from gemini_tracing.install import install

        assert callable(install)

    def test_uninstall_function_exists(self):
        from gemini_tracing.install import uninstall

        assert callable(uninstall)


# ---------------------------------------------------------------------------
# Install writes settings.json
# ---------------------------------------------------------------------------


class TestInstallWritesSettingsJson:
    """install() writes Gemini hook entries to settings.json."""

    def test_settings_json_created(self, tmp_path, monkeypatch):
        """install() creates ~/.gemini/settings.json with hook entries."""
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        # Mock prompts (same pattern as copilot tests)
        monkeypatch.setattr(
            _install,
            "prompt_backend",
            lambda existing_harnesses=None: ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""}),
        )
        monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: {"prompts": True, "tool_details": True, "tool_content": True},
        )
        monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)

        import core.constants as c
        import core.setup as setup_mod

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(setup_mod, "VENV_DIR", tmp_path / ".arize" / "harness" / "venv")
        monkeypatch.setattr(setup_mod, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "BIN_DIR", tmp_path / ".arize" / "harness" / "bin")
        monkeypatch.setattr(setup_mod, "RUN_DIR", tmp_path / ".arize" / "harness" / "run")
        monkeypatch.setattr(setup_mod, "LOG_DIR", tmp_path / ".arize" / "harness" / "logs")
        monkeypatch.setattr(setup_mod, "STATE_DIR", tmp_path / ".arize" / "harness" / "state")

        _install.install()

        assert settings_file.is_file(), "settings.json should be created by install()"

    def test_settings_json_has_hooks_key(self, tmp_path, monkeypatch):
        """settings.json should contain a 'hooks' top-level key."""
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        monkeypatch.setattr(
            _install,
            "prompt_backend",
            lambda existing_harnesses=None: ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""}),
        )
        monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: {"prompts": True, "tool_details": True, "tool_content": True},
        )
        monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)

        import core.constants as c
        import core.setup as setup_mod

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(setup_mod, "VENV_DIR", tmp_path / ".arize" / "harness" / "venv")
        monkeypatch.setattr(setup_mod, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "BIN_DIR", tmp_path / ".arize" / "harness" / "bin")
        monkeypatch.setattr(setup_mod, "RUN_DIR", tmp_path / ".arize" / "harness" / "run")
        monkeypatch.setattr(setup_mod, "LOG_DIR", tmp_path / ".arize" / "harness" / "logs")
        monkeypatch.setattr(setup_mod, "STATE_DIR", tmp_path / ".arize" / "harness" / "state")

        _install.install()

        data = json.loads(settings_file.read_text())
        assert "hooks" in data, "settings.json should contain 'hooks' key"

    def test_all_8_events_in_settings(self, tmp_path, monkeypatch):
        """settings.json hooks should contain entries for all 8 Gemini events."""
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        monkeypatch.setattr(
            _install,
            "prompt_backend",
            lambda existing_harnesses=None: ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""}),
        )
        monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: {"prompts": True, "tool_details": True, "tool_content": True},
        )
        monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)

        import core.constants as c
        import core.setup as setup_mod

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(setup_mod, "VENV_DIR", tmp_path / ".arize" / "harness" / "venv")
        monkeypatch.setattr(setup_mod, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
        monkeypatch.setattr(setup_mod, "BIN_DIR", tmp_path / ".arize" / "harness" / "bin")
        monkeypatch.setattr(setup_mod, "RUN_DIR", tmp_path / ".arize" / "harness" / "run")
        monkeypatch.setattr(setup_mod, "LOG_DIR", tmp_path / ".arize" / "harness" / "logs")
        monkeypatch.setattr(setup_mod, "STATE_DIR", tmp_path / ".arize" / "harness" / "state")

        _install.install()

        data = json.loads(settings_file.read_text())
        hooks = data.get("hooks", {})
        expected_events = {
            "SessionStart",
            "SessionEnd",
            "BeforeAgent",
            "AfterAgent",
            "BeforeModel",
            "AfterModel",
            "BeforeTool",
            "AfterTool",
        }
        for event in expected_events:
            assert event in hooks, f"Event '{event}' missing from settings.json hooks"


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------


class TestUninstallRemovesEntries:
    """uninstall() removes arize entries from settings.json."""

    def test_uninstall_removes_arize_hooks(self, tmp_path, monkeypatch):
        """After uninstall, arize hook entries should be removed from settings.json."""
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        # Pre-seed a settings.json with arize hooks
        settings_dir.mkdir(parents=True, exist_ok=True)
        seed = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "arize-hook-gemini-session-start",
                                "name": "arize-tracing",
                                "timeout": 30000,
                            }
                        ],
                    }
                ]
            }
        }
        settings_file.write_text(json.dumps(seed, indent=2))

        import core.constants as c

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")

        _install.uninstall()

        if settings_file.is_file():
            data = json.loads(settings_file.read_text())
            hooks = data.get("hooks", {})
            # Either the event key is removed or the arize-tracing entries are gone
            for event_name, entries in hooks.items():
                for entry in entries:
                    for hook in entry.get("hooks", []):
                        assert hook.get("name") != "arize-tracing", (
                            f"arize-tracing hook still present in {event_name}"
                        )

    def test_uninstall_is_idempotent(self, tmp_path, monkeypatch):
        """Running uninstall twice succeeds without error."""
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        import core.constants as c

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")

        # First uninstall on non-existent file
        _install.uninstall()
        # Second uninstall should also be fine
        _install.uninstall()


# ---------------------------------------------------------------------------
# Preserve user hooks on uninstall
# ---------------------------------------------------------------------------


class TestUninstallPreservesUserHooks:
    """Uninstall should preserve non-arize hooks in settings.json."""

    def test_preserves_user_hooks(self, tmp_path, monkeypatch):
        import gemini_tracing.constants as gc
        import gemini_tracing.install as _install

        settings_dir = tmp_path / ".gemini"
        settings_file = settings_dir / "settings.json"
        monkeypatch.setattr(gc, "SETTINGS_DIR", settings_dir)
        monkeypatch.setattr(gc, "SETTINGS_FILE", settings_file)

        # Pre-seed with both arize and user hooks
        settings_dir.mkdir(parents=True, exist_ok=True)
        seed = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "my-user-hook", "name": "my-hook"},
                            {
                                "type": "command",
                                "command": "arize-hook-gemini-session-start",
                                "name": "arize-tracing",
                                "timeout": 30000,
                            },
                        ],
                    }
                ]
            }
        }
        settings_file.write_text(json.dumps(seed, indent=2))

        import core.constants as c

        monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
        monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")

        _install.uninstall()

        if settings_file.is_file():
            data = json.loads(settings_file.read_text())
            # User hooks should still be present
            session_start = data.get("hooks", {}).get("SessionStart", [])
            user_hooks = []
            for entry in session_start:
                for hook in entry.get("hooks", []):
                    if hook.get("name") == "my-hook":
                        user_hooks.append(hook)
            assert len(user_hooks) >= 1, "User hooks should be preserved after uninstall"
