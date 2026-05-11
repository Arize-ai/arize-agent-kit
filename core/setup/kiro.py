#!/usr/bin/env python3
"""Arize Kiro Tracing - Interactive Setup.

Entry point for ``arize-setup-kiro``. The heavy lifting lives in
``tracing/kiro/install.py``; this module is a thin shim for the
``arize-setup-kiro`` console script.
"""

from __future__ import annotations

import sys

from tracing.kiro import install as _install_mod


def main() -> None:
    """Entry point for arize-setup-kiro."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the install module in tracing/kiro/."""
    _install_mod.install(with_skills=False)


if __name__ == "__main__":
    main()
