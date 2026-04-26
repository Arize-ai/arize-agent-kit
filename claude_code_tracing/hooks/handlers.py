#!/usr/bin/env python3
"""Claude Code hook handlers. One exported function per hook event.

Replaces 9 bash scripts in claude-code-tracing/hooks/. Each function is a CLI
entry point registered in pyproject.toml [project.scripts].
"""
import json
import sys
from pathlib import Path

from claude_code_tracing.hooks.adapter import (
    SCOPE_NAME,
    SERVICE_NAME,
    check_requirements,
    ensure_session_initialized,
    gc_stale_state_files,
    resolve_session,
)
from core.common import build_span, error, generate_span_id, generate_trace_id, get_timestamp_ms, log, send_span

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _read_stdin() -> dict:
    """Read JSON from stdin. Returns {} on empty/invalid input."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Internal handler implementations
# ---------------------------------------------------------------------------


def _handle_session_start(input_json: dict) -> None:
    """Handle session_start: initialize session."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)
    log(f"Session started: {state.get('session_id')}")


def _handle_pre_tool_use(input_json: dict) -> None:
    """Handle pre_tool_use: record tool start time."""
    state = resolve_session(input_json)
    tool_id = input_json.get("tool_use_id") or generate_trace_id()
    state.set(f"tool_{tool_id}_start", str(get_timestamp_ms()))


def _handle_post_tool_use(input_json: dict) -> None:
    """Handle post_tool_use: build and send a TOOL span."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    if session_id is None:
        return

    trace_id = state.get("current_trace_id")
    parent_span_id = state.get("current_trace_span_id")
    state.increment("tool_count")

    # Extract tool info
    tool_name = input_json.get("tool_name", "unknown")
    tool_id = input_json.get("tool_use_id", "")
    tool_input = json.dumps(input_json.get("tool_input", {}))
    tool_response = str(input_json.get("tool_response", ""))

    # Tool-specific metadata
    tool_command = ""
    tool_file_path = ""
    tool_url = ""
    tool_query = ""
    tool_description = ""

    if tool_name == "Bash":
        tool_command = input_json.get("tool_input", {}).get("command", "")
        tool_description = tool_command[:200]
    elif tool_name in ("Read", "Write", "Edit", "Glob"):
        tool_file_path = input_json.get("tool_input", {}).get("file_path") or input_json.get("tool_input", {}).get(
            "pattern", ""
        )
        tool_description = tool_file_path[:200]
    elif tool_name == "WebSearch":
        tool_query = input_json.get("tool_input", {}).get("query", "")
        tool_description = tool_query[:200]
    elif tool_name == "WebFetch":
        tool_url = input_json.get("tool_input", {}).get("url", "")
        tool_description = tool_url[:200]
    elif tool_name == "Grep":
        tool_query = input_json.get("tool_input", {}).get("pattern", "")
        tool_file_path = input_json.get("tool_input", {}).get("path", "")
        tool_description = f"grep: {tool_query[:100]}"
    else:
        tool_description = tool_input[:200]

    # Timing
    start_time = state.get(f"tool_{tool_id}_start") or str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())
    state.delete(f"tool_{tool_id}_start")

    # Build attributes
    user_id = state.get("user_id") or ""
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "TOOL",
        "tool.name": tool_name,
        "input.value": tool_input,
        "output.value": tool_response,
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
        trace_id or "",
        parent_span_id or "",
        start_time,
        end_time,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_user_prompt_submit(input_json: dict) -> None:
    """Handle user_prompt_submit: set up a new trace (close orphaned turn first)."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)
    session_id = state.get("session_id")

    # Fail-safe: close any orphaned Turn span
    prev_trace_id = state.get("current_trace_id")
    prev_span_id = state.get("current_trace_span_id")
    if prev_trace_id and prev_span_id:
        prev_start = state.get("current_trace_start_time") or str(get_timestamp_ms())
        prev_prompt = state.get("current_trace_prompt") or ""
        prev_count = state.get("trace_count") or "?"
        failsafe_attrs = {
            "session.id": session_id,
            "openinference.span.kind": "LLM",
            "input.value": prev_prompt,
            "output.value": "(Turn closed by fail-safe: Stop hook did not fire)",
        }
        user_id = state.get("user_id") or ""
        if user_id:
            failsafe_attrs["user.id"] = user_id
        failsafe_span = build_span(
            f"Turn {prev_count}",
            "LLM",
            prev_span_id,
            prev_trace_id,
            "",
            prev_start,
            str(get_timestamp_ms()),
            failsafe_attrs,
            SERVICE_NAME,
            SCOPE_NAME,
        )
        send_span(failsafe_span)
        state.delete("current_trace_id")
        state.delete("current_trace_span_id")
        state.delete("current_trace_start_time")
        state.delete("current_trace_prompt")
        log(f"Fail-safe: closed orphaned Turn {prev_count}")

    # Set up new trace
    state.increment("trace_count")
    state.set("current_trace_id", generate_trace_id())
    state.set("current_trace_span_id", generate_span_id())
    state.set("current_trace_start_time", str(get_timestamp_ms()))
    state.set("current_trace_prompt", input_json.get("prompt", "") or "")

    # Track transcript position
    transcript = input_json.get("transcript_path", "")
    if transcript and Path(transcript).is_file():
        with open(transcript) as f:
            line_count = sum(1 for _ in f)
        state.set("trace_start_line", str(line_count))
    else:
        state.set("trace_start_line", "0")


