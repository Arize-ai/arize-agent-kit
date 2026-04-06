#!/usr/bin/env python3
"""Codex hook handler — creates OpenInference LLM spans from agent-turn-complete events.

Replaces codex-tracing/hooks/notify.sh (445 lines). Registered as the
``arize-hook-codex-notify`` CLI entry point.

Input contract: JSON as sys.argv[1] (NOT stdin -- Codex passes JSON as a CLI arg).
No stdout output -- Codex doesn't expect a response.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from core.common import (
    build_multi_span,
    build_span,
    debug_dump,
    env,
    error,
    generate_span_id,
    generate_trace_id,
    get_timestamp_ms,
    log,
)
from core.hooks.codex.adapter import (
    SCOPE_NAME,
    SERVICE_NAME,
    check_requirements,
    ensure_session_initialized,
    gc_stale_state_files,
    load_env_file,
    resolve_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flex_get(d: dict, *keys, default=""):
    """Try multiple key names, return first non-None/non-empty value."""
    for key in keys:
        val = d.get(key)
        if val is not None and val != "":
            return val
    return default


def _flex_get_obj(d: dict, *keys):
    """Like _flex_get but returns None instead of empty string default."""
    for key in keys:
        val = d.get(key)
        if val is not None and val != "":
            return val
    return None


def _nested_get(d: dict, *keys):
    """Walk nested dicts by key sequence. Returns None if any step fails."""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_text(node) -> str:
    """Recursively extract text from a nested message structure.

    Handles: str, list (join with newlines), dict (try .text, .content,
    .message, .data, .value, then json.dumps as fallback), None -> "".
    Matches the jq as_text function in notify.sh lines 37-44.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(_as_text(item) for item in node)
    if isinstance(node, dict):
        for key in ("text", "content", "message", "data", "value"):
            if key in node:
                result = _as_text(node[key])
                if result:
                    return result
        return json.dumps(node)
    return str(node)


def _extract_user_prompt(user_input) -> str:
    """Extract the last user message from input-messages.

    input-messages can be:
    - list of message objects -> find last with role=="user", extract content
    - list of strings -> use last non-empty string
    - plain string -> use directly

    Matches the jq expression at bash lines 63-79.
    """
    if isinstance(user_input, list):
        # Try: last user-role message object
        for msg in reversed(user_input):
            if isinstance(msg, dict) and msg.get("role") == "user":
                text = _as_text(msg.get("content", ""))
                if text:
                    return text
        # Fallback: last non-empty string in the array
        for msg in reversed(user_input):
            if isinstance(msg, str) and msg:
                return msg
        return ""
    if isinstance(user_input, str):
        return user_input
    return str(user_input) if user_input else ""


# ---------------------------------------------------------------------------
# Token enrichment
# ---------------------------------------------------------------------------

def _find_token_usage(input_json: dict):
    """Search for token usage dict in multiple payload locations.

    Tries (matching bash lines 127-134):
    1. input_json itself: .token_usage / .token-usage / .usage
    2. input_json["last-assistant-message"]: same keys
    3. input_json["last-assistant-message"]["message"]: same keys
    """
    usage_keys = ("token_usage", "token-usage", "usage")
    search_locations = [
        input_json,
        _flex_get_obj(input_json, "last-assistant-message", "last_assistant_message", "lastAssistantMessage"),
        _nested_get(input_json, "last-assistant-message", "message"),
    ]
    for obj in search_locations:
        if not isinstance(obj, dict):
            continue
        for key in usage_keys:
            val = obj.get(key)
            if isinstance(val, dict):
                return val
    return None


def _extract_token_counts(usage: dict) -> dict:
    """Extract prompt/completion/total counts, trying multiple key variants.

    Returns {"prompt": int|None, "completion": int|None, "total": int|None}.
    Auto-computes total if prompt + completion are present but total isn't.
    """
    def pick_first(*keys):
        for k in keys:
            val = usage.get(k)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
        return None

    prompt = pick_first(
        "prompt_tokens", "input_tokens", "promptTokens", "inputTokens",
        "prompt", "input", "cache_read_input_tokens", "cache_creation_input_tokens",
    )
    completion = pick_first(
        "completion_tokens", "output_tokens", "completionTokens", "outputTokens",
        "completion", "output",
    )
    total = pick_first(
        "total_tokens", "totalTokens", "tokens", "token_count", "overall", "sum",
    )
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    return {"prompt": prompt, "completion": completion, "total": total}


