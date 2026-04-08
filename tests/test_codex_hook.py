#!/usr/bin/env python3
"""Tests for core.hooks.codex.handlers — the Codex notify hook handler."""

import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

import pytest

from core.hooks.codex.handlers import (
    _as_text,
    _build_child_spans,
    _drain_events,
    _extract_token_counts,
    _extract_user_prompt,
    _find_token_usage,
    _find_tool_calls,
    _flex_get,
    _handle_notify,
    _send_span,
    notify,
)
from core.common import StateManager


@pytest.fixture(autouse=True)
def _mock_sleep(monkeypatch):
    """Mock time.sleep to prevent real delays while tracking calls."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    return sleep_calls



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _DrainHandler(BaseHTTPRequestHandler):
    """Mock collector that responds to /drain/ requests."""

    def do_GET(self):
        if self.path.startswith("/drain/"):
            resp = json.dumps(self.server._drain_response).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server._received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture
def drain_server():
    """Start a mock collector with configurable drain response.

    Yields dict with: port, set_drain_response(data), received (list of POSTed spans).
    """
    server = HTTPServer(("127.0.0.1", 0), _DrainHandler)
    server._drain_response = []
    server._received = []
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_drain(data):
        server._drain_response = data

    yield {
        "port": port,
        "set_drain": set_drain,
        "received": server._received,
    }
    server.shutdown()


@pytest.fixture
def codex_state(tmp_harness_dir):
    """Create a Codex StateManager pointed at the temp harness dir."""
    import core.constants as c
    state_dir = c.STATE_BASE_DIR / "codex"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Also patch the adapter's STATE_DIR
    import core.hooks.codex.adapter as adapter
    original_state_dir = adapter.STATE_DIR
    adapter.STATE_DIR = state_dir

    sm = StateManager(
        state_dir=state_dir,
        state_file=state_dir / "state_test-thread.yaml",
        lock_path=state_dir / ".lock_test-thread",
    )
    sm.init_state()
    yield sm

    adapter.STATE_DIR = original_state_dir


# ---------------------------------------------------------------------------
# Event filtering tests
# ---------------------------------------------------------------------------

class TestEventFiltering:

    def test_agent_turn_complete_processed(self, tmp_harness_dir, monkeypatch):
        """type: agent-turn-complete processes normally."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")  # unreachable port

        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)

        # Mock _send_span to capture what was sent
        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t1",
                "turn-id": "turn1",
                "input-messages": [{"role": "user", "content": "hello"}],
                "last-assistant-message": "world",
            })

        assert len(sent) == 1
        # Verify it's an OTLP payload
        assert "resourceSpans" in sent[0]

    def test_non_agent_turn_ignored(self, monkeypatch, capsys):
        """type: session-start is ignored."""
        monkeypatch.setenv("ARIZE_VERBOSE", "true")
        _handle_notify({"type": "session-start"})
        # No crash, no span sent

    def test_missing_type_ignored(self, monkeypatch):
        """Missing type field is ignored."""
        _handle_notify({})
        # No crash


# ---------------------------------------------------------------------------
# _flex_get tests
# ---------------------------------------------------------------------------

class TestFlexGet:

    def test_hyphenated_key(self):
        assert _flex_get({"thread-id": "abc"}, "thread-id", "thread_id", "threadId") == "abc"

    def test_underscored_key(self):
        assert _flex_get({"thread_id": "abc"}, "thread-id", "thread_id", "threadId") == "abc"

    def test_camel_case_key(self):
        assert _flex_get({"threadId": "abc"}, "thread-id", "thread_id", "threadId") == "abc"

    def test_none_returns_default(self):
        assert _flex_get({}, "thread-id", "thread_id", "threadId") == ""

    def test_custom_default(self):
        assert _flex_get({}, "a", "b", default="fallback") == "fallback"

    def test_first_match_wins(self):
        d = {"thread-id": "first", "thread_id": "second"}
        assert _flex_get(d, "thread-id", "thread_id") == "first"

    def test_skips_empty_string(self):
        d = {"thread-id": "", "thread_id": "found"}
        assert _flex_get(d, "thread-id", "thread_id") == "found"

    def test_skips_none_value(self):
        d = {"thread-id": None, "thread_id": "found"}
        assert _flex_get(d, "thread-id", "thread_id") == "found"


# ---------------------------------------------------------------------------
# _as_text tests
# ---------------------------------------------------------------------------

