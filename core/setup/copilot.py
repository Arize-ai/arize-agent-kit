#!/usr/bin/env python3
"""Arize Copilot Tracing Plugin - Interactive Setup.

Configures tracing for GitHub Copilot in both VS Code and CLI modes.
Writes config.yaml to ~/.arize/harness/config.yaml and installs hooks
into .github/hooks/ (project-local).

The ``arize-setup-copilot`` entry point calls ``main()`` here, which runs the
legacy interactive wizard.  The new ``copilot-tracing/install.py`` module
provides the decomposed ``install()`` / ``uninstall()`` API used by the
shell router.  ``install()`` and ``uninstall()`` below delegate to it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Delegation to copilot-tracing/install.py
# ---------------------------------------------------------------------------

def _load_installer():
    """Lazily import copilot-tracing/install.py (hyphenated dir)."""
    install_py = Path(__file__).resolve().parent.parent.parent / "copilot-tracing" / "install.py"
    spec = importlib.util.spec_from_file_location("_copilot_install", install_py)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_copilot_mod = None


def _get_copilot_mod():
    global _copilot_mod
    if _copilot_mod is None:
        _copilot_mod = _load_installer()
    return _copilot_mod


def install() -> None:
    """Delegate to copilot-tracing/install.py install()."""
    _get_copilot_mod().install()


def uninstall() -> None:
    """Delegate to copilot-tracing/install.py uninstall()."""
    _get_copilot_mod().uninstall()


def main() -> None:
    """Entry point for arize-setup-copilot."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the new install module in copilot-tracing/.

    This replaces the old interactive flow so that ``arize-setup-copilot``
    and the installer router share a single code path.
    """
    installer = _load_installer()
    installer.install()


if __name__ == "__main__":
    main()
