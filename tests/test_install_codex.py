#!/usr/bin/env python3
"""Tests for codex-tracing install/uninstall module."""

from __future__ import annotations

import importlib.util
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers to load the install module from a hyphenated directory
# ---------------------------------------------------------------------------

def _load_codex_install():
    """Import codex-tracing/install.py by file path."""
    install_py = Path(__file__).resolve().parent.parent / "codex-tracing" / "install.py"
    spec = importlib.util.spec_from_file_location("codex_install", install_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codex_install = _load_codex_install()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Redirect all paths to a temp directory.

    Patches:
    - Path.home() -> tmp_path
    - core.setup constants (INSTALL_DIR, CONFIG_FILE, etc.)
    - codex_install constants (CODEX_CONFIG_DIR, etc.)
    - core.constants.CONFIG_FILE (used by config.py)
    """
    install_dir = tmp_path / ".arize" / "harness"
    install_dir.mkdir(parents=True)
    config_file = install_dir / "config.yaml"
    codex_dir = tmp_path / ".codex"
    venv_bin_dir = install_dir / "venv" / "bin"
    venv_bin_dir.mkdir(parents=True)

    # Patch Path.home
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    # Patch core.setup constants
    monkeypatch.setattr("core.setup.INSTALL_DIR", install_dir)
    monkeypatch.setattr("core.setup.CONFIG_FILE", config_file)
    monkeypatch.setattr("core.setup.VENV_DIR", install_dir / "venv")
    monkeypatch.setattr("core.setup.BIN_DIR", install_dir / "bin")
    monkeypatch.setattr("core.setup.RUN_DIR", install_dir / "run")
    monkeypatch.setattr("core.setup.LOG_DIR", install_dir / "logs")
    monkeypatch.setattr("core.setup.STATE_DIR", install_dir / "state")

    # Patch core.constants.CONFIG_FILE and core.config.CONFIG_FILE
    # (config.py imports CONFIG_FILE at module level, binding a local name)
    monkeypatch.setattr("core.constants.CONFIG_FILE", config_file)
    monkeypatch.setattr("core.config.CONFIG_FILE", config_file)

    # Patch the constants in the install module itself
    monkeypatch.setattr(codex_install, "CODEX_CONFIG_DIR", codex_dir)
    monkeypatch.setattr(codex_install, "CODEX_CONFIG_FILE", codex_dir / "config.toml")
    monkeypatch.setattr(codex_install, "CODEX_ENV_FILE", codex_dir / "arize-env.sh")
    monkeypatch.setattr(codex_install, "CONFIG_FILE", config_file)

    return tmp_path


@pytest.fixture()
def mock_buffer():
    """Mock the buffer service control functions."""
    with patch.object(codex_install, "buffer_start", return_value=True) as m_start, \
         patch.object(codex_install, "buffer_stop", return_value="stopped") as m_stop, \
         patch.object(codex_install, "buffer_status", return_value=("stopped", None, None)) as m_status:
        yield {"start": m_start, "stop": m_stop, "status": m_status}


@pytest.fixture()
def mock_prompts(monkeypatch):
    """Mock interactive prompts to return defaults."""
    monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
    monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")
    monkeypatch.setattr(
        codex_install,
        "prompt_backend",
        lambda: ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""}),
    )


# ---------------------------------------------------------------------------
# TOML helper tests
# ---------------------------------------------------------------------------

class TestTomlHelpers:
    """Tests for the TOML read/write helpers."""

    def test_roundtrip_simple(self, tmp_path):
        data = {
            "notify": ["/usr/bin/hook"],
            "otel": {
                "exporter": {
                    "otlp-http": {
                        "endpoint": "http://127.0.0.1:4318/v1/logs",
                        "protocol": "json",
                    }
                }
            },
        }
        p = tmp_path / "config.toml"
        codex_install._toml_write(data, p)
        parsed = codex_install._toml_line_parse(p.read_text())
        assert parsed["notify"] == ["/usr/bin/hook"]
        assert parsed["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"
        assert parsed["otel"]["exporter"]["otlp-http"]["protocol"] == "json"

    def test_parse_preserves_unrelated_sections(self, tmp_path):
        content = textwrap.dedent("""\
            [model]
            name = "gpt-4"

            [otel.exporter.otlp-http]
            endpoint = "http://127.0.0.1:4318/v1/logs"
            protocol = "json"
        """)
        parsed = codex_install._toml_line_parse(content)
        assert parsed["model"]["name"] == "gpt-4"
        assert parsed["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"


# ---------------------------------------------------------------------------
# Install tests
# ---------------------------------------------------------------------------

class TestInstall:
    """Tests for install()."""

    def test_fresh_install_writes_toml_and_env(self, fake_home, mock_buffer, mock_prompts):
        """Fresh install writes config.toml with notify + otel, writes env file, calls buffer start."""
        codex_install.install()

        codex_dir = fake_home / ".codex"

        # Check config.toml
        toml_path = codex_dir / "config.toml"
        assert toml_path.is_file()
        toml_data = codex_install._toml_load(toml_path)
        assert "notify" in toml_data
        assert isinstance(toml_data["notify"], list)
        assert len(toml_data["notify"]) == 1
        assert toml_data["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"
        assert toml_data["otel"]["exporter"]["otlp-http"]["protocol"] == "json"

        # Check env file
        env_path = codex_dir / "arize-env.sh"
        assert env_path.is_file()
        env_text = env_path.read_text()
        assert "export ARIZE_TRACE_ENABLED=true" in env_text
        assert "export ARIZE_CODEX_BUFFER_PORT=4318" in env_text

        # Check buffer start was called
        mock_buffer["start"].assert_called_once()

        # Check config.yaml has harness entry
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        assert config_file.is_file()
        config = yaml.safe_load(config_file.read_text())
        assert config["harnesses"]["codex"]["project_name"] == "codex"

    def test_reinstall_is_idempotent(self, fake_home, mock_buffer, mock_prompts):
        """Re-install does not duplicate notify line or otel block."""
        codex_install.install()
        # Reset mock to track second call
        mock_buffer["start"].reset_mock()
        mock_buffer["status"].return_value = ("running", 1234, "127.0.0.1:4318")

        codex_install.install()

        toml_path = fake_home / ".codex" / "config.toml"
        toml_data = codex_install._toml_load(toml_path)
        # Only one notify entry
        assert len(toml_data["notify"]) == 1
        # Only one otel exporter
        assert "otlp-http" in toml_data["otel"]["exporter"]
        # Buffer start not called again (already running)
        mock_buffer["start"].assert_not_called()

    def test_install_with_user_id(self, fake_home, mock_buffer, monkeypatch):
        """Install with user ID includes it in env file."""
        monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "test-user")
        monkeypatch.setattr(
            codex_install,
            "prompt_backend",
            lambda: ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""}),
        )

        codex_install.install()

        env_text = (fake_home / ".codex" / "arize-env.sh").read_text()
        assert "export ARIZE_USER_ID=test-user" in env_text

    def test_install_with_skills_calls_symlink(self, fake_home, mock_buffer, mock_prompts):
        """install(with_skills=True) calls symlink_skills."""
        with patch.object(codex_install, "symlink_skills") as m_symlink:
            codex_install.install(with_skills=True)
            m_symlink.assert_called_once_with("codex")

    def test_install_reuses_existing_backend(self, fake_home, mock_buffer, mock_prompts):
        """Install reuses existing backend config instead of prompting."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(yaml.safe_dump({
            "backend": {
                "target": "arize",
                "arize": {"endpoint": "otlp.arize.com:443", "api_key": "k", "space_id": "s"},
            },
            "harnesses": {},
        }))

        codex_install.install()

        config = yaml.safe_load(config_file.read_text())
        assert config["harnesses"]["codex"]["project_name"] == "codex"
        assert config["backend"]["target"] == "arize"


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------