# ---------------------------------------------------------------------------
# Tool call extraction
# ---------------------------------------------------------------------------

def _find_tool_calls(input_json: dict):
    """Search for tool calls list in multiple payload locations.

    Tries keys: tool_calls, tool-calls, toolCalls, tool_invocations,
    toolInvocations, tools, tool_results.
    Searches: root, last-assistant-message, last-assistant-message.message
    """
    tool_keys = (
        "tool_calls", "tool-calls", "toolCalls",
        "tool_invocations", "toolInvocations",
        "tools", "tool_results",
    )
    search_locations = [
        input_json,
        _flex_get_obj(input_json, "last-assistant-message", "last_assistant_message", "lastAssistantMessage"),
        _nested_get(input_json, "last-assistant-message", "message"),
    ]
    for obj in search_locations:
        if not isinstance(obj, dict):
            continue
        for key in tool_keys:
            val = obj.get(key)
            if val is not None:
                if isinstance(val, list):
                    return val
                # Wrap non-list in a list (matches bash: [.] fallback)
                return [val]
    return None


# ---------------------------------------------------------------------------
# Event buffer drain
# ---------------------------------------------------------------------------

def _drain_events(thread_id: str, state, collector_port: int) -> list:
    """Drain buffered events from the collector for this thread.

    HTTP GET http://127.0.0.1:{port}/drain/{thread_id}?since_ns={last}&wait_ms=8000&quiet_ms=1200

    Retry schedule (matches bash drain_attempts array at line 225):
    - Attempt 1: immediate
    - Attempt 2: wait 1.2s, then request
    - Attempt 3: wait 2.0s, then request

    Returns list of event dicts. Returns [] on any failure.
    """
    if not thread_id:
        log("Skipping event buffer drain because thread-id is missing")
        return []

    last_ns = state.get("last_collector_time_ns") or "0"
    url = f"http://127.0.0.1:{collector_port}/drain/{thread_id}"
    query = f"since_ns={last_ns}&wait_ms=8000&quiet_ms=1200"
    retry_waits = [0, 1.2, 2.0]  # seconds (matches bash: 0, 1200ms, 2000ms)

    for wait in retry_waits:
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(f"{url}?{query}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read())
        except Exception:
            events = []

        if not isinstance(events, list):
            events = []

        log(f"Collector drain attempt (thread={thread_id}, wait={wait}s) => {len(events)} events")
        if events:
            return events

    return []


# ---------------------------------------------------------------------------
# Span sending
# ---------------------------------------------------------------------------

def _send_span(payload: dict, collector_port: int) -> None:
    """Send an OTLP span payload to the collector via HTTP POST.

    POST http://127.0.0.1:{port}/v1/spans with JSON body.
    Matches bash send_to_collector / send_span.
    """
    if env.dry_run:
        try:
            names = [s["name"] for s in payload.get("resourceSpans", [{}])[0]
                     .get("scopeSpans", [{}])[0].get("spans", [])]
            log(f"DRY RUN: {names}")
        except Exception:
            log("DRY RUN: (unparseable payload)")
        return

    url = f"http://127.0.0.1:{collector_port}/v1/spans"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        error(f"Failed to send span to collector: {e}")


# ---------------------------------------------------------------------------
# Child span building from collector events
# ---------------------------------------------------------------------------

def _build_child_spans(events: list, trace_id: str, parent_span_id: str,
                       session_id: str, start_time: int, attrs: dict) -> list:
    """Build child spans from collector events and enrich parent attrs in-place.

    Returns list of child span payloads (each from build_span()).
    Modifies attrs dict in-place with enrichments from events.
    """
    child_spans = []

    # --- Adjust timing from event timestamps (bash lines 259-266) ---
    timestamps_ns = []
    for e in events:
        try:
            t = int(e.get("time_ns", 0))
            if t > 0:
                timestamps_ns.append(t)
        except (ValueError, TypeError):
            pass

    event_start_time = start_time
    event_end_time = start_time
    if timestamps_ns:
        event_start_time = min(timestamps_ns) // 1_000_000
        event_end_time = max(timestamps_ns) // 1_000_000
        attrs["codex.trace.duration_ms"] = event_end_time - event_start_time

    # --- Model name enrichment (bash lines 270-277) ---
    for e in events:
        if e.get("event") in ("codex.conversation_starts", "codex.api_request"):
            a = e.get("attrs", {})
            model = a.get("model") or a.get("llm.model_name") or a.get("model_name")
            if model:
                attrs["llm.model_name"] = model
                break

    # --- Token enrichment from SSE events (bash lines 280-315) ---
    sse_events = [
        e for e in events
        if e.get("event") == "codex.sse_event"
        and (
            (e.get("attrs", {}).get("type") == "response.completed")
            or (e.get("attrs", {}).get("sse.type") == "response.completed")
            or (e.get("attrs", {}).get("event.kind") == "response.completed")
        )
    ]
    if sse_events:
        ea = sse_events[-1].get("attrs", {})
        _enrich_tokens_from_event_attrs(ea, attrs)

    # --- Sandbox/approval from conversation_starts (bash lines 317-326) ---
    for e in events:
        if e.get("event") == "codex.conversation_starts":
            a = e.get("attrs", {})
            sandbox = a.get("sandbox") or a.get("sandbox_mode")
            approval = a.get("approval_mode") or a.get("approval")
            if sandbox:
                attrs["codex.sandbox_mode"] = sandbox
            if approval:
                attrs["codex.approval_mode"] = approval
            break

    # --- TOOL child spans from tool_decision + tool_result pairs (bash lines 328-379) ---
    decisions = [e for e in events if e.get("event") == "codex.tool_decision"]
    results = [e for e in events if e.get("event") == "codex.tool_result"]

    for i, decision in enumerate(decisions):
        da = decision.get("attrs", {})
        tool_name = (da.get("tool_name") or da.get("tool.name")
                     or da.get("name") or "unknown_tool")
        decision_ns = _safe_int(decision.get("time_ns", 0))
        approval_status = (da.get("approved") or da.get("approval")
                           or da.get("decision") or da.get("status") or "unknown")

        # Match result by tool name, fall back to index
        result = None
        for r in results:
            ra = r.get("attrs", {})
            rname = ra.get("tool_name") or ra.get("tool.name") or ra.get("name")
            if rname == tool_name:
                result = r
                break
        if result is None and i < len(results):
            result = results[i]

        result_ns = _safe_int(result.get("time_ns", 0)) if result else decision_ns
        tool_output = ""
        if result:
            ra = result.get("attrs", {})
            tool_output = str(
                ra.get("output") or ra.get("result") or ra.get("tool.output") or ""
            )[:2000]

        tool_start_ms = decision_ns // 1_000_000 or event_start_time
        tool_end_ms = result_ns // 1_000_000 or tool_start_ms

        tool_attrs = {
            "openinference.span.kind": "TOOL",
            "tool.name": tool_name,
            "output.value": tool_output,
            "codex.tool.approval_status": approval_status,
            "session.id": session_id,
        }
        child_span = build_span(
            tool_name, "TOOL", generate_span_id(), trace_id,
            parent_span_id, tool_start_ms, tool_end_ms, tool_attrs,
            SERVICE_NAME, SCOPE_NAME,
        )
        child_spans.append(child_span)

    # --- INTERNAL child spans from API/websocket requests (bash lines 381-421) ---
    api_events = [
        e for e in events
        if e.get("event") in ("codex.api_request", "codex.websocket_request")
    ]
    for req_event in api_events:
        ra = req_event.get("attrs", {})
        req_model = ra.get("model") or ra.get("llm.model_name") or "unknown"
        req_status = str(ra.get("status") or ra.get("status_code") or ra.get("success") or "ok")
        req_attempt = str(ra.get("attempt", "1"))
        req_duration_ms = ra.get("duration_ms", "0")
        req_auth_mode = ra.get("auth_mode", "")
        req_conn_reused = ra.get("auth.connection_reused", "")
        req_ns = _safe_int(req_event.get("time_ns", 0))
        req_start_ms = req_ns // 1_000_000 or event_start_time

        request_attrs = {
            "openinference.span.kind": "CHAIN",
            "codex.request.model": req_model,
            "codex.request.status": req_status,
            "codex.request.attempt": req_attempt,
            "codex.request.duration_ms": _safe_int(req_duration_ms),
            "session.id": session_id,
        }
        # Only include non-empty optional attrs (matches bash with_entries filter)
        if req_auth_mode:
            request_attrs["codex.request.auth_mode"] = req_auth_mode
        if req_conn_reused:
            request_attrs["codex.request.connection_reused"] = req_conn_reused == "true"

        child_span = build_span(
            f"API Request ({req_model})", "INTERNAL",
            generate_span_id(), trace_id, parent_span_id,
            req_start_ms, req_start_ms, request_attrs,
            SERVICE_NAME, SCOPE_NAME,
        )
        child_spans.append(child_span)

    return child_spans, event_start_time, event_end_time


def _enrich_tokens_from_event_attrs(ea: dict, attrs: dict) -> None:
    """Extract token counts from SSE event attrs and apply to parent attrs.

    Matches bash lines 286-313 — tries multiple key variants for each count.
    """
    def _pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v is not None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    pass
        return None

    prompt = _pick(ea, "prompt_tokens", "input_tokens", "input_token_count", "usage.prompt_tokens")
    completion = _pick(ea, "completion_tokens", "output_tokens", "output_token_count", "usage.completion_tokens")
    total = _pick(ea, "total_tokens", "usage.total_tokens")

    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    if prompt is not None:
        attrs["llm.token_count.prompt"] = prompt
    if completion is not None:
        attrs["llm.token_count.completion"] = completion
    if total is not None:
        attrs["llm.token_count.total"] = total


def _safe_int(val) -> int:
    """Convert to int, returning 0 on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def _handle_notify(input_json: dict) -> None:
    """Main notify handler, broken into phases matching notify.sh."""

    # Phase 1: Event filtering (bash lines 22-27)
    event_type = input_json.get("type", "")
    if event_type != "agent-turn-complete":
        log(f"Ignoring event type: {event_type}")
        return

    # Phase 2: Parse payload with flexible key names (bash lines 29-90)
    thread_id = _flex_get(input_json, "thread-id", "thread_id", "threadId")
    turn_id = _flex_get(input_json, "turn-id", "turn_id", "turnId")
    cwd = _flex_get(input_json, "cwd", "working-directory", "working_directory")
    user_input = _flex_get_obj(input_json, "input-messages", "input_messages", "inputMessages")
    assistant_msg = _flex_get_obj(
        input_json, "last-assistant-message", "last_assistant_message", "lastAssistantMessage"
    )

    debug_prefix = f"notify_{thread_id or 'unknown'}_{turn_id or 'unknown'}"
    debug_dump(f"{debug_prefix}_raw", input_json)

    assistant_output = _as_text(assistant_msg)
    user_prompt = _extract_user_prompt(user_input)

    # Truncate to reasonable sizes (bash lines 87-89)
    user_prompt = user_prompt[:5000]
    assistant_output = assistant_output[:5000]
    if not assistant_output:
        assistant_output = "(No response)"

    debug_dump(f"{debug_prefix}_text", {"input": user_prompt, "assistant": assistant_output})

    # Phase 3: Resolve session and state (bash lines 48-56)
    state = resolve_session(thread_id)
    ensure_session_initialized(state, thread_id, cwd or os.getcwd())
    session_id = state.get("session_id")
    state.increment("trace_count")
    trace_count = state.get("trace_count")
    project_name = state.get("project_name")
    user_id = state.get("user_id")

    # Phase 4: Generate IDs and build base attributes (bash lines 92-123)
    trace_id = generate_trace_id()
    span_id = generate_span_id()
    start_time = get_timestamp_ms()
    end_time = start_time  # Turn already completed, no precise timing from notify

    output_messages = [{"message.role": "assistant", "message.content": assistant_output}]

    attrs = {
        "session.id": session_id,
        "trace.number": trace_count,
        "project.name": project_name,
        "openinference.span.kind": "LLM",
        "input.value": user_prompt,
        "output.value": assistant_output,
        "codex.turn_id": turn_id,
        "codex.thread_id": thread_id,
        "llm.output_messages": json.dumps(output_messages),
    }
    if user_id:
        attrs["user.id"] = user_id

    # Phase 5: Token enrichment from notify payload (bash lines 125-166)
    usage = _find_token_usage(input_json)
    if usage:
        attrs["codex.token_usage"] = json.dumps(usage)
        debug_dump(f"{debug_prefix}_token_usage", usage)
        counts = _extract_token_counts(usage)
        if counts["prompt"] is not None:
            attrs["llm.token_count.prompt"] = counts["prompt"]
        if counts["completion"] is not None:
            attrs["llm.token_count.completion"] = counts["completion"]
        if counts["total"] is not None:
            attrs["llm.token_count.total"] = counts["total"]

    # Phase 6: Tool call extraction from notify payload (bash lines 168-211)
    tool_calls = _find_tool_calls(input_json)
    if tool_calls:
        count = len(tool_calls)
        attrs["llm.tool_call_count"] = count
        if count > 0:
            preview = tool_calls[:5]
            attrs["llm.tool_calls"] = json.dumps(preview)
            if count > 5:
                attrs["llm.tool_calls_omitted"] = count - 5
        debug_dump(f"{debug_prefix}_tool_calls", tool_calls)

    # Phase 7: Drain collector event buffer (bash lines 213-254)
    collector_port = int(os.environ.get("ARIZE_COLLECTOR_PORT", "4318"))
    events = _drain_events(thread_id, state, collector_port)
    debug_dump(f"{debug_prefix}_collector_events", events)

    if events:
        max_ns = 0
        for e in events:
            try:
                t = int(e.get("time_ns", 0))
                if t > max_ns:
                    max_ns = t
            except (ValueError, TypeError):
                pass
        if max_ns > 0:
            state.set("last_collector_time_ns", str(max_ns))

    # Phase 8: Enrich parent span and build child spans from events
    child_spans = []
    if events:
        log(f"Processing {len(events)} collector events")
        child_spans, event_start, event_end = _build_child_spans(
            events, trace_id, span_id, session_id, start_time, attrs,
        )
        # Use event-derived timing if available
        if event_start != start_time or event_end != start_time:
            start_time = event_start
            end_time = event_end

    # Phase 9: Build and send (bash lines 424-440)
    parent_span = build_span(
        f"Turn {trace_count}", "LLM", span_id, trace_id, "",
        start_time, end_time, attrs, SERVICE_NAME, SCOPE_NAME,
    )
    debug_dump(f"{debug_prefix}_parent_span", parent_span)

    if child_spans:
        log(f"Building multi-span payload: 1 parent + {len(child_spans)} children")
        all_spans = [parent_span] + child_spans
        multi_payload = build_multi_span(all_spans, SERVICE_NAME, SCOPE_NAME)
        debug_dump(f"{debug_prefix}_multi_span", multi_payload)
        _send_span(multi_payload, collector_port)
    else:
        debug_dump(f"{debug_prefix}_span", parent_span)
        _send_span(parent_span, collector_port)

    log(f"Turn {trace_count} sent (thread={thread_id}, turn={turn_id}, children={len(child_spans)})")

    # Phase 10: Periodic GC (bash lines 442-445)
    try:
        tc = int(trace_count or "0")
    except (ValueError, TypeError):
        tc = 0
    if tc % 10 == 0:
        gc_stale_state_files()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def notify():
    """Entry point for arize-hook-codex-notify. Codex hook.

    Input contract: JSON as sys.argv[1] (NOT stdin -- Codex passes JSON as a CLI arg).
    No stdout output -- Codex doesn't expect a response.
    """
    try:
        # Load env file before anything else (matches bash line 13)
        load_env_file(Path.home() / ".codex" / "arize-env.sh")

        if not check_requirements():
            return

        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        input_json = json.loads(raw)
        _handle_notify(input_json)
    except Exception as e:
        error(f"codex notify hook failed: {e}")


if __name__ == "__main__":
    notify()
