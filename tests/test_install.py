"""Tests for install.py — the cross-platform installer."""
import ast
import json
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

# Ensure repo root is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import install


# ---------------------------------------------------------------------------
# Syntax validation
# ---------------------------------------------------------------------------

def test_install_syntax_valid():
    """install.py must parse without syntax errors."""
    source = (REPO_ROOT / "install.py").read_text()
    ast.parse(source)


# ---------------------------------------------------------------------------
# find_python
# ---------------------------------------------------------------------------

def test_find_python_returns_working_interpreter():
    """find_python() should find the current interpreter (or one >=3.9)."""
    result = install.find_python()
    assert result is not None
    assert os.path.isfile(result)


def test_find_python_returns_none_when_no_python(monkeypatch):
    """find_python() returns None if no candidate works."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(returncode=1),
    )
    monkeypatch.setattr("shutil.which", lambda x: None)
    result = install.find_python()
    assert result is None


# ---------------------------------------------------------------------------
# setup_venv
# ---------------------------------------------------------------------------

def test_setup_venv_creates_venv_dir(tmp_path, monkeypatch):
    """setup_venv() calls python -m venv and pip install."""
    venv_dir = tmp_path / "venv"
    monkeypatch.setattr(install, "VENV_DIR", venv_dir)
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        # Create fake venv structure so _venv_pip finds it
        if "-m" in cmd and "venv" in cmd:
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "pip").touch()
            (bin_dir / "python").touch()
        if kw.get("check"):
            return result
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    result = install.setup_venv("/usr/bin/python3", "phoenix")
    assert result is True
    # Should have called venv creation and pip install
    assert any("-m" in str(c) and "venv" in str(c) for c in calls)
    assert any("pip" in str(c) or "install" in str(c) for c in calls)


def test_setup_venv_installs_grpc_for_arize(tmp_path, monkeypatch):
    """setup_venv() installs grpc extras for arize backend."""
    venv_dir = tmp_path / "venv"
    monkeypatch.setattr(install, "VENV_DIR", venv_dir)
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        if "-m" in cmd and "venv" in cmd:
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "pip").touch()
            (bin_dir / "python").touch()
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    install.setup_venv("/usr/bin/python3", "arize")
    # Should have a pip install call with grpcio
    pip_calls = [c for c in calls if "pip" in str(c[0]) if isinstance(c, list)]
    grpc_call = [c for c in pip_calls if any("grpcio" in str(arg) for arg in c)]
    assert len(grpc_call) > 0, "Should install grpcio for arize backend"


# ---------------------------------------------------------------------------
# Config writing
# ---------------------------------------------------------------------------

def test_write_config_produces_valid_yaml(tmp_path, monkeypatch):
    """write_config() writes valid YAML with correct structure."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "test-key",
        "arize_api_key": "",
        "arize_space_id": "",
        "arize_endpoint": "otlp.arize.com:443",
    }
    install.write_config("phoenix", credentials, "claude-code", 4318)

    assert config_file.is_file()
    config = yaml.safe_load(config_file.read_text())
    assert config["collector"]["host"] == "127.0.0.1"
    assert config["collector"]["port"] == 4318
    assert config["backend"]["target"] == "phoenix"
    assert config["backend"]["phoenix"]["endpoint"] == "http://localhost:6006"
    assert config["backend"]["phoenix"]["api_key"] == "test-key"
    assert config["harnesses"]["claude-code"]["project_name"] == "claude-code"


def test_write_config_adds_harness_to_existing(tmp_path, monkeypatch):
    """write_config() only adds harness when config already exists."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)

    # Write initial config
    existing = {
        "collector": {"host": "127.0.0.1", "port": 4318},
        "backend": {"target": "phoenix", "phoenix": {"endpoint": "http://localhost:6006"}},
        "harnesses": {"claude-code": {"project_name": "claude-code"}},
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(existing, f)

    install.write_config("phoenix", {}, "codex")

    config = yaml.safe_load(config_file.read_text())
    # Both harnesses should be present
    assert "claude-code" in config["harnesses"]
    assert "codex" in config["harnesses"]
    # Original backend should be preserved
    assert config["backend"]["target"] == "phoenix"


def test_write_config_fallback_no_yaml(tmp_path, monkeypatch):
    """write_config() writes YAML manually when yaml module unavailable."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)
    monkeypatch.setattr(install, "_load_yaml", lambda: None)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "",
    }
    install.write_config("phoenix", credentials, "claude-code", 4318)

    text = config_file.read_text()
    assert "target:" in text
    assert "phoenix" in text
    assert "claude-code" in text