class TestAsText:

    def test_none(self):
        assert _as_text(None) == ""

    def test_string(self):
        assert _as_text("hello") == "hello"

    def test_list(self):
        assert _as_text(["a", "b"]) == "a\nb"

    def test_dict_text_key(self):
        assert _as_text({"text": "hello"}) == "hello"

    def test_dict_content_key(self):
        assert _as_text({"content": "hello"}) == "hello"

    def test_nested_dict(self):
        assert _as_text({"content": {"text": "nested"}}) == "nested"

    def test_dict_fallback_json(self):
        result = _as_text({"foo": "bar"})
        assert "foo" in result
        assert "bar" in result

    def test_number(self):
        assert _as_text(42) == "42"

    def test_nested_list_of_dicts(self):
        data = [{"text": "a"}, {"text": "b"}]
        assert _as_text(data) == "a\nb"

    def test_deeply_nested(self):
        data = {"content": {"message": {"text": "deep"}}}
        assert _as_text(data) == "deep"

    def test_empty_string(self):
        assert _as_text("") == ""

    def test_empty_list(self):
        assert _as_text([]) == ""


# ---------------------------------------------------------------------------
# _extract_user_prompt tests
# ---------------------------------------------------------------------------

class TestExtractUserPrompt:

    def test_list_of_messages_last_user(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert _extract_user_prompt(messages) == "second"

    def test_list_of_strings(self):
        assert _extract_user_prompt(["", "hello", "world"]) == "world"

    def test_plain_string(self):
        assert _extract_user_prompt("hello") == "hello"

    def test_empty_list(self):
        assert _extract_user_prompt([]) == ""

    def test_none_input(self):
        assert _extract_user_prompt(None) == ""

    def test_nested_content(self):
        messages = [{"role": "user", "content": {"text": "nested"}}]
        assert _extract_user_prompt(messages) == "nested"

    def test_mixed_types_in_list(self):
        """If no user-role message, falls back to last string."""
        messages = [{"role": "assistant", "content": "skip"}, "fallback"]
        assert _extract_user_prompt(messages) == "fallback"


# ---------------------------------------------------------------------------
# Truncation and empty assistant tests
# ---------------------------------------------------------------------------

class TestTruncationAndDefaults:

    def test_truncation_5000(self, tmp_harness_dir, monkeypatch):
        """Both user prompt and assistant output are truncated to 5000 chars."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t1",
                "input-messages": "x" * 10000,
                "last-assistant-message": "y" * 10000,
            })

        span = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert len(attrs["input.value"]["stringValue"]) == 5000
        assert len(attrs["output.value"]["stringValue"]) == 5000

    def test_empty_assistant_becomes_no_response(self, tmp_harness_dir, monkeypatch):
        """Empty assistant output becomes '(No response)'."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t1",
                "input-messages": "hello",
                "last-assistant-message": "",
            })

        span = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["output.value"]["stringValue"] == "(No response)"


# ---------------------------------------------------------------------------
# Token enrichment tests (from payload)
# ---------------------------------------------------------------------------

