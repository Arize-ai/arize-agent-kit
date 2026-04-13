"""Tests for core/installer/harnesses/base.py — HarnessInstaller base class."""

import yaml
import pytest

from core.installer.harnesses.base import HarnessInstaller


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestInit:
    def test_sets_harness_name(self):
        h = HarnessInstaller("claude-code")
        assert h.harness_name == "claude-code"

    def test_default_config_path_is_none(self):
        h = HarnessInstaller("codex")
        assert h._config_path is None

    def test_custom_config_path(self, tmp_path):
        path = str(tmp_path / "custom.yaml")
        h = HarnessInstaller("cursor", config_path=path)
        assert h._config_path == path


# ---------------------------------------------------------------------------
# Abstract interface — subclasses must implement
# ---------------------------------------------------------------------------


class TestNotImplemented:
    def test_install_raises(self):
        h = HarnessInstaller("test")
        with pytest.raises(NotImplementedError):
            h.install()

    def test_uninstall_raises(self):
        h = HarnessInstaller("test")
        with pytest.raises(NotImplementedError):
            h.uninstall()

    def test_is_installed_raises(self):
        h = HarnessInstaller("test")
        with pytest.raises(NotImplementedError):
            h.is_installed()

    def test_get_status_raises(self):
        h = HarnessInstaller("test")
        with pytest.raises(NotImplementedError):
            h.get_status()


# ---------------------------------------------------------------------------
# _add_harness_to_config
# ---------------------------------------------------------------------------