class TestUninstall:
    """Tests for uninstall()."""

    def test_uninstall_removes_our_toml_entries_preserves_unrelated(
        self, fake_home, mock_buffer, mock_prompts
    ):
        """Uninstall removes notify + otel but preserves unrelated TOML content."""
        # Install first
        codex_install.install()

        # Seed an unrelated [model] section into config.toml
        toml_path = fake_home / ".codex" / "config.toml"
        data = codex_install._toml_load(toml_path)
        data["model"] = {"name": "gpt-4"}
        codex_install._toml_write(data, toml_path)

        # Uninstall
        codex_install.uninstall()

        # config.toml should still exist with [model] section
        assert toml_path.is_file()
        remaining = codex_install._toml_load(toml_path)
        assert remaining.get("model", {}).get("name") == "gpt-4"
        assert "notify" not in remaining
        assert "otel" not in remaining

        # Buffer stop called
        mock_buffer["stop"].assert_called_once()

        # Env file removed
        assert not (fake_home / ".codex" / "arize-env.sh").is_file()

        # Harness entry removed from config.yaml
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        if config_file.is_file():
            config = yaml.safe_load(config_file.read_text())
            harnesses = config.get("harnesses", {})
            assert "codex" not in harnesses

    def test_uninstall_preserves_foreign_notify(self, fake_home, mock_buffer, mock_prompts):
        """Uninstall does NOT remove a notify line that points elsewhere."""
        codex_install.install()

        # Add a foreign notify entry
        toml_path = fake_home / ".codex" / "config.toml"
        data = codex_install._toml_load(toml_path)
        data["notify"].append("/usr/local/bin/my-custom-hook")
        codex_install._toml_write(data, toml_path)

        codex_install.uninstall()

        remaining = codex_install._toml_load(toml_path)
        assert remaining["notify"] == ["/usr/local/bin/my-custom-hook"]

    def test_uninstall_no_op_when_not_installed(self, fake_home, mock_buffer):
        """Uninstall on a clean system is a safe no-op."""
        codex_install.uninstall()
        mock_buffer["stop"].assert_called_once()


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------

class TestDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_writes_nothing(self, fake_home, mock_buffer, mock_prompts, monkeypatch):
        """With ARIZE_DRY_RUN=true, no files are written."""
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")

        codex_install.install()

        codex_dir = fake_home / ".codex"
        assert not (codex_dir / "config.toml").exists()
        assert not (codex_dir / "arize-env.sh").exists()

        # Buffer start not called in dry-run
        mock_buffer["start"].assert_not_called()

    def test_dry_run_uninstall_preserves_files(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch
    ):
        """Dry-run uninstall does not remove existing files."""
        # Install normally first
        codex_install.install()

        toml_path = fake_home / ".codex" / "config.toml"
        env_path = fake_home / ".codex" / "arize-env.sh"
        assert toml_path.is_file()
        assert env_path.is_file()

        # Now uninstall in dry-run mode
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        mock_buffer["stop"].reset_mock()
        codex_install.uninstall()

        # Files still exist
        assert toml_path.is_file()
        assert env_path.is_file()
        # Buffer stop not called
        mock_buffer["stop"].assert_not_called()


# ---------------------------------------------------------------------------
# Env file heuristic tests
# ---------------------------------------------------------------------------

class TestEnvFileHeuristic:
    """Tests for _is_our_env_file()."""

    def test_recognizes_our_file(self, tmp_path):
        p = tmp_path / "arize-env.sh"
        p.write_text("export ARIZE_TRACE_ENABLED=true\nexport ARIZE_CODEX_BUFFER_PORT=4318\n")
        assert codex_install._is_our_env_file(p) is True

    def test_rejects_foreign_file(self, tmp_path):
        p = tmp_path / "arize-env.sh"
        p.write_text("#!/bin/bash\necho hello\nexport SOMETHING=else\n")
        assert codex_install._is_our_env_file(p) is False

    def test_rejects_large_file(self, tmp_path):
        p = tmp_path / "arize-env.sh"
        lines = [f"export ARIZE_VAR_{i}=val" for i in range(20)]
        p.write_text("\n".join(lines) + "\n")
        assert codex_install._is_our_env_file(p) is False

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent"
        assert codex_install._is_our_env_file(p) is False
