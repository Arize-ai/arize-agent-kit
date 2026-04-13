#!/usr/bin/env python3
"""OS, IDE, and Python detection utilities for arize-install.

All functions are cross-platform (macOS, Linux, Windows) and use only the
standard library.  Paths come from core.constants where applicable.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Python discovery
# ---------------------------------------------------------------------------

def check_python_version(python_path: str) -> bool:
    """Return True if *python_path* points to Python >= 3.9."""
    try:
        result = subprocess.run(
            [python_path, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return False
        major, minor = int(parts[0]), int(parts[1])
        return major == 3 and minor >= 9
    except (subprocess.SubprocessError, FileNotFoundError, ValueError, OSError):
        return False


def find_python() -> "str | None":
    """Locate a Python >= 3.9 interpreter on the system.

    Check candidates in order:
      1. python3 / python on PATH
      2. Platform-specific well-known paths
      3. pyenv shims
      4. conda base python
    Returns the first match, or None.
    """
    candidates: list[str] = []

    # 1. PATH candidates
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # 2. Platform-specific paths
    system = platform.system()
    if system == "Darwin":
        for p in (
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        ):
            if os.path.isfile(p):
                candidates.append(p)
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            py_dir = Path(local) / "Programs" / "Python"
            if py_dir.is_dir():
                # Sort descending so newest version is tried first
                for d in sorted(py_dir.iterdir(), reverse=True):
                    exe = d / "python.exe"
                    if exe.is_file():
                        candidates.append(str(exe))
    else:
        # Linux
        for p in ("/usr/bin/python3", "/usr/local/bin/python3"):
            if os.path.isfile(p):
                candidates.append(p)

    # 3. pyenv
    pyenv_root = os.environ.get("PYENV_ROOT", str(Path.home() / ".pyenv"))
    pyenv_shim = Path(pyenv_root) / "shims" / "python3"
    if pyenv_shim.is_file():
        candidates.append(str(pyenv_shim))

    # 4. conda
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        if system == "Windows":
            conda_py = Path(conda_prefix) / "python.exe"
        else:
            conda_py = Path(conda_prefix) / "bin" / "python3"
        if conda_py.is_file():
            candidates.append(str(conda_py))

    # De-duplicate while preserving order
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if check_python_version(candidate):
            return candidate

    return None


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> dict:
    """Return a dict describing the current platform.

    Keys: os, arch, python_version, hostname.
    """
    system = platform.system().lower()
    os_name = {"darwin": "darwin", "linux": "linux", "windows": "win32"}.get(system, system)

    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    return {
        "os": os_name,
        "arch": arch,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "hostname": platform.node(),
    }


# ---------------------------------------------------------------------------
# IDE / harness detection
# ---------------------------------------------------------------------------

def detect_ides() -> "dict[str, bool]":
    """Check whether known harnesses are installed.

    Returns ``{"claude": bool, "codex": bool, "cursor": bool}``.
    """
    return {
        "claude": _detect_claude(),
        "codex": _detect_codex(),
        "cursor": _detect_cursor(),
    }


def _detect_claude() -> bool:
    """Claude Code: check for ~/.claude/ directory or `claude` on PATH."""
    if (Path.home() / ".claude").is_dir():
        return True
    return shutil.which("claude") is not None


def _detect_codex() -> bool:
    """Codex CLI: check for ~/.codex/ directory or `codex` on PATH."""
    if (Path.home() / ".codex").is_dir():
        return True
    return shutil.which("codex") is not None


def _detect_cursor() -> bool:
    """Cursor: check for ~/.cursor/ or platform-specific app paths."""
    if (Path.home() / ".cursor").is_dir():
        return True
    system = platform.system()
    if system == "Darwin":
        return Path("/Applications/Cursor.app").exists()
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local and (Path(local) / "Programs" / "Cursor" / "Cursor.exe").exists():
            return True
    # Linux — check PATH
    return shutil.which("cursor") is not None
