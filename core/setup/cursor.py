#!/usr/bin/env python3
"""Arize Cursor Tracing - Interactive Setup.

Entry point for ``arize-setup-cursor``.  The heavy lifting now lives in
``cursor-tracing/install.py``; this module is kept for backwards
compatibility with the existing entry point.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> None:
    """Entry point for arize-setup-cursor."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the new install module in cursor-tracing/.

    This replaces the old interactive flow so that ``arize-setup-cursor``
    and the installer router share a single code path.
    """
    plugin_dir = Path(__file__).resolve().parents[2] / "cursor-tracing"
    mod_name = "cursor_tracing_install"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        spec = importlib.util.spec_from_file_location(mod_name, plugin_dir / "install.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

    mod.install(with_skills=False)


if __name__ == "__main__":
    main()
