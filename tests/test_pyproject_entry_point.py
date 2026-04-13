"""Tests for pyproject.toml — arize-install entry point and package discovery."""

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject_data():
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Entry point declaration
# ---------------------------------------------------------------------------


class TestArizeInstallEntryPoint:
    """Verify [project.scripts] declares arize-install correctly."""

    def test_arize_install_declared(self, pyproject_data):
        scripts = pyproject_data.get("project", {}).get("scripts", {})
        assert "arize-install" in scripts, "arize-install not in [project.scripts]"

    def test_arize_install_points_to_cli_main(self, pyproject_data):
        scripts = pyproject_data["project"]["scripts"]
        assert scripts["arize-install"] == "core.installer.cli:main"

    def test_cli_module_importable(self):
        """core.installer.cli must be importable."""
        mod = importlib.import_module("core.installer.cli")
        assert hasattr(mod, "main"), "core.installer.cli has no main() function"

    def test_main_is_callable(self):
        from core.installer.cli import main
        assert callable(main)


# ---------------------------------------------------------------------------
# Package inclusion — setuptools find config
# ---------------------------------------------------------------------------


class TestPackageInclusion:
    """Verify [tool.setuptools.packages.find] covers installer subpackages."""

    def test_include_pattern_present(self, pyproject_data):
        find_cfg = pyproject_data["tool"]["setuptools"]["packages"]["find"]
        assert "include" in find_cfg

    def test_core_star_in_include(self, pyproject_data):
        include = pyproject_data["tool"]["setuptools"]["packages"]["find"]["include"]
        assert "core*" in include

    @pytest.mark.parametrize("pkg", [
        "core",
        "core.installer",
        "core.installer.harnesses",
    ])
    def test_core_star_matches_subpackages(self, pyproject_data, pkg):
        """Ensure the 'core*' glob covers all installer subpackages."""
        import fnmatch
        include = pyproject_data["tool"]["setuptools"]["packages"]["find"]["include"]
        matched = any(fnmatch.fnmatch(pkg, pat) for pat in include)
        assert matched, f"{pkg} not matched by include patterns {include}"


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


class TestInstallerModuleStructure:
    """Verify the installer package files exist and are importable."""

    def test_installer_init_exists(self):
        assert (PYPROJECT.parent / "core" / "installer" / "__init__.py").is_file()

    def test_installer_cli_exists(self):
        assert (PYPROJECT.parent / "core" / "installer" / "cli.py").is_file()

    def test_installer_package_importable(self):
        mod = importlib.import_module("core.installer")
        assert mod is not None

    def test_cli_build_parser_exists(self):
        from core.installer.cli import build_parser
        parser = build_parser()
        assert parser.prog == "arize-install"


# ---------------------------------------------------------------------------
# CLI --help smoke test (subprocess)
# ---------------------------------------------------------------------------


class TestCLIHelpSmoke:
    """Run 'python -m core.installer --help' as a subprocess smoke test."""

    def test_module_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.installer", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "arize-install" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_help_lists_subcommands(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.installer", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        for cmd in ("claude", "codex", "cursor", "uninstall", "status", "collector"):
            assert cmd in result.stdout, f"subcommand '{cmd}' not in --help output"

    def test_no_args_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.installer"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0
