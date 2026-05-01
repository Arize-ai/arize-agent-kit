#!/usr/bin/env python3
"""Tests for codex-tracing install/uninstall module."""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import codex_tracing.install as codex_install

# ---------------------------------------------------------------------------
# Import the install module (now a proper Python package)
# ---------------------------------------------------------------------------


PHOENIX_BACKEND = ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""})
ARIZE_BACKEND = (
    "arize",
    {"endpoint": "otlp.arize.com:443", "api_key": "ak-xxx", "space_id": "U3Bh"},
)


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
    monkeypatch.setattr("core.constants.CONFIG_FILE", config_file)
    monkeypatch.setattr("core.config.CONFIG_FILE", config_file)

    # Patch the constants in the install module itself
    monkeypatch.setattr(codex_install, "BIN_DIR", install_dir / "bin")
    monkeypatch.setattr(codex_install, "CODEX_CONFIG_DIR", codex_dir)
    monkeypatch.setattr(codex_install, "CODEX_CONFIG_FILE", codex_dir / "config.toml")
    monkeypatch.setattr(codex_install, "CODEX_ENV_FILE", codex_dir / "arize-env.sh")
    monkeypatch.setattr(codex_install, "CONFIG_FILE", config_file)

    return tmp_path


@pytest.fixture(autouse=True)
def _stub_logging_prompts(monkeypatch):
    """Auto-stub the content-logging wizard so tests don't block on stdin."""
    monkeypatch.setattr(
        codex_install,
        "prompt_content_logging",
        lambda: {"prompts": True, "tool_details": True, "tool_content": True},
    )
    monkeypatch.setattr(codex_install, "write_logging_config", lambda block, config_path=None: None)


@pytest.fixture()
def mock_buffer():
    """Mock the buffer service control functions."""
    with (
        patch.object(codex_install, "buffer_start", return_value=True) as m_start,
        patch.object(codex_install, "buffer_stop", return_value="stopped") as m_stop,
        patch.object(codex_install, "buffer_status", return_value=("stopped", None, None)) as m_status,
    ):
        yield {"start": m_start, "stop": m_stop, "status": m_status}


@pytest.fixture()
def mock_prompts(monkeypatch):
    """Mock interactive prompts to return phoenix defaults."""
    monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
    monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")
    monkeypatch.setattr(
        codex_install,
        "prompt_backend",
        lambda existing_harnesses=None: PHOENIX_BACKEND,
    )


