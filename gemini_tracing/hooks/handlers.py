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
    debug_dump,
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


def _get_robust(data: dict, *keys, default=None):
    """Try both snake_case and camelCase variants of keys."""
    for key in keys:
        if key in data:
            return data[key]
        if "_" in key:
            parts = key.split("_")
            camel = parts[0] + "".join(x.capitalize() for x in parts[1:])
            if camel in data:
                return data[camel]
    return default


def _extract_text(obj) -> str:
    """Extract string content from various nested structures (parts, content, etc.)."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(_extract_text(item) for item in obj)
    if isinstance(obj, dict):
        if "parts" in obj:
            return _extract_text(obj["parts"])
        if "text" in obj:
            return _extract_text(obj["text"])
        if "content" in obj:
            return _extract_text(obj["content"])
    return str(obj)


def _extract_tokens(input_json: dict) -> tuple[int, int]:
    """Extract prompt and completion tokens from various usage schemas."""
    resp = _get_robust(input_json, "llm_response", "response", "model_response") or {}
    usage = _get_robust(resp, "usage_metadata", "usage") or _get_robust(input_json, "usage_metadata", "usage") or {}

    prompt = _get_robust(usage, "prompt_token_count", "prompt_tokens", default=0)
    completion = _get_robust(usage, "candidates_token_count", "candidates_tokens", "output_tokens", default=0)

    try:
        return int(prompt), int(completion)
    except (ValueError, TypeError):
        return 0, 0


# ---------------------------------------------------------------------------
# Internal handler implementations
# ---------------------------------------------------------------------------


def _handle_session_start(input_json: dict) -> None:
    """Handle session start: initialize session."""
    debug_dump("gemini_session_start", input_json)
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)
    session_id = state.get("session_id") or ""
    log(f"Session started: {session_id}")


def _handle_session_end(input_json: dict) -> None:
    """Handle session end: close pending turns, log summary, clean up."""
    debug_dump("gemini_session_end", input_json)
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
    debug_dump("gemini_before_agent", input_json)
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)

    state.increment("trace_count")
    state.set("current_trace_id", generate_trace_id())
    state.set("current_trace_span_id", generate_span_id())
    state.set("current_trace_start_time", str(get_timestamp_ms()))

    # Extract prompt: real CLI uses flat 'prompt'
    prompt_str = _get_robust(input_json, "prompt")
    if prompt_str is None:
        messages = _get_robust(input_json, "messages", default=[])
        if isinstance(messages, list) and messages:
            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            if last_user:
                prompt_str = _extract_text(_get_robust(last_user, "content", default=""))

    if not isinstance(prompt_str, str):
        prompt_str = json.dumps(prompt_str) if prompt_str else ""

    state.set("current_trace_prompt", redact_content(env.log_prompts, prompt_str))


def _handle_after_agent(input_json: dict) -> None:
    """Handle after_agent: build the root CHAIN span for the completed turn."""
    debug_dump("gemini_after_agent", input_json)
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

    # Extract response: real CLI uses 'prompt_response'
    response_str = _get_robust(input_json, "prompt_response")
    if response_str is None:
        resp_obj = _get_robust(input_json, "response", "model_response")
        response_str = _extract_text(resp_obj)

    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "project.name": project_name,
        "input.value": prompt,
        "output.value": redact_content(env.log_prompts, response_str or ""),
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
    """Handle before_model: stash model call start time and prompt."""
    debug_dump("gemini_before_model", input_json)
    state = resolve_session(input_json)

    model_call_id = _get_robust(input_json, "model_call_id") or generate_span_id()
    state.set(f"model_{model_call_id}_start", str(get_timestamp_ms()))
    state.set("current_model_call_id", model_call_id)

    req = _get_robust(input_json, "llm_request") or {}
    messages = _get_robust(req, "messages") or _get_robust(input_json, "messages", default=[])
    if isinstance(messages, list) and messages:
        state.set(f"model_{model_call_id}_prompt", json.dumps(messages))


def _handle_after_model(input_json: dict) -> None:
    """Handle after_model: build an LLM span as child of current turn."""
    debug_dump("gemini_after_model", input_json)
    state = resolve_session(input_json)

    trace_id = state.get("current_trace_id")
    if not trace_id:
        return

    parent_span_id = state.get("current_trace_span_id") or ""
    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    model_call_id = _get_robust(input_json, "model_call_id") or state.get("current_model_call_id") or ""

    if model_call_id:
        start_time = state.get(f"model_{model_call_id}_start") or str(get_timestamp_ms())
    else:
        start_time = str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())

    if model_call_id:
        state.delete(f"model_{model_call_id}_start")
    state.delete("current_model_call_id")

    req = _get_robust(input_json, "llm_request") or {}
    model_name = _get_robust(req, "model") or _get_robust(input_json, "model", "model_name", default="")

    input_tokens, output_tokens = _extract_tokens(input_json)
    total_tokens = input_tokens + output_tokens

    prompt_str = ""
    if model_call_id:
        prompt_str = state.get(f"model_{model_call_id}_prompt") or ""
        state.delete(f"model_{model_call_id}_prompt")

    if not prompt_str:
        prompt_str = state.get("current_trace_prompt") or ""

    resp_obj = _get_robust(input_json, "llm_response", "response", "model_response")
    response_str = _get_robust(resp_obj, "text") if isinstance(resp_obj, dict) else None
    if response_str is None:
        response_str = _extract_text(resp_obj)

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
        "output.value": redact_content(env.log_prompts, response_str or ""),
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
    debug_dump("gemini_before_tool", input_json)
    state = resolve_session(input_json)

    tool_id = _get_robust(input_json, "tool_call_id", "tool_name", default="unknown")
    state.set(f"tool_{tool_id}_start", str(get_timestamp_ms()))


def _handle_after_tool(input_json: dict) -> None:
    """Handle after_tool: build and send a TOOL span."""
    debug_dump("gemini_after_tool", input_json)
    state = resolve_session(input_json)

    trace_id = state.get("current_trace_id")
    parent_span_id = state.get("current_trace_span_id")
    if not trace_id or not parent_span_id:
        return

    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    state.increment("tool_count")

    tool_name = _get_robust(input_json, "tool_name", default="unknown")
    tool_id = _get_robust(input_json, "tool_call_id") or tool_name

    tool_args_raw = _get_robust(input_json, "tool_args") or {}
    tool_input = json.dumps(tool_args_raw) if isinstance(tool_args_raw, (dict, list)) else str(tool_args_raw)
    tool_output = _extract_text(_get_robust(input_json, "tool_result", "result"))

    tool_command = ""
    tool_file_path = ""
    tool_url = ""
    tool_query = ""
    tool_description = ""

    if isinstance(tool_args_raw, dict):
        if tool_name == "run_shell_command":
            tool_command = _get_robust(tool_args_raw, "command", default="")
            tool_description = tool_command[:200]
        elif tool_name in ("read_file", "write_file", "replace", "edit"):
            tool_file_path = _get_robust(tool_args_raw, "file_path", "absolute_path", default="")
            tool_description = tool_file_path[:200]
        elif tool_name == "glob":
            tool_query = _get_robust(tool_args_raw, "pattern", default="")
            tool_file_path = _get_robust(tool_args_raw, "path", default="")
            tool_description = tool_query[:200]
        elif tool_name in ("search_file_content", "grep"):
            tool_query = _get_robust(tool_args_raw, "pattern", default="")
            tool_file_path = _get_robust(tool_args_raw, "path", default="")
            tool_description = f"grep: {tool_query[:100]}"
        elif tool_name == "web_fetch":
            tool_url = _get_robust(tool_args_raw, "url", default="")
            tool_description = tool_url[:200]
        elif tool_name in ("google_web_search", "web_search"):
            tool_query = _get_robust(tool_args_raw, "query", default="")
            tool_description = tool_query[:200]
        else:
            tool_description = tool_input[:200]
    else:
        tool_description = tool_input[:200]

    start_time = state.get(f"tool_{tool_id}_start") or str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())
    state.delete(f"tool_{tool_id}_start")

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


def main() -> None:
    """Manual execution dispatcher."""
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <handler_name>", file=sys.stderr)
        sys.exit(1)

    handler_name = sys.argv[1]
    handlers = {
        "session_start": session_start,
        "session_end": session_end,
        "before_agent": before_agent,
        "after_agent": after_agent,
        "before_model": before_model,
        "after_model": after_model,
        "before_tool": before_tool,
        "after_tool": after_tool,
    }

    handler = handlers.get(handler_name)
    if not handler:
        print(f"unknown handler: {handler_name}", file=sys.stderr)
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
