#!/usr/bin/env python3
"""Tests for cursor_tracing.hooks.handlers — the Cursor hook dispatcher and 14 event handlers."""

import io
import json
import sys
from unittest import mock

import pytest

from cursor_tracing.hooks import adapter
from cursor_tracing.hooks.handlers import _dispatch, _event_name, _jq_str, _print_permissive, _trace_id_from_event, main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_sleep(monkeypatch):
    """Mock time.sleep to prevent real delays while tracking calls."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    return sleep_calls


@pytest.fixture(autouse=True)
def _patch_cursor_state(tmp_path, monkeypatch):
    """Redirect cursor adapter STATE_DIR to temp."""
    state_dir = tmp_path / "state" / "cursor"
    state_dir.mkdir(parents=True)
    monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
    return state_dir


@pytest.fixture
def captured_spans():
    """Mock send_span and collect all payloads sent."""
    sent = []
    with mock.patch("cursor_tracing.hooks.handlers.send_span", side_effect=lambda s: sent.append(s)):
        yield sent


# ---------------------------------------------------------------------------
# _print_permissive tests
# ---------------------------------------------------------------------------


class TestPrintPermissive:

    def test_before_event_returns_permission_allow(self):
        """before* events write {"permission": "allow"} to sys.__stdout__."""
        buf = io.StringIO()
        with mock.patch.object(sys, "__stdout__", buf):
            _print_permissive("beforeSubmitPrompt")
        assert json.loads(buf.getvalue()) == {"permission": "allow"}

    def test_before_shell_event(self):
        """beforeShellExecution also returns permission allow."""
        buf = io.StringIO()
        with mock.patch.object(sys, "__stdout__", buf):
            _print_permissive("beforeShellExecution")
        assert json.loads(buf.getvalue()) == {"permission": "allow"}

    def test_after_event_returns_continue_true(self):
        """Non-before events write {"continue": true}."""
        buf = io.StringIO()
        with mock.patch.object(sys, "__stdout__", buf):
            _print_permissive("afterAgentResponse")
        assert json.loads(buf.getvalue()) == {"continue": True}

    def test_stop_event_returns_continue_true(self):
        """stop event writes {"continue": true}."""
        buf = io.StringIO()
        with mock.patch.object(sys, "__stdout__", buf):
            _print_permissive("stop")
        assert json.loads(buf.getvalue()) == {"continue": True}

    def test_empty_event_returns_continue_true(self):
        """Empty event string writes {"continue": true}."""
        buf = io.StringIO()
        with mock.patch.object(sys, "__stdout__", buf):
            _print_permissive("")
        assert json.loads(buf.getvalue()) == {"continue": True}


# ---------------------------------------------------------------------------
# _jq_str tests
# ---------------------------------------------------------------------------


class TestJqStr:

    def test_returns_first_matching_key(self):
        d = {"prompt": "hello", "input": "world"}
        assert _jq_str(d, "prompt", "input") == "hello"

    def test_skips_to_second_key(self):
        d = {"input": "world"}
        assert _jq_str(d, "prompt", "input") == "world"

    def test_returns_default_when_no_match(self):
        assert _jq_str({}, "a", "b", default="fallback") == "fallback"

    def test_returns_empty_default(self):
        assert _jq_str({}, "a") == ""

    def test_skips_none_value(self):
        d = {"a": None, "b": "found"}
        assert _jq_str(d, "a", "b") == "found"

    def test_skips_empty_string_value(self):
        d = {"a": "", "b": "found"}
        assert _jq_str(d, "a", "b") == "found"

    def test_converts_non_string_to_str(self):
        d = {"count": 42}
        assert _jq_str(d, "count") == "42"

    def test_all_none_returns_default(self):
        d = {"a": None, "b": None}
        assert _jq_str(d, "a", "b", default="x") == "x"


# ---------------------------------------------------------------------------
# _dispatch tests
# ---------------------------------------------------------------------------


class TestDispatch:

    def test_routes_to_correct_handler(self, monkeypatch):
        """Known event routes to correct handler function."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers._handle_before_submit_prompt") as h,
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            h.assert_called_once()

    def test_routes_after_agent_response(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers._handle_after_agent_response") as h,
        ):
            _dispatch("afterAgentResponse", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_routes_stop(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers._handle_stop") as h,
        ):
            _dispatch("stop", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_unknown_event_logs_warning(self, monkeypatch):
        """Unknown event logs warning, no crash."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.log") as log_mock,
        ):
            _dispatch("unknownEvent", {"conversation_id": "c1", "generation_id": "g1"})
            log_mock.assert_called_once()
            assert "Unknown" in log_mock.call_args[0][0]

    def test_tracing_disabled_returns_early(self, monkeypatch):
        """Tracing disabled -> returns without dispatching."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        with mock.patch("cursor_tracing.hooks.handlers._handle_before_submit_prompt") as h:
            _dispatch("beforeSubmitPrompt", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_not_called()

    def test_no_backend_send_fails_gracefully(self, monkeypatch):
        """send_span failure doesn't crash — root span sent from afterAgentResponse."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.send_span", return_value=False) as send_mock,
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            # Root span is deferred — not sent yet
            send_mock.assert_not_called()
            _dispatch(
                "afterAgentResponse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "response": "done",
                },
            )
            # LLM child span + deferred root span both sent
            assert send_mock.call_count == 2


# ---------------------------------------------------------------------------
# _handle_before_submit_prompt tests
# ---------------------------------------------------------------------------


class TestHandleBeforeSubmitPrompt:

    def test_deferred_root_span_sent_at_agent_response(self, captured_spans, monkeypatch):
        """Root span is deferred until afterAgentResponse, then sent with input+output."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="aabb" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_save") as save_mock,
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "prompt": "fix the bug",
                    "model_name": "claude-4",
                },
            )

        save_mock.assert_called_once_with("gen-1", "aabb" * 4)
        # Root span is deferred — not sent yet
        assert len(captured_spans) == 0

        with mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=9000):
            _dispatch(
                "afterAgentResponse",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "response": "I fixed the bug",
                    "model_name": "claude-4",
                },
            )

        # afterAgentResponse sends LLM child + deferred root
        root_spans = [
            s for s in captured_spans if s["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] == "User Prompt"
        ]
        assert len(root_spans) == 1
        span = root_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["input.value"]["stringValue"] == "fix the bug"
        assert attrs["output.value"]["stringValue"] == "I fixed the bug"
        assert attrs["session.id"]["stringValue"] == "conv-1"
        assert span["name"] == "User Prompt"


# ---------------------------------------------------------------------------
# _handle_after_agent_response tests
# ---------------------------------------------------------------------------


class TestHandleAfterAgentResponse:

    def test_creates_llm_span_with_response(self, captured_spans, monkeypatch):
        """Creates LLM span with response and gets parent from gen_root_span_get."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="ccdd" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent123") as get_mock,
        ):
            _dispatch(
                "afterAgentResponse",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "response": "I found the issue",
                    "model_name": "claude-4",
                },
            )

        get_mock.assert_called_once_with("gen-1")
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "LLM"
        assert attrs["output.value"]["stringValue"] == "I found the issue"
        assert span["name"] == "Agent Response"
        assert span["parentSpanId"] == "parent123"


# ---------------------------------------------------------------------------
# _handle_after_shell_execution tests
# ---------------------------------------------------------------------------


class TestHandleAfterShellExecution:

    def test_creates_tool_span_with_popped_state(self, captured_spans, monkeypatch):
        """Creates TOOL span, merges with before state from state_pop."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        popped = {"command": "ls -la", "cwd": "/tmp", "start_ms": "1000", "trace_id": "t1", "conversation_id": "c1"}
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="eeff" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=popped),
        ):
            _dispatch(
                "afterShellExecution",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "output": "total 0",
                    "exit_code": "0",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "shell"
        assert attrs["output.value"]["stringValue"] == "total 0"
        assert attrs["shell.exit_code"]["stringValue"] == "0"
        assert span["name"] == "Shell"

    def test_uses_after_command_when_present(self, captured_spans, monkeypatch):
        """After-event command overrides before-event command."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        popped = {"command": "old_cmd", "start_ms": "1000"}
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=popped),
        ):
            _dispatch(
                "afterShellExecution",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "command": "new_cmd",
                    "output": "ok",
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["input.value"]["stringValue"] == "new_cmd"

    def test_no_popped_state_uses_now(self, captured_spans, monkeypatch):
        """Without popped state, start_ms defaults to now_ms."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=None),
        ):
            _dispatch(
                "afterShellExecution",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "output": "ok",
                },
            )

        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        # start_ms = "3000" -> ns = "3000000000"
        assert span["startTimeUnixNano"] == "3000000000"

    def test_uses_fixture(self, captured_spans, monkeypatch, cursor_after_shell_input):
        """Works with cursor_after_shell fixture."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        fixture = cursor_after_shell_input
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=None),
        ):
            _dispatch(fixture["hook_event_name"], fixture)

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["input.value"]["stringValue"] == "ls -la"
        assert attrs["output.value"]["stringValue"] == "total 0"
        assert attrs["shell.exit_code"]["stringValue"] == "0"


# ---------------------------------------------------------------------------
# _handle_stop tests
# ---------------------------------------------------------------------------


class TestHandleStop:

    def test_creates_chain_span_and_cleans_up(self, captured_spans, monkeypatch):
        """Creates CHAIN span and calls state_cleanup_generation."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="root1"),
            mock.patch("cursor_tracing.hooks.handlers.state_cleanup_generation") as cleanup,
        ):
            _dispatch(
                "stop",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "status": "completed",
                    "loop_count": "3",
                },
            )

        cleanup.assert_called_once_with("gen-1")
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["cursor.stop.status"]["stringValue"] == "completed"
        assert attrs["cursor.stop.loop_count"]["stringValue"] == "3"
        assert span["name"] == "Agent Stop"

    def test_no_gen_id_skips_cleanup(self, captured_spans, monkeypatch):
        """Without gen_id, state_cleanup_generation is not called."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_cleanup_generation") as cleanup,
        ):
            _dispatch("stop", {"conversation_id": "c1"})

        cleanup.assert_not_called()
        assert len(captured_spans) == 1

    def test_optional_attrs_omitted(self, captured_spans, monkeypatch):
        """Status and loop_count omitted when empty."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch("stop", {"conversation_id": "c1", "generation_id": "g1"})

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "cursor.stop.status" not in attr_keys
        assert "cursor.stop.loop_count" not in attr_keys