def _mock_prompts_arize(monkeypatch):
    """Mock interactive prompts to return arize defaults."""
    monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
    monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")
    monkeypatch.setattr(
        codex_install,
        "prompt_backend",
        lambda existing_harnesses=None: ARIZE_BACKEND,
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
        content = textwrap.dedent(
            """\
            [model]
            name = "gpt-4"

            [otel.exporter.otlp-http]
            endpoint = "http://127.0.0.1:4318/v1/logs"
            protocol = "json"
        """
        )
        parsed = codex_install._toml_line_parse(content)
        assert parsed["model"]["name"] == "gpt-4"
        assert parsed["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"

    def test_roundtrip_windows_path_with_backslashes(self, tmp_path):
        """Windows notify_cmd paths with backslashes round-trip cleanly.

        Regression guard: previously written as unescaped basic strings
        ("C:\\Users\\..."), which produced invalid TOML. Now written as
        literal strings ('C:\\Users\\...') which take bytes as-is.
        """
        win_path = r"C:\Users\foo\.arize\harness\venv\Scripts\arize-hook-codex-notify.exe"
        data = {"notify": [win_path]}
        p = tmp_path / "config.toml"
        codex_install._toml_write(data, p)

        raw = p.read_text()
        assert f"'{win_path}'" in raw  # literal string, no escape mangling
        assert "\\\\" not in raw  # no accidental double-escaping

        parsed = codex_install._toml_line_parse(raw)
        assert parsed["notify"] == [win_path]

    def test_roundtrip_value_with_single_quote_falls_back_to_basic(self, tmp_path):
        """A value containing ' can't use literal form — must escape into basic."""
        data = {"desc": "it's a value"}
        p = tmp_path / "config.toml"
        codex_install._toml_write(data, p)

        raw = p.read_text()
        # Basic string (double-quoted) because literal can't carry a '
        assert 'desc = "it\'s a value"' in raw


# ---------------------------------------------------------------------------
# Install tests — flat schema
# ---------------------------------------------------------------------------


class TestInstall:
    """Tests for install() using the flat config schema."""

    def test_install_fresh_writes_flat_phoenix_entry(self, fake_home, mock_buffer, mock_prompts):
        """Fresh install with phoenix writes flat harnesses.codex entry."""
        codex_install.install()

        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        assert config_file.is_file()
        config = yaml.safe_load(config_file.read_text())

        entry = config["harnesses"]["codex"]
        assert entry["target"] == "phoenix"
        assert entry["endpoint"] == "http://localhost:6006"
        assert entry["api_key"] == ""
        assert entry["project_name"] == "codex"
        # No top-level backend or collector
        assert "backend" not in config
        assert "collector" not in config

    def test_install_fresh_writes_flat_arize_entry(self, fake_home, mock_buffer, monkeypatch):
        """Fresh install with arize writes flat harnesses.codex entry with space_id."""
        _mock_prompts_arize(monkeypatch)
        codex_install.install()

        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config = yaml.safe_load(config_file.read_text())

        entry = config["harnesses"]["codex"]
        assert entry["target"] == "arize"
        assert entry["endpoint"] == "otlp.arize.com:443"
        assert entry["api_key"] == "ak-xxx"
        assert entry["space_id"] == "U3Bh"
        assert entry["project_name"] == "codex"

    def test_install_fresh_writes_collector_under_codex_entry(self, fake_home, mock_buffer, mock_prompts):
        """Fresh install writes collector under harnesses.codex.collector, not top-level."""
        codex_install.install()

        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config = yaml.safe_load(config_file.read_text())

        # Collector under harnesses.codex
        collector = config["harnesses"]["codex"]["collector"]
        assert collector["host"] == "127.0.0.1"
        assert collector["port"] == 4318
        # No top-level collector
        assert "collector" not in config

    def test_install_fresh_writes_toml_and_env(self, fake_home, mock_buffer, mock_prompts):
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

    def test_install_existing_codex_entry_only_updates_project_name(self, fake_home, mock_buffer, monkeypatch):
        """When harnesses.codex already exists, install reuses it and updates project_name."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "harnesses": {
                        "codex": {
                            "project_name": "old-name",
                            "target": "arize",
                            "endpoint": "otlp.arize.com:443",
                            "api_key": "ak-existing",
                            "space_id": "S123",
                            "collector": {"host": "127.0.0.1", "port": 4318},
                        }
                    }
                }
            )
        )

        monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: "new-name")
        monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")

        codex_install.install()

        config = yaml.safe_load(config_file.read_text())
        entry = config["harnesses"]["codex"]
        assert entry["project_name"] == "new-name"
        # Credentials preserved
        assert entry["target"] == "arize"
        assert entry["api_key"] == "ak-existing"
        assert entry["space_id"] == "S123"

    def test_install_offers_copy_from_existing_arize_harness(self, fake_home, mock_buffer, monkeypatch):
        """Pre-populate harnesses.claude-code with arize; verify codex gets copied creds."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "harnesses": {
                        "claude-code": {
                            "project_name": "claude-code",
                            "target": "arize",
                            "endpoint": "otlp.arize.com:443",
                            "api_key": "ak-shared",
                            "space_id": "S-shared",
                        }
                    }
                }
            )
        )

        # prompt_backend receives existing_harnesses and returns arize with copied creds
        captured_kwargs = {}

        def fake_prompt_backend(existing_harnesses=None):
            captured_kwargs["existing_harnesses"] = existing_harnesses
            return (
                "arize",
                {
                    "endpoint": "otlp.arize.com:443",
                    "api_key": "ak-shared",
                    "space_id": "S-shared",
                },
            )

        monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(codex_install, "prompt_backend", fake_prompt_backend)

        codex_install.install()

        # Verify existing_harnesses was passed to prompt_backend
        assert "claude-code" in captured_kwargs["existing_harnesses"]

        config = yaml.safe_load(config_file.read_text())
        codex_entry = config["harnesses"]["codex"]
        assert codex_entry["target"] == "arize"
        assert codex_entry["api_key"] == "ak-shared"
        assert codex_entry["space_id"] == "S-shared"
        # Collector written under codex
        assert codex_entry["collector"]["host"] == "127.0.0.1"
        assert codex_entry["collector"]["port"] == 4318

    def test_reinstall_is_idempotent(self, fake_home, mock_buffer, mock_prompts):
        """Re-install does not duplicate notify line or otel block."""
        codex_install.install()
        mock_buffer["start"].reset_mock()
        mock_buffer["status"].return_value = ("running", 1234, "127.0.0.1:4318")

        codex_install.install()

        toml_path = fake_home / ".codex" / "config.toml"
        toml_data = codex_install._toml_load(toml_path)
        assert len(toml_data["notify"]) == 1
        assert "otlp-http" in toml_data["otel"]["exporter"]
        mock_buffer["start"].assert_not_called()

    def test_install_with_user_id(self, fake_home, mock_buffer, monkeypatch):
        """Install with user ID includes it in env file."""
        monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "test-user")
        monkeypatch.setattr(
            codex_install,
            "prompt_backend",
            lambda existing_harnesses=None: PHOENIX_BACKEND,
        )

        codex_install.install()

        env_text = (fake_home / ".codex" / "arize-env.sh").read_text()
        assert "export ARIZE_USER_ID=test-user" in env_text

    def test_install_with_skills_calls_symlink(self, fake_home, mock_buffer, mock_prompts):
        """install(with_skills=True) calls symlink_skills."""
        with patch.object(codex_install, "symlink_skills") as m_symlink:
            codex_install.install(with_skills=True)
            m_symlink.assert_called_once_with("codex")

    def test_install_reads_collector_port_from_codex_entry(self, fake_home, mock_buffer, monkeypatch):
        """Verify the TOML writer picks up collector port from harnesses.codex.collector.port."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "harnesses": {
                        "codex": {
                            "project_name": "codex",
                            "target": "phoenix",
                            "endpoint": "http://localhost:6006",
                            "api_key": "",
                            "collector": {"host": "127.0.0.1", "port": 4319},
                        }
                    }
                }
            )
        )

        monkeypatch.setattr(codex_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(codex_install, "prompt_user_id", lambda: "")

        codex_install.install()

        # Verify collector port preserved in config
        config = yaml.safe_load(config_file.read_text())
        assert config["harnesses"]["codex"]["collector"]["port"] == 4319

        # Verify TOML otel endpoint uses port 4319, not the default 4318
        toml_path = fake_home / ".codex" / "config.toml"
        toml_data = codex_install._toml_load(toml_path)
        otel_ep = toml_data["otel"]["exporter"]["otlp-http"]["endpoint"]
        assert ":4319/" in otel_ep


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------


class TestUninstall:
    """Tests for uninstall()."""

    def test_uninstall_removes_codex_entry_including_collector(self, fake_home, mock_buffer, mock_prompts):
        """Uninstall removes harnesses.codex entirely (including collector sub-block)."""
        codex_install.install()

        # Verify collector exists before uninstall
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config = yaml.safe_load(config_file.read_text())
        assert "collector" in config["harnesses"]["codex"]

        codex_install.uninstall()

        config = yaml.safe_load(config_file.read_text())
        harnesses = config.get("harnesses", {})
        assert "codex" not in harnesses

    def test_uninstall_removes_our_toml_entries_preserves_unrelated(self, fake_home, mock_buffer, mock_prompts):
        """Uninstall removes notify + otel but preserves unrelated TOML content."""
        codex_install.install()

        toml_path = fake_home / ".codex" / "config.toml"
        data = codex_install._toml_load(toml_path)
        data["model"] = {"name": "gpt-4"}
        codex_install._toml_write(data, toml_path)

        codex_install.uninstall()

        assert toml_path.is_file()
        remaining = codex_install._toml_load(toml_path)
        assert remaining.get("model", {}).get("name") == "gpt-4"
        assert "notify" not in remaining
        assert "otel" not in remaining

        mock_buffer["stop"].assert_called_once()
        assert not (fake_home / ".codex" / "arize-env.sh").is_file()

    def test_uninstall_preserves_foreign_notify(self, fake_home, mock_buffer, mock_prompts):
        """Uninstall does NOT remove a notify line that points elsewhere."""
        codex_install.install()

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

    def test_uninstall_is_idempotent(self, fake_home, mock_buffer, mock_prompts):
        """Calling uninstall() twice succeeds both times; second call is a no-op."""
        codex_install.install()

        codex_install.uninstall()
        mock_buffer["stop"].reset_mock()

        # Second uninstall should not raise
        codex_install.uninstall()
        mock_buffer["stop"].assert_called_once()

        # Config still exists with empty harnesses
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        if config_file.is_file():
            config = yaml.safe_load(config_file.read_text())
            assert "codex" not in config.get("harnesses", {})


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


class TestDryRun:
    """Tests for dry-run mode."""

    def test_install_dry_run_writes_nothing(self, fake_home, mock_buffer, mock_prompts, monkeypatch):
        """With ARIZE_DRY_RUN=true, no files are written."""
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")

        codex_install.install()

        codex_dir = fake_home / ".codex"
        assert not (codex_dir / "config.toml").exists()
        assert not (codex_dir / "arize-env.sh").exists()

        # config.yaml should not exist either
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        assert not config_file.exists()

        mock_buffer["start"].assert_not_called()

    def test_dry_run_uninstall_preserves_files(self, fake_home, mock_buffer, mock_prompts, monkeypatch):
        """Dry-run uninstall does not remove existing files."""
        codex_install.install()

        toml_path = fake_home / ".codex" / "config.toml"
        env_path = fake_home / ".codex" / "arize-env.sh"
        assert toml_path.is_file()
        assert env_path.is_file()

        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        mock_buffer["stop"].reset_mock()
        codex_install.uninstall()

        assert toml_path.is_file()
        assert env_path.is_file()
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


# ---------------------------------------------------------------------------
# Additional TOML helper unit tests
# ---------------------------------------------------------------------------


class TestTomlAddRemove:
    """Unit tests for _codex_toml_add and _codex_toml_remove."""

    def test_add_to_empty_file(self, tmp_path):
        p = tmp_path / "config.toml"
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        data = codex_install._toml_load(p)
        assert data["notify"] == ["/venv/bin/hook"]
        assert data["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"
        assert data["otel"]["exporter"]["otlp-http"]["protocol"] == "json"

    def test_add_idempotent(self, tmp_path):
        p = tmp_path / "config.toml"
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        data = codex_install._toml_load(p)
        assert data["notify"] == ["/venv/bin/hook"]
        assert data["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://127.0.0.1:4318/v1/logs"
        assert data["otel"]["exporter"]["otlp-http"]["protocol"] == "json"

    def test_add_preserves_existing_notify(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text('notify = ["/usr/bin/other-hook"]\n')
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        data = codex_install._toml_load(p)
        assert data["notify"] == ["/usr/bin/other-hook", "/venv/bin/hook"]

    def test_add_preserves_unrelated_sections(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text('[model]\nname = "gpt-4"\n')
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        data = codex_install._toml_load(p)
        assert data["model"]["name"] == "gpt-4"
        assert data["notify"] == ["/venv/bin/hook"]

    def test_remove_only_our_notify(self, tmp_path):
        p = tmp_path / "config.toml"
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        data = codex_install._toml_load(p)
        data["notify"].append("/usr/bin/other")
        codex_install._toml_write(data, p)

        codex_install._codex_toml_remove(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        remaining = codex_install._toml_load(p)
        assert remaining["notify"] == ["/usr/bin/other"]
        assert "otel" not in remaining

    def test_remove_nonexistent_file_is_noop(self, tmp_path):
        p = tmp_path / "nonexistent.toml"
        codex_install._codex_toml_remove(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        assert not p.exists()

    def test_remove_non_matching_endpoint_preserves_otel(self, tmp_path):
        p = tmp_path / "config.toml"
        data = {
            "otel": {
                "exporter": {
                    "otlp-http": {
                        "endpoint": "http://other-host:9999/v1/logs",
                        "protocol": "json",
                    }
                }
            }
        }
        codex_install._toml_write(data, p)
        codex_install._codex_toml_remove(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        remaining = codex_install._toml_load(p)
        assert remaining["otel"]["exporter"]["otlp-http"]["endpoint"] == "http://other-host:9999/v1/logs"

    def test_add_dry_run_no_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        p = tmp_path / "config.toml"
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        assert not p.exists()

    def test_remove_dry_run_no_write(self, tmp_path, monkeypatch):
        p = tmp_path / "config.toml"
        codex_install._codex_toml_add(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        original = p.read_text()
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        codex_install._codex_toml_remove(p, "/venv/bin/hook", "http://127.0.0.1:4318/v1/logs")
        assert p.read_text() == original


# ---------------------------------------------------------------------------
# TOML edge case tests
# ---------------------------------------------------------------------------


class TestTomlEdgeCases:
    """Edge cases for TOML parser/writer."""

    def test_boolean_roundtrip(self, tmp_path):
        p = tmp_path / "test.toml"
        codex_install._toml_write({"flag": True, "other": False}, p)
        data = codex_install._toml_line_parse(p.read_text())
        assert data["flag"] is True
        assert data["other"] is False

    def test_integer_roundtrip(self, tmp_path):
        p = tmp_path / "test.toml"
        codex_install._toml_write({"port": 4318}, p)
        data = codex_install._toml_line_parse(p.read_text())
        assert data["port"] == 4318

    def test_empty_array(self, tmp_path):
        p = tmp_path / "test.toml"
        codex_install._toml_write({"notify": []}, p)
        text = p.read_text()
        assert "notify = []" in text
        data = codex_install._toml_line_parse(text)
        assert data["notify"] == []

    def test_comments_ignored_in_parse(self):
        text = '# comment\nkey = "val"\n'
        data = codex_install._toml_line_parse(text)
        assert data["key"] == "val"


# ---------------------------------------------------------------------------
# Write env file tests
# ---------------------------------------------------------------------------


class TestWriteEnvFile:
    """Tests for _write_env_file."""

    def test_env_file_permissions(self, tmp_path):
        p = tmp_path / "env.sh"
        codex_install._write_env_file(p)
        mode = oct(p.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_env_file_without_user_id(self, tmp_path):
        p = tmp_path / "env.sh"
        codex_install._write_env_file(p)
        text = p.read_text()
        assert "ARIZE_USER_ID" not in text
        assert "ARIZE_TRACE_ENABLED=true" in text

    def test_env_file_with_user_id(self, tmp_path):
        p = tmp_path / "env.sh"
        codex_install._write_env_file(p, user_id="alice")
        text = p.read_text()
        assert "export ARIZE_USER_ID=alice" in text

    def test_env_file_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "subdir" / "env.sh"
        codex_install._write_env_file(p)
        assert p.is_file()

    def test_env_file_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        p = tmp_path / "env.sh"
        codex_install._write_env_file(p)
        assert not p.exists()


# ---------------------------------------------------------------------------
# core/setup/codex.py delegation tests
# ---------------------------------------------------------------------------


class TestCoreSetupDelegation:
    """Test that core/setup/codex.py delegates to codex_tracing/install.py."""

    def test_install_delegates(self, fake_home, mock_buffer, mock_prompts):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_install_mod", mock_mod):
            setup_codex.install(with_skills=True)
            mock_mod.install.assert_called_once_with(with_skills=True)

    def test_uninstall_delegates(self, fake_home, mock_buffer):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_install_mod", mock_mod):
            setup_codex.uninstall()
            mock_mod.uninstall.assert_called_once()


# ---------------------------------------------------------------------------
# CLI __main__ dispatch tests
# ---------------------------------------------------------------------------


class TestCLIDispatch:
    """Tests for cli_main() dispatch logic."""

    def test_cli_install(self, fake_home, mock_buffer, mock_prompts):
        with patch.object(codex_install, "install") as m:
            codex_install.cli_main(["install.py", "install"])
            m.assert_called_once_with(with_skills=False)

    def test_cli_install_with_skills(self, fake_home, mock_buffer, mock_prompts):
        with patch.object(codex_install, "install") as m:
            codex_install.cli_main(["install.py", "install", "--with-skills"])
            m.assert_called_once_with(with_skills=True)

    def test_cli_uninstall(self, fake_home, mock_buffer):
        with patch.object(codex_install, "uninstall") as m:
            codex_install.cli_main(["install.py", "uninstall"])
            m.assert_called_once()

    def test_cli_invalid_action_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            codex_install.cli_main(["install.py", "bogus"])
        assert exc_info.value.code == 1

    def test_cli_no_args_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            codex_install.cli_main(["install.py"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Buffer service interaction tests
# ---------------------------------------------------------------------------


class TestBufferInteraction:
    """Tests for buffer service control during install/uninstall."""

    def test_buffer_already_running_skips_start(self, fake_home, mock_buffer, mock_prompts):
        mock_buffer["status"].return_value = ("running", 1234, "127.0.0.1:4318")
        codex_install.install()
        mock_buffer["start"].assert_not_called()

    def test_buffer_start_failure_doesnt_crash(self, fake_home, mock_buffer, mock_prompts):
        mock_buffer["start"].return_value = False
        codex_install.install()
        mock_buffer["start"].assert_called_once()

    def test_uninstall_calls_buffer_stop(self, fake_home, mock_buffer):
        codex_install.uninstall()
        mock_buffer["stop"].assert_called_once()


# ---------------------------------------------------------------------------
# TOML fallback quoting tests
# ---------------------------------------------------------------------------


class TestTomlFallbackQuoting:
    """Tests for quote-aware TOML fallback parser/writer."""

    def test_unkey_roundtrips_through_key(self):
        inputs = [
            "plain",
            "with.dot",
            "with@at",
            "with/slash",
            'with"quote',
            "with\\backslash",
            "@scope/server",
        ]
        for s in inputs:
            assert codex_install._toml_unkey(codex_install._toml_key(s)) == s, f"roundtrip failed for {s!r}"

    def test_split_key_path_respects_quotes(self):
        cases = [
            ("a.b.c", ["a", "b", "c"]),
            ('mcp_servers."@scope/server"', ["mcp_servers", "@scope/server"]),
            ('plugins."browser-use@openai-bundled"', ["plugins", "browser-use@openai-bundled"]),
            ('mcp_servers."a.b.c"', ["mcp_servers", "a.b.c"]),
            ('  outer . "inner.path"  ', ["outer", "inner.path"]),
        ]
        for path, expected in cases:
            assert codex_install._toml_split_key_path(path) == expected, f"split failed for {path!r}"

    def test_fallback_roundtrips_quoted_section_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codex_tracing.install._tomllib", None)
        toml_text = textwrap.dedent(
            """\
            [mcp_servers."@scope/server"]
            command = "npx"
            args = ["-y", "@scope/server"]
        """
        )
        p = tmp_path / "config.toml"
        p.write_text(toml_text)

        data = codex_install._toml_load(p)
        assert data == {
            "mcp_servers": {
                "@scope/server": {
                    "command": "npx",
                    "args": ["-y", "@scope/server"],
                }
            }
        }

        # Round-trip: write and re-read
        p2 = tmp_path / "config2.toml"
        codex_install._toml_write(data, p2)
        data2 = codex_install._toml_load(p2)
        assert data2 == data

    def test_fallback_repairs_malformed_unquoted_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codex_tracing.install._tomllib", None)
        toml_text = textwrap.dedent(
            """\
            [plugins.@scope/server]
            enabled = true
        """
        )
        p = tmp_path / "config.toml"
        p.write_text(toml_text)

        data = codex_install._toml_load(p)
        assert data == {"plugins": {"@scope/server": {"enabled": True}}}

        # Round-trip: write produces properly quoted output
        p2 = tmp_path / "config2.toml"
        codex_install._toml_write(data, p2)
        rewritten = p2.read_text()
        assert '[plugins."@scope/server"]' in rewritten

        # Strict tomllib can now parse the rewritten output
        tomllib = pytest.importorskip("tomllib")

        strict_data = tomllib.loads(rewritten)
        assert strict_data == data

    # --- Additional edge-case tests ---

    def test_split_key_path_leading_and_trailing_dots(self):
        """Constraint: leading/trailing dots must not crash, flush empty segments."""
        assert codex_install._toml_split_key_path("a.") == ["a", ""]
        assert codex_install._toml_split_key_path(".b") == ["", "b"]
        assert codex_install._toml_split_key_path(".") == ["", ""]

    def test_split_key_path_empty_string(self):
        assert codex_install._toml_split_key_path("") == [""]

    def test_split_key_path_single_bare_key(self):
        assert codex_install._toml_split_key_path("server") == ["server"]

    def test_split_key_path_single_quoted_key(self):
        assert codex_install._toml_split_key_path('"@scope/server"') == ["@scope/server"]

    def test_unkey_roundtrip_backslash_and_quote(self):
        """Key containing both backslash and double-quote round-trips correctly."""
        s = 'back\\and"quote'
        assert codex_install._toml_unkey(codex_install._toml_key(s)) == s

    def test_unkey_bare_key_passthrough(self):
        """Bare keys (no quotes) pass through _toml_unkey unchanged."""
        assert codex_install._toml_unkey("simple-key_0") == "simple-key_0"

    def test_fallback_deeply_nested_quoted_keys(self, tmp_path, monkeypatch):
        """Multiple levels with quoted keys parse and round-trip correctly."""
        monkeypatch.setattr("codex_tracing.install._tomllib", None)
        toml_text = textwrap.dedent(
            """\
            [a."b.c"."d/e"]
            x = 1
        """
        )
        p = tmp_path / "deep.toml"
        p.write_text(toml_text)

        data = codex_install._toml_load(p)
        assert data == {"a": {"b.c": {"d/e": {"x": 1}}}}

        # Round-trip
        p2 = tmp_path / "deep2.toml"
        codex_install._toml_write(data, p2)
        data2 = codex_install._toml_load(p2)
        assert data2 == data

    def test_fallback_multiple_sections_with_quoted_keys(self, tmp_path, monkeypatch):
        """Multiple sections with special-char keys coexist correctly."""
        monkeypatch.setattr("codex_tracing.install._tomllib", None)
        toml_text = textwrap.dedent(
            """\
            [servers."@org/alpha"]
            port = 8080

            [servers."@org/beta"]
            port = 9090
        """
        )
        p = tmp_path / "multi.toml"
        p.write_text(toml_text)

        data = codex_install._toml_load(p)
        assert data == {
            "servers": {
                "@org/alpha": {"port": 8080},
                "@org/beta": {"port": 9090},
            }
        }

        # Round-trip
        p2 = tmp_path / "multi2.toml"
        codex_install._toml_write(data, p2)
        data2 = codex_install._toml_load(p2)
        assert data2 == data

    def test_toml_key_idempotent_for_bare_keys(self):
        """Bare keys should not be modified by _toml_key."""
        for bare in ["simple", "with-dash", "with_under", "CamelCase", "num123"]:
            assert codex_install._toml_key(bare) == bare

    def test_toml_key_quotes_special_chars(self):
        """Keys with special characters get quoted."""
        assert codex_install._toml_key("a.b") == '"a.b"'
        assert codex_install._toml_key("@scope") == '"@scope"'
        assert codex_install._toml_key("a/b") == '"a/b"'

    def test_written_toml_valid_for_strict_parser(self, tmp_path, monkeypatch):
        """Data with special-char keys produces strict-parseable TOML on write."""
        tomllib = pytest.importorskip("tomllib")

        data = {
            "mcp_servers": {
                "@anthropic/server": {"command": "run", "args": ["--flag"]},
                "normal-server": {"command": "exec"},
            },
            "projects": {
                "/Users/someone/proj": {"enabled": True},
            },
        }
        p = tmp_path / "out.toml"
        codex_install._toml_write(data, p)
        text = p.read_text()
        parsed = tomllib.loads(text)
        assert parsed == data


# ---------------------------------------------------------------------------
# Codex proxy shim tests
# ---------------------------------------------------------------------------


class TestCodexProxyShim:
    """Tests for the codex proxy shim install/uninstall helpers."""

    def test_install_writes_codex_proxy_shim(self, fake_home, mock_buffer, mock_prompts):
        """Install creates a codex shim in BIN_DIR containing arize-codex-proxy."""
        codex_install.install()

        shim = fake_home / ".arize" / "harness" / "bin" / "codex"
        assert shim.is_file()
        text = shim.read_text()
        assert "arize-codex-proxy" in text
        assert "Arize Codex proxy shim" in text
        # POSIX shim must be executable
        assert shim.stat().st_mode & stat.S_IXUSR

    def test_install_adds_harness_bin_to_supported_shell_profiles(self, fake_home, mock_buffer, mock_prompts):
        """Install persists the proxy PATH for sh, bash, zsh, and PowerShell."""
        codex_install.install()

        expected_profiles = [
            fake_home / ".profile",
            fake_home / ".bashrc",
            fake_home / ".zshrc",
            fake_home / ".config" / "powershell" / "Microsoft.PowerShell_profile.ps1",
        ]
        for profile in expected_profiles:
            text = profile.read_text()
            assert "arize codex tracing PATH" in text
            assert ".arize/harness/bin" in text

        assert str(fake_home / ".arize" / "harness" / "bin") in os.environ["PATH"].split(os.pathsep)

    def test_install_updates_existing_login_profiles_without_creating_shadowing_files(
        self, fake_home, mock_buffer, mock_prompts
    ):
        """Existing bash/zsh login profiles are updated; absent precedence-changing files are not created."""
        bash_profile = fake_home / ".bash_profile"
        zprofile = fake_home / ".zprofile"
        bash_profile.write_text("export EXISTING=1\n")
        zprofile.write_text("export ZEXISTING=1\n")

        codex_install.install()

        assert "arize codex tracing PATH" in bash_profile.read_text()
        assert "arize codex tracing PATH" in zprofile.read_text()
        assert not (fake_home / ".bash_login").exists()
        assert not (fake_home / ".zlogin").exists()

    def test_install_path_profile_updates_are_idempotent(self, fake_home, mock_buffer, mock_prompts):
        """Running install twice does not duplicate the managed PATH block."""
        codex_install.install()
        codex_install.install()

        profile = fake_home / ".profile"
        assert profile.read_text().count(">>> arize codex tracing PATH >>>") == 1

    def test_windows_install_updates_powershell_bash_sh_and_user_path(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch
    ):
        """Windows installs persist PATH for PowerShell, Git Bash/sh, and user environment PATH."""
        calls = []
        monkeypatch.setattr(codex_install.os, "name", "nt")
        monkeypatch.setattr(codex_install, "_ensure_windows_user_path", lambda path: calls.append(path) or True)

        codex_install.install()

        assert calls == [fake_home / ".arize" / "harness" / "bin"]
        cmd_shim = fake_home / ".arize" / "harness" / "bin" / "codex.cmd"
        sh_shim = fake_home / ".arize" / "harness" / "bin" / "codex"
        assert "Arize Codex proxy shim" in cmd_shim.read_text()
        assert "arize-codex-proxy.exe" in cmd_shim.read_text()
        assert "Arize Codex proxy shim" in sh_shim.read_text()
        assert "arize-codex-proxy.exe" in sh_shim.read_text()
        for profile in [
            fake_home / ".profile",
            fake_home / ".bashrc",
            fake_home / ".zshrc",
            fake_home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
            fake_home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
        ]:
            assert "arize codex tracing PATH" in profile.read_text()

    def test_install_does_not_overwrite_foreign_codex_shim(self, fake_home, mock_buffer, mock_prompts):
        """A pre-existing non-Arize codex file is never overwritten."""
        bin_dir = fake_home / ".arize" / "harness" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        foreign = bin_dir / "codex"
        foreign.write_text("#!/bin/sh\necho real codex\n")
        original_text = foreign.read_text()

        codex_install.install()

        assert foreign.read_text() == original_text

    def test_uninstall_removes_our_codex_proxy_shim(self, fake_home, mock_buffer, mock_prompts):
        """Install creates the shim, uninstall removes it."""
        codex_install.install()

        shim = fake_home / ".arize" / "harness" / "bin" / "codex"
        assert shim.is_file()

        codex_install.uninstall()
        assert not shim.exists()

    def test_uninstall_removes_managed_path_blocks(self, fake_home, mock_buffer, mock_prompts):
        """Uninstall removes only the installer-managed PATH blocks."""
        profile = fake_home / ".profile"
        profile.write_text("export KEEP_ME=1\n")
        codex_install.install()

        assert "arize codex tracing PATH" in profile.read_text()

        codex_install.uninstall()

        text = profile.read_text()
        assert "arize codex tracing PATH" not in text
        assert "export KEEP_ME=1" in text

    def test_uninstall_preserves_foreign_codex_shim(self, fake_home, mock_buffer, mock_prompts):
        """A non-Arize codex file survives uninstall."""
        bin_dir = fake_home / ".arize" / "harness" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        foreign = bin_dir / "codex"
        foreign.write_text("#!/bin/sh\necho real codex\n")
        original_text = foreign.read_text()

        codex_install.uninstall()

        assert foreign.read_text() == original_text

    def test_codex_proxy_path_status_active_shadowed_missing(self, tmp_path, monkeypatch):
        """Unit-test _codex_proxy_path_status for each case."""
        shim = tmp_path / "bin" / "codex"
        shim.parent.mkdir(parents=True)
        shim.write_text('#!/bin/sh\n# Arize Codex proxy shim\nexec arize-codex-proxy "$@"\n')

        shim_real = os.path.realpath(str(shim))

        # Active: shutil.which returns the shim path
        monkeypatch.setattr("shutil.which", lambda cmd: str(shim))
        status, resolved = codex_install._codex_proxy_path_status(shim)
        assert status == "active"
        assert resolved == shim_real

        # Shadowed: shutil.which returns a different path
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/codex")
        status, resolved = codex_install._codex_proxy_path_status(shim)
        assert status == "shadowed"
        assert resolved == os.path.realpath("/usr/local/bin/codex")

        # Missing: shutil.which returns None
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        status, resolved = codex_install._codex_proxy_path_status(shim)
        assert status == "missing"
        assert resolved is None

    def test_codex_proxy_shim_dry_run(self, tmp_path, monkeypatch):
        """In dry-run mode, no shim file is created."""
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        shim = tmp_path / "bin" / "codex"
        codex_install._write_codex_proxy_shim(shim, Path("/fake/arize-codex-proxy"))
        assert not shim.exists()

    def test_install_prints_active_message_when_shim_resolves_first(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch, capsys
    ):
        """When shutil.which('codex') returns the shim, the active message prints."""
        shim = fake_home / ".arize" / "harness" / "bin" / "codex"

        def fake_which(cmd):
            if cmd == "codex":
                return str(shim)
            return None

        monkeypatch.setattr("shutil.which", fake_which)
        codex_install.install()

        output = capsys.readouterr().out
        assert "Codex proxy active for codex exec" in output

    def test_install_prints_shadowed_message_with_resolved_path(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch, capsys
    ):
        """When shutil.which('codex') returns a different path, the shadowed message prints."""

        def fake_which(cmd):
            if cmd == "codex":
                return "/usr/local/bin/codex"
            return None

        monkeypatch.setattr("shutil.which", fake_which)
        codex_install.install()

        output = capsys.readouterr().out
        assert "but PATH resolves codex to /usr/local/bin/codex" in output
        assert "Open a new shell after install" in output

    def test_install_prints_missing_message_when_no_codex_on_path(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch, capsys
    ):
        """When shutil.which('codex') returns None, the missing message prints."""

        def fake_which(cmd):
            return None

        monkeypatch.setattr("shutil.which", fake_which)
        codex_install.install()

        output = capsys.readouterr().out
        assert "open a new shell to activate codex exec tracing" in output
