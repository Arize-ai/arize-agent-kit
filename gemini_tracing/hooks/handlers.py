#!/usr/bin/env python3
"""Gemini hook handlers. One exported function per Gemini hook event.

Single-mode (CLI-only). Each entry point reads stdin JSON, runs the handler
in a try/except, and prints {} to stdout in finally.
"""
from __future__ import annotations

import json
import sys

from core.common import (
    build_span,
    env,
    error,
    generate_span_id,
    generate_trace_id,
    get_timestamp_ms,
    log,
    redact_content,
    send_span,
)
from gemini_tracing.hooks.adapter import (
    SCOPE_NAME,
    SERVICE_NAME,
    check_requirements,
    ensure_session_initialized,
    gc_stale_state_files,
    resolve_session,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_stdin() -> dict:
    """Read JSON from stdin. Returns {} on empty/invalid input."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _print_response() -> None:
    """Print {} to stdout. Same for all 8 events."""
    print(json.dumps({}))


# ---------------------------------------------------------------------------
# Internal handler implementations
# ---------------------------------------------------------------------------


def _handle_session_start(input_json: dict) -> None:
    """Handle session start: initialize session."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)
    session_id = state.get("session_id") or ""
    log(f"Session started: {session_id}")


def _handle_session_end(input_json: dict) -> None:
    """Handle session end: close pending turns, log summary, clean up."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    if session_id is None:
        return

    # Fail-safe: close any pending turn as an LLM span
    pending_trace_id = state.get("current_trace_id")
    pending_span_id = state.get("current_trace_span_id")
    if pending_trace_id and pending_span_id:
        start_time = state.get("current_trace_start_time") or str(get_timestamp_ms())
        prompt = state.get("current_trace_prompt") or ""
        project_name = state.get("project_name") or ""
        user_id = state.get("user_id") or ""

        attrs = {
            "session.id": session_id,
            "openinference.span.kind": "LLM",
            "project.name": project_name,
            "input.value": prompt,
            "output.value": "(closed by SessionEnd fail-safe)",
        }
        if user_id:
            attrs["user.id"] = user_id

        span = build_span(
            "LLM",
            "LLM",
            pending_span_id,
            pending_trace_id,
            "",
            start_time,
            str(get_timestamp_ms()),
            attrs,
            SERVICE_NAME,
            SCOPE_NAME,
        )
        send_span(span)

    trace_count = state.get("trace_count") or "0"
    tool_count = state.get("tool_count") or "0"
    log(f"Session complete: {trace_count} traces, {tool_count} tools")

    # Clean up state file and lock
    if state.state_file is not None:
        state.state_file.unlink(missing_ok=True)
    if state._lock_path is not None:
        if state._lock_path.is_dir():
            try:
                state._lock_path.rmdir()
            except OSError:
                pass
        elif state._lock_path.is_file():
            try:
                state._lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    gc_stale_state_files()


def _handle_before_agent(input_json: dict) -> None:
    """Handle before_agent: start of a turn."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)

    state.increment("trace_count")
    state.set("current_trace_id", generate_trace_id())
    state.set("current_trace_span_id", generate_span_id())
    state.set("current_trace_start_time", str(get_timestamp_ms()))
    state.set("current_trace_prompt", redact_content(env.log_prompts, input_json.get("prompt", "")))


def _handle_after_agent(input_json: dict) -> None:
    """Handle after_agent: build the root CHAIN span for the completed turn."""
    state = resolve_session(input_json)

    trace_id = state.get("current_trace_id")
    span_id = state.get("current_trace_span_id")
    start_time = state.get("current_trace_start_time")
    prompt = state.get("current_trace_prompt") or ""

    if not trace_id or not span_id:
        return

    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "project.name": project_name,
        "input.value": prompt,
        "output.value": redact_content(env.log_prompts, input_json.get("response", "")),
    }
    if user_id:
        attrs["user.id"] = user_id

    span = build_span(
        "Turn",
        "CHAIN",
        span_id,
        trace_id,
        "",
        start_time or str(get_timestamp_ms()),
        str(get_timestamp_ms()),
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)

    # Clear trace state
    state.delete("current_trace_id")
    state.delete("current_trace_span_id")
    state.delete("current_trace_start_time")
    state.delete("current_trace_prompt")


