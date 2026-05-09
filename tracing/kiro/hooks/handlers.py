#!/usr/bin/env python3
"""Kiro hook handler: single entry point dispatching all five Kiro CLI hook events.

Input contract: JSON on stdin with ``hook_event_name`` discriminator.
Exit code: always 0 (exit 2 from preToolUse would block the tool).
"""

from __future__ import annotations

import json
import sys

from core.common import env, error, log


def _dispatch(event: str, input_json: dict) -> None:
    """Route event to the appropriate handler (stub — filled in by later tasks)."""
    log(f"kiro hook: {event} (not yet implemented)")


def main() -> None:
    """Entry point for arize-hook-kiro."""
    event = ""
    try:
        try:
            _log_fd = open(env.log_file, "a")
            sys.stderr = _log_fd
        except OSError:
            pass

        input_json = json.loads(sys.stdin.read() or "{}")
        event = input_json.get("hook_event_name", "")
        _dispatch(event, input_json)
    except Exception as e:
        error(f"kiro hook failed ({event}): {e}")
