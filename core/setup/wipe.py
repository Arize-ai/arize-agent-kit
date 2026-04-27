#!/usr/bin/env python3
"""Full teardown: remove venv, repo, shared config, run/logs/state."""

from __future__ import annotations

import shutil

from core.setup import INSTALL_DIR, dry_run, info


def wipe_shared_runtime() -> None:
    """Remove ~/.arize/harness entirely.

    Respects ARIZE_DRY_RUN. Does NOT touch harness-specific config files
    (~/.claude/settings.json, .github/hooks/*, ~/.codex/config.toml,
    ~/.cursor/hooks.json) — those belong to per-harness uninstall.
    """
    install_dir = INSTALL_DIR

    if not install_dir.exists():
        info(f"{install_dir} does not exist, nothing to wipe")
        return

    if dry_run():
        info(f"would remove {install_dir}")
        return

    shutil.rmtree(install_dir)
    info(f"removed {install_dir}")


if __name__ == "__main__":
    wipe_shared_runtime()
