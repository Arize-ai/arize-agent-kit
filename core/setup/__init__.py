#!/usr/bin/env python3
"""Shared setup utilities for all harness setup wizards."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml  # noqa: F401  # presence check; writing configs needs PyYAML at runtime
except ImportError:
    sys.stderr.write("error: PyYAML not installed. Install it in the collector venv.\n")
    sys.exit(1)

from core.config import delete_value, load_config, save_config, set_value

# ---------------------------------------------------------------------------
# Shared path constants
# ---------------------------------------------------------------------------

INSTALL_DIR = Path.home() / ".arize" / "harness"
VENV_DIR = INSTALL_DIR / "venv"
CONFIG_FILE = INSTALL_DIR / "config.yaml"
BIN_DIR = INSTALL_DIR / "bin"
RUN_DIR = INSTALL_DIR / "run"
LOG_DIR = INSTALL_DIR / "logs"
STATE_DIR = INSTALL_DIR / "state"

# Legacy collector artefacts to clean up
_LEGACY_ARTEFACTS = ("bin/arize-collector", "run/collector.pid", "logs/collector.log")


# ---------------------------------------------------------------------------
# Output helpers (unchanged)
# ---------------------------------------------------------------------------


def print_color(msg: str, color: str = "") -> None:
    """Print with ANSI color. No-op on Windows if terminal doesn't support it."""
    codes = {
        "green": "\033[0;32m",
        "yellow": "\033[1;33m",
        "blue": "\033[0;34m",
        "red": "\033[0;31m",
    }
    nc = "\033[0m"

    use_color = color in codes and sys.stdout.isatty() and os.name != "nt"
    if use_color:
        print(f"{codes[color]}{msg}{nc}")
    else:
        print(msg)


def info(msg: str) -> None:
    """Print an info message with [arize] prefix."""
    if sys.stdout.isatty() and os.name != "nt":
        print(f"\033[0;32m[arize]\033[0m {msg}")
    else:
        print(f"[arize] {msg}")


def err(msg: str) -> None:
    """Print an error message with [arize] prefix to stderr."""
    if sys.stderr.isatty() and os.name != "nt":
        sys.stderr.write(f"\033[0;31m[arize]\033[0m {msg}\n")
    else:
        sys.stderr.write(f"[arize] {msg}\n")


# ---------------------------------------------------------------------------
# Harness presence check (soft signal)
# ---------------------------------------------------------------------------


def is_harness_installed(
    home_subdir: Optional[str] = None,
    bin_name: Optional[str] = None,
) -> bool:
    """True if ``~/<home_subdir>`` exists OR ``<bin_name>`` is on PATH.

    ``Path.home()`` is resolved at call time so tests can monkeypatch it.
    """
    if home_subdir and (Path.home() / home_subdir).exists():
        return True
    if bin_name and shutil.which(bin_name):
        return True
    return False