class TestAddHarnessToConfig:
    def test_adds_to_empty_config(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        h = HarnessInstaller("claude-code", config_path=path)
        h._add_harness_to_config("my-project")

        data = yaml.safe_load(open(path))
        assert data["harnesses"]["claude-code"]["project_name"] == "my-project"

    def test_adds_second_harness(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        # Pre-populate with one harness
        initial = {"harnesses": {"codex": {"project_name": "codex-proj"}}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        h._add_harness_to_config("claude-proj")

        data = yaml.safe_load(open(path))
        assert data["harnesses"]["codex"]["project_name"] == "codex-proj"
        assert data["harnesses"]["claude-code"]["project_name"] == "claude-proj"

    def test_overwrites_existing_project_name(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"harnesses": {"cursor": {"project_name": "old"}}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("cursor", config_path=path)
        h._add_harness_to_config("new")

        data = yaml.safe_load(open(path))
        assert data["harnesses"]["cursor"]["project_name"] == "new"

    def test_preserves_other_config_keys(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"collector": {"port": 4318}, "backend": {"target": "phoenix"}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("codex", config_path=path)
        h._add_harness_to_config("codex-proj")

        data = yaml.safe_load(open(path))
        assert data["collector"]["port"] == 4318
        assert data["backend"]["target"] == "phoenix"
        assert data["harnesses"]["codex"]["project_name"] == "codex-proj"


# ---------------------------------------------------------------------------
# _remove_harness_from_config
# ---------------------------------------------------------------------------


class TestRemoveHarnessFromConfig:
    def test_removes_harness(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {
            "harnesses": {
                "claude-code": {"project_name": "proj1"},
                "codex": {"project_name": "proj2"},
            }
        }
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        h._remove_harness_from_config()

        data = yaml.safe_load(open(path))
        assert "claude-code" not in data["harnesses"]
        assert data["harnesses"]["codex"]["project_name"] == "proj2"

    def test_cleans_up_empty_harnesses_dict(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"harnesses": {"cursor": {"project_name": "proj"}}, "backend": {"target": "local"}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("cursor", config_path=path)
        h._remove_harness_from_config()

        data = yaml.safe_load(open(path))
        assert "harnesses" not in data
        assert data["backend"]["target"] == "local"

    def test_noop_if_harness_not_present(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"harnesses": {"codex": {"project_name": "proj"}}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        h._remove_harness_from_config()

        data = yaml.safe_load(open(path))
        # codex should still be there
        assert data["harnesses"]["codex"]["project_name"] == "proj"

    def test_noop_on_empty_config(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        h = HarnessInstaller("codex", config_path=path)
        h._remove_harness_from_config()
        # File was created (save_config creates it) but should be empty/minimal
        data = yaml.safe_load(open(path))
        assert data == {} or data is None


# ---------------------------------------------------------------------------
# _check_last_harness
# ---------------------------------------------------------------------------


class TestCheckLastHarness:
    def test_true_when_only_harness(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"harnesses": {"claude-code": {"project_name": "proj"}}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        assert h._check_last_harness() is True

    def test_false_when_multiple_harnesses(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {
            "harnesses": {
                "claude-code": {"project_name": "proj1"},
                "codex": {"project_name": "proj2"},
            }
        }
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        assert h._check_last_harness() is False

    def test_true_when_no_harnesses_key(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"backend": {"target": "local"}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("codex", config_path=path)
        assert h._check_last_harness() is True

    def test_true_when_empty_config(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        h = HarnessInstaller("cursor", config_path=path)
        assert h._check_last_harness() is True

    def test_false_when_different_harness_only(self, tmp_path):
        """When only a *different* harness is present, not the last of *this* one."""
        path = str(tmp_path / "config.yaml")
        initial = {"harnesses": {"codex": {"project_name": "proj"}}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        assert h._check_last_harness() is False


# ---------------------------------------------------------------------------
# Round-trip: add then remove
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_add_then_remove_leaves_clean_config(self, tmp_path):
        path = str(tmp_path / "config.yaml")
        initial = {"backend": {"target": "phoenix"}}
        with open(path, "w") as f:
            yaml.safe_dump(initial, f)

        h = HarnessInstaller("claude-code", config_path=path)
        h._add_harness_to_config("my-project")

        data = yaml.safe_load(open(path))
        assert "claude-code" in data["harnesses"]

        h._remove_harness_from_config()
        data = yaml.safe_load(open(path))
        assert "harnesses" not in data
        assert data["backend"]["target"] == "phoenix"

    def test_add_multiple_remove_one(self, tmp_path):
        path = str(tmp_path / "config.yaml")

        h1 = HarnessInstaller("claude-code", config_path=path)
        h2 = HarnessInstaller("codex", config_path=path)

        h1._add_harness_to_config("proj-claude")
        h2._add_harness_to_config("proj-codex")

        data = yaml.safe_load(open(path))
        assert len(data["harnesses"]) == 2

        h1._remove_harness_from_config()
        data = yaml.safe_load(open(path))
        assert "claude-code" not in data["harnesses"]
        assert data["harnesses"]["codex"]["project_name"] == "proj-codex"

    def test_check_last_during_sequential_removal(self, tmp_path):
        path = str(tmp_path / "config.yaml")

        h1 = HarnessInstaller("claude-code", config_path=path)
        h2 = HarnessInstaller("codex", config_path=path)

        h1._add_harness_to_config("proj1")
        h2._add_harness_to_config("proj2")

        assert h1._check_last_harness() is False
        assert h2._check_last_harness() is False

        h1._remove_harness_from_config()
        assert h2._check_last_harness() is True


# ---------------------------------------------------------------------------
# Import verification
# ---------------------------------------------------------------------------


class TestImports:
    """Verify that the module imports expected config helpers."""

    def test_config_helpers_imported(self):
        from core.installer.harnesses import base
        assert hasattr(base, "load_config")
        assert hasattr(base, "save_config")
        assert hasattr(base, "get_value")
        assert hasattr(base, "set_value")
        assert hasattr(base, "delete_value")

    def test_init_packages_importable(self):
        import core.installer
        import core.installer.harnesses
        # Packages should be importable (empty __init__.py)
        assert core.installer is not None
        assert core.installer.harnesses is not None
