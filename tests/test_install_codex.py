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

    def test_install_existing_codex_entry_only_updates_project_name(
        self, fake_home, mock_buffer, monkeypatch
    ):
        """When harnesses.codex already exists, install reuses it and updates project_name."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(yaml.safe_dump({
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
        }))

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

    def test_install_offers_copy_from_existing_arize_harness(
        self, fake_home, mock_buffer, monkeypatch
    ):
        """Pre-populate harnesses.claude-code with arize; verify codex gets copied creds."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(yaml.safe_dump({
            "harnesses": {
                "claude-code": {
                    "project_name": "claude-code",
                    "target": "arize",
                    "endpoint": "otlp.arize.com:443",
                    "api_key": "ak-shared",
                    "space_id": "S-shared",
                }
            }
        }))

        # prompt_backend receives existing_harnesses and returns arize with copied creds
        captured_kwargs = {}

        def fake_prompt_backend(existing_harnesses=None):
            captured_kwargs["existing_harnesses"] = existing_harnesses
            return ("arize", {
                "endpoint": "otlp.arize.com:443",
                "api_key": "ak-shared",
                "space_id": "S-shared",
            })

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

    def test_install_reads_collector_port_from_codex_entry(
        self, fake_home, mock_buffer, monkeypatch
    ):
        """Verify the TOML writer picks up collector port from harnesses.codex.collector.port."""
        config_file = fake_home / ".arize" / "harness" / "config.yaml"
        config_file.write_text(yaml.safe_dump({
            "harnesses": {
                "codex": {
                    "project_name": "codex",
                    "target": "phoenix",
                    "endpoint": "http://localhost:6006",
                    "api_key": "",
                    "collector": {"host": "127.0.0.1", "port": 4319},
                }
            }
        }))

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

    def test_uninstall_removes_codex_entry_including_collector(
        self, fake_home, mock_buffer, mock_prompts
    ):
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

    def test_uninstall_removes_our_toml_entries_preserves_unrelated(
        self, fake_home, mock_buffer, mock_prompts
    ):
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

    def test_dry_run_uninstall_preserves_files(
        self, fake_home, mock_buffer, mock_prompts, monkeypatch
    ):
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
    """Test that core/setup/codex.py delegates to codex-tracing/install.py."""

    def test_install_delegates(self, fake_home, mock_buffer, mock_prompts):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_get_codex_mod", return_value=mock_mod):
            setup_codex.install(with_skills=True)
            mock_mod.install.assert_called_once_with(with_skills=True)

    def test_uninstall_delegates(self, fake_home, mock_buffer):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_get_codex_mod", return_value=mock_mod):
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
