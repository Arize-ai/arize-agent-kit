#!/usr/bin/env python3
"""Arize Gemini Tracing Plugin - Interactive Setup.

Configures tracing for Gemini CLI.
Writes config.yaml to ~/.arize/harness/config.yaml and installs hooks
into ~/.gemini/settings.json.

The ``arize-setup-gemini`` entry point calls ``main()`` here, which runs the
legacy interactive wizard.  The new ``gemini_tracing/install.py`` module
provides the decomposed ``install()`` / ``uninstall()`` API used by the
shell router.  ``install()`` and ``uninstall()`` below delegate to it.
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
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the install module in gemini_tracing/.

    This replaces the old interactive flow so that ``arize-setup-gemini``
    and the installer router share a single code path.
    """
    _install_mod.install()


if __name__ == "__main__":
    main()