def _handle_stop(input_json: dict) -> None:
    """Handle stop: parse transcript and send LLM span for the completed turn."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    trace_id = state.get("current_trace_id")
    if session_id is None or trace_id is None:
        return

    trace_span_id = state.get("current_trace_span_id") or generate_span_id()
    trace_start_time = state.get("current_trace_start_time") or str(get_timestamp_ms())
    user_prompt = state.get("current_trace_prompt") or ""
    project_name = state.get("project_name") or ""
    trace_count = state.get("trace_count") or "0"
    user_id = state.get("user_id") or ""

    # Parse transcript
    transcript_path = input_json.get("transcript_path", "")
    output = ""
    model = ""
    in_tokens = 0
    out_tokens = 0

    if transcript_path and Path(transcript_path).is_file():
        start_line = int(state.get("trace_start_line") or "0")
        with open(transcript_path) as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("message", {}).get("role") != "assistant":
                    continue
                # Extract text from message.content
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    text = "\n".join(
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                elif isinstance(content, str):
                    text = content
                else:
                    text = ""
                if text:
                    output = f"{output}\n{text}" if output else text
                # Extract model
                model = entry.get("message", {}).get("model", "") or model
                # Accumulate tokens
                usage = entry.get("message", {}).get("usage", {})
                for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    val = usage.get(key, 0)
                    if isinstance(val, int):
                        in_tokens += val
                val = usage.get("output_tokens", 0)
                if isinstance(val, int):
                    out_tokens += val

    output = output or "(No response)"
    total_tokens = in_tokens + out_tokens

    # Build and send LLM span
    output_messages = [{"message.role": "assistant", "message.content": output}]
    attrs = {
        "session.id": session_id,
        "trace.number": trace_count,
        "project.name": project_name,
        "openinference.span.kind": "LLM",
        "llm.model_name": model,
        "llm.token_count.prompt": in_tokens,
        "llm.token_count.completion": out_tokens,
        "llm.token_count.total": total_tokens,
        "input.value": user_prompt,
        "output.value": output,
        "llm.output_messages": json.dumps(output_messages),
    }
    if user_id:
        attrs["user.id"] = user_id

    span = build_span(
        f"Turn {trace_count}",
        "LLM",
        trace_span_id,
        trace_id,
        "",
        trace_start_time,
        str(get_timestamp_ms()),
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)

    # Clean up state
    state.delete("current_trace_id")
    state.delete("current_trace_span_id")
    state.delete("current_trace_start_time")
    state.delete("current_trace_prompt")

    # Periodic GC
    try:
        tc = int(trace_count or "0")
    except (ValueError, TypeError):
        tc = 0
    if tc % 5 == 0:
        gc_stale_state_files()


def _handle_subagent_stop(input_json: dict) -> None:
    """Handle subagent_stop: parse subagent transcript and send CHAIN span."""
    state = resolve_session(input_json)
    trace_id = state.get("current_trace_id")
    if trace_id is None:
        return

    session_id = state.get("session_id")
    agent_id = input_json.get("agent_id", "")
    agent_type = input_json.get("agent_type", "")

    if not agent_type or agent_type in ("unknown", "null"):
        return

    span_id = generate_span_id()
    end_time = str(get_timestamp_ms())
    parent = state.get("current_trace_span_id")

    # Parse subagent transcript
    output = ""
    model = ""
    in_tokens = 0
    out_tokens = 0
    start_time = end_time

    transcript_path = input_json.get("agent_transcript_path", "")
    if transcript_path and Path(transcript_path).is_file():
        p = Path(transcript_path)
        # Get file creation time for start_time
        st = p.stat()
        # st_birthtime is macOS/BSD only; fall back to ctime elsewhere.
        birth = getattr(st, "st_birthtime", st.st_ctime)
        start_ms = int(birth * 1000)
        start_time = str(start_ms)

        # Parse JSONL
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("message", {}).get("role") != "assistant":
                    continue
                content = entry.get("message", {}).get("content")
                if isinstance(content, list):
                    text = "\n".join(
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                elif isinstance(content, str):
                    text = content
                else:
                    text = ""
                if text:
                    output = f"{output}\n{text}" if output else text
                model = entry.get("message", {}).get("model", "") or model
                usage = entry.get("message", {}).get("usage", {})
                for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    val = usage.get(key, 0)
                    if isinstance(val, int):
                        in_tokens += val
                val = usage.get("output_tokens", 0)
                if isinstance(val, int):
                    out_tokens += val

    total_tokens = in_tokens + out_tokens

    # Build attributes
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "subagent.id": agent_id,
        "subagent.type": agent_type,
        "llm.model_name": model,
        "llm.token_count.prompt": in_tokens,
        "llm.token_count.completion": out_tokens,
        "llm.token_count.total": total_tokens,
    }
    if output:
        attrs["output.value"] = output
    user_id = state.get("user_id") or ""
    if user_id:
        attrs["user.id"] = user_id

    span = build_span(
        f"Subagent: {agent_type}",
        "CHAIN",
        span_id,
        trace_id,
        parent or "",
        start_time,
        end_time,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_notification(input_json: dict) -> None:
    """Handle notification: send a CHAIN span for the notification event."""
    state = resolve_session(input_json)
    trace_id = state.get("current_trace_id")
    if trace_id is None:
        return

    session_id = state.get("session_id")
    message = input_json.get("message", "")
    title = input_json.get("title", "")
    notification_type = input_json.get("type", "info")

    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "notification.message": message,
        "notification.title": title,
        "notification.type": notification_type,
        "input.value": message,
    }
    user_id = state.get("user_id") or ""
    if user_id:
        attrs["user.id"] = user_id

    now = str(get_timestamp_ms())
    span = build_span(
        f"Notification: {notification_type}",
        "CHAIN",
        generate_span_id(),
        trace_id,
        state.get("current_trace_span_id") or "",
        now,
        now,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_permission_request(input_json: dict) -> None:
    """Handle permission_request: send a CHAIN span for the permission event."""
    state = resolve_session(input_json)
    log(f"DEBUG permission_request input: {json.dumps(input_json)}")

    trace_id = state.get("current_trace_id")
    if trace_id is None:
        return

    session_id = state.get("session_id")
    permission = input_json.get("permission", "")
    tool_name = input_json.get("tool_name", "")
    tool_input = json.dumps(input_json.get("tool_input", {}))

    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "permission.type": permission,
        "permission.tool": tool_name,
        "input.value": tool_input,
    }
    user_id = state.get("user_id") or ""
    if user_id:
        attrs["user.id"] = user_id

    now = str(get_timestamp_ms())
    span = build_span(
        "Permission Request",
        "CHAIN",
        generate_span_id(),
        trace_id,
        state.get("current_trace_span_id") or "",
        now,
        now,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_session_end(input_json: dict) -> None:
    """Handle session_end: log summary and clean up state file."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    if session_id is None:
        return

    trace_count = state.get("trace_count") or "0"
    tool_count = state.get("tool_count") or "0"

    error(f"Session complete: {trace_count} traces, {tool_count} tools")
    error(f"View in Arize/Phoenix: session.id = {session_id}")

    # Clean up state file and lock
    if state.state_file is not None:
        state.state_file.unlink(missing_ok=True)
    if state._lock_path is not None and state._lock_path.is_dir():
        try:
            state._lock_path.rmdir()
        except OSError:
            pass

    gc_stale_state_files()


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def session_start():
    """Entry point for arize-hook-session-start."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_session_start(input_json)
    except Exception as e:
        error(f"session_start hook failed: {e}")


def pre_tool_use():
    """Entry point for arize-hook-pre-tool-use."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_pre_tool_use(input_json)
    except Exception as e:
        error(f"pre_tool_use hook failed: {e}")


def post_tool_use():
    """Entry point for arize-hook-post-tool-use."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_post_tool_use(input_json)
    except Exception as e:
        error(f"post_tool_use hook failed: {e}")


def user_prompt_submit():
    """Entry point for arize-hook-user-prompt-submit."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_user_prompt_submit(input_json)
    except Exception as e:
        error(f"user_prompt_submit hook failed: {e}")


def stop():
    """Entry point for arize-hook-stop."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_stop(input_json)
    except Exception as e:
        error(f"stop hook failed: {e}")


def subagent_stop():
    """Entry point for arize-hook-subagent-stop."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_subagent_stop(input_json)
    except Exception as e:
        error(f"subagent_stop hook failed: {e}")


def notification():
    """Entry point for arize-hook-notification."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_notification(input_json)
    except Exception as e:
        error(f"notification hook failed: {e}")


def permission_request():
    """Entry point for arize-hook-permission-request."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_permission_request(input_json)
    except Exception as e:
        error(f"permission_request hook failed: {e}")


def session_end():
    """Entry point for arize-hook-session-end."""
    try:
        if not check_requirements():
            return
        input_json = _read_stdin()
        _handle_session_end(input_json)
    except Exception as e:
        error(f"session_end hook failed: {e}")
