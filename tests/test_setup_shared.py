"""Tests for core.setup shared helpers and core.setup.wipe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Redirect all core.setup path constants to a temp directory.

    Returns the install dir Path.
    """
    install_dir = tmp_path / ".arize" / "harness"
    install_dir.mkdir(parents=True)

    import core.setup as setup_mod

    monkeypatch.setattr(setup_mod, "INSTALL_DIR", install_dir)
    monkeypatch.setattr(setup_mod, "VENV_DIR", install_dir / "venv")
    monkeypatch.setattr(setup_mod, "CONFIG_FILE", install_dir / "config.yaml")
    monkeypatch.setattr(setup_mod, "BIN_DIR", install_dir / "bin")
    monkeypatch.setattr(setup_mod, "RUN_DIR", install_dir / "run")
    monkeypatch.setattr(setup_mod, "LOG_DIR", install_dir / "logs")
    monkeypatch.setattr(setup_mod, "STATE_DIR", install_dir / "state")

    # Also patch core.constants so load_config/save_config can use default paths
    import core.constants as c

    monkeypatch.setattr(c, "BASE_DIR", install_dir)
    monkeypatch.setattr(c, "CONFIG_FILE", install_dir / "config.yaml")

    return install_dir


@pytest.fixture
def populated_config(fake_install):
    """Write a config.yaml with a backend block and one harness entry."""
    config = {
        "backend": {
            "target": "phoenix",
            "phoenix": {"endpoint": "http://localhost:6006", "api_key": ""},
        },
        "harnesses": {
            "claude-code": {"project_name": "claude-code"},
        },
    }
    config_path = fake_install / "config.yaml"
    fd = os.open(str(config_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    return config


# ---------------------------------------------------------------------------
# dry_run()
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.parametrize("val", ["1", "true", "yes", "TRUE", "True", "YES"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("ARIZE_DRY_RUN", val)
        from core.setup import dry_run

        assert dry_run() is True

    @pytest.mark.parametrize("val", ["0", "false", "", "no", "FALSE"])
    def test_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("ARIZE_DRY_RUN", val)
        from core.setup import dry_run

        assert dry_run() is False

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("ARIZE_DRY_RUN", raising=False)
        from core.setup import dry_run

        assert dry_run() is False


# ---------------------------------------------------------------------------
# ensure_shared_runtime()
# ---------------------------------------------------------------------------


class TestEnsureSharedRuntime:
    def test_creates_subdirs(self, fake_install):
        from core.setup import ensure_shared_runtime

        ensure_shared_runtime()

        assert (fake_install / "bin").is_dir()
        assert (fake_install / "run").is_dir()
        assert (fake_install / "logs").is_dir()
        assert (fake_install / "state").is_dir()

    def test_idempotent(self, fake_install):
        from core.setup import ensure_shared_runtime

        ensure_shared_runtime()
        ensure_shared_runtime()  # should not raise

        assert (fake_install / "bin").is_dir()

    def test_removes_legacy_artefacts(self, fake_install):
        from core.setup import ensure_shared_runtime

        # Create subdirs and legacy files
        for d in ("bin", "run", "logs"):
            (fake_install / d).mkdir(parents=True, exist_ok=True)
        (fake_install / "bin" / "arize-collector").write_text("legacy")
        (fake_install / "run" / "collector.pid").write_text("123")
        (fake_install / "logs" / "collector.log").write_text("log")

        ensure_shared_runtime()

        assert not (fake_install / "bin" / "arize-collector").exists()
        assert not (fake_install / "run" / "collector.pid").exists()
        assert not (fake_install / "logs" / "collector.log").exists()

    def test_dry_run_does_not_create(self, fake_install, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        from core.setup import ensure_shared_runtime

        ensure_shared_runtime()

        assert not (fake_install / "bin").exists()
        assert not (fake_install / "run").exists()


# ---------------------------------------------------------------------------
# venv_bin()
# ---------------------------------------------------------------------------


class TestVenvBin:
    def test_posix(self, fake_install, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        from core.setup import VENV_DIR, venv_bin

        result = venv_bin("foo")
        assert result == VENV_DIR / "bin" / "foo"

    def test_windows(self, fake_install, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        from core.setup import VENV_DIR, venv_bin

        result = venv_bin("foo")
        assert result == VENV_DIR / "Scripts" / "foo.exe"


# ---------------------------------------------------------------------------
# merge_harness_entry()
# ---------------------------------------------------------------------------


class TestMergeHarnessEntry:
    def test_creates_on_fresh_config(self, fake_install):
        from core.setup import merge_harness_entry

        merge_harness_entry("copilot", "my-copilot")

        config_path = fake_install / "config.yaml"
        assert config_path.exists()
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config["harnesses"]["copilot"]["project_name"] == "my-copilot"

    def test_preserves_existing_backend(self, fake_install, populated_config):
        from core.setup import merge_harness_entry

        merge_harness_entry("copilot", "my-copilot")

        with open(fake_install / "config.yaml") as f:
            config = yaml.safe_load(f)
        # Original backend preserved
        assert config["backend"]["target"] == "phoenix"
        # Original harness preserved
        assert config["harnesses"]["claude-code"]["project_name"] == "claude-code"
        # New harness added
        assert config["harnesses"]["copilot"]["project_name"] == "my-copilot"

    def test_per_harness_backend(self, fake_install):
        from core.setup import merge_harness_entry

        merge_harness_entry("copilot", "my-copilot", per_harness_backend={"target": "arize"})

        with open(fake_install / "config.yaml") as f:
            config = yaml.safe_load(f)
        assert config["harnesses"]["copilot"]["backend"] == {"target": "arize"}

    def test_dry_run_no_write(self, fake_install, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        from core.setup import merge_harness_entry

        merge_harness_entry("copilot", "my-copilot")

        assert not (fake_install / "config.yaml").exists()


# ---------------------------------------------------------------------------
# remove_harness_entry()
# ---------------------------------------------------------------------------


class TestRemoveHarnessEntry:
    def test_noop_missing_config(self, fake_install):
        from core.setup import remove_harness_entry

        # Should not raise
        remove_harness_entry("copilot")

    def test_removes_entry(self, fake_install, populated_config):
        from core.setup import remove_harness_entry

        remove_harness_entry("claude-code")

        with open(fake_install / "config.yaml") as f:
            config = yaml.safe_load(f)
        assert "claude-code" not in config.get("harnesses", {})

    def test_noop_missing_key(self, fake_install, populated_config):
        from core.setup import remove_harness_entry

        remove_harness_entry("nonexistent")

        with open(fake_install / "config.yaml") as f:
            config = yaml.safe_load(f)
        # Original entry still present
        assert "claude-code" in config["harnesses"]

    def test_dry_run_no_write(self, fake_install, populated_config, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        from core.setup import remove_harness_entry

        remove_harness_entry("claude-code")

        with open(fake_install / "config.yaml") as f:
            config = yaml.safe_load(f)
        # Entry should still be there
        assert "claude-code" in config["harnesses"]


# ---------------------------------------------------------------------------
# list_installed_harnesses()
# ---------------------------------------------------------------------------


class TestListInstalledHarnesses:
    def test_empty_on_missing_config(self, fake_install):
        from core.setup import list_installed_harnesses

        assert list_installed_harnesses() == []

    def test_returns_keys(self, fake_install, populated_config):
        from core.setup import list_installed_harnesses

        result = list_installed_harnesses()
        assert result == ["claude-code"]


# ---------------------------------------------------------------------------
# harness_dir()
# ---------------------------------------------------------------------------


class TestHarnessDir:
    def test_primary_path(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "copilot-tracing").mkdir()
        assert harness_dir("copilot") == fake_install / "copilot-tracing"

    def test_legacy_fallback(self, fake_install):
        from core.setup import harness_dir

        legacy = fake_install / "plugins" / "copilot-tracing"
        legacy.mkdir(parents=True)
        assert harness_dir("copilot") == legacy

    def test_defaults_to_primary(self, fake_install):
        from core.setup import harness_dir

        # Neither exists — returns primary path
        assert harness_dir("copilot") == fake_install / "copilot-tracing"


# ---------------------------------------------------------------------------
# symlink_skills() / unlink_skills()
# ---------------------------------------------------------------------------


class TestSymlinkSkills:
    def test_creates_symlink(self, fake_install, tmp_path):
        from core.setup import symlink_skills

        # Set up a harness with a skills dir
        hdir = fake_install / "copilot-tracing" / "skills"
        hdir.mkdir(parents=True)
        (hdir / "my-skill.md").write_text("skill content")

        target = tmp_path / "project"
        target.mkdir()

        symlink_skills("copilot", target_dir=target)

        link = target / ".agents" / "skills" / "my-skill.md"
        assert link.is_symlink()
        assert link.read_text() == "skill content"

    def test_idempotent(self, fake_install, tmp_path):
        from core.setup import symlink_skills

        hdir = fake_install / "copilot-tracing" / "skills"
        hdir.mkdir(parents=True)
        (hdir / "my-skill.md").write_text("skill content")

        target = tmp_path / "project"
        target.mkdir()

        symlink_skills("copilot", target_dir=target)
        symlink_skills("copilot", target_dir=target)  # should not raise

        link = target / ".agents" / "skills" / "my-skill.md"
        assert link.is_symlink()

    def test_no_skills_dir_noop(self, fake_install, tmp_path):
        from core.setup import symlink_skills

        (fake_install / "copilot-tracing").mkdir(parents=True)
        target = tmp_path / "project"
        target.mkdir()

        symlink_skills("copilot", target_dir=target)

        assert not (target / ".agents").exists()


class TestUnlinkSkills:
    def test_removes_symlink(self, fake_install, tmp_path):
        from core.setup import symlink_skills, unlink_skills

        hdir = fake_install / "copilot-tracing" / "skills"
        hdir.mkdir(parents=True)
        (hdir / "my-skill.md").write_text("skill content")

        target = tmp_path / "project"
        target.mkdir()

        symlink_skills("copilot", target_dir=target)
        unlink_skills("copilot", target_dir=target)

        link = target / ".agents" / "skills" / "my-skill.md"
        assert not link.exists()

    def test_preserves_regular_file(self, fake_install, tmp_path):
        from core.setup import unlink_skills

        hdir = fake_install / "copilot-tracing" / "skills"
        hdir.mkdir(parents=True)
        (hdir / "my-skill.md").write_text("source skill")

        target = tmp_path / "project"
        dest = target / ".agents" / "skills"
        dest.mkdir(parents=True)
        # Create a regular file with the same name
        (dest / "my-skill.md").write_text("user file")

        unlink_skills("copilot", target_dir=target)

        # Regular file should survive
        assert (dest / "my-skill.md").exists()
        assert not (dest / "my-skill.md").is_symlink()
        assert (dest / "my-skill.md").read_text() == "user file"

    def test_idempotent(self, fake_install, tmp_path):
        from core.setup import unlink_skills

        hdir = fake_install / "copilot-tracing" / "skills"
        hdir.mkdir(parents=True)
        (hdir / "my-skill.md").write_text("skill")

        target = tmp_path / "project"
        target.mkdir()

        # No links to remove — should not raise
        unlink_skills("copilot", target_dir=target)


# ---------------------------------------------------------------------------
# wipe_shared_runtime()
# ---------------------------------------------------------------------------


class TestWipeSharedRuntime:
    def test_removes_directory(self, fake_install):
        from core.setup.wipe import wipe_shared_runtime

        # Create some content
        (fake_install / "bin").mkdir(exist_ok=True)
        (fake_install / "config.yaml").write_text("test: true")

        wipe_shared_runtime()

        assert not fake_install.exists()

    def test_idempotent_missing_dir(self, fake_install):
        from core.setup.wipe import wipe_shared_runtime

        import shutil

        shutil.rmtree(fake_install)

        # Should not raise
        wipe_shared_runtime()

    def test_dry_run_preserves(self, fake_install, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        from core.setup.wipe import wipe_shared_runtime

        (fake_install / "config.yaml").write_text("test: true")

        wipe_shared_runtime()

        assert fake_install.exists()
        assert (fake_install / "config.yaml").exists()