# ---------------------------------------------------------------------------
# setup_claude
# ---------------------------------------------------------------------------

def test_setup_claude_writes_hooks(tmp_path, monkeypatch):
    """setup_claude() writes correct hook commands to settings.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")

    # Create plugin dir
    plugin_dir = tmp_path / "claude-code-tracing"
    plugin_dir.mkdir()

    # Create claude settings dir
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_file = claude_dir / "settings.json"

    monkeypatch.setattr(install, "Path", _MockPathHome(tmp_path))

    # Write empty settings
    settings_file.write_text("{}")

    # Monkeypatch Path.home() to use tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    install.setup_claude()

    settings = json.loads(settings_file.read_text())

    # Check hooks were written
    assert "hooks" in settings
    for event in install.CLAUDE_HOOK_EVENTS:
        assert event in settings["hooks"], f"Missing hook event: {event}"
        entries = settings["hooks"][event]
        assert len(entries) >= 1
        assert entries[0]["hooks"][0]["type"] == "command"
        assert "arize-hook" in entries[0]["hooks"][0]["command"]

    # Check plugin was registered
    assert "plugins" in settings
    assert any(
        isinstance(p, dict) and "claude-code-tracing" in p.get("path", "")
        for p in settings["plugins"]
    )


def test_setup_claude_idempotent(tmp_path, monkeypatch):
    """setup_claude() doesn't duplicate hooks on second run."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    (tmp_path / "claude-code-tracing").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")

    install.setup_claude()
    install.setup_claude()

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    for event in install.CLAUDE_HOOK_EVENTS:
        assert len(settings["hooks"][event]) == 1, f"Duplicate hooks for {event}"


# ---------------------------------------------------------------------------
# setup_codex
# ---------------------------------------------------------------------------

def test_setup_codex_writes_toml(tmp_path, monkeypatch):
    """setup_codex() writes correct [otel] section to config.toml."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "4318" if "port" in k else "")
    monkeypatch.setattr(install, "_discover_real_codex", lambda: None)
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))

    (tmp_path / "codex-tracing").mkdir()
    (tmp_path / ".codex").mkdir(parents=True)

    install.setup_codex()

    config_text = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[otel]" in config_text
    assert "endpoint" in config_text
    assert "127.0.0.1" in config_text
    assert "notify" in config_text


def test_setup_codex_env_file(tmp_path, monkeypatch):
    """setup_codex() creates env file template."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")
    monkeypatch.setattr(install, "_discover_real_codex", lambda: None)
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))

    (tmp_path / "codex-tracing").mkdir()
    (tmp_path / ".codex").mkdir(parents=True)

    install.setup_codex()

    env_file = tmp_path / ".codex" / "arize-env.sh"
    assert env_file.is_file()
    text = env_file.read_text()
    assert "ARIZE_TRACE_ENABLED" in text


# ---------------------------------------------------------------------------
# setup_cursor
# ---------------------------------------------------------------------------

def test_setup_cursor_writes_hooks_json(tmp_path, monkeypatch):
    """setup_cursor() writes correct hooks.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "4318" if "port" in k else "")

    (tmp_path / "cursor-tracing").mkdir()
    (tmp_path / ".cursor").mkdir(parents=True)

    install.setup_cursor()

    hooks_file = tmp_path / ".cursor" / "hooks.json"
    assert hooks_file.is_file()
    hooks_data = json.loads(hooks_file.read_text())
    assert "hooks" in hooks_data

    for event in install.CURSOR_HOOK_EVENTS:
        assert event in hooks_data["hooks"], f"Missing event: {event}"
        entries = hooks_data["hooks"][event]
        assert len(entries) >= 1
        assert "arize-hook-cursor" in entries[0]["command"]


def test_setup_cursor_merges_existing(tmp_path, monkeypatch):
    """setup_cursor() merges with existing hooks.json without clobbering."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")

    (tmp_path / "cursor-tracing").mkdir()
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True)

    # Write existing hooks
    existing = {
        "version": 1,
        "hooks": {
            "beforeSubmitPrompt": [{"command": "my-existing-hook"}],
        },
    }
    (cursor_dir / "hooks.json").write_text(json.dumps(existing))

    install.setup_cursor()

    hooks_data = json.loads((cursor_dir / "hooks.json").read_text())
    # Existing hook preserved
    commands = [h["command"] for h in hooks_data["hooks"]["beforeSubmitPrompt"]]
    assert "my-existing-hook" in commands
    # Our hook added
    assert any("arize-hook-cursor" in c for c in commands)


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

