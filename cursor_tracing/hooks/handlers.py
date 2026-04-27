#!/usr/bin/env python3
"""Cursor hook handler: single entry point dispatching all 14 Cursor hook events.

Replaces cursor-tracing/hooks/hook-handler.sh (475 lines).

Input contract: JSON on stdin, all 14 events (IDE + CLI) routed here.
stdout: MUST print permissive JSON response, even on error.
stderr: redirected to ARIZE_LOG_FILE before dispatch.
"""
import json
import sys

from core.common import build_span, env, error, get_timestamp_ms, log, send_span
from cursor_tracing.hooks.adapter import (
    SCOPE_NAME,
    SERVICE_NAME,
    check_requirements,
    gen_root_span_get,
    gen_root_span_save,
    sanitize,
    span_id_16,
    state_cleanup_generation,
    state_pop,
    state_push,
    trace_id_from_generation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_permissive(event: str) -> None:
    """Print the permissive JSON response to stdout.

    before* events -> {"permission": "allow"}
    all others     -> {"continue": true}

    Uses sys.__stdout__ (the original stdout saved by Python) in case
    sys.stdout has been redirected.
    """
    stdout = sys.__stdout__ or sys.stdout
    if event.startswith("before"):
        stdout.write('{"permission": "allow"}')
    else:
        stdout.write('{"continue": true}')
    stdout.flush()


def _jq_str(input_json: dict, *keys, default: str = "") -> str:
    """Try multiple keys in order, return first non-None/non-empty string value.

    Matches bash: echo "$INPUT" | jq -r "$1" 2>/dev/null || echo "${2:-}"
    """
    for key in keys:
        val = input_json.get(key)
        if val is not None and val != "":
            return str(val)
    return default


def _event_name(input_json: dict) -> str:
    """Extract event name from payload, tolerant of IDE and CLI key variants.

    Cursor IDE uses ``hook_event_name``; Cursor CLI uses ``hookEventName``.
    """
    return _jq_str(input_json, "hook_event_name", "hookEventName", "event_name", "eventName", "event")


def _trace_id_from_event(gen_id: str, conversation_id: str) -> str:
    """Derive a trace ID from generation or conversation ID.

    Prefers gen_id; falls back to conversation_id for CLI events that may
    lack a generation_id.
    """
    if gen_id:
        return trace_id_from_generation(gen_id)
    if conversation_id:
        return trace_id_from_generation(conversation_id)
    return ""


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(event: str, input_json: dict) -> None:
    """Route event to the appropriate handler."""
    conversation_id = input_json.get("conversation_id", "")
    gen_id = input_json.get("generation_id", "")

    # Early exit: tracing disabled
    if not env.trace_enabled:
        return

    trace_id = _trace_id_from_event(gen_id, conversation_id)
    now_ms = get_timestamp_ms()

    handlers = {
        "beforeSubmitPrompt": _handle_before_submit_prompt,
        "afterAgentResponse": _handle_after_agent_response,
        "afterAgentThought": _handle_after_agent_thought,
        "beforeShellExecution": _handle_before_shell_execution,
        "afterShellExecution": _handle_after_shell_execution,
        "beforeMCPExecution": _handle_before_mcp_execution,
        "afterMCPExecution": _handle_after_mcp_execution,
        "beforeReadFile": _handle_before_read_file,
        "afterFileEdit": _handle_after_file_edit,
        "beforeTabFileRead": _handle_before_tab_file_read,
        "afterTabFileEdit": _handle_after_tab_file_edit,
        "stop": _handle_stop,
        "sessionStart": _handle_session_start,
        "postToolUse": _handle_post_tool_use,
    }

    handler = handlers.get(event)
    if handler:
        handler(input_json, conversation_id, gen_id, trace_id, now_ms)
    else:
        log(f"Unknown hook event: {event}")


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _handle_before_submit_prompt(input_json, conversation_id, gen_id, trace_id, now_ms):
    """Root span for the turn — deferred until afterAgentResponse so it gets output.value."""
    sid = span_id_16()
    gen_root_span_save(gen_id, sid)

    prompt = _jq_str(input_json, "prompt", "input", "text")
    model = _jq_str(input_json, "model", "model_name")

    # Save root span state — sent by afterAgentResponse with output + timing
    state_push(
        f"root_{sanitize(gen_id)}",
        {
            "span_id": sid,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "start_ms": now_ms,
            "prompt": prompt,
            "model": model,
        },
    )
    log(f"beforeSubmitPrompt: deferred root span {sid} (trace={trace_id})")


def _handle_after_agent_response(input_json, conversation_id, gen_id, trace_id, now_ms):
    """LLM child span + send deferred root span with input+output."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    # "text" is the documented field; fall back to "response"/"output" for compat
    response = _jq_str(input_json, "text", "response", "output")
    # "model" is a base field on all hook events
    model = _jq_str(input_json, "model", "model_name")

    # Read prompt from deferred root state
    safe_gen = sanitize(gen_id) if gen_id else ""
    root_state = state_pop(f"root_{safe_gen}") if safe_gen else None
    prompt = root_state.get("prompt", "") if root_state else ""

    # Send LLM child span with input + output + model
    attrs = {
        "openinference.span.kind": "LLM",
        "input.value": prompt,
        "output.value": response,
        "session.id": conversation_id,
    }
    if model:
        attrs["llm.model_name"] = model

    span = build_span(
        "Agent Response",
        "LLM",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterAgentResponse: child span {sid}")

    # Send deferred root span with input + output
    if root_state:
        root_attrs = {
            "openinference.span.kind": "CHAIN",
            "input.value": prompt,
            "output.value": response,
            "session.id": root_state.get("conversation_id", conversation_id),
        }
        root_model = model or root_state.get("model", "")
        if root_model:
            root_attrs["llm.model_name"] = root_model

        root_span = build_span(
            "User Prompt",
            "CHAIN",
            root_state["span_id"],
            root_state.get("trace_id", trace_id),
            "",
            root_state.get("start_ms", now_ms),
            now_ms,
            root_attrs,
            SERVICE_NAME,
            SCOPE_NAME,
        )
        send_span(root_span)
        log(f"afterAgentResponse: sent deferred root span {root_state['span_id']}")


def _handle_after_agent_thought(input_json, conversation_id, gen_id, trace_id, now_ms):
    """CHAIN span for thinking. Replaces bash lines 138-158."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    thought = _jq_str(input_json, "thought", "thinking", "text")

    attrs = {
        "openinference.span.kind": "CHAIN",
        "output.value": thought,
        "session.id": conversation_id,
    }

    span = build_span(
        "Agent Thinking",
        "CHAIN",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterAgentThought: span {sid}")


def _handle_before_shell_execution(input_json, conversation_id, gen_id, trace_id, now_ms):
    """State push only, no span. Replaces bash lines 163-179."""
    if not gen_id:
        return

    command = _jq_str(input_json, "command", "shell_command")
    cwd = _jq_str(input_json, "cwd", "working_directory")

    state_push(
        f"shell_{sanitize(gen_id)}",
        {
            "command": command,
            "cwd": cwd,
            "start_ms": str(now_ms),
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        },
    )
    log(f"beforeShellExecution: pushed state for gen={gen_id}")


def _handle_after_shell_execution(input_json, conversation_id, gen_id, trace_id, now_ms):
    """Merge with before state, create TOOL span. Replaces bash lines 184-232."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)
    popped = state_pop(f"shell_{sanitize(gen_id)}") if gen_id else None

    if popped:
        start_ms = popped.get("start_ms", "")
        command = popped.get("command", "")
    else:
        start_ms = ""
        command = ""
    start_ms = start_ms or str(now_ms)

    # Override command from after-event if present
    after_cmd = _jq_str(input_json, "command", "shell_command")
    if after_cmd:
        command = after_cmd

    output = _jq_str(input_json, "output", "stdout", "result")
    exit_code = _jq_str(input_json, "exit_code", "exitCode")

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": "shell",
        "input.value": command,
        "output.value": output,
        "session.id": conversation_id,
    }
    if exit_code:
        attrs["shell.exit_code"] = exit_code

    span = build_span(
        "Shell",
        "TOOL",
        sid,
        trace_id,
        parent,
        start_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterShellExecution: span {sid} (merged)")


def _handle_before_mcp_execution(input_json, conversation_id, gen_id, trace_id, now_ms):
    """State push only, no span. Replaces bash lines 237-257."""
    if not gen_id:
        return

    tool_name = _jq_str(input_json, "tool_name", "toolName", "name")
    tool_input = _jq_str(input_json, "tool_input", "toolInput", "input", "arguments")
    mcp_url = _jq_str(input_json, "url", "server_url", "serverUrl")
    mcp_cmd = _jq_str(input_json, "command")

    state_push(
        f"mcp_{sanitize(gen_id)}",
        {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "url": mcp_url,
            "command": mcp_cmd,
            "start_ms": str(now_ms),
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        },
    )
    log(f"beforeMCPExecution: pushed state for gen={gen_id}")


def _handle_after_mcp_execution(input_json, conversation_id, gen_id, trace_id, now_ms):
    """Merge with before state, create TOOL span. Replaces bash lines 262-312."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)
    popped = state_pop(f"mcp_{sanitize(gen_id)}") if gen_id else None

    if popped:
        start_ms = popped.get("start_ms", "")
        tool_name = popped.get("tool_name", "")
        tool_input = popped.get("tool_input", "")
    else:
        start_ms = ""
        tool_name = ""
        tool_input = ""
    start_ms = start_ms or str(now_ms)

    # Override tool name from after-event if present
    after_tool = _jq_str(input_json, "tool_name", "toolName", "name")
    if after_tool:
        tool_name = after_tool
    tool_name = tool_name or "unknown"

    result = _jq_str(input_json, "result", "output", "result_json")

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": tool_name,
        "input.value": tool_input,
        "output.value": result,
        "session.id": conversation_id,
    }

    span = build_span(
        f"MCP: {tool_name}",
        "TOOL",
        sid,
        trace_id,
        parent,
        start_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterMCPExecution: span {sid} (merged, tool={tool_name})")


def _handle_before_read_file(input_json, conversation_id, gen_id, trace_id, now_ms):
    """TOOL span for file read. Replaces bash lines 317-339."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    file_path = _jq_str(input_json, "file_path", "filePath", "path")

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": "read_file",
        "input.value": file_path,
        "session.id": conversation_id,
    }

    span = build_span(
        "Read File",
        "TOOL",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"beforeReadFile: span {sid}")


def _handle_after_file_edit(input_json, conversation_id, gen_id, trace_id, now_ms):
    """TOOL span for file edit. Replaces bash lines 344-371."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    file_path = _jq_str(input_json, "file_path", "filePath", "path")
    edits = _jq_str(input_json, "edits", "changes", "diff")
    input_val = f"{file_path}: {edits}" if edits else file_path

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": "edit_file",
        "input.value": input_val,
        "session.id": conversation_id,
    }

    span = build_span(
        "File Edit",
        "TOOL",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterFileEdit: span {sid}")


def _handle_before_tab_file_read(input_json, conversation_id, gen_id, trace_id, now_ms):
    """TOOL span for tab file read. Replaces bash lines 376-398."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    file_path = _jq_str(input_json, "file_path", "filePath", "path")

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": "read_file_tab",
        "input.value": file_path,
        "session.id": conversation_id,
    }

    span = build_span(
        "Tab Read File",
        "TOOL",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"beforeTabFileRead: span {sid}")


def _handle_after_tab_file_edit(input_json, conversation_id, gen_id, trace_id, now_ms):
    """TOOL span for tab file edit. Replaces bash lines 403-430."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    file_path = _jq_str(input_json, "file_path", "filePath", "path")
    edits = _jq_str(input_json, "edits", "changes", "diff")
    input_val = f"{file_path}: {edits}" if edits else file_path

    attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": "edit_file_tab",
        "input.value": input_val,
        "session.id": conversation_id,
    }

    span = build_span(
        "Tab File Edit",
        "TOOL",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"afterTabFileEdit: span {sid}")


def _handle_stop(input_json, conversation_id, gen_id, trace_id, now_ms):
    """Stop span + generation cleanup."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id)

    status = _jq_str(input_json, "status", "reason")
    loop_count = _jq_str(input_json, "loop_count", "loopCount", "iterations")

    attrs = {
        "openinference.span.kind": "CHAIN",
        "session.id": conversation_id,
    }
    if status:
        attrs["cursor.stop.status"] = status
    if loop_count:
        attrs["cursor.stop.loop_count"] = loop_count

    span = build_span(
        "Agent Stop",
        "CHAIN",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)

    if gen_id:
        state_cleanup_generation(gen_id)
    log(f"stop: span {sid}, cleaned up gen={gen_id}")


def _handle_session_start(input_json, conversation_id, gen_id, trace_id, now_ms):
    """CHAIN span for Cursor CLI sessionStart event."""
    sid = span_id_16()

    attrs = {
        "openinference.span.kind": "CHAIN",
        "session.id": conversation_id,
    }

    cwd = _jq_str(input_json, "cwd", "workspace_root")
    if cwd:
        attrs["cursor.session.cwd"] = cwd

    user_email = _jq_str(input_json, "user_email")
    if user_email:
        attrs["user.id"] = user_email

    span = build_span(
        "Session Start",
        "CHAIN",
        sid,
        trace_id,
        "",
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)

    if gen_id:
        gen_root_span_save(gen_id, sid)

    log(f"sessionStart: span {sid} (trace={trace_id})")


_SHELL_TOOL_NAMES = frozenset({"shell", "terminal", "bash", "run_command"})


def _handle_post_tool_use(input_json, conversation_id, gen_id, trace_id, now_ms):
    """TOOL span for Cursor CLI postToolUse event."""
    sid = span_id_16()
    parent = gen_root_span_get(gen_id) if gen_id else ""

    tool_name = _jq_str(input_json, "tool_name", "toolName", "name", "tool")
    tool_input = _jq_str(input_json, "tool_input", "toolInput", "input", "arguments", "args")
    output = _jq_str(input_json, "result", "output", "response", "stdout")

    # Shell-like tools: prefer the top-level ``command`` field as input
    if tool_name.lower() in _SHELL_TOOL_NAMES:
        command = _jq_str(input_json, "command")
        if command:
            tool_input = command

    attrs = {
        "openinference.span.kind": "TOOL",
        "session.id": conversation_id,
    }
    if tool_name:
        attrs["tool.name"] = tool_name
    if tool_input:
        attrs["input.value"] = tool_input
    if output:
        attrs["output.value"] = output

    span_name = f"Tool: {tool_name}" if tool_name else "Tool Use"

    span = build_span(
        span_name,
        "TOOL",
        sid,
        trace_id,
        parent,
        now_ms,
        now_ms,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)
    log(f"postToolUse: span {sid} (tool={tool_name})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Entry point for arize-hook-cursor. Cursor hook.

    Input contract: JSON on stdin, all 14 events (IDE + CLI) routed here.
    stdout: MUST print permissive JSON response, even on error.
    stderr: redirected to ARIZE_LOG_FILE before dispatch.
    """
    event = ""
    try:
        # Redirect stderr to log file BEFORE any processing
        # (matches bash: { ... } 2>>"$ARIZE_LOG_FILE" || true at line 471)
        try:
            _log_fd = open(env.log_file, "a")
            sys.stderr = _log_fd
        except OSError:
            pass

        if not check_requirements():
            return

        input_json = json.loads(sys.stdin.read() or "{}")
        event = _event_name(input_json)
        _dispatch(event, input_json)
    except Exception as e:
        error(f"cursor hook failed ({event}): {e}")
    finally:
        # ALWAYS print permissive response — this is the LAST thing that happens
        _print_permissive(event)
