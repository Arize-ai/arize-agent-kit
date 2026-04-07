"""Tests for install.py — the cross-platform installer."""
import ast
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock, call

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
# Venv helpers
# ---------------------------------------------------------------------------

def test_venv_python_finds_unix_python(tmp_path, monkeypatch):
    """_venv_python() finds bin/python in venv."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").touch()
    monkeypatch.setattr(install, "VENV_DIR", venv)
    assert install._venv_python() == str(venv / "bin" / "python")


def test_venv_python_returns_none_if_missing(tmp_path, monkeypatch):
    """_venv_python() returns None when no python in venv."""
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "nonexistent")
    assert install._venv_python() is None


def test_venv_bin_unix(tmp_path, monkeypatch):
    """_venv_bin() returns correct path on Unix."""
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr("os.name", "posix")
    result = install._venv_bin("arize-hook-session-start")
    assert result == str(tmp_path / "venv" / "bin" / "arize-hook-session-start")


def test_venv_bin_windows(tmp_path, monkeypatch):
    """_venv_bin() returns Scripts/*.exe path on Windows."""
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr("os.name", "nt")
    result = install._venv_bin("arize-hook-session-start")
    assert result == str(tmp_path / "venv" / "Scripts" / "arize-hook-session-start.exe")


def test_venv_pip_finds_pip(tmp_path, monkeypatch):
    """_venv_pip() finds bin/pip in venv."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "pip").touch()
    monkeypatch.setattr(install, "VENV_DIR", venv)
    assert install._venv_pip() == str(venv / "bin" / "pip")


def test_venv_pip_returns_none(tmp_path, monkeypatch):
    """_venv_pip() returns None when pip not in venv."""
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "nonexistent")
    assert install._venv_pip() is None


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
    pip_calls = [c for c in calls if isinstance(c, list) and "pip" in str(c[0])]
    grpc_call = [c for c in pip_calls if any("grpcio" in str(arg) for arg in c)]
    assert len(grpc_call) > 0, "Should install grpcio for arize backend"


def test_setup_venv_returns_false_on_venv_failure(tmp_path, monkeypatch):
    """setup_venv() returns False when venv creation fails."""
    import subprocess as sp
    venv_dir = tmp_path / "venv"
    monkeypatch.setattr(install, "VENV_DIR", venv_dir)
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)

    def mock_run(cmd, **kw):
        if "-m" in cmd and "venv" in cmd:
            raise sp.SubprocessError("venv creation failed")
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    result = install.setup_venv("/usr/bin/python3", "phoenix")
    assert result is False


def test_setup_venv_skips_if_already_has_packages(tmp_path, monkeypatch):
    """setup_venv() returns True early if venv already has required packages."""
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").touch()
    monkeypatch.setattr(install, "VENV_DIR", venv_dir)
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    result = install.setup_venv("/usr/bin/python3", "phoenix")
    assert result is True
    # Should NOT have called venv creation — just the check
    assert not any("-m" in str(c) and "venv" in str(c) for c in calls)


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


def test_write_config_arize_backend(tmp_path, monkeypatch):
    """write_config() correctly writes arize backend credentials."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "",
        "arize_api_key": "my-api-key",
        "arize_space_id": "my-space-id",
        "arize_endpoint": "otlp.arize.com:443",
    }
    install.write_config("arize", credentials, "codex", 5000)

    config = yaml.safe_load(config_file.read_text())
    assert config["backend"]["target"] == "arize"
    assert config["backend"]["arize"]["api_key"] == "my-api-key"
    assert config["backend"]["arize"]["space_id"] == "my-space-id"
    assert config["collector"]["port"] == 5000
    assert config["harnesses"]["codex"]["project_name"] == "codex"


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


def test_write_config_no_harness(tmp_path, monkeypatch):
    """write_config() works when harness_name is None."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "",
        "arize_api_key": "",
        "arize_space_id": "",
        "arize_endpoint": "otlp.arize.com:443",
    }
    install.write_config("phoenix", credentials, None, 4318)

    config = yaml.safe_load(config_file.read_text())
    assert config["harnesses"] == {}


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
    # Verify the fallback YAML is parseable
    config = yaml.safe_load(text)
    assert config["backend"]["target"] == "phoenix"
    assert config["collector"]["port"] == 4318


def test_write_config_fallback_no_harness(tmp_path, monkeypatch):
    """write_config() fallback produces valid YAML when no harness given."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)
    monkeypatch.setattr(install, "_load_yaml", lambda: None)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "",
    }
    install.write_config("phoenix", credentials, None, 4318)

    text = config_file.read_text()
    # Must be valid YAML — no indented {} under harnesses
    config = yaml.safe_load(text)
    assert config is not None
    # harnesses: with nothing under it parses as None in YAML
    assert config.get("harnesses") is None or config.get("harnesses") == {}


def test_write_config_file_permissions(tmp_path, monkeypatch):
    """write_config() creates config with restrictive permissions."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(install, "CONFIG_FILE", config_file)

    credentials = {
        "phoenix_endpoint": "http://localhost:6006",
        "phoenix_api_key": "",
        "arize_api_key": "",
        "arize_space_id": "",
        "arize_endpoint": "otlp.arize.com:443",
    }
    install.write_config("phoenix", credentials, "claude-code", 4318)

    if os.name != "nt":
        mode = oct(config_file.stat().st_mode & 0o777)
        assert mode == "0o600", f"Config should have 0o600 permissions, got {mode}"


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
    # Plugin should also not be duplicated
    plugin_entries = [
        p for p in settings["plugins"]
        if isinstance(p, dict) and "claude-code-tracing" in p.get("path", "")
    ]
    assert len(plugin_entries) == 1, "Plugin should not be duplicated"


def test_setup_claude_preserves_existing_settings(tmp_path, monkeypatch):
    """setup_claude() preserves other settings in settings.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    (tmp_path / "claude-code-tracing").mkdir()
    (tmp_path / ".claude").mkdir()
    existing = {"theme": "dark", "plugins": ["/some/other/plugin"]}
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(existing))

    install.setup_claude()

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark"
    assert "/some/other/plugin" in settings["plugins"]


def test_setup_claude_exits_if_plugin_missing(tmp_path, monkeypatch):
    """setup_claude() exits if plugin dir not found."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Do NOT create claude-code-tracing dir

    with pytest.raises(SystemExit):
        install.setup_claude()


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
    assert "PHOENIX_ENDPOINT" in text
    assert "ARIZE_API_KEY" in text


def test_setup_codex_preserves_existing_notify(tmp_path, monkeypatch):
    """setup_codex() updates existing notify line in config.toml."""
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
    (tmp_path / ".codex" / "config.toml").write_text('notify = ["old-command"]\n')

    install.setup_codex()

    config_text = (tmp_path / ".codex" / "config.toml").read_text()
    # Old notify should be replaced, not duplicated
    assert config_text.count("notify =") == 1
    assert "arize-hook-codex-notify" in config_text


def test_setup_codex_exits_if_plugin_missing(tmp_path, monkeypatch):
    """setup_codex() exits if codex-tracing dir not found."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    with pytest.raises(SystemExit):
        install.setup_codex()


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


def test_setup_cursor_idempotent(tmp_path, monkeypatch):
    """setup_cursor() doesn't duplicate hooks on second run."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")

    (tmp_path / "cursor-tracing").mkdir()
    (tmp_path / ".cursor").mkdir(parents=True)

    install.setup_cursor()
    install.setup_cursor()

    hooks_data = json.loads((tmp_path / ".cursor" / "hooks.json").read_text())
    for event in install.CURSOR_HOOK_EVENTS:
        assert len(hooks_data["hooks"][event]) == 1, f"Duplicate hooks for {event}"


def test_setup_cursor_creates_backup(tmp_path, monkeypatch):
    """setup_cursor() creates backup of existing hooks.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "state")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")

    (tmp_path / "cursor-tracing").mkdir()
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True)
    original = {"version": 1, "hooks": {"stop": [{"command": "other"}]}}
    (cursor_dir / "hooks.json").write_text(json.dumps(original))

    install.setup_cursor()

    backup = cursor_dir / "hooks.json.bak"
    assert backup.is_file()
    assert json.loads(backup.read_text()) == original


def test_setup_cursor_exits_if_plugin_missing(tmp_path, monkeypatch):
    """setup_cursor() exits if cursor-tracing dir not found."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    with pytest.raises(SystemExit):
        install.setup_cursor()


def test_setup_cursor_creates_state_dir(tmp_path, monkeypatch):
    """setup_cursor() creates the cursor state directory."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    state_base = tmp_path / "state"
    monkeypatch.setattr(install, "STATE_BASE_DIR", state_base)
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "logs" / "collector.log")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")

    (tmp_path / "cursor-tracing").mkdir()
    (tmp_path / ".cursor").mkdir(parents=True)

    install.setup_cursor()

    assert (state_base / "cursor").is_dir()


# ---------------------------------------------------------------------------
# Collector lifecycle
# ---------------------------------------------------------------------------

def test_is_process_alive_own_pid():
    """_is_process_alive() returns True for our own process."""
    assert install._is_process_alive(os.getpid()) is True


def test_is_process_alive_invalid_pid():
    """_is_process_alive() returns False for invalid PIDs."""
    assert install._is_process_alive(0) is False
    assert install._is_process_alive(-1) is False


def test_is_process_alive_nonexistent_pid():
    """_is_process_alive() returns False for a PID that doesn't exist."""
    # Use a very high PID that is unlikely to exist
    assert install._is_process_alive(99999999) is False


def test_health_check_returns_false_on_no_server():
    """_health_check() returns False when no server is listening."""
    assert install._health_check(port=19999, timeout=0.1) is False


def test_stop_collector_no_pidfile(tmp_path, monkeypatch):
    """stop_collector() does nothing when PID file doesn't exist."""
    monkeypatch.setattr(install, "PID_FILE", tmp_path / "nonexistent.pid")
    # Should not raise
    install.stop_collector()


def test_stop_collector_stale_pid(tmp_path, monkeypatch):
    """stop_collector() cleans up stale PID file."""
    pid_file = tmp_path / "collector.pid"
    pid_file.write_text("99999999")  # non-existent PID
    monkeypatch.setattr(install, "PID_FILE", pid_file)

    install.stop_collector()
    assert not pid_file.exists()


def test_stop_collector_invalid_pid_file(tmp_path, monkeypatch):
    """stop_collector() handles invalid PID file content."""
    pid_file = tmp_path / "collector.pid"
    pid_file.write_text("not-a-number")
    monkeypatch.setattr(install, "PID_FILE", pid_file)

    install.stop_collector()
    assert not pid_file.exists()


# ---------------------------------------------------------------------------
# write_collector_launcher
# ---------------------------------------------------------------------------

def test_write_collector_launcher_unix(tmp_path, monkeypatch):
    """write_collector_launcher() creates executable Python launcher on Unix."""
    monkeypatch.setattr(install, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(install, "COLLECTOR_BIN", tmp_path / "bin" / "arize-collector")
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr("os.name", "posix")

    # No venv python, so falls back to python_cmd
    install.write_collector_launcher("/usr/bin/python3")

    launcher = tmp_path / "bin" / "arize-collector"
    assert launcher.is_file()
    text = launcher.read_text()
    # Should use Python shebang, not bash
    assert "#!/usr/bin/python3" in text
    assert "runpy" in text
    assert "collector.py" in text
    # Should NOT reference bash
    assert "bash" not in text
    # Check executable
    assert launcher.stat().st_mode & 0o755


# ---------------------------------------------------------------------------
# collect_backend_credentials
# ---------------------------------------------------------------------------

def test_collect_backend_from_arize_env(monkeypatch):
    """collect_backend_credentials() detects Arize AX from env vars."""
    monkeypatch.setenv("ARIZE_API_KEY", "test-key")
    monkeypatch.setenv("ARIZE_SPACE_ID", "test-space")
    monkeypatch.setenv("ARIZE_OTLP_ENDPOINT", "custom.endpoint:443")

    backend, creds, port = install.collect_backend_credentials()
    assert backend == "arize"
    assert creds["arize_api_key"] == "test-key"
    assert creds["arize_space_id"] == "test-space"
    assert creds["arize_endpoint"] == "custom.endpoint:443"


def test_collect_backend_from_phoenix_env(monkeypatch):
    """collect_backend_credentials() detects Phoenix from env vars."""
    # Ensure Arize vars are not set
    monkeypatch.delenv("ARIZE_API_KEY", raising=False)
    monkeypatch.delenv("ARIZE_SPACE_ID", raising=False)
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://my-phoenix:6006")
    monkeypatch.setenv("PHOENIX_API_KEY", "phoenix-key")

    backend, creds, port = install.collect_backend_credentials()
    assert backend == "phoenix"
    assert creds["phoenix_endpoint"] == "http://my-phoenix:6006"
    assert creds["phoenix_api_key"] == "phoenix-key"


def test_collect_backend_defaults_phoenix_non_interactive(monkeypatch):
    """collect_backend_credentials() defaults to phoenix when non-interactive."""
    monkeypatch.delenv("ARIZE_API_KEY", raising=False)
    monkeypatch.delenv("ARIZE_SPACE_ID", raising=False)
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))
    monkeypatch.setattr(install, "_can_open_tty", lambda: False)

    backend, creds, port = install.collect_backend_credentials()
    assert backend == "phoenix"
    assert port == 4318


# ---------------------------------------------------------------------------
# _detect_shell_profile
# ---------------------------------------------------------------------------

def test_detect_shell_profile_zshrc(tmp_path, monkeypatch):
    """_detect_shell_profile() finds .zshrc."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".zshrc").touch()
    assert install._detect_shell_profile() == tmp_path / ".zshrc"


def test_detect_shell_profile_bashrc(tmp_path, monkeypatch):
    """_detect_shell_profile() finds .bashrc when .zshrc missing."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".bashrc").touch()
    assert install._detect_shell_profile() == tmp_path / ".bashrc"


def test_detect_shell_profile_none(tmp_path, monkeypatch):
    """_detect_shell_profile() returns None when no profile found."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert install._detect_shell_profile() is None


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


def test_uninstall_handles_missing_dir(tmp_path, monkeypatch):
    """uninstall() handles gracefully when install dir doesn't exist."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "nonexistent")
    monkeypatch.setattr(install, "CONFIG_FILE", tmp_path / "nonexistent" / "config.yaml")
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "nonexistent" / "venv")
    monkeypatch.setattr(install, "BIN_DIR", tmp_path / "nonexistent" / "bin")
    monkeypatch.setattr(install, "PID_DIR", tmp_path / "nonexistent" / "run")
    monkeypatch.setattr(install, "PID_FILE", tmp_path / "nonexistent" / "run" / "collector.pid")
    monkeypatch.setattr(install, "LOG_DIR", tmp_path / "nonexistent" / "logs")
    monkeypatch.setattr(install, "COLLECTOR_LOG_FILE", tmp_path / "nonexistent" / "logs" / "collector.log")
    monkeypatch.setattr(install, "COLLECTOR_BIN", tmp_path / "nonexistent" / "bin" / "arize-collector")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "nonexistent" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(install, "_cfg_delete", lambda k: None)
    monkeypatch.setattr(install, "_venv_bin", lambda n: "")
    monkeypatch.setattr(install, "_venv_python", lambda: None)

    # Should not raise
    install.uninstall()


# ---------------------------------------------------------------------------
# _cleanup_claude_config
# ---------------------------------------------------------------------------

def test_cleanup_claude_removes_hooks(tmp_path, monkeypatch):
    """_cleanup_claude_config() removes arize hooks from settings.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "harness" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "confirm", lambda *a, **kw: True)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "/path/to/arize-hook-session-start"}]},
                {"hooks": [{"type": "command", "command": "other-hook"}]},
            ],
        },
        "plugins": [
            {"type": "local", "path": str(tmp_path / "harness" / "claude-code-tracing")},
            "/some/other/plugin",
        ],
    }
    (claude_dir / "settings.json").write_text(json.dumps(settings))

    install._cleanup_claude_config()

    result = json.loads((claude_dir / "settings.json").read_text())
    # Arize hooks removed, other hooks kept
    session_hooks = result.get("hooks", {}).get("SessionStart", [])
    for entry in session_hooks:
        for h in entry.get("hooks", []):
            assert "arize" not in h.get("command", "").lower()
    # Other plugin kept
    assert "/some/other/plugin" in result["plugins"]


# ---------------------------------------------------------------------------
# _uninstall_cursor
# ---------------------------------------------------------------------------

def test_uninstall_cursor_removes_hooks(tmp_path, monkeypatch):
    """_uninstall_cursor() removes arize hooks from hooks.json."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "harness" / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "harness" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_delete", lambda k: None)
    monkeypatch.setattr(install, "_venv_bin", lambda n: f"/path/to/{n}")

    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    hooks_data = {
        "version": 1,
        "hooks": {
            "beforeSubmitPrompt": [
                {"command": "/path/to/arize-hook-cursor"},
                {"command": "my-other-hook"},
            ],
            "stop": [{"command": "/path/to/arize-hook-cursor"}],
        },
    }
    (cursor_dir / "hooks.json").write_text(json.dumps(hooks_data))

    install._uninstall_cursor()

    hooks_file = cursor_dir / "hooks.json"
    result = json.loads(hooks_file.read_text())
    # Arize hook removed, other hook kept
    commands = [h["command"] for h in result["hooks"].get("beforeSubmitPrompt", [])]
    assert "my-other-hook" in commands
    assert "/path/to/arize-hook-cursor" not in commands
    # stop event should be gone (only had arize hook)
    assert "stop" not in result["hooks"]


def test_uninstall_cursor_removes_file_if_empty(tmp_path, monkeypatch):
    """_uninstall_cursor() removes hooks.json when only arize hooks exist."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "harness" / "venv")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "harness" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_delete", lambda k: None)
    monkeypatch.setattr(install, "_venv_bin", lambda n: f"/path/to/{n}")

    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    hooks_data = {
        "version": 1,
        "hooks": {
            "beforeSubmitPrompt": [{"command": "/path/to/arize-hook-cursor"}],
        },
    }
    (cursor_dir / "hooks.json").write_text(json.dumps(hooks_data))

    install._uninstall_cursor()

    # File should be deleted since no hooks remain
    assert not (cursor_dir / "hooks.json").exists()


# ---------------------------------------------------------------------------
# install_repo
# ---------------------------------------------------------------------------

def test_install_repo_uses_git_clone(tmp_path, monkeypatch):
    """install_repo() uses git clone when git is available."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/git" if x == "git" else None)

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        # Create the dir to simulate clone
        (tmp_path / "harness").mkdir(parents=True, exist_ok=True)
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    install.install_repo()

    clone_calls = [c for c in calls if "clone" in str(c)]
    assert len(clone_calls) == 1
    assert "--depth" in clone_calls[0]


def test_install_repo_git_pull_existing(tmp_path, monkeypatch):
    """install_repo() does git pull when .git dir exists."""
    harness = tmp_path / "harness"
    (harness / ".git").mkdir(parents=True)
    monkeypatch.setattr(install, "INSTALL_DIR", harness)

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    install.install_repo()

    pull_calls = [c for c in calls if "pull" in str(c)]
    assert len(pull_calls) == 1


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


def test_warn_output(capsys):
    install.warn("warning message")
    out = capsys.readouterr().out
    assert "warning message" in out
    assert "[arize]" in out


def test_err_output(capsys):
    install.err("error message")
    captured = capsys.readouterr()
    assert "error message" in captured.err
    assert "[arize]" in captured.err


def test_header_output(capsys):
    install.header("Section Title")
    out = capsys.readouterr().out
    assert "Section Title" in out


def test_confirm_noninteractive(monkeypatch):
    """confirm() returns default when stdin is not a tty and no /dev/tty."""
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))
    # Mock _tty_input to return empty (simulating no tty available)
    monkeypatch.setattr(install, "_tty_input", lambda prompt: "")
    assert install.confirm("test? ", "n") is False
    assert install.confirm("test? ", "y") is True


def test_supports_color_no_color_env(monkeypatch):
    """_supports_color() returns False when NO_COLOR is set."""
    monkeypatch.setenv("NO_COLOR", "1")
    assert install._supports_color() is False


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------

def test_claude_hook_events_match_pyproject():
    """CLAUDE_HOOK_EVENTS matches the entry points in pyproject.toml."""
    expected_events = {
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
        "Stop", "SubagentStop", "Notification", "PermissionRequest", "SessionEnd",
    }
    assert set(install.CLAUDE_HOOK_EVENTS.keys()) == expected_events


def test_cursor_hook_events_count():
    """CURSOR_HOOK_EVENTS has all 12 events."""
    assert len(install.CURSOR_HOOK_EVENTS) == 12


def test_hook_entry_point_naming():
    """All Claude hook entry points follow arize-hook-* naming convention."""
    for event, name in install.CLAUDE_HOOK_EVENTS.items():
        assert name.startswith("arize-hook-"), f"Entry point {name} doesn't follow convention"


# ---------------------------------------------------------------------------
# update_install
# ---------------------------------------------------------------------------

def test_update_exits_if_not_installed(tmp_path, monkeypatch):
    """update_install() exits if INSTALL_DIR doesn't exist."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "nonexistent")
    with pytest.raises(SystemExit):
        install.update_install()


def test_update_pulls_and_reinstalls(tmp_path, monkeypatch):
    """update_install() does git pull and pip reinstall when .git exists."""
    harness = tmp_path / "harness"
    (harness / ".git").mkdir(parents=True)
    (harness / "core").mkdir()
    (harness / "core" / "collector.py").touch()
    venv = harness / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").touch()
    (venv / "bin" / "pip").touch()
    monkeypatch.setattr(install, "INSTALL_DIR", harness)
    monkeypatch.setattr(install, "VENV_DIR", venv)
    monkeypatch.setattr(install, "PID_FILE", tmp_path / "collector.pid")
    monkeypatch.setattr(install, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(install, "COLLECTOR_BIN", tmp_path / "bin" / "arize-collector")
    monkeypatch.setattr(install, "_health_check", lambda **kw: False)
    monkeypatch.setattr(install, "_cfg_get", lambda k: "")
    monkeypatch.setattr("os.name", "posix")

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: MagicMock(pid=12345))

    install.update_install()

    # Should have done git pull and pip install
    assert any("pull" in str(c) for c in calls)
    assert any("install" in str(c) for c in calls)


# ---------------------------------------------------------------------------
# start_collector
# ---------------------------------------------------------------------------

def test_start_collector_already_running(monkeypatch):
    """start_collector() returns True if collector is already healthy."""
    monkeypatch.setattr(install, "_cfg_get", lambda k: "4318")
    monkeypatch.setattr(install, "_health_check", lambda **kw: True)

    assert install.start_collector() is True


def test_start_collector_via_entry_point(tmp_path, monkeypatch):
    """start_collector() tries the venv entry point first."""
    monkeypatch.setattr(install, "_cfg_get", lambda k: "4318")
    monkeypatch.setattr(install, "_health_check", lambda **kw: False)
    monkeypatch.setattr(install, "PID_FILE", tmp_path / "collector.pid")

    ctl_path = tmp_path / "venv" / "bin" / "arize-collector-ctl"
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    ctl_path.touch()
    monkeypatch.setattr(install, "VENV_DIR", tmp_path / "venv")
    monkeypatch.setattr("os.name", "posix")

    calls = []

    def mock_run(cmd, **kw):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("subprocess.run", mock_run)

    result = install.start_collector()
    assert result is True
    assert any("arize-collector-ctl" in str(c) for c in calls)


# ---------------------------------------------------------------------------
# _uninstall_codex preserves non-arize notify
# ---------------------------------------------------------------------------

def test_uninstall_codex_preserves_non_arize_notify(tmp_path, monkeypatch):
    """_uninstall_codex() only removes arize-related notify lines."""
    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "harness")
    monkeypatch.setattr(install, "STATE_BASE_DIR", tmp_path / "harness" / "state")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(install, "_cfg_delete", lambda k: None)
    monkeypatch.setattr(install, "_venv_bin", lambda n: f"/path/to/{n}")

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    # Write config with a non-arize notify line
    config_text = 'notify = ["my-custom-hook"]\n\n[other]\nkey = "value"\n'
    (codex_dir / "config.toml").write_text(config_text)

    install._uninstall_codex()

    result = (codex_dir / "config.toml").read_text()
    # Non-arize notify should be preserved
    assert 'notify = ["my-custom-hook"]' in result


# ---------------------------------------------------------------------------
# tarball extraction security
# ---------------------------------------------------------------------------

def test_tarball_rejects_path_traversal(tmp_path, monkeypatch):
    """_install_repo_tarball() skips members with path traversal."""
    import tarfile
    import io

    monkeypatch.setattr(install, "INSTALL_DIR", tmp_path / "install")
    (tmp_path / "install").mkdir()

    # Create a tarball with a path traversal member
    tar_path = tmp_path / "test.tar.gz"
    with tarfile.open(str(tar_path), "w:gz") as tf:
        # Normal file
        info = tarfile.TarInfo(name="repo/normal.txt")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"hello"))
        # Path traversal attempt
        info2 = tarfile.TarInfo(name="repo/../../../etc/evil.txt")
        info2.size = 4
        tf.addfile(info2, io.BytesIO(b"evil"))

    monkeypatch.setattr("urllib.request.urlretrieve", lambda url, path: None)

    # Manually call with the real tarball
    import shutil
    shutil.copy2(str(tar_path), str(tmp_path / "download.tar.gz"))
    # Patch urlretrieve to copy our test tarball
    def fake_retrieve(url, dest):
        shutil.copy2(str(tar_path), dest)
    monkeypatch.setattr("urllib.request.urlretrieve", fake_retrieve)

    install._install_repo_tarball(tarball_url="http://example.com/test.tar.gz")

    # Normal file should be extracted
    assert (tmp_path / "install" / "normal.txt").is_file()
    # Path traversal file should NOT exist anywhere outside install dir
    assert not (tmp_path / "etc" / "evil.txt").exists()


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