class TestFindTokenUsage:

    def test_finds_at_root(self):
        data = {"token_usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        assert _find_token_usage(data) == {"prompt_tokens": 10, "completion_tokens": 20}

    def test_finds_in_last_assistant_message(self):
        data = {"last-assistant-message": {"usage": {"prompt_tokens": 5}}}
        assert _find_token_usage(data) == {"prompt_tokens": 5}

    def test_returns_none_when_absent(self):
        assert _find_token_usage({"type": "agent-turn-complete"}) is None

    def test_finds_hyphenated_key(self):
        data = {"token-usage": {"input_tokens": 42}}
        assert _find_token_usage(data) == {"input_tokens": 42}


class TestExtractTokenCounts:

    def test_standard_keys(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        counts = _extract_token_counts(usage)
        assert counts == {"prompt": 10, "completion": 20, "total": 30}

    def test_camel_case_keys(self):
        usage = {"inputTokens": 15, "outputTokens": 25}
        counts = _extract_token_counts(usage)
        assert counts["prompt"] == 15
        assert counts["completion"] == 25

    def test_auto_compute_total(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        counts = _extract_token_counts(usage)
        assert counts["total"] == 30

    def test_string_values_converted(self):
        usage = {"prompt_tokens": "10", "completion_tokens": "20"}
        counts = _extract_token_counts(usage)
        assert counts["prompt"] == 10
        assert counts["completion"] == 20
        assert counts["total"] == 30

    def test_empty_usage(self):
        counts = _extract_token_counts({})
        assert counts == {"prompt": None, "completion": None, "total": None}


# ---------------------------------------------------------------------------
# Tool call extraction tests
# ---------------------------------------------------------------------------

class TestFindToolCalls:

    def test_finds_at_root(self):
        data = {"tool_calls": [{"name": "edit"}, {"name": "run"}]}
        result = _find_tool_calls(data)
        assert len(result) == 2

    def test_finds_in_last_assistant_message(self):
        data = {"last-assistant-message": {"toolCalls": [{"name": "search"}]}}
        result = _find_tool_calls(data)
        assert len(result) == 1

    def test_returns_none_when_absent(self):
        assert _find_tool_calls({"type": "test"}) is None

    def test_tool_count_and_preview(self, tmp_harness_dir, monkeypatch):
        """Tool count attr set, preview is first 5, omitted count for > 5."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)

        tools = [{"name": f"tool{i}"} for i in range(8)]
        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-tools",
                "input-messages": "test",
                "last-assistant-message": "done",
                "tool_calls": tools,
            })

        span = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["llm.tool_call_count"]["intValue"] == 8
        preview = json.loads(attrs["llm.tool_calls"]["stringValue"])
        assert len(preview) == 5
        assert attrs["llm.tool_calls_omitted"]["intValue"] == 3

    def test_no_tool_calls_no_attrs(self, tmp_harness_dir, monkeypatch):
        """When no tool calls found, no tool attributes on span."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-no-tools",
                "input-messages": "test",
                "last-assistant-message": "done",
            })

        span = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_keys = {a["key"] for a in span["attributes"]}
        assert "llm.tool_call_count" not in attr_keys
        assert "llm.tool_calls" not in attr_keys


# ---------------------------------------------------------------------------
# Event drain tests
# ---------------------------------------------------------------------------

class TestDrainEvents:

    def test_drain_returns_events(self, drain_server, codex_state):
        """Drain with events returns parsed list."""
        events = [
            {"event": "codex.tool_decision", "time_ns": "1000000000", "attrs": {"tool_name": "edit"}},
        ]
        drain_server["set_drain"](events)

        result = _drain_events("test-thread", codex_state, drain_server["port"])
        assert len(result) == 1
        assert result[0]["event"] == "codex.tool_decision"

    def test_drain_empty_returns_empty(self, drain_server, codex_state):
        """Empty drain response returns []."""
        drain_server["set_drain"]([])
        result = _drain_events("test-thread", codex_state, drain_server["port"])
        assert result == []

    def test_drain_missing_thread_id(self, codex_state):
        """Missing thread_id skips drain entirely."""
        result = _drain_events("", codex_state, 9999)
        assert result == []

    def test_drain_retry_second_attempt(self, codex_state, _mock_sleep):
        """First attempt returns [], second returns events; sleep called with correct delay."""
        attempt_count = [0]
        events = [{"event": "codex.api_request", "time_ns": "5000000000", "attrs": {}}]

        class RetryHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                attempt_count[0] += 1
                if attempt_count[0] == 1:
                    resp = b"[]"
                else:
                    resp = json.dumps(events).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), RetryHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = _drain_events("test-thread", codex_state, port)
            assert len(result) == 1
            assert attempt_count[0] == 2
            # Verify retry sleep was called with the correct delay (1.2s for second attempt)
            assert _mock_sleep == [1.2]
        finally:
            server.shutdown()

    def test_drain_saves_last_collector_time(self, tmp_harness_dir, monkeypatch, drain_server):
        """last_collector_time_ns saved in state after successful drain."""
        import core.constants as c
        import core.hooks.codex.adapter as adapter
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", str(drain_server["port"]))

        events = [
            {"event": "codex.tool_decision", "time_ns": "2000000000", "attrs": {}},
            {"event": "codex.tool_result", "time_ns": "3000000000", "attrs": {}},
        ]
        drain_server["set_drain"](events)

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-drain",
                "input-messages": "test",
                "last-assistant-message": "done",
            })

        # Verify state was updated
        sm = StateManager(
            state_dir=state_dir,
            state_file=state_dir / "state_t-drain.yaml",
        )
        assert sm.get("last_collector_time_ns") == "3000000000"


# ---------------------------------------------------------------------------
# Child span building tests
# ---------------------------------------------------------------------------