# ---------------------------------------------------------------------------
# _handle_before_shell_execution tests
# ---------------------------------------------------------------------------


class TestHandleBeforeShellExecution:

    def test_pushes_state(self, monkeypatch):
        """Pushes command, cwd, start_ms, trace_id, conversation_id to state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.state_push") as push_mock,
        ):
            _dispatch(
                "beforeShellExecution",
                {
                    "conversation_id": "c1",
                    "generation_id": "gen-1",
                    "command": "ls -la",
                    "cwd": "/home",
                },
            )

        push_mock.assert_called_once()
        key, value = push_mock.call_args[0]
        assert "gen-1" in key or "gen_1" in key
        assert value["command"] == "ls -la"
        assert value["cwd"] == "/home"
        assert value["start_ms"] == "1000"

    def test_no_gen_id_returns_early(self, monkeypatch):
        """Without gen_id, returns without pushing state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.state_push") as push_mock,
        ):
            _dispatch(
                "beforeShellExecution",
                {
                    "conversation_id": "c1",
                    "command": "ls",
                },
            )

        push_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_after_agent_thought tests
# ---------------------------------------------------------------------------


class TestHandleAfterAgentThought:

    def test_creates_chain_span_with_thought(self, captured_spans, monkeypatch):
        """Creates CHAIN span with thought as output.value."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="abcd" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1") as get_mock,
        ):
            _dispatch(
                "afterAgentThought",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "thought": "thinking about the problem",
                },
            )

        get_mock.assert_called_once_with("gen-1")
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["output.value"]["stringValue"] == "thinking about the problem"
        assert attrs["session.id"]["stringValue"] == "conv-1"
        assert span["name"] == "Agent Thinking"
        assert span["parentSpanId"] == "parent1"


# ---------------------------------------------------------------------------
# _handle_before_mcp_execution tests
# ---------------------------------------------------------------------------


class TestHandleBeforeMcpExecution:

    def test_pushes_state(self, monkeypatch):
        """Pushes tool_name, tool_input, url, command, start_ms to state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1500),
            mock.patch("cursor_tracing.hooks.handlers.state_push") as push_mock,
        ):
            _dispatch(
                "beforeMCPExecution",
                {
                    "conversation_id": "c1",
                    "generation_id": "gen-1",
                    "tool_name": "search",
                    "tool_input": '{"query": "test"}',
                    "url": "http://localhost:3000",
                },
            )

        push_mock.assert_called_once()
        key, value = push_mock.call_args[0]
        assert "gen-1" in key or "gen_1" in key
        assert value["tool_name"] == "search"
        assert value["tool_input"] == '{"query": "test"}'
        assert value["start_ms"] == "1500"

    def test_no_gen_id_returns_early(self, monkeypatch):
        """Without gen_id, returns without pushing state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers.state_push") as push_mock,
        ):
            _dispatch(
                "beforeMCPExecution",
                {
                    "conversation_id": "c1",
                    "tool_name": "search",
                },
            )

        push_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_after_mcp_execution tests
# ---------------------------------------------------------------------------


class TestHandleAfterMcpExecution:

    def test_creates_tool_span_with_popped_state(self, captured_spans, monkeypatch):
        """Creates TOOL span, merges with before state from state_pop."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        popped = {
            "tool_name": "search",
            "tool_input": '{"query": "test"}',
            "url": "http://localhost:3000",
            "command": "",
            "start_ms": "1000",
            "trace_id": "t1",
            "conversation_id": "c1",
        }
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="ffaa" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=popped),
        ):
            _dispatch(
                "afterMCPExecution",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "result": "found 3 items",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "search"
        assert attrs["input.value"]["stringValue"] == '{"query": "test"}'
        assert attrs["output.value"]["stringValue"] == "found 3 items"
        assert span["name"] == "MCP: search"
        assert span["parentSpanId"] == "parent1"

    def test_no_popped_state_uses_input(self, captured_spans, monkeypatch):
        """Without popped state, span still created from input_json fields."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="bbcc" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("cursor_tracing.hooks.handlers.state_pop", return_value=None),
        ):
            _dispatch(
                "afterMCPExecution",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "tool_name": "list_repos",
                    "result": "ok",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["tool.name"]["stringValue"] == "list_repos"
        assert span["name"] == "MCP: list_repos"


# ---------------------------------------------------------------------------
# _handle_before_read_file tests
# ---------------------------------------------------------------------------


class TestHandleBeforeReadFile:

    def test_creates_tool_span(self, captured_spans, monkeypatch):
        """Creates TOOL span with file path as input."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="1122" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
        ):
            _dispatch(
                "beforeReadFile",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "file_path": "/foo/bar.py",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "read_file"
        assert attrs["input.value"]["stringValue"] == "/foo/bar.py"
        assert span["name"] == "Read File"
        assert span["parentSpanId"] == "parent1"


# ---------------------------------------------------------------------------
# _handle_after_file_edit tests
# ---------------------------------------------------------------------------


class TestHandleAfterFileEdit:

    def test_creates_tool_span(self, captured_spans, monkeypatch):
        """Creates TOOL span with file path and diff."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="3344" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
        ):
            _dispatch(
                "afterFileEdit",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "file_path": "/foo/bar.py",
                    "diff": "+added line",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "edit_file"
        assert attrs["input.value"]["stringValue"] == "/foo/bar.py: +added line"
        assert span["name"] == "File Edit"
        assert span["parentSpanId"] == "parent1"

    def test_no_diff_uses_path_only(self, captured_spans, monkeypatch):
        """Without diff, input.value is just the file path."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="3344" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "afterFileEdit",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "file_path": "/foo/bar.py",
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["input.value"]["stringValue"] == "/foo/bar.py"


# ---------------------------------------------------------------------------
# _handle_before_tab_file_read tests
# ---------------------------------------------------------------------------


class TestHandleBeforeTabFileRead:

    def test_creates_tool_span(self, captured_spans, monkeypatch):
        """Creates TOOL span with file path as input for tab read."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="5566" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
        ):
            _dispatch(
                "beforeTabFileRead",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "file_path": "/src/main.ts",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "read_file_tab"
        assert attrs["input.value"]["stringValue"] == "/src/main.ts"
        assert span["name"] == "Tab Read File"
        assert span["parentSpanId"] == "parent1"


# ---------------------------------------------------------------------------
# _handle_after_tab_file_edit tests
# ---------------------------------------------------------------------------


class TestHandleAfterTabFileEdit:

    def test_creates_tool_span(self, captured_spans, monkeypatch):
        """Creates TOOL span with file path and edits for tab edit."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="7788" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent1"),
        ):
            _dispatch(
                "afterTabFileEdit",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "file_path": "/src/main.ts",
                    "edits": "replaced function",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "edit_file_tab"
        assert attrs["input.value"]["stringValue"] == "/src/main.ts: replaced function"
        assert span["name"] == "Tab File Edit"
        assert span["parentSpanId"] == "parent1"

    def test_no_edits_uses_path_only(self, captured_spans, monkeypatch):
        """Without edits, input.value is just the file path."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="7788" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "afterTabFileEdit",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "file_path": "/src/main.ts",
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["input.value"]["stringValue"] == "/src/main.ts"


# ---------------------------------------------------------------------------
# main() entry point tests
# ---------------------------------------------------------------------------


class TestMain:

    def test_reads_stdin_dispatches_prints_permissive(self, monkeypatch, tmp_path):
        """main() reads JSON from stdin, dispatches, prints permissive response."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        input_data = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "c1",
            "generation_id": "g1",
            "prompt": "hello",
        }
        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(input_data))),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
            mock.patch("cursor_tracing.hooks.handlers._dispatch") as dispatch_mock,
        ):
            main()

        dispatch_mock.assert_called_once_with("beforeSubmitPrompt", input_data)
        result = json.loads(stdout_buf.getvalue())
        assert result == {"permission": "allow"}

    def test_invalid_json_still_prints_permissive(self, monkeypatch, tmp_path):
        """Invalid JSON on stdin still prints permissive response."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO("not valid json")),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
        ):
            main()

        result = json.loads(stdout_buf.getvalue())
        # event is "" when JSON parse fails, so we get continue response
        assert result == {"continue": True}

    def test_exception_in_dispatch_still_prints_permissive(self, monkeypatch, tmp_path):
        """Exception in _dispatch still prints permissive response."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        input_data = {
            "hook_event_name": "afterAgentResponse",
            "conversation_id": "c1",
            "generation_id": "g1",
        }
        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(input_data))),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
            mock.patch("cursor_tracing.hooks.handlers._dispatch", side_effect=RuntimeError("boom")),
        ):
            main()

        result = json.loads(stdout_buf.getvalue())
        assert result == {"continue": True}

    def test_check_requirements_false_still_prints_permissive(self, monkeypatch, tmp_path):
        """When check_requirements returns False, still prints permissive."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO('{"hook_event_name":"beforeSubmitPrompt"}')),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=False),
        ):
            main()

        result = json.loads(stdout_buf.getvalue())
        # event is "" because we return before reading stdin
        assert result == {"continue": True}

    def test_empty_stdin(self, monkeypatch, tmp_path):
        """Empty stdin produces empty dict, still prints permissive."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO("")),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
            mock.patch("cursor_tracing.hooks.handlers._dispatch") as dispatch_mock,
        ):
            main()

        dispatch_mock.assert_called_once_with("", {})
        result = json.loads(stdout_buf.getvalue())
        assert result == {"continue": True}

    def test_stderr_redirected_to_log_file(self, monkeypatch, tmp_path):
        """main() redirects stderr to env.log_file."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        log_file = tmp_path / "hook.log"
        monkeypatch.setenv("ARIZE_LOG_FILE", str(log_file))

        stdout_buf = io.StringIO()
        original_stderr = sys.stderr

        with (
            mock.patch("sys.stdin", io.StringIO('{"hook_event_name":"stop"}')),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
            mock.patch("cursor_tracing.hooks.handlers._dispatch"),
        ):
            main()

        # Restore stderr for safety
        sys.stderr = original_stderr


# ---------------------------------------------------------------------------
# _event_name tests
# ---------------------------------------------------------------------------


class TestEventName:

    def test_supports_hook_event_name(self):
        assert _event_name({"hook_event_name": "stop"}) == "stop"

    def test_supports_hookEventName(self):
        assert _event_name({"hookEventName": "sessionStart"}) == "sessionStart"

    def test_supports_event_name(self):
        assert _event_name({"event_name": "postToolUse"}) == "postToolUse"

    def test_supports_eventName(self):
        assert _event_name({"eventName": "afterFileEdit"}) == "afterFileEdit"

    def test_supports_event(self):
        assert _event_name({"event": "beforeSubmitPrompt"}) == "beforeSubmitPrompt"

    def test_prefers_hook_event_name_over_hookEventName(self):
        assert _event_name({"hook_event_name": "stop", "hookEventName": "sessionStart"}) == "stop"

    def test_returns_empty_for_missing(self):
        assert _event_name({}) == ""


# ---------------------------------------------------------------------------
# _trace_id_from_event tests
# ---------------------------------------------------------------------------


class TestTraceIdFromEvent:

    def test_prefers_gen_id(self):
        result = _trace_id_from_event("gen-1", "conv-1")
        assert result  # non-empty
        from cursor_tracing.hooks.adapter import trace_id_from_generation

        assert result == trace_id_from_generation("gen-1")

    def test_falls_back_to_conversation_id(self):
        result = _trace_id_from_event("", "conv-1")
        assert result
        from cursor_tracing.hooks.adapter import trace_id_from_generation

        assert result == trace_id_from_generation("conv-1")

    def test_returns_empty_when_both_empty(self):
        assert _trace_id_from_event("", "") == ""


# ---------------------------------------------------------------------------
# _dispatch routes sessionStart / postToolUse
# ---------------------------------------------------------------------------


class TestDispatchNewEvents:

    def test_dispatch_routes_session_start(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers._handle_session_start") as h,
        ):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            h.assert_called_once()

    def test_dispatch_routes_post_tool_use(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("cursor_tracing.hooks.handlers._handle_post_tool_use") as h,
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            h.assert_called_once()


# ---------------------------------------------------------------------------
# main() dispatches camelCase event key
# ---------------------------------------------------------------------------


class TestMainCamelCase:

    def test_main_dispatches_camel_case_event_key(self, monkeypatch, tmp_path):
        """main() resolves hookEventName from CLI payloads and dispatches correctly."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        input_data = {
            "hookEventName": "sessionStart",
            "conversation_id": "c1",
            "generation_id": "g1",
            "cwd": "/tmp",
        }
        stdout_buf = io.StringIO()

        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(input_data))),
            mock.patch.object(sys, "__stdout__", stdout_buf),
            mock.patch("cursor_tracing.hooks.handlers.check_requirements", return_value=True),
            mock.patch("cursor_tracing.hooks.handlers._dispatch") as dispatch_mock,
        ):
            main()

        dispatch_mock.assert_called_once_with("sessionStart", input_data)


