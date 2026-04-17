#!/usr/bin/env python3
"""Copilot hook handlers. One exported function per hook event.

Supports dual-mode operation:
- VS Code Copilot: sessionId-based, full event set (8 events)
- Copilot CLI: PID-based sessions, minimal event set (6 events)

Each entry point reads stdin JSON, detects mode, and adapts behavior accordingly.
"""
import json
import sys
from pathlib import Path

from core.common import (
    StateManager,
    build_span,
    error,
    generate_span_id,
    generate_trace_id,
    get_timestamp_ms,
    log,
    send_span,
)
from core.hooks.copilot.adapter import (
    SCOPE_NAME,
    SERVICE_NAME,
    check_requirements,
    ensure_session_initialized,
    gc_stale_state_files,
    is_vscode_mode,
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


def _print_response(input_json: dict, event: str) -> None:
    """Print appropriate response to stdout based on mode and event.

    VS Code mode: {"continue": true} for most events.
    PreToolUse VS Code: wrapped permission response.
    PreToolUse CLI: flat permission response.
    CLI mode (non-preToolUse): print nothing.
    """
    vscode = is_vscode_mode(input_json)

    if event == "PreToolUse" or event == "preToolUse":
        if vscode:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                        }
                    }
                )
            )
        else:
            print(json.dumps({"permissionDecision": "allow"}))
    elif vscode:
        print(json.dumps({"continue": True}))
    # CLI mode, non-preToolUse: print nothing