def ensure_harness_installed(
    display_name: str,
    home_subdir: Optional[str] = None,
    bin_name: Optional[str] = None,
) -> bool:
    """Soft check that the harness appears installed on this machine.

    If yes, return ``True`` silently.  If no, warn and either prompt the user
    (interactive) or proceed with a note (non-interactive).  Return ``True`` to
    proceed with install, ``False`` to abort.
    """
    if is_harness_installed(home_subdir=home_subdir, bin_name=bin_name):
        return True

    print_color(f"warning: {display_name} does not appear to be installed", "yellow")
    checks = []
    if home_subdir:
        checks.append(str(Path.home() / home_subdir))
    if bin_name:
        checks.append(f"'{bin_name}' on PATH")
    if checks:
        info(f"  (not found: {', '.join(checks)})")

    if not sys.stdout.isatty():
        info("  non-interactive — proceeding anyway")
        return True

    try:
        reply = input(f"Install tracing for {display_name} anyway? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return reply in ("y", "yes")


# ---------------------------------------------------------------------------
# Interactive prompts (unchanged)
# ---------------------------------------------------------------------------


def prompt_backend() -> tuple[str, dict]:
    """Interactive backend selection.

    Returns:
        ("phoenix", {"endpoint": "...", "api_key": ""})
        or ("arize", {"endpoint": "...", "api_key": "...", "space_id": "..."})
    """
    print("Which backend do you want to use?")
    print("")
    print("  1) Phoenix (self-hosted, no Python required)")
    print("  2) Arize AX (cloud, requires Python)")
    print("")
    choice = input("Enter choice [1/2]: ").strip()

    if choice in ("1", "phoenix", "Phoenix", ""):
        print("")
        phoenix_endpoint = input("Phoenix endpoint [http://localhost:6006]: ").strip()
        if not phoenix_endpoint:
            phoenix_endpoint = "http://localhost:6006"
        return ("phoenix", {"endpoint": phoenix_endpoint, "api_key": ""})

    elif choice in ("2", "arize", "ax", "AX"):
        print("")
        api_key = input("Arize API Key: ").strip()
        space_id = input("Arize Space ID: ").strip()

        if not api_key or not space_id:
            err("API key and Space ID are required for Arize AX")
            sys.exit(1)

        print("")
        if sys.stdout.isatty() and os.name != "nt":
            print("\033[1;33mOTLP Endpoint\033[0m (for hosted Arize instances, leave blank for default):")
        else:
            print("OTLP Endpoint (for hosted Arize instances, leave blank for default):")
        otlp_endpoint = input("OTLP Endpoint [otlp.arize.com:443]: ").strip()
        if not otlp_endpoint:
            otlp_endpoint = "otlp.arize.com:443"

        return (
            "arize",
            {
                "endpoint": otlp_endpoint,
                "api_key": api_key,
                "space_id": space_id,
            },
        )

    else:
        err("Invalid choice. Run setup again.")
        sys.exit(1)


def prompt_project_name(default: str) -> str:
    """Prompt for project name. Returns default if blank."""
    print("")
    name = input(f"Project name [{default}]: ").strip()
    return name if name else default


def prompt_user_id() -> str:
    """Optional user ID prompt. Returns "" if skipped."""
    print("")
    if sys.stdout.isatty() and os.name != "nt":
        print("\033[0;34mOptional:\033[0m Set a user ID to identify your spans (useful for teams).")
    else:
        print("Optional: Set a user ID to identify your spans (useful for teams).")
    user_id = input("User ID (leave blank to skip): ").strip()
    return user_id


def write_config(
    target: str,
    credentials: dict,
    harness_name: str,
    project_name: str,
    user_id: str = "",
    config_path: Optional[str] = None,
) -> None:
    """Write or merge config.yaml with backend credentials and harness entry.

    If config.yaml exists with valid backend, only add/update the harness entry.
    If no config, create fresh with all fields.
    """
    config = load_config(config_path)

    if not config:
        # Fresh config
        config = {
            "collector": {
                "host": "127.0.0.1",
                "port": 4318,
            },
            "backend": {
                "target": target,
            },
            "harnesses": {},
        }

        if target == "phoenix":
            config["backend"]["phoenix"] = {
                "endpoint": credentials.get("endpoint", "http://localhost:6006"),
                "api_key": credentials.get("api_key", ""),
            }
            config["backend"]["arize"] = {
                "endpoint": "otlp.arize.com:443",
                "api_key": "",
                "space_id": "",
            }
        else:
            config["backend"]["phoenix"] = {
                "endpoint": "http://localhost:6006",
                "api_key": "",
            }
            config["backend"]["arize"] = {
                "endpoint": credentials.get("endpoint", "otlp.arize.com:443"),
                "api_key": credentials.get("api_key", ""),
                "space_id": credentials.get("space_id", ""),
            }

    # Add/update harness entry
    set_value(config, f"harnesses.{harness_name}.project_name", project_name)

    if user_id:
        set_value(config, "user_id", user_id)

    save_config(config, config_path)


# ---------------------------------------------------------------------------
# New shared helpers
# ---------------------------------------------------------------------------


def dry_run() -> bool:
    """True when ARIZE_DRY_RUN env var is set to a truthy value ('1','true','yes')."""
    return os.environ.get("ARIZE_DRY_RUN", "").lower() in ("1", "true", "yes")


def ensure_shared_runtime() -> None:
    """Create ~/.arize/harness/{bin,run,logs,state} if missing. Idempotent.

    Also removes any legacy collector artefacts (bin/arize-collector,
    run/collector.pid, logs/collector.log) left over from pre-buffer-service
    installs.
    """
    install_dir = INSTALL_DIR
    subdirs = [BIN_DIR, RUN_DIR, LOG_DIR, STATE_DIR]

    for d in subdirs:
        if not d.exists():
            if dry_run():
                info(f"would create {d}")
            else:
                d.mkdir(parents=True, exist_ok=True)

    # Remove legacy collector artefacts
    for rel in _LEGACY_ARTEFACTS:
        legacy = install_dir / rel
        if legacy.exists():
            if dry_run():
                info(f"would remove legacy artefact {legacy}")
            else:
                legacy.unlink()


def venv_bin(name: str) -> Path:
    """Return the full path to a venv binary.

    On POSIX: VENV_DIR/bin/<name>. On Windows: VENV_DIR/Scripts/<name>.exe.
    Does NOT verify the file exists.
    """
    if os.name == "nt":
        return VENV_DIR / "Scripts" / f"{name}.exe"
    return VENV_DIR / "bin" / name


def merge_harness_entry(
    name: str,
    project_name: str,
    per_harness_backend: dict | None = None,
) -> None:
    """Read config.yaml, add/update harnesses.<name>, write back with 0o600.

    If the file doesn't exist yet, create a minimal one with just the harness
    entry (no backend block).
    """
    config_path = str(CONFIG_FILE)
    config = load_config(config_path)

    if not config:
        config = {"harnesses": {}}

    set_value(config, f"harnesses.{name}.project_name", project_name)

    if per_harness_backend is not None:
        set_value(config, f"harnesses.{name}.backend", per_harness_backend)

    if dry_run():
        info(f"would write harness entry '{name}' to {config_path}")
        return

    save_config(config, config_path)


def remove_harness_entry(name: str) -> None:
    """Read config.yaml, remove harnesses.<name> if present, write back.

    No-op if the file doesn't exist or the key isn't present.
    """
    config_path = str(CONFIG_FILE)
    config = load_config(config_path)

    if not config:
        return

    harnesses = config.get("harnesses")
    if not isinstance(harnesses, dict) or name not in harnesses:
        return

    if dry_run():
        info(f"would remove harness entry '{name}' from {config_path}")
        return

    delete_value(config, f"harnesses.{name}")
    save_config(config, config_path)


def list_installed_harnesses() -> list[str]:
    """Return the list of keys under harnesses.* in config.yaml.

    Returns empty list if config is missing.
    """
    config_path = str(CONFIG_FILE)
    config = load_config(config_path)

    if not config:
        return []

    harnesses = config.get("harnesses")
    if not isinstance(harnesses, dict):
        return []

    return list(harnesses.keys())


def harness_dir(harness: str) -> Path:
    """Return the absolute path of <install-dir>/<harness>-tracing/.

    Prefers ~/.arize/harness/<harness>-tracing, falls back to
    ~/.arize/harness/plugins/<harness>-tracing (legacy plugin layout).
    """
    primary = INSTALL_DIR / f"{harness}-tracing"
    if primary.is_dir():
        return primary

    legacy = INSTALL_DIR / "plugins" / f"{harness}-tracing"
    if legacy.is_dir():
        return legacy

    # Default to primary even if it doesn't exist yet
    return primary


def symlink_skills(harness: str, target_dir: Path | None = None) -> None:
    """Symlink <install-dir>/<harness>-tracing/skills/* into target_dir/.agents/skills/.

    target_dir defaults to the current working directory. Idempotent (skip
    existing links pointing at the right target). Does nothing if the harness
    has no skills/ directory.
    """
    hdir = harness_dir(harness)
    skills_src = hdir / "skills"

    if not skills_src.is_dir():
        return

    if target_dir is None:
        target_dir = Path.cwd()

    dest = target_dir / ".agents" / "skills"

    if dry_run():
        for item in skills_src.iterdir():
            info(f"would symlink {dest / item.name} -> {item}")
        return

    dest.mkdir(parents=True, exist_ok=True)

    for item in skills_src.iterdir():
        link = dest / item.name
        if link.is_symlink():
            if link.resolve() == item.resolve():
                continue  # already correct
            link.unlink()
        elif link.exists():
            continue  # regular file — don't overwrite
        link.symlink_to(item)


def unlink_skills(harness: str, target_dir: Path | None = None) -> None:
    """Remove symlinks created by symlink_skills() for <harness>.

    Only removes symlinks, never regular files. Idempotent.
    """
    hdir = harness_dir(harness)
    skills_src = hdir / "skills"

    if not skills_src.is_dir():
        return

    if target_dir is None:
        target_dir = Path.cwd()

    dest = target_dir / ".agents" / "skills"

    if not dest.is_dir():
        return

    for item in skills_src.iterdir():
        link = dest / item.name
        if link.is_symlink():
            if dry_run():
                info(f"would unlink {link}")
            else:
                link.unlink()
