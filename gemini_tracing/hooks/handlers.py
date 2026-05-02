"""Gemini hook handlers. One exported function per hook event.

Each entry point reads stdin JSON, runs the handler in a try/except, and prints
the appropriate stdout response in finally. Errors never crash the host process.
"""
import json
import sys

from core.common import error
from gemini_tracing.hooks.adapter import check_requirements


def _read_stdin() -> dict:
    """Read JSON from stdin. Returns {} on empty/invalid input."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


def session_start():
    """Entry point for arize-hook-gemini-session-start."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini session_start hook failed: {e}")


def session_end():
    """Entry point for arize-hook-gemini-session-end."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini session_end hook failed: {e}")


def before_agent():
    """Entry point for arize-hook-gemini-before-agent."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini before_agent hook failed: {e}")


def after_agent():
    """Entry point for arize-hook-gemini-after-agent."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini after_agent hook failed: {e}")


def before_model():
    """Entry point for arize-hook-gemini-before-model."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini before_model hook failed: {e}")


def after_model():
    """Entry point for arize-hook-gemini-after-model."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini after_model hook failed: {e}")


def before_tool():
    """Entry point for arize-hook-gemini-before-tool."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini before_tool hook failed: {e}")


def after_tool():
    """Entry point for arize-hook-gemini-after-tool."""
    try:
        _read_stdin()
        if check_requirements():
            pass
    except Exception as e:
        error(f"gemini after_tool hook failed: {e}")
