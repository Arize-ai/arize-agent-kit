#!/usr/bin/env python3
"""arize-install — unified CLI for configuring Arize Agent Kit harnesses.

Subcommands:
    claude / codex / cursor   Install & configure a harness
    uninstall                  Remove one or all harnesses
    status                     Print installed state as JSON
    collector                  start / stop / status / restart
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from core.config import (
    delete_value,
    get_value,
    load_config,
    save_config,
)
from core.collector_ctl import (
    collector_start,
    collector_status,
    collector_stop,
)
from core.constants import BASE_DIR, CONFIG_FILE
from core.setup import (
    err,
    info,
    prompt_backend,
    prompt_user_id,
    write_config,
)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_ARGS = 2


# ---------------------------------------------------------------------------
# Harness install helpers
# ---------------------------------------------------------------------------

def _resolve_backend(args: argparse.Namespace) -> "tuple[str, dict]":
    """Return (target, credentials) from CLI flags or interactive prompts.

    In non-interactive mode, missing required args cause exit(2).
    """
    if args.non_interactive:
        if not args.backend:
            err("--backend is required in non-interactive mode")
            sys.exit(EXIT_MISSING_ARGS)
        target = args.backend
        if target == "arize":
            if not args.api_key or not args.space_id:
                err("--api-key and --space-id are required for arize backend in non-interactive mode")
                sys.exit(EXIT_MISSING_ARGS)
            credentials = {
                "endpoint": args.otlp_endpoint or "otlp.arize.com:443",
                "api_key": args.api_key,
                "space_id": args.space_id,
            }
        else:
            credentials = {
                "endpoint": args.phoenix_endpoint or "http://localhost:6006",
                "api_key": "",
            }
        return target, credentials
    else:
        return prompt_backend()


def _resolve_user_id(args: argparse.Namespace) -> str:
    """Return user_id from flag or interactive prompt."""
    if args.non_interactive:
        return args.user_id or ""
    return args.user_id or prompt_user_id()


# ---------------------------------------------------------------------------
# Harness-specific setup adapters
# ---------------------------------------------------------------------------

def _setup_claude(args: argparse.Namespace) -> None:
    """Configure Claude Code harness."""
    from core.setup.claude import (
        _ensure_settings_file,
        _load_settings,
        _save_settings,
    )

    target, credentials = _resolve_backend(args)
    user_id = _resolve_user_id(args)

    # Determine settings scope
    scope = getattr(args, "scope", None) or "local"
    if scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path(".claude") / "settings.local.json"

    # Write env vars to settings.json
    _ensure_settings_file(settings_path)
    settings = _load_settings(settings_path)
    env_block = settings.setdefault("env", {})

    if target == "phoenix":
        env_block["PHOENIX_ENDPOINT"] = credentials["endpoint"]
        env_block["ARIZE_TRACE_ENABLED"] = "true"
    else:
        env_block["ARIZE_API_KEY"] = credentials["api_key"]
        env_block["ARIZE_SPACE_ID"] = credentials["space_id"]
        env_block["ARIZE_OTLP_ENDPOINT"] = credentials["endpoint"]
        env_block["ARIZE_TRACE_ENABLED"] = "true"

    if user_id:
        env_block["ARIZE_USER_ID"] = user_id

    _save_settings(settings_path, settings)

    # Write shared config.yaml
    write_config(target, credentials, "claude-code", "claude-code", user_id=user_id)
    info(f"Claude Code configured (scope={scope}, backend={target})")


def _setup_codex(args: argparse.Namespace) -> None:
    """Configure Codex harness."""
    from core.setup.codex import _write_env_file, _update_toml_otel_section

    target, credentials = _resolve_backend(args)
    user_id = _resolve_user_id(args)

    codex_config_dir = Path.home() / ".codex"
    codex_config = codex_config_dir / "config.toml"
    env_file = codex_config_dir / "arize-env.sh"

    # Write shared config.yaml
    write_config(target, credentials, "codex", "codex", user_id=user_id)

    # Write env file
    _write_env_file(env_file, target, credentials)

    # Configure OTLP exporter in config.toml
    config = load_config()
    collector_port = get_value(config, "collector.port") or 4318
    _update_toml_otel_section(codex_config, collector_port)

    info(f"Codex configured (backend={target})")


def _setup_cursor(args: argparse.Namespace) -> None:
    """Configure Cursor harness."""
    target, credentials = _resolve_backend(args)
    user_id = _resolve_user_id(args)

    # Write shared config.yaml
    write_config(target, credentials, "cursor", "cursor", user_id=user_id)
    info(f"Cursor configured (backend={target})")


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

def _clean_harness_artifacts(harness: str) -> None:
    """Remove harness-specific files written during install.

    This complements config removal by reverting external file changes.
    """
    if harness == "claude":
        # Remove Arize env vars from Claude settings files
        from core.setup.claude import _load_settings, _save_settings

        _arize_env_keys = {
            "PHOENIX_ENDPOINT", "ARIZE_API_KEY", "ARIZE_SPACE_ID",
            "ARIZE_OTLP_ENDPOINT", "ARIZE_TRACE_ENABLED", "ARIZE_USER_ID",
        }
        for settings_path in (
            Path.home() / ".claude" / "settings.json",
            Path(".claude") / "settings.local.json",
        ):
            if settings_path.is_file():
                settings = _load_settings(settings_path)
                env_block = settings.get("env", {})
                changed = False
                for key in _arize_env_keys:
                    if key in env_block:
                        del env_block[key]
                        changed = True
                if changed:
                    _save_settings(settings_path, settings)

    elif harness == "codex":
        # Remove Codex arize-env.sh and [otel] section from config.toml
        codex_dir = Path.home() / ".codex"
        env_file = codex_dir / "arize-env.sh"
        if env_file.is_file():
            env_file.unlink()

        toml_path = codex_dir / "config.toml"
        if toml_path.is_file():
            lines = toml_path.read_text().splitlines()
            filtered = []
            in_otel = False
            for line in lines:
                stripped = line.strip()
                if stripped == "[otel]" or stripped.startswith("[otel."):
                    in_otel = True
                    continue
                if in_otel and stripped.startswith("[") and not stripped.startswith("[otel"):
                    in_otel = False
                if not in_otel:
                    filtered.append(line)
            # Remove trailing blank lines
            while filtered and not filtered[-1].strip():
                filtered.pop()
            # Also remove the auto-generated comment if present
            if filtered and filtered[-1].strip().startswith("# Arize shared collector"):
                filtered.pop()
            while filtered and not filtered[-1].strip():
                filtered.pop()
            toml_path.write_text("\n".join(filtered) + "\n" if filtered else "")


def _uninstall(args: argparse.Namespace) -> None:
    """Remove one or all harnesses."""
    if not args.harness and not args.all and not args.purge:
        err("specify --harness <name>, --all, or --purge")
        sys.exit(EXIT_MISSING_ARGS)

    if args.purge:
        if not args.non_interactive:
            confirm = input(
                f"This will stop the collector, remove all harnesses, and delete {BASE_DIR}.\n"
                "Continue? [y/N]: "
            ).strip()
            if confirm.lower() != "y":
                print("Cancelled.")
                return

        # Stop collector
        collector_stop()
        info("Collector stopped")

        # Clean up harness artifacts from external config files
        config = load_config()
        harnesses_cfg = get_value(config, "harnesses") or {}
        for config_key in list(harnesses_cfg.keys()):
            cli_name = "claude" if config_key == "claude-code" else config_key
            _clean_harness_artifacts(cli_name)

        # Remove the entire harness directory
        if BASE_DIR.is_dir():
            shutil.rmtree(BASE_DIR)
            info(f"Removed {BASE_DIR}")
        else:
            info(f"{BASE_DIR} does not exist")
        return

    if args.all:
        if not args.non_interactive:
            confirm = input("Remove all harnesses and stop collector? [y/N]: ").strip()
            if confirm.lower() != "y":
                print("Cancelled.")
                return

        # Stop collector
        collector_stop()
        info("Collector stopped")

        # Clean up artifacts for each configured harness
        config = load_config()
        harnesses_cfg = get_value(config, "harnesses") or {}
        for config_key in list(harnesses_cfg.keys()):
            # Map config keys back to CLI names for artifact cleanup
            cli_name = "claude" if config_key == "claude-code" else config_key
            _clean_harness_artifacts(cli_name)

        # Remove all harness entries from config
        if "harnesses" in config:
            config["harnesses"] = {}
            save_config(config)
        info("All harnesses removed from config")
        return

    harness = args.harness
    # Map CLI names to config keys
    config_key = "claude-code" if harness == "claude" else harness

    if not args.non_interactive:
        confirm = input(f"Remove {harness} harness? [y/N]: ").strip()
        if confirm.lower() != "y":
            print("Cancelled.")
            return

    config = load_config()
    harness_entry = get_value(config, f"harnesses.{config_key}")
    if harness_entry is None:
        err(f"Harness '{harness}' is not configured")
        sys.exit(EXIT_ERROR)

    _clean_harness_artifacts(harness)
    delete_value(config, f"harnesses.{config_key}")
    save_config(config)
    info(f"Removed {harness} harness from config")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _status(_args: argparse.Namespace) -> None:
    """Print installed state as JSON (for extension consumption)."""
    config = load_config()

    # Collector
    coll_state, coll_pid, coll_addr = collector_status()

    harnesses_cfg = get_value(config, "harnesses") or {}
    backend_target = get_value(config, "backend.target") or ""

    status_dict = {
        "config_file": str(CONFIG_FILE),
        "config_exists": CONFIG_FILE.is_file(),
        "backend": backend_target,
        "collector": {
            "status": coll_state,
            "pid": coll_pid,
            "address": coll_addr,
        },
        "harnesses": {k: v for k, v in harnesses_cfg.items() if isinstance(v, dict)},
        "user_id": get_value(config, "user_id") or "",
    }

    print(json.dumps(status_dict, indent=2))


# ---------------------------------------------------------------------------
# Collector subcommand
# ---------------------------------------------------------------------------

def _collector_cmd(args: argparse.Namespace) -> None:
    """Route collector sub-actions: start, stop, status, restart."""
    action = args.action
    if action == "start":
        ok = collector_start()
        if ok:
            state, pid, addr = collector_status()
            if state == "running":
                info(f"Collector running (PID {pid}, {addr})")
            else:
                info("Collector started")
        else:
            err("Failed to start collector")
            sys.exit(EXIT_ERROR)

    elif action == "stop":
        collector_stop()
        info("Collector stopped")

    elif action == "status":
        state, pid, addr = collector_status()
        if state == "running":
            print(f"running (PID {pid}, {addr})")
        else:
            print("stopped")

    elif action == "restart":
        collector_stop()
        ok = collector_start()
        if ok:
            state, pid, addr = collector_status()
            if state == "running":
                info(f"Collector restarted (PID {pid}, {addr})")
            else:
                info("Collector restarted")
        else:
            err("Failed to restart collector")
            sys.exit(EXIT_ERROR)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_common_harness_args(parser: argparse.ArgumentParser) -> None:
    """Add flags shared by all harness subcommands."""
    parser.add_argument(
        "--backend",
        choices=["phoenix", "arize"],
        help="Backend target (required in non-interactive mode)",
    )
    parser.add_argument("--api-key", help="Arize AX API key")
    parser.add_argument("--space-id", help="Arize AX space ID")
    parser.add_argument(
        "--otlp-endpoint",
        help="OTLP endpoint (default: otlp.arize.com:443)",
    )
    parser.add_argument(
        "--phoenix-endpoint",
        help="Phoenix endpoint (default: http://localhost:6006)",
    )
    parser.add_argument("--user-id", help="Optional user identifier")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip all prompts; fail if required args are missing",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="arize-install",
        description="Configure Arize Agent Kit harnesses, collector, and backend.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- claude --
    p_claude = subparsers.add_parser("claude", help="Install & configure Claude Code harness")
    _add_common_harness_args(p_claude)
    p_claude.add_argument(
        "--scope",
        choices=["local", "global"],
        default="local",
        help="Claude settings scope (default: local)",
    )
    p_claude.set_defaults(func=_setup_claude)

    # -- codex --
    p_codex = subparsers.add_parser("codex", help="Install & configure Codex harness")
    _add_common_harness_args(p_codex)
    p_codex.set_defaults(func=_setup_codex)

    # -- cursor --
    p_cursor = subparsers.add_parser("cursor", help="Install & configure Cursor harness")
    _add_common_harness_args(p_cursor)
    p_cursor.set_defaults(func=_setup_cursor)

    # -- uninstall --
    p_uninstall = subparsers.add_parser("uninstall", help="Remove one or all harnesses")
    p_uninstall.add_argument(
        "--harness",
        choices=["claude", "codex", "cursor"],
        help="Remove a single harness",
    )
    p_uninstall.add_argument(
        "--all",
        action="store_true",
        help="Stop collector and remove all harnesses from config",
    )
    p_uninstall.add_argument(
        "--purge",
        action="store_true",
        help="Full teardown: stop collector, remove all harnesses, delete ~/.arize/harness",
    )
    p_uninstall.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip confirmation prompts",
    )
    p_uninstall.set_defaults(func=_uninstall)

    # -- status --
    p_status = subparsers.add_parser("status", help="Print installed state as JSON")
    p_status.set_defaults(func=_status)

    # -- collector --
    p_collector = subparsers.add_parser("collector", help="Manage the OTLP collector")
    p_collector.add_argument(
        "action",
        choices=["start", "stop", "status", "restart"],
        help="Collector action",
    )
    p_collector.set_defaults(func=_collector_cmd)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse args and route to the appropriate handler."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_MISSING_ARGS)

    try:
        args.func(args)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
