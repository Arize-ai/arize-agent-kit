"""Tests for install.sh — the native bash installer."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_BAT = REPO_ROOT / "install.bat"


# ---------------------------------------------------------------------------
# File existence and basic validity
# ---------------------------------------------------------------------------

def test_install_sh_exists():
    """install.sh must exist at repo root."""
    assert INSTALL_SH.is_file()


def test_install_bat_exists():
    """install.bat must exist at repo root."""
    assert INSTALL_BAT.is_file()


def test_install_sh_is_executable():
    """install.sh must be executable."""
    assert os.access(INSTALL_SH, os.X_OK)


def test_install_sh_has_bash_shebang():
    """install.sh must start with a bash shebang."""
    first_line = INSTALL_SH.read_text().splitlines()[0]
    assert first_line.startswith("#!/bin/bash"), f"Expected bash shebang, got: {first_line}"


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_syntax_valid():
    """install.sh must parse without syntax errors."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"Bash syntax error: {result.stderr}"


# ---------------------------------------------------------------------------
# Help / usage
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_help():
    """install.sh --help exits 0 and shows usage."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_no_args_exits_nonzero():
    """install.sh with no arguments should exit with error."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_unknown_command_exits_nonzero():
    """install.sh with unknown command should exit with error."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "bogus"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Script content checks
# ---------------------------------------------------------------------------

def test_install_sh_has_all_commands():
    """install.sh must support claude, codex, cursor, update, uninstall."""
    text = INSTALL_SH.read_text()
    for cmd in ["claude", "codex", "cursor", "update", "uninstall"]:
        assert cmd in text, f"Missing command: {cmd}"


def test_install_sh_existing_repo_syncs_requested_branch():
    """Existing harness git dir must fetch/checkout INSTALL_BRANCH, not only git pull."""
    text = INSTALL_SH.read_text()
    assert "syncing with origin/" in text.lower()
    assert "checkout -B" in text and "FETCH_HEAD" in text


def test_install_sh_venv_checks_package_and_cli():
    """Venv fast-path must verify package import + arize-install console script."""
    text = INSTALL_SH.read_text()
    assert '"import core"' in text
    assert "arize-install" in text


def test_install_sh_delegates_to_arize_install():
    """install.sh must delegate to arize-install Python CLI for all configuration."""
    text = INSTALL_SH.read_text()
    assert "arize-install" in text
    assert "exec" in text


def test_install_sh_uses_pip_install_package():
    """install.sh must install the package via pip (not just individual deps)."""
    text = INSTALL_SH.read_text()
    assert 'pip" install' in text or "pip install" in text


def test_install_sh_no_jq_dependency():
    """install.sh must not require jq (uses Python for JSON instead)."""
    text = INSTALL_SH.read_text()
    # Should not have jq as a required dependency check
    assert "jq is required" not in text


def test_install_sh_does_not_reference_install_py():
    """install.sh must not reference install.py."""
    text = INSTALL_SH.read_text()
    assert "install.py" not in text


def test_install_bat_has_all_commands():
    """install.bat must support claude, codex, cursor, update, uninstall."""
    text = INSTALL_BAT.read_text()
    for cmd in ["claude", "codex", "cursor", "update", "uninstall"]:
        assert cmd.lower() in text.lower(), f"Missing command: {cmd}"


def test_install_bat_does_not_reference_install_py():
    """install.bat must not reference install.py."""
    text = INSTALL_BAT.read_text()
    assert "install.py" not in text


def test_install_bat_delegates_to_arize_install():
    """Windows installer must delegate to arize-install.exe for all configuration."""
    text = INSTALL_BAT.read_text()
    assert "arize-install" in text
    assert "ARIZE_INSTALL" in text


def test_install_bat_venv_fast_path_checks_cli():
    """Windows venv fast-path must check arize-install.exe exists before skipping setup."""
    text = INSTALL_BAT.read_text()
    assert "arize-install.exe" in text
