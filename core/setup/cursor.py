#!/usr/bin/env python3
"""Arize Cursor Tracing - Interactive Setup.

Entry point for ``arize-setup-cursor``.  The heavy lifting now lives in
``tracing/cursor/install.py``; this module is kept for backwards
compatibility with the existing entry point.
"""

from __future__ import annotations

import sys

from tracing.cursor import install as _install_mod


def main() -> None:
    """Entry point for arize-setup-cursor."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the install module in tracing/cursor/.

    This replaces the old interactive flow so that ``arize-setup-cursor``
    and the installer router share a single code path.
    """
    _install_mod.install(with_skills=False)


if __name__ == "__main__":
    main()
