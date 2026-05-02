"""Arize Gemini Tracing Plugin - Setup.

The ``arize-setup-gemini`` entry point calls ``main()`` here.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Entry point for arize-setup-gemini."""
    try:
        print("Gemini tracing setup is not yet implemented.")
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


if __name__ == "__main__":
    main()
