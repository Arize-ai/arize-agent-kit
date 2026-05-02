#!/usr/bin/env python3
"""Arize Gemini Tracing Plugin - Interactive Setup.

Entry point for ``arize-setup-gemini``.  Delegates to
``gemini_tracing/install.py`` for the actual install logic.
"""

from __future__ import annotations

import sys

from gemini_tracing import install as _install_mod


def install() -> None:
    """Delegate to gemini_tracing/install.py install()."""
    _install_mod.install()


def uninstall() -> None:
    """Delegate to gemini_tracing/install.py uninstall()."""
    _install_mod.uninstall()


def main() -> None:
    """Entry point for arize-setup-gemini."""
    try:
        _install_mod.install()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


if __name__ == "__main__":
    main()