# ---------------------------------------------------------------------------
# _handle_session_start tests
# ---------------------------------------------------------------------------


class TestHandleSessionStart:

    def test_session_start_sends_chain_span(self, captured_spans, monkeypatch):
        """sessionStart produces a CHAIN span with session.id and cwd."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="ss11" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_save") as save_mock,
        ):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "conv-sess",
                    "generation_id": "gen-sess",
                    "cwd": "/Users/alice/code/myrepo",
                    "user_email": "alice@example.com",
                },
            )

        save_mock.assert_called_once_with("gen-sess", "ss11" * 4)
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span["name"] == "Session Start"
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["session.id"]["stringValue"] == "conv-sess"
        assert attrs["cursor.session.cwd"]["stringValue"] == "/Users/alice/code/myrepo"
        assert attrs["user.id"]["stringValue"] == "alice@example.com"

    def test_session_start_no_gen_id_skips_save(self, captured_spans, monkeypatch):
        """Without gen_id, gen_root_span_save is not called."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_save") as save_mock,
        ):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "conv-sess",
                    "cwd": "/tmp",
                },
            )

        save_mock.assert_not_called()
        assert len(captured_spans) == 1

    def test_session_start_optional_fields_omitted(self, captured_spans, monkeypatch):
        """Optional fields like cwd and user_email are omitted when absent."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=5000),):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "conv-sess",
                },
            )

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "cursor.session.cwd" not in attr_keys
        assert "user.id" not in attr_keys


# ---------------------------------------------------------------------------
# _handle_post_tool_use tests
# ---------------------------------------------------------------------------


class TestHandlePostToolUse:

    def test_post_tool_use_sends_tool_span(self, captured_spans, monkeypatch):
        """postToolUse produces a TOOL span with tool.name, input.value, output.value."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("cursor_tracing.hooks.handlers.span_id_16", return_value="pt11" * 4),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value="parent-pt"),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "conv-pt",
                    "generation_id": "gen-pt",
                    "toolName": "read_file",
                    "toolInput": '{"path": "src/main.py"}',
                    "result": "<file contents elided>",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span["name"] == "Tool: read_file"
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "read_file"
        assert attrs["input.value"]["stringValue"] == '{"path": "src/main.py"}'
        assert attrs["output.value"]["stringValue"] == "<file contents elided>"
        assert attrs["session.id"]["stringValue"] == "conv-pt"
        assert span["parentSpanId"] == "parent-pt"

    def test_post_tool_use_shell_command_uses_command_as_input(self, captured_spans, monkeypatch):
        """Shell-like postToolUse uses 'command' field as input.value."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "toolName": "shell",
                    "command": "ls -la",
                    "stdout": "total 40\ndrwxr-xr-x ...",
                    "exit_code": 0,
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["input.value"]["stringValue"] == "ls -la"
        assert attrs["output.value"]["stringValue"] == "total 40\ndrwxr-xr-x ..."

    def test_post_tool_use_bash_tool_uses_command(self, captured_spans, monkeypatch):
        """Other shell-like tool names (bash, terminal, run_command) also use command."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        for tool in ("bash", "terminal", "run_command"):
            captured_spans.clear()
            with (
                mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
                mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
            ):
                _dispatch(
                    "postToolUse",
                    {
                        "conversation_id": "c1",
                        "generation_id": "g1",
                        "toolName": tool,
                        "command": "echo hi",
                    },
                )

            attrs = {
                a["key"]: a["value"]
                for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
            }
            assert attrs["input.value"]["stringValue"] == "echo hi", f"Failed for tool={tool}"

    def test_post_tool_use_missing_fields_omitted(self, captured_spans, monkeypatch):
        """Missing optional fields are omitted from attributes."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("cursor_tracing.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("cursor_tracing.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "tool.name" not in attr_keys
        assert "input.value" not in attr_keys
        assert "output.value" not in attr_keys