def test_uninstall_removes_expected_files(tmp_path, monkeypatch):
    """uninstall() removes expected files."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr(install, "CONFIG_FILE", tmp_path / "harness" / "config.yaml")
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "harness" / "venv")
    monkeypatch.setattr(install, "BIN_DIR", tmp_path / "harness" / "bin")
    monkeypatch.setattr(install, "PID_DIR", tmp_path / "harness" / "run")
    monkeypatch.setattr(install, "PID_FILE", tmp_path / "harness" / "run" / "collector.pid")
    monkeypatch.setattr(install, "LOG_DIR", tmp_path / "harness" / "logs")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "harness" / "logs" / "collector.log")
    monkeypatch.setattr(install, "COLLECTOR_BIN", tmp_path / "harness" / "bin" / "arize-collector")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "harness" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(install, "_cfg_delete", lambda k: None)
    monkeypatch.setattr(install, "_venv_bin", lambda n: str(tmp_path / "harness" / "venv" / "bin" / n))
    monkeypatch.setattr(install, "_venv_python", lambda: None)

    # Create structure
    harness = tmp_path / "harness"
    for d in ["bin", "run", "logs", "venv", "state/claude-code", "state/codex", "state/cursor"]:
        (harness / d).mkdir(parents=True, exist_ok=True)
    (harness / "config.yaml").write_text("collector: {}")
    (harness / "bin" / "arize-collector").touch()
    (harness / "run" / "collector.pid").write_text("99999")
    (harness / "logs" / "collector.log").touch()

    install.uninstall()

    assert not harness.exists()


# ---------------------------------------------------------------------------
# CLI arg parsing
# ---------------------------------------------------------------------------

def test_cli_valid_commands():
    """All expected commands are recognized by argparse."""
    for cmd in ["claude", "codex", "cursor", "update", "uninstall"]:
        parser = _make_parser()
        args = parser.parse_args([cmd])
        assert args.command == cmd


def test_cli_unknown_command():
    """Unknown command causes argparse error."""
    parser = _make_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["badcommand"])


def test_cli_with_skills_flag():
    """--with-skills flag is parsed correctly."""
    parser = _make_parser()
    args = parser.parse_args(["claude", "--with-skills"])
    assert args.with_skills is True


def test_cli_branch_flag():
    """--branch flag is parsed correctly."""
    parser = _make_parser()
    args = parser.parse_args(["claude", "--branch", "dev"])
    assert args.branch == "dev"


def test_cli_no_args_shows_error():
    """No args causes error."""
    parser = _make_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def test_info_output(capsys):
    install.info("test message")
    out = capsys.readouterr().out
    assert "test message" in out
    assert "[arize]" in out


def test_err_output(capsys):
    install.err("error message")
    captured = capsys.readouterr()
    assert "error message" in captured.err
    assert "[arize]" in captured.err


def test_confirm_noninteractive(monkeypatch):
    """confirm() returns default when stdin is not a tty."""
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))
    assert install.confirm("test? ", "n") is False
    assert install.confirm("test? ", "y") is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parser():
    """Create the argparse parser matching install.main()."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["claude", "codex", "cursor", "update", "uninstall"])
    parser.add_argument("--with-skills", action="store_true")
    parser.add_argument("--branch", default=None)
    return parser


class _MockPathHome:
    """Helper to mock Path.home() for setup_claude tests."""
    def __init__(self, home_path):
        self._home = home_path
        self._real_path = Path

    def __call__(self, *args, **kwargs):
        return self._real_path(*args, **kwargs)

    def home(self):
        return self._home

    def __getattr__(self, name):
        return getattr(self._real_path, name)
