#!/usr/bin/env python3
"""Shared setup utilities for all harness setup wizards."""

import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("error: PyYAML not installed. Install it in the collector venv.\n")
    sys.exit(1)

from core.config import load_config, save_config, set_value


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

        return ("arize", {
            "endpoint": otlp_endpoint,
            "api_key": api_key,
            "space_id": space_id,
        })

    else:
        err("Invalid choice. Run setup again.")
        sys.exit(1)


def prompt_user_id() -> str:
    """Optional user ID prompt. Returns "" if skipped."""
    print("")
    if sys.stdout.isatty() and os.name != "nt":
        print("\033[0;34mOptional:\033[0m Set a user ID to identify your spans (useful for teams).")
    else:
        print("Optional: Set a user ID to identify your spans (useful for teams).")
    user_id = input("User ID (leave blank to skip): ").strip()
    return user_id


def write_config(target: str, credentials: dict, harness_name: str,
                 project_name: str, user_id: str = "",
                 config_path: str = None) -> None:
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