class TestBuildChildSpans:

    def test_tool_decision_with_result(self):
        """tool_decision + matching tool_result -> TOOL child span."""
        events = [
            {
                "event": "codex.tool_decision",
                "time_ns": "1000000000",
                "attrs": {"tool_name": "edit_file", "approved": "true"},
            },
            {
                "event": "codex.tool_result",
                "time_ns": "2000000000",
                "attrs": {"tool_name": "edit_file", "output": "File edited"},
            },
        ]
        attrs = {}
        children, start, end = _build_child_spans(
            events, "trace123", "parent456", "sess1", 1000, attrs,
        )
        assert len(children) == 1
        span = children[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["name"] == "edit_file"
        span_attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span_attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert span_attrs["output.value"]["stringValue"] == "File edited"
        assert span_attrs["codex.tool.approval_status"]["stringValue"] == "true"

    def test_tool_decision_without_matching_result(self):
        """tool_decision without matching result uses fallback timing."""
        events = [
            {
                "event": "codex.tool_decision",
                "time_ns": "1000000000",
                "attrs": {"tool_name": "search"},
            },
        ]
        attrs = {}
        children, _, _ = _build_child_spans(
            events, "trace123", "parent456", "sess1", 1000, attrs,
        )
        assert len(children) == 1
        span = children[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["name"] == "search"

    def test_api_request_creates_internal_span(self):
        """codex.api_request -> INTERNAL child span."""
        events = [
            {
                "event": "codex.api_request",
                "time_ns": "1500000000",
                "attrs": {"model": "gpt-4", "status": "200", "attempt": "1", "duration_ms": "500"},
            },
        ]
        attrs = {}
        children, _, _ = _build_child_spans(
            events, "trace123", "parent456", "sess1", 1000, attrs,
        )
        assert len(children) == 1
        span = children[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["name"] == "API Request (gpt-4)"
        span_attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span_attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert span_attrs["codex.request.model"]["stringValue"] == "gpt-4"
        assert span_attrs["codex.request.duration_ms"]["intValue"] == 500

    def test_websocket_request_creates_internal_span(self):
        """codex.websocket_request also creates INTERNAL child span."""
        events = [
            {
                "event": "codex.websocket_request",
                "time_ns": "1500000000",
                "attrs": {"model": "o3"},
            },
        ]
        attrs = {}
        children, _, _ = _build_child_spans(
            events, "trace123", "parent456", "sess1", 1000, attrs,
        )
        assert len(children) == 1
        span = children[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert "API Request" in span["name"]

    def test_optional_attrs_omitted_when_empty(self):
        """auth_mode and connection_reused omitted when empty."""
        events = [
            {
                "event": "codex.api_request",
                "time_ns": "1500000000",
                "attrs": {"model": "gpt-4", "auth_mode": "", "auth.connection_reused": ""},
            },
        ]
        attrs = {}
        children, _, _ = _build_child_spans(
            events, "trace123", "parent456", "sess1", 1000, attrs,
        )
        span = children[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_keys = {a["key"] for a in span["attributes"]}
        assert "codex.request.auth_mode" not in attr_keys
        assert "codex.request.connection_reused" not in attr_keys


# ---------------------------------------------------------------------------
# Event enrichment tests
# ---------------------------------------------------------------------------

class TestEventEnrichment:

    def test_model_name_from_conversation_starts(self):
        """codex.conversation_starts enriches llm.model_name on parent."""
        events = [
            {"event": "codex.conversation_starts", "time_ns": "1000000000", "attrs": {"model": "o3-mini"}},
        ]
        attrs = {}
        _build_child_spans(events, "t", "p", "s", 1000, attrs)
        assert attrs["llm.model_name"] == "o3-mini"

    def test_token_enrichment_from_sse(self):
        """codex.sse_event with response.completed enriches token counts."""
        events = [
            {
                "event": "codex.sse_event",
                "time_ns": "2000000000",
                "attrs": {
                    "type": "response.completed",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                },
            },
        ]
        attrs = {}
        _build_child_spans(events, "t", "p", "s", 1000, attrs)
        assert attrs["llm.token_count.prompt"] == 100
        assert attrs["llm.token_count.completion"] == 50
        assert attrs["llm.token_count.total"] == 150

    def test_sandbox_approval_from_conversation_starts(self):
        """codex.conversation_starts enriches sandbox/approval mode."""
        events = [
            {
                "event": "codex.conversation_starts",
                "time_ns": "1000000000",
                "attrs": {"sandbox": "docker", "approval_mode": "auto"},
            },
        ]
        attrs = {}
        _build_child_spans(events, "t", "p", "s", 1000, attrs)
        assert attrs["codex.sandbox_mode"] == "docker"
        assert attrs["codex.approval_mode"] == "auto"

    def test_timing_adjusted_from_events(self):
        """Timing adjusted from event timestamps (min -> start, max -> end)."""
        events = [
            {"event": "codex.tool_decision", "time_ns": "2000000000", "attrs": {"tool_name": "x"}},
            {"event": "codex.tool_result", "time_ns": "5000000000", "attrs": {"tool_name": "x"}},
        ]
        attrs = {}
        children, start, end = _build_child_spans(events, "t", "p", "s", 1000, attrs)
        assert start == 2000  # 2000000000 / 1_000_000
        assert end == 5000    # 5000000000 / 1_000_000
        assert attrs["codex.trace.duration_ms"] == 3000


# ---------------------------------------------------------------------------
# Multi-span assembly tests
# ---------------------------------------------------------------------------

class TestMultiSpanAssembly:

    def test_with_children_sends_multi_span(self, tmp_harness_dir, monkeypatch, drain_server):
        """With child spans, multi-span payload sent (parent + children)."""
        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", str(drain_server["port"]))

        drain_server["set_drain"]([
            {"event": "codex.tool_decision", "time_ns": "1000000000", "attrs": {"tool_name": "edit"}},
            {"event": "codex.tool_result", "time_ns": "2000000000", "attrs": {"tool_name": "edit", "output": "ok"}},
        ])

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-multi",
                "input-messages": "test",
                "last-assistant-message": "done",
            })

        assert len(sent) == 1
        spans = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 2  # parent + 1 child
        names = [s["name"] for s in spans]
        assert any("Turn" in n for n in names)
        assert "edit" in names

    def test_without_children_sends_single_span(self, tmp_harness_dir, monkeypatch):
        """Without child spans, single parent span sent."""
        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-single",
                "input-messages": "test",
                "last-assistant-message": "done",
            })

        assert len(sent) == 1
        spans = sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1  # parent only

    def test_debug_dumps_when_enabled(self, tmp_harness_dir, monkeypatch):
        """Debug dumps written at each stage when trace_debug enabled."""
        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_TRACE_DEBUG", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", "19999")

        with mock.patch("core.hooks.codex.handlers._send_span"):
            _handle_notify({
                "type": "agent-turn-complete",
                "thread-id": "t-debug",
                "input-messages": "test",
                "last-assistant-message": "done",
            })

        debug_dir = c.STATE_BASE_DIR / "debug"
        assert debug_dir.is_dir()
        debug_files = list(debug_dir.glob("notify_t-debug_*.yaml"))
        assert len(debug_files) >= 2  # at least _raw and _text dumps


