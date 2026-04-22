"""Tests for copilot-tracing/install.py: install and uninstall of Copilot hooks."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Import helpers (directory name is hyphenated)
# ---------------------------------------------------------------------------


def _load_module(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_constants = _load_module("copilot_constants", REPO_ROOT / "copilot-tracing" / "constants.py")
_install = _load_module("copilot_install", REPO_ROOT / "copilot-tracing" / "install.py")

install = _install.install
uninstall = _install.uninstall


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cwd_tmp(tmp_path, monkeypatch):
    """Set cwd to tmp_path and patch core.setup paths for isolation."""
    monkeypatch.chdir(tmp_path)

    import core.setup as setup_mod

    monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path / ".arize" / "harness")
    monkeypatch.setattr(setup_mod, "VENV_DIR", tmp_path / ".arize" / "harness" / "venv")
    monkeypatch.setattr(setup_mod, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")
    monkeypatch.setattr(setup_mod, "BIN_DIR", tmp_path / ".arize" / "harness" / "bin")
    monkeypatch.setattr(setup_mod, "RUN_DIR", tmp_path / ".arize" / "harness" / "run")
    monkeypatch.setattr(setup_mod, "LOG_DIR", tmp_path / ".arize" / "harness" / "logs")
    monkeypatch.setattr(setup_mod, "STATE_DIR", tmp_path / ".arize" / "harness" / "state")

    import core.constants as c

    monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
    monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.yaml")

    return tmp_path


@pytest.fixture
def hooks_dir(cwd_tmp):
    """Return the .github/hooks directory under the temp cwd."""
    return cwd_tmp / ".github" / "hooks"


# ---------------------------------------------------------------------------
# Install tests
# ---------------------------------------------------------------------------


class TestFreshInstall:
    """Fresh install writes 6 VS Code files + 1 hooks.json with 6 CLI events."""

    def test_vscode_files_created(self, hooks_dir):
        install()
        expected_files = [
            "session-start.json",
            "user-prompt.json",
            "pre-tool.json",
            "post-tool.json",
            "stop.json",
            "subagent-stop.json",
        ]
        for fname in expected_files:
            assert (hooks_dir / fname).is_file(), f"Missing {fname}"

    def test_vscode_file_structure(self, hooks_dir):
        install()
        data = json.loads((hooks_dir / "session-start.json").read_text())
        assert "hooks" in data
        assert len(data["hooks"]) == 1
        hook = data["hooks"][0]
        assert hook["event"] == "SessionStart"
        assert "arize-hook-copilot-session-start" in hook["command"]

    def test_cli_hooks_json_created(self, hooks_dir):
        install()
        assert (hooks_dir / "hooks.json").is_file()

    def test_cli_hooks_json_structure(self, hooks_dir):
        install()
        data = json.loads((hooks_dir / "hooks.json").read_text())
        assert data["version"] == 1
        assert set(data["hooks"].keys()) == {
            "sessionStart",
            "userPromptSubmitted",
            "preToolUse",
            "postToolUse",
            "errorOccurred",
            "sessionEnd",
        }
        for event, entries in data["hooks"].items():
            assert len(entries) == 1
            assert "bash" in entries[0]
            assert "arize-hook-copilot-" in entries[0]["bash"]

    def test_total_file_count(self, hooks_dir):
        install()
        json_files = list(hooks_dir.glob("*.json"))
        assert len(json_files) == 7  # 6 VS Code + 1 hooks.json


class TestConfigEntry:
    """install() writes harnesses.copilot to config.yaml."""

    def test_harness_entry_written(self, cwd_tmp):
        install()
        config_path = cwd_tmp / ".arize" / "harness" / "config.yaml"
        assert config_path.is_file()
        config = yaml.safe_load(config_path.read_text())
        assert config["harnesses"]["copilot"]["project_name"] == "copilot"

    def test_custom_project_name(self, cwd_tmp):
        install(project_name="my-copilot")
        config_path = cwd_tmp / ".arize" / "harness" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert config["harnesses"]["copilot"]["project_name"] == "my-copilot"


class TestIdempotent:
    """Re-install is idempotent — no duplicate entries."""

    def test_vscode_no_duplicates(self, hooks_dir):
        install()
        install()
        data = json.loads((hooks_dir / "session-start.json").read_text())
        assert len(data["hooks"]) == 1

    def test_cli_no_duplicates(self, hooks_dir):
        install()
        install()
        data = json.loads((hooks_dir / "hooks.json").read_text())
        for event, entries in data["hooks"].items():
            assert len(entries) == 1, f"Duplicate entries for CLI event {event}"


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------


class TestUninstall:
    """Uninstall removes all 7 hook files."""

    def test_all_files_removed(self, hooks_dir):
        install()
        assert len(list(hooks_dir.glob("*.json"))) == 7
        uninstall()
        json_files = list(hooks_dir.glob("*.json"))
        assert len(json_files) == 0

    def test_config_entry_removed(self, cwd_tmp):
        install()
        uninstall()
        config_path = cwd_tmp / ".arize" / "harness" / "config.yaml"
        if config_path.is_file():
            config = yaml.safe_load(config_path.read_text())
            harnesses = config.get("harnesses", {})
            assert "copilot" not in harnesses


class TestUninstallPreservesUserHooks:
    """Uninstall on a pre-populated hooks.json preserves unrelated user hooks."""

    def test_preserves_user_cli_hooks(self, hooks_dir):
        install()

        # Add a user hook to hooks.json
        hf = hooks_dir / "hooks.json"
        data = json.loads(hf.read_text())
        data["hooks"]["customEvent"] = [{"bash": "/usr/local/bin/my-hook"}]
        data["hooks"]["sessionStart"].append({"bash": "/usr/local/bin/user-session"})
        hf.write_text(json.dumps(data, indent=2) + "\n")

        uninstall()

        # hooks.json should still exist with user entries
        assert hf.is_file()
        remaining = json.loads(hf.read_text())
        assert "customEvent" in remaining["hooks"]
        assert remaining["hooks"]["customEvent"][0]["bash"] == "/usr/local/bin/my-hook"
        assert len(remaining["hooks"]["sessionStart"]) == 1
        assert remaining["hooks"]["sessionStart"][0]["bash"] == "/usr/local/bin/user-session"

    def test_preserves_user_vscode_hooks(self, hooks_dir):
        install()

        # Add a user hook to a VS Code file
        sf = hooks_dir / "session-start.json"
        data = json.loads(sf.read_text())
        data["hooks"].append({"event": "SessionStart", "command": "/usr/local/bin/user-hook"})
        sf.write_text(json.dumps(data, indent=2) + "\n")

        uninstall()

        # File should still exist with the user hook
        assert sf.is_file()
        remaining = json.loads(sf.read_text())
        assert len(remaining["hooks"]) == 1
        assert remaining["hooks"][0]["command"] == "/usr/local/bin/user-hook"


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


class TestDryRun:
    """Dry-run mode writes nothing."""

    def test_dry_run_no_files(self, hooks_dir, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        install()
        json_files = list(hooks_dir.glob("*.json")) if hooks_dir.exists() else []
        assert len(json_files) == 0

    def test_dry_run_no_config(self, cwd_tmp, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        install()
        config_path = cwd_tmp / ".arize" / "harness" / "config.yaml"
        assert not config_path.is_file()