def _flush_pending_turn(state: StateManager) -> None:
    """CLI mode only: if a pending_turn exists in state, build and send
    the root CHAIN span, then clear it.

    The root span has input.value (prompt) but no output.value
    (CLI doesn't expose agent response).
    """
    prompt = state.get("pending_turn_prompt")
    if prompt is None:
        return

    trace_id = state.get("pending_turn_trace_id")
    span_id = state.get("pending_turn_span_id")
    start_time = state.get("pending_turn_start_time")
    trace_count = state.get("pending_turn_trace_count")

    if not trace_id or not span_id:
        # Clean up invalid pending turn
        _clear_pending_turn(state)
        return

    session_id = state.get("session_id") or ""
    project_name = state.get("project_name") or ""
    user_id = state.get("user_id") or ""

    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "project.name": project_name,
        "input.value": prompt,
    }
    if user_id:
        attrs["user.id"] = user_id

    span = build_span(
        f"Turn {trace_count}",
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

    _clear_pending_turn(state)


def _clear_pending_turn(state: StateManager) -> None:
    """Remove all pending_turn keys from state."""
    for key in (
        "pending_turn_prompt",
        "pending_turn_trace_id",
        "pending_turn_span_id",
        "pending_turn_start_time",
        "pending_turn_trace_count",
    ):
        state.delete(key)


def _save_pending_turn(state: StateManager, prompt: str) -> None:
    """CLI mode: save a new prompt as a pending turn for deferred sending."""
    state.increment("trace_count")
    trace_count = state.get("trace_count") or "1"
    state.set("pending_turn_prompt", prompt)
    state.set("pending_turn_trace_id", generate_trace_id())
    state.set("pending_turn_span_id", generate_span_id())
    state.set("pending_turn_start_time", str(get_timestamp_ms()))
    state.set("pending_turn_trace_count", trace_count)
    # Set current trace context for child spans (tool spans, etc.)
    state.set("current_trace_id", state.get("pending_turn_trace_id") or "")
    state.set("current_trace_span_id", state.get("pending_turn_span_id") or "")


# ---------------------------------------------------------------------------
# Internal handler implementations
# ---------------------------------------------------------------------------


def _handle_session_start(input_json: dict) -> None:
    """Handle session start: initialize session."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)

    source = input_json.get("source", "")
    if source:
        state.set("source", source)

    vscode = is_vscode_mode(input_json)
    initial_prompt = input_json.get("initialPrompt", "")
    if initial_prompt:
        if vscode:
            state.set("initial_prompt", initial_prompt)
        else:
            # CLI: save as pending turn for deferred sending
            _save_pending_turn(state, initial_prompt)

    log(f"Session started: {state.get('session_id')} (mode={'vscode' if vscode else 'cli'})")


def _handle_user_prompt_submitted(input_json: dict) -> None:
    """Handle user prompt submission."""
    state = resolve_session(input_json)
    ensure_session_initialized(state, input_json)

    prompt = input_json.get("prompt", "") or ""
    vscode = is_vscode_mode(input_json)

    if vscode:
        # VS Code mode: set up new trace (close orphaned turn first)
        prev_trace_id = state.get("current_trace_id")
        prev_span_id = state.get("current_trace_span_id")
        if prev_trace_id and prev_span_id:
            prev_start = state.get("current_trace_start_time") or str(get_timestamp_ms())
            prev_prompt = state.get("current_trace_prompt") or ""
            prev_count = state.get("trace_count") or "?"
            session_id = state.get("session_id") or ""
            project_name = state.get("project_name") or ""
            failsafe_attrs = {
                "session.id": session_id,
                "openinference.span.kind": "LLM",
                "project.name": project_name,
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
            log(f"Fail-safe: closed orphaned Turn {prev_count}")

        state.increment("trace_count")
        state.set("current_trace_id", generate_trace_id())
        state.set("current_trace_span_id", generate_span_id())
        state.set("current_trace_start_time", str(get_timestamp_ms()))
        state.set("current_trace_prompt", prompt)

        # Track transcript position
        transcript = input_json.get("transcript_path", "")
        if transcript and Path(transcript).is_file():
            with open(transcript) as f:
                line_count = sum(1 for _ in f)
            state.set("trace_start_line", str(line_count))
        else:
            state.set("trace_start_line", "0")
    else:
        # CLI mode: flush previous pending turn, save new one
        _flush_pending_turn(state)
        _save_pending_turn(state, prompt)


def _handle_pre_tool_use(input_json: dict) -> None:
    """Handle pre_tool_use: record tool start time."""
    state = resolve_session(input_json)

    vscode = is_vscode_mode(input_json)
    if vscode:
        tool_id = input_json.get("tool_use_id") or generate_trace_id()
    else:
        # CLI: no tool_use_id; use toolName as key fallback
        tool_id = input_json.get("toolName", "") or generate_trace_id()

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

    vscode = is_vscode_mode(input_json)

    # Normalize tool info from VS Code or CLI format
    if vscode:
        tool_name = input_json.get("tool_name", "unknown")
        tool_id = input_json.get("tool_use_id", "")
        tool_input_raw = input_json.get("tool_input", {})
        tool_input = json.dumps(tool_input_raw) if isinstance(tool_input_raw, dict) else str(tool_input_raw)
        tool_response = str(input_json.get("tool_response", ""))
    else:
        tool_name = input_json.get("toolName", "unknown")
        tool_id = tool_name  # CLI uses toolName as key (matches pre_tool_use)
        # toolArgs is a JSON string in CLI mode
        tool_args_raw = input_json.get("toolArgs", "")
        if isinstance(tool_args_raw, str):
            try:
                tool_input_raw = json.loads(tool_args_raw)
                tool_input = json.dumps(tool_input_raw)
            except (json.JSONDecodeError, TypeError):
                tool_input_raw = {}
                tool_input = tool_args_raw
        else:
            tool_input_raw = tool_args_raw or {}
            tool_input = json.dumps(tool_input_raw)
        # toolResult is a nested object with resultType and textResultForLlm
        tool_result = input_json.get("toolResult", {}) or {}
        tool_response = str(tool_result.get("textResultForLlm", ""))

    # Tool-specific metadata (same enrichment as Claude)
    tool_command = ""
    tool_file_path = ""
    tool_url = ""
    tool_query = ""
    tool_description = ""

    if isinstance(tool_input_raw, dict):
        if tool_name == "Bash":
            tool_command = tool_input_raw.get("command", "")
            tool_description = tool_command[:200]
        elif tool_name in ("Read", "Write", "Edit", "Glob"):
            tool_file_path = tool_input_raw.get("file_path") or tool_input_raw.get("pattern", "")
            tool_description = tool_file_path[:200]
        elif tool_name == "WebSearch":
            tool_query = tool_input_raw.get("query", "")
            tool_description = tool_query[:200]
        elif tool_name == "WebFetch":
            tool_url = tool_input_raw.get("url", "")
            tool_description = tool_url[:200]
        elif tool_name == "Grep":
            tool_query = tool_input_raw.get("pattern", "")
            tool_file_path = tool_input_raw.get("path", "")
            tool_description = f"grep: {tool_query[:100]}"
        else:
            tool_description = tool_input[:200]
    else:
        tool_description = tool_input[:200]

    # Timing
    start_time = state.get(f"tool_{tool_id}_start") or str(get_timestamp_ms())
    end_time = str(get_timestamp_ms())
    state.delete(f"tool_{tool_id}_start")

    # Build attributes
    user_id = state.get("user_id") or ""
    project_name = state.get("project_name") or ""
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "TOOL",
        "project.name": project_name,
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

    # CLI-specific: result type
    if not vscode:
        tool_result = input_json.get("toolResult", {}) or {}
        result_type = tool_result.get("resultType", "")
        if result_type:
            attrs["tool.result_type"] = result_type

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


def _handle_stop(input_json: dict) -> None:
    """Handle stop: VS Code only. Parse transcript and send LLM span for the completed turn."""
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


def _handle_error_occurred(input_json: dict) -> None:
    """Handle error: build and send an error CHAIN span."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    if session_id is None:
        return

    trace_id = state.get("current_trace_id")
    parent_span_id = state.get("current_trace_span_id")

    # Try both field patterns (VS Code may vary, CLI has nested error object)
    error_obj = input_json.get("error", {})
    if isinstance(error_obj, dict):
        error_message = error_obj.get("message", "")
        error_name = error_obj.get("name", "")
        error_stack = error_obj.get("stack", "")
    else:
        error_message = str(error_obj)
        error_name = ""
        error_stack = ""

    # Fallback: check top-level fields
    if not error_message:
        error_message = input_json.get("message", "") or input_json.get("error_message", "")
    if not error_name:
        error_name = input_json.get("name", "") or input_json.get("error_name", "")
    if not error_stack:
        error_stack = input_json.get("stack", "") or input_json.get("error_stack", "")

    user_id = state.get("user_id") or ""
    project_name = state.get("project_name") or ""
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "CHAIN",
        "project.name": project_name,
        "error.message": error_message,
        "error.name": error_name,
    }
    if error_stack:
        attrs["error.stack"] = error_stack
    if error_message:
        attrs["input.value"] = error_message
    if user_id:
        attrs["user.id"] = user_id

    now = str(get_timestamp_ms())
    span = build_span(
        f"Error: {error_name or 'unknown'}",
        "CHAIN",
        generate_span_id(),
        trace_id or generate_trace_id(),
        parent_span_id or "",
        now,
        now,
        attrs,
        SERVICE_NAME,
        SCOPE_NAME,
    )
    send_span(span)