def _handle_before_model(input_json: dict) -> None:
    """Handle before_model: stash model call start time."""
    state = resolve_session(input_json)

    model_call_id = input_json.get("model_call_id") or generate_span_id()
    state.set(f"model_{model_call_id}_start", str(get_timestamp_ms()))
    state.set("current_model_call_id", model_call_id)


def _handle_after_model(input_json: dict) -> None:
    """Handle after_model: build an LLM span as child of current turn."""
    state = resolve_session(input_json)

    trace_id = state.get("current_trace_id")
    if not trace_id:
        return

    parent_span_id = state.get("current_trace_span_id") or ""
    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    # Resolve model call ID
    model_call_id = input_json.get("model_call_id") or state.get("current_model_call_id") or ""

    # Timing
    if model_call_id:
        start_time = state.get(f"model_{model_call_id}_start") or str(get_timestamp_ms())
    else:
        start_time = str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())

    # Clean up state
    if model_call_id:
        state.delete(f"model_{model_call_id}_start")
    state.delete("current_model_call_id")

    # Model info
    model_name = input_json.get("model", "")

    # Token counts
    input_tokens = int(input_json.get("input_tokens", 0) or 0)
    output_tokens = int(input_json.get("output_tokens", 0) or 0)
    total_tokens = input_tokens + output_tokens

    # Prompt handling (may be structured)
    prompt_raw = input_json.get("prompt", "")
    if isinstance(prompt_raw, str):
        prompt_str = prompt_raw
    else:
        prompt_str = json.dumps(prompt_raw)

    response_raw = input_json.get("response", "")
    if isinstance(response_raw, str):
        response_str = response_raw
    else:
        response_str = json.dumps(response_raw)

    # Span name
    span_name = f"LLM: {model_name}" if model_name else "LLM"

    attrs = {
        "session.id": session_id,
        "project.name": project_name,
        "openinference.span.kind": "LLM",
        "llm.model_name": model_name,
        "llm.token_count.prompt": input_tokens,
        "llm.token_count.completion": output_tokens,
        "llm.token_count.total": total_tokens,
        "input.value": redact_content(env.log_prompts, prompt_str),
        "output.value": redact_content(env.log_prompts, response_str),
    }
    if user_id:
        attrs["user.id"] = user_id

    span = build_span(
        span_name,
        "LLM",
        generate_span_id(),
        trace_id,
        parent_span_id,
        start_time,
        end_time,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_before_tool(input_json: dict) -> None:
    """Handle before_tool: record tool start time."""
    state = resolve_session(input_json)

    tool_id = input_json.get("tool_call_id") or input_json.get("tool_name", "unknown")
    state.set(f"tool_{tool_id}_start", str(get_timestamp_ms()))


def _handle_after_tool(input_json: dict) -> None:
    """Handle after_tool: build and send a TOOL span."""
    state = resolve_session(input_json)

    trace_id = state.get("current_trace_id")
    parent_span_id = state.get("current_trace_span_id")
    if not trace_id or not parent_span_id:
        return

    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    state.increment("tool_count")

    tool_name = input_json.get("tool_name", "unknown")
    tool_id = input_json.get("tool_call_id") or tool_name

    # Raw values
    tool_args_raw = input_json.get("tool_args") or {}
    tool_input = json.dumps(tool_args_raw)
    tool_output = str(input_json.get("tool_result", ""))

    # Tool-specific metadata enrichment
    tool_command = ""
    tool_file_path = ""
    tool_url = ""
    tool_query = ""
    tool_description = ""

    if isinstance(tool_args_raw, dict):
        if tool_name == "run_shell_command":
            tool_command = tool_args_raw.get("command", "")
            tool_description = tool_command[:200]
        elif tool_name in ("read_file", "write_file", "replace", "edit"):
            tool_file_path = tool_args_raw.get("file_path") or tool_args_raw.get("absolute_path", "")
            tool_description = tool_file_path[:200]
        elif tool_name == "glob":
            tool_query = tool_args_raw.get("pattern", "")
            tool_file_path = tool_args_raw.get("path", "")
            tool_description = tool_query[:200]
        elif tool_name in ("search_file_content", "grep"):
            tool_query = tool_args_raw.get("pattern", "")
            tool_file_path = tool_args_raw.get("path", "")
            tool_description = f"grep: {tool_query[:100]}"
        elif tool_name == "web_fetch":
            tool_url = tool_args_raw.get("url", "")
            tool_description = tool_url[:200]
        elif tool_name in ("google_web_search", "web_search"):
            tool_query = tool_args_raw.get("query", "")
            tool_description = tool_query[:200]
        else:
            tool_description = tool_input[:200]
    else:
        tool_description = tool_input[:200]

    # Timing
    start_time = state.get(f"tool_{tool_id}_start") or str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())
    state.delete(f"tool_{tool_id}_start")

    # Redaction
    tool_input = redact_content(env.log_tool_content, tool_input)
    tool_output = redact_content(env.log_tool_content, tool_output)
    tool_description = redact_content(env.log_tool_details, tool_description)
    if tool_command:
        tool_command = redact_content(env.log_tool_details, tool_command)
    if tool_file_path:
        tool_file_path = redact_content(env.log_tool_details, tool_file_path)
    if tool_url:
        tool_url = redact_content(env.log_tool_details, tool_url)
    if tool_query:
        tool_query = redact_content(env.log_tool_details, tool_query)

    # Build attributes
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "TOOL",
        "project.name": project_name,
        "tool.name": tool_name,
        "input.value": tool_input,
        "output.value": tool_output,
        "tool.description": tool_description,
    }
    if user_id:
        attrs["user.id"] = user_id
    if tool_command:
        attrs["tool.command"] = tool_command
    if tool_file_path:
        attrs["tool.file_path"] = tool_file_path
    if tool_url:
        attrs["tool.url"] = tool_url
    if tool_query:
        attrs["tool.query"] = tool_query

    span = build_span(
        tool_name,
        "TOOL",
        generate_span_id(),
        trace_id,
        parent_span_id,
        start_time,
        end_time,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def session_start():
    """Entry point for arize-hook-gemini-session-start."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_session_start(input_json)
    except Exception as e:
        error(f"gemini session_start hook failed: {e}")
    finally:
        _print_response()


def session_end():
    """Entry point for arize-hook-gemini-session-end."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_session_end(input_json)
    except Exception as e:
        error(f"gemini session_end hook failed: {e}")
    finally:
        _print_response()


def before_agent():
    """Entry point for arize-hook-gemini-before-agent."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_before_agent(input_json)
    except Exception as e:
        error(f"gemini before_agent hook failed: {e}")
    finally:
        _print_response()


def after_agent():
    """Entry point for arize-hook-gemini-after-agent."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_after_agent(input_json)
    except Exception as e:
        error(f"gemini after_agent hook failed: {e}")
    finally:
        _print_response()


def before_model():
    """Entry point for arize-hook-gemini-before-model."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_before_model(input_json)
    except Exception as e:
        error(f"gemini before_model hook failed: {e}")
    finally:
        _print_response()


def after_model():
    """Entry point for arize-hook-gemini-after-model."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_after_model(input_json)
    except Exception as e:
        error(f"gemini after_model hook failed: {e}")
    finally:
        _print_response()


def before_tool():
    """Entry point for arize-hook-gemini-before-tool."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_before_tool(input_json)
    except Exception as e:
        error(f"gemini before_tool hook failed: {e}")
    finally:
        _print_response()


def after_tool():
    """Entry point for arize-hook-gemini-after-tool."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_after_tool(input_json)
    except Exception as e:
        error(f"gemini after_tool hook failed: {e}")
    finally:
        _print_response()
