"""Tests for claude-code-tracing/install.py — install/uninstall module."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to tmp_path so all file writes land in a temp dir.

    Also patches the module-level constants in install.py and core.setup that
    derive from Path.home() so they point at the temp tree.
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    # Patch INSTALL_DIR / VENV_DIR / CONFIG_FILE in core.setup
    import core.setup as setup_mod

    install_dir = tmp_path / ".arize" / "harness"
    venv_dir = install_dir / "venv"
    config_file = install_dir / "config.yaml"

    monkeypatch.setattr(setup_mod, "INSTALL_DIR", install_dir)
    monkeypatch.setattr(setup_mod, "VENV_DIR", venv_dir)
    monkeypatch.setattr(setup_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(setup_mod, "BIN_DIR", install_dir / "bin")
    monkeypatch.setattr(setup_mod, "RUN_DIR", install_dir / "run")
    monkeypatch.setattr(setup_mod, "LOG_DIR", install_dir / "logs")
    monkeypatch.setattr(setup_mod, "STATE_DIR", install_dir / "state")

    # Patch CONFIG_FILE in core.config so load_config/save_config use tmp
    import core.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(config_file))

    # Patch SETTINGS_FILE in the install module's constants
    settings_file = tmp_path / ".claude" / "settings.json"

    # We need to patch both the constants module and the install module's reference
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-code-tracing"))
    import constants as claude_constants
    import install as claude_install

    monkeypatch.setattr(claude_constants, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(claude_install, "SETTINGS_FILE", settings_file)

    # Create the harness plugin dir so harness_dir() resolves
    plugin_dir = install_dir / "claude-code-tracing"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    return tmp_path


def _fake_stdout():
    """Non-tty stdout to suppress ANSI codes."""
    return type(
        "FakeOut",
        (),
        {
            "isatty": lambda self: False,
            "write": lambda self, s: None,
            "flush": lambda self: None,
        },
    )()


PHOENIX_BACKEND = ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""})
ARIZE_BACKEND = (
    "arize",
    {"endpoint": "otlp.arize.com:443", "api_key": "test-key", "space_id": "test-space"},
)


def _mock_prompts(monkeypatch, backend=None):
    """Patch prompt functions on the install module (where they're bound after import)."""
    import install as claude_install

    if backend is None:
        backend = PHOENIX_BACKEND

    monkeypatch.setattr(
        claude_install,
        "prompt_backend",
        lambda: backend,
    )
    monkeypatch.setattr(claude_install, "prompt_project_name", lambda default: default)
    monkeypatch.setattr(claude_install, "prompt_user_id", lambda: "")
    monkeypatch.setattr("sys.stdout", _fake_stdout())


class TestFreshInstall:
    """Fresh install with no existing config."""

    @pytest.mark.parametrize(
        "backend,expected_target",
        [
            (PHOENIX_BACKEND, "phoenix"),
            (ARIZE_BACKEND, "arize"),
        ],
        ids=["phoenix", "arize"],
    )
    def test_fresh_install_creates_config_and_hooks(self, fake_home, monkeypatch, backend, expected_target):
        """With no existing config, install() prompts and writes config.yaml + settings.json."""
        import install as claude_install

        _mock_prompts(monkeypatch, backend=backend)

        claude_install.install(with_skills=False)

        # Check config.yaml was written
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        assert config_file.exists()
        config = yaml.safe_load(config_file.read_text())
        assert config["backend"]["target"] == expected_target
        assert config["harnesses"]["claude-code"]["project_name"] == "claude-code"

        # Check settings.json has plugin + 9 hook events
        settings_file = fake_home / ".claude" / "settings.json"
        assert settings_file.exists()
        settings = json.loads(settings_file.read_text())

        assert len(settings.get("plugins", [])) == 1
        assert settings["plugins"][0]["type"] == "local"

        hooks = settings.get("hooks", {})
        assert len(hooks) == 9

        env = settings.get("env", {})
        assert env.get("ARIZE_TRACE_ENABLED") == "true"
        assert env.get("ARIZE_PROJECT_NAME") == "claude-code"


class TestIdempotent:
    """Re-install is idempotent — no duplicate hooks."""

    def test_double_install_no_duplicates(self, fake_home, monkeypatch):
        """Running install() twice does not duplicate hooks or plugins."""
        import install as claude_install

        _mock_prompts(monkeypatch)

        claude_install.install(with_skills=False)
        claude_install.install(with_skills=False)

        settings_file = fake_home / ".claude" / "settings.json"
        settings = json.loads(settings_file.read_text())

        # Still exactly 1 plugin
        assert len(settings["plugins"]) == 1

        # Still exactly 1 hook entry per event
        for event, entries in settings["hooks"].items():
            assert len(entries) == 1, f"Event {event} has {len(entries)} entries"


class TestUninstall:
    """Uninstall removes hooks and harness entry."""

    def test_uninstall_removes_hooks_and_config(self, fake_home, monkeypatch):
        """Uninstall removes hooks, plugin, and harness entry from config.yaml."""
        import install as claude_install

        _mock_prompts(monkeypatch)

        claude_install.install(with_skills=False)
        claude_install.uninstall()

        # settings.json should have no hooks and no plugins
        settings_file = fake_home / ".claude" / "settings.json"
        settings = json.loads(settings_file.read_text())
        assert "hooks" not in settings
        assert "plugins" not in settings

        # config.yaml should have no claude-code entry
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config = yaml.safe_load(config_file.read_text())
        harnesses = config.get("harnesses", {})
        assert "claude-code" not in harnesses

    def test_uninstall_preserves_third_party_hooks(self, fake_home, monkeypatch):
        """Uninstall keeps hooks that don't belong to us."""
        import install as claude_install

        _mock_prompts(monkeypatch)

        claude_install.install(with_skills=False)

        # Inject a third-party hook into SessionStart
        settings_file = fake_home / ".claude" / "settings.json"
        settings = json.loads(settings_file.read_text())
        third_party = {"hooks": [{"type": "command", "command": "/usr/local/bin/my-hook"}]}
        settings["hooks"]["SessionStart"].append(third_party)
        # Also add a completely separate event
        settings["hooks"]["CustomEvent"] = [
            {"hooks": [{"type": "command", "command": "/usr/local/bin/other"}]}
        ]
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")

        claude_install.uninstall()

        settings = json.loads(settings_file.read_text())
        hooks = settings.get("hooks", {})

        # Third-party hook in SessionStart survives
        assert "SessionStart" in hooks
        assert len(hooks["SessionStart"]) == 1
        assert hooks["SessionStart"][0]["hooks"][0]["command"] == "/usr/local/bin/my-hook"

        # CustomEvent survives
        assert "CustomEvent" in hooks
        assert hooks["CustomEvent"][0]["hooks"][0]["command"] == "/usr/local/bin/other"


class TestDryRun:
    """Dry-run mode should not write files."""

    def test_dry_run_no_files_written(self, fake_home, monkeypatch):
        """With ARIZE_DRY_RUN=true, install() logs but does not write files."""
        import install as claude_install

        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        _mock_prompts(monkeypatch)

        claude_install.install(with_skills=False)

        settings_file = fake_home / ".claude" / "settings.json"
        assert not settings_file.exists()

        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        assert not config_file.exists()