def _handle_session_end(input_json: dict) -> None:
    """Handle session end: flush pending turn (CLI), log summary, clean up."""
    state = resolve_session(input_json)
    session_id = state.get("session_id")
    if session_id is None:
        return

    vscode = is_vscode_mode(input_json)

    # CLI mode: flush any pending turn as root span
    if not vscode:
        _flush_pending_turn(state)

    reason = input_json.get("reason", "")
    trace_count = state.get("trace_count") or "0"
    tool_count = state.get("tool_count") or "0"

    error(f"Session complete: {trace_count} traces, {tool_count} tools (reason={reason})")
    error(f"View in Arize/Phoenix: session.id = {session_id}")

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


def _handle_subagent_stop(input_json: dict) -> None:
    """Handle subagent_stop: VS Code only. Build and send LLM span for subagent."""
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

    transcript_path = input_json.get("transcript_path", "") or input_json.get("agent_transcript_path", "")
    if transcript_path and Path(transcript_path).is_file():
        p = Path(transcript_path)
        st = p.stat()
        # st_birthtime is macOS/BSD only; fall back to ctime elsewhere.
        birth = getattr(st, "st_birthtime", st.st_ctime)
        start_ms = int(birth * 1000)
        start_time = str(start_ms)

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

    project_name = state.get("project_name") or ""
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "LLM",
        "project.name": project_name,
        "copilot.agent.type": agent_type,
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
        "LLM",
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


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def session_start():
    """Entry point for arize-hook-copilot-session-start."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_session_start(input_json)
    except Exception as e:
        error(f"copilot session_start hook failed: {e}")
    finally:
        _print_response(input_json, "SessionStart")


def user_prompt_submitted():
    """Entry point for arize-hook-copilot-user-prompt."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_user_prompt_submitted(input_json)
    except Exception as e:
        error(f"copilot user_prompt_submitted hook failed: {e}")
    finally:
        _print_response(input_json, "UserPromptSubmit")


def pre_tool_use():
    """Entry point for arize-hook-copilot-pre-tool."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_pre_tool_use(input_json)
    except Exception as e:
        error(f"copilot pre_tool_use hook failed: {e}")
    finally:
        _print_response(input_json, "PreToolUse")


def post_tool_use():
    """Entry point for arize-hook-copilot-post-tool."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_post_tool_use(input_json)
    except Exception as e:
        error(f"copilot post_tool_use hook failed: {e}")
    finally:
        _print_response(input_json, "PostToolUse")


def stop():
    """Entry point for arize-hook-copilot-stop."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_stop(input_json)
    except Exception as e:
        error(f"copilot stop hook failed: {e}")
    finally:
        _print_response(input_json, "Stop")


def error_occurred():
    """Entry point for arize-hook-copilot-error."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_error_occurred(input_json)
    except Exception as e:
        error(f"copilot error_occurred hook failed: {e}")
    finally:
        _print_response(input_json, "ErrorOccurred")


def session_end():
    """Entry point for arize-hook-copilot-session-end."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_session_end(input_json)
    except Exception as e:
        error(f"copilot session_end hook failed: {e}")
    finally:
        _print_response(input_json, "SessionEnd")


def subagent_stop():
    """Entry point for arize-hook-copilot-subagent-stop."""
    input_json = {}
    try:
        input_json = _read_stdin()
        if check_requirements():
            _handle_subagent_stop(input_json)
    except Exception as e:
        error(f"copilot subagent_stop hook failed: {e}")
    finally:
        _print_response(input_json, "SubagentStop")