# ---------------------------------------------------------------------------
# Integration test with fixture
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_full_handle_notify_with_fixture(self, tmp_harness_dir, monkeypatch, drain_server, load_fixture):
        """Full _handle_notify with codex_notify.json fixture + mock drain."""
        import core.hooks.codex.adapter as adapter
        import core.constants as c
        state_dir = c.STATE_BASE_DIR / "codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_COLLECTOR_PORT", str(drain_server["port"]))

        # Load the fixture
        fixture = load_fixture("codex_notify.json")

        # Set up drain with some events
        drain_server["set_drain"]([
            {"event": "codex.conversation_starts", "time_ns": "1000000000", "attrs": {"model": "gpt-4o"}},
            {"event": "codex.api_request", "time_ns": "1500000000", "attrs": {"model": "gpt-4o", "status": "200"}},
        ])

        sent = []
        with mock.patch("core.hooks.codex.handlers._send_span", side_effect=lambda p, port: sent.append(p)):
            _handle_notify(fixture)

        assert len(sent) == 1
        payload = sent[0]
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) >= 1  # at least parent

        # Verify parent span attributes
        parent = spans[0]
        attr_map = {a["key"]: a["value"] for a in parent["attributes"]}
        assert "session.id" in attr_map
        assert attr_map["openinference.span.kind"]["stringValue"] == "LLM"
        assert attr_map["input.value"]["stringValue"] == "hello"
        assert attr_map["output.value"]["stringValue"] == "I can help with that."
        assert attr_map["codex.thread_id"]["stringValue"] == "thread-1"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_exception_in_handle_notify_caught(self, monkeypatch, capsys):
        """Exception in _handle_notify is caught by notify()."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")

        with mock.patch("core.hooks.codex.handlers._handle_notify", side_effect=RuntimeError("boom")), \
             mock.patch.object(sys, "argv", ["hook", '{"type":"agent-turn-complete"}']):
            # Should not raise
            notify()

        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_invalid_json_handled(self, monkeypatch, capsys):
        """Invalid JSON in argv is handled gracefully."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")

        with mock.patch.object(sys, "argv", ["hook", "not-json"]):
            notify()

        captured = capsys.readouterr()
        assert "codex notify hook failed" in captured.err

    def test_no_argv_uses_empty_json(self, monkeypatch):
        """No sys.argv[1] defaults to empty JSON."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")

        with mock.patch.object(sys, "argv", ["hook"]):
            # Should not raise — empty JSON means no "agent-turn-complete" type → early return
            notify()
