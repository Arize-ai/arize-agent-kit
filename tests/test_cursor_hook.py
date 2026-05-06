#!/usr/bin/env python3
"""Tests for tracing.cursor.hooks.handlers — the Cursor hook dispatcher and 15 event handlers."""

import io
import json
import sys
from unittest import mock

import pytest

from tracing.cursor.hooks import adapter
from tracing.cursor.hooks.handlers import (
    _dispatch,
    _event_name,
    _is_cursor_ide_hook_payload,
    _jq_str,
    _print_permissive,
    _trace_id_from_event,
    main,
)

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
    with mock.patch("tracing.cursor.hooks.handlers.send_span", side_effect=lambda s: sent.append(s)):
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


class TestIdeCliPayloadDetection:

    def test_hook_event_name_implies_ide(self):
        assert _is_cursor_ide_hook_payload({"hook_event_name": "beforeSubmitPrompt"}) is True

    def test_hook_event_name_empty_defaults_ide_unless_cli_present(self):
        assert _is_cursor_ide_hook_payload({"hook_event_name": ""}) is True
        assert _is_cursor_ide_hook_payload({"hook_event_name": "", "hookEventName": "x"}) is False

    def test_hook_event_name_only_cli_key(self):
        assert _is_cursor_ide_hook_payload({"hookEventName": "beforeSubmitPrompt"}) is False

    def test_neither_key_defaults_ide(self):
        assert _is_cursor_ide_hook_payload({"conversation_id": "c"}) is True


# ---------------------------------------------------------------------------
# _dispatch tests
# ---------------------------------------------------------------------------


class TestDispatch:

    def test_routes_to_correct_handler(self, monkeypatch):
        """Known event routes to correct handler function."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_before_submit_prompt") as h,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_after_agent_response") as h,
        ):
            _dispatch("afterAgentResponse", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_routes_stop(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_stop") as h,
        ):
            _dispatch("stop", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_unknown_event_logs_warning(self, monkeypatch):
        """Unknown event logs warning, no crash."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.log") as log_mock,
        ):
            _dispatch("unknownEvent", {"conversation_id": "c1", "generation_id": "g1"})
            log_mock.assert_called_once()
            assert "Unknown" in log_mock.call_args[0][0]

    def test_tracing_disabled_returns_early(self, monkeypatch):
        """Tracing disabled -> returns without dispatching."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        with mock.patch("tracing.cursor.hooks.handlers._handle_before_submit_prompt") as h:
            _dispatch("beforeSubmitPrompt", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_not_called()

    def test_no_backend_send_fails_gracefully(self, monkeypatch):
        """send_span failure doesn't crash — IDE defers root to afterAgentResponse (hook_event_name)."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.send_span", return_value=False) as send_mock,
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "hook_event_name": "beforeSubmitPrompt",
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            assert send_mock.call_count == 0
            _dispatch(
                "afterAgentResponse",
                {
                    "hook_event_name": "afterAgentResponse",
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "response": "done",
                },
            )
            assert send_mock.call_count == 2


# ---------------------------------------------------------------------------
# _handle_before_submit_prompt tests
# ---------------------------------------------------------------------------


class TestHandleBeforeSubmitPrompt:

    def test_cli_payload_sends_root_before_submit(self, captured_spans, monkeypatch):
        """CLI-style payload (hookEventName only): root CHAIN at submit; LLM at afterAgentResponse."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="aabb" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_save") as save_mock,
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "hookEventName": "beforeSubmitPrompt",
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "prompt": "fix the bug",
                    "model_name": "claude-4",
                },
            )

        save_mock.assert_called_once_with("gen-1", "aabb" * 4)
        assert len(captured_spans) == 1
        root0 = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert root0["name"] == "User Prompt"
        root_attrs0 = {a["key"]: a["value"] for a in root0["attributes"]}
        assert root_attrs0["input.value"]["stringValue"] == "fix the bug"
        assert "output.value" not in root_attrs0

        with mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=9000):
            _dispatch(
                "afterAgentResponse",
                {
                    "hookEventName": "afterAgentResponse",
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "response": "I fixed the bug",
                    "model_name": "claude-4",
                },
            )

        names = [s["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] for s in captured_spans]
        assert names == ["User Prompt", "Agent Response"]
        llm = captured_spans[1]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        llm_attrs = {a["key"]: a["value"] for a in llm["attributes"]}
        assert llm_attrs["openinference.span.kind"]["stringValue"] == "LLM"
        assert llm_attrs["input.value"]["stringValue"] == "fix the bug"
        assert llm_attrs["output.value"]["stringValue"] == "I fixed the bug"
        assert llm_attrs["session.id"]["stringValue"] == "conv-1"

    def test_ide_payload_defers_root_chain_to_after_response(self, captured_spans, monkeypatch):
        """IDE payload (hook_event_name): original deferred CHAIN with full duration and output on root."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="aabb" * 4),
        ):
            _dispatch(
                "beforeSubmitPrompt",
                {
                    "hook_event_name": "beforeSubmitPrompt",
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "prompt": "fix the bug",
                    "model_name": "claude-4",
                },
            )

        assert len(captured_spans) == 0

        with mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=9000):
            _dispatch(
                "afterAgentResponse",
                {
                    "hook_event_name": "afterAgentResponse",
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "response": "I fixed the bug",
                    "model_name": "claude-4",
                },
            )

        names = [s["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] for s in captured_spans]
        assert names == ["User Prompt", "Agent Response"]
        root = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        root_attrs = {a["key"]: a["value"] for a in root["attributes"]}
        assert root_attrs["input.value"]["stringValue"] == "fix the bug"
        assert root_attrs["output.value"]["stringValue"] == "I fixed the bug"
        assert root["startTimeUnixNano"].startswith("5000")
        assert root["endTimeUnixNano"].startswith("9000")


# ---------------------------------------------------------------------------
# _handle_after_agent_response tests
# ---------------------------------------------------------------------------


class TestHandleAfterAgentResponse:

    def test_creates_llm_span_with_response(self, captured_spans, monkeypatch):
        """Creates LLM span with response and gets parent from gen_root_span_get."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="ccdd" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent123") as get_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="eeff" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=popped),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=popped),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=None),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=None),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="root1"),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation") as cleanup,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation") as cleanup,
        ):
            _dispatch("stop", {"conversation_id": "c1"})

        cleanup.assert_not_called()
        assert len(captured_spans) == 1

    def test_optional_attrs_omitted(self, captured_spans, monkeypatch):
        """Status and loop_count omitted when empty."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.state_push") as push_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.state_push") as push_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="abcd" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1") as get_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1500),
            mock.patch("tracing.cursor.hooks.handlers.state_push") as push_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.state_push") as push_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="ffaa" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=popped),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="bbcc" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=None),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="1122" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="3344" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="3344" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="5566" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="7788" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent1"),
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="7788" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.cursor.hooks.handlers._dispatch") as dispatch_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.cursor.hooks.handlers._dispatch", side_effect=RuntimeError("boom")),
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=False),
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.cursor.hooks.handlers._dispatch") as dispatch_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.cursor.hooks.handlers._dispatch"),
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
        from tracing.cursor.hooks.adapter import trace_id_from_generation

        assert result == trace_id_from_generation("gen-1")

    def test_falls_back_to_conversation_id(self):
        result = _trace_id_from_event("", "conv-1")
        assert result
        from tracing.cursor.hooks.adapter import trace_id_from_generation

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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_session_start") as h,
        ):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            h.assert_called_once()

    def test_dispatch_routes_session_end(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_session_end") as h,
        ):
            _dispatch(
                "sessionEnd",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                },
            )
            h.assert_called_once()

    def test_dispatch_routes_post_tool_use(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers._handle_post_tool_use") as h,
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
            mock.patch("tracing.cursor.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.cursor.hooks.handlers._dispatch") as dispatch_mock,
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
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="ss11" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_save") as save_mock,
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

    def test_session_start_no_gen_id_skips_save(self, captured_spans, monkeypatch):
        """Without gen_id, gen_root_span_save is not called."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_save") as save_mock,
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
        with (mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),):
            _dispatch(
                "sessionStart",
                {
                    "conversation_id": "conv-sess",
                },
            )

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "cursor.session.cwd" not in attr_keys


# ---------------------------------------------------------------------------
# _handle_post_tool_use tests
# ---------------------------------------------------------------------------


class TestHandlePostToolUse:

    def test_post_tool_use_sends_tool_span(self, captured_spans, monkeypatch):
        """postToolUse produces a TOOL span with tool.name, input.value, output.value."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.span_id_16", return_value="pt11" * 4),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="parent-pt"),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "conv-pt",
                    "generation_id": "gen-pt",
                    "toolName": "code_search",
                    "toolInput": '{"query": "main function"}',
                    "result": "<search results>",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span["name"] == "Tool: code_search"
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "code_search"
        assert attrs["input.value"]["stringValue"] == '{"query": "main function"}'
        assert attrs["output.value"]["stringValue"] == "<search results>"
        assert attrs["session.id"]["stringValue"] == "conv-pt"
        assert span["parentSpanId"] == "parent-pt"

    def test_post_tool_use_unknown_tool_uses_command_field_when_present(self, captured_spans, monkeypatch):
        """Non-deduped shell-like tool uses 'command' field as input.value fallback."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "toolName": "custom_runner",
                    "command": "ls -la",
                    "stdout": "total 40\ndrwxr-xr-x ...",
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        # custom_runner is not in _SHELL_TOOL_NAMES so command field is NOT used as input
        # tool_input comes from the standard extraction keys
        assert attrs["output.value"]["stringValue"] == "total 40\ndrwxr-xr-x ..."

    def test_post_tool_use_missing_fields_omitted(self, captured_spans, monkeypatch):
        """Missing optional fields are omitted from attributes."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
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

    def test_post_tool_use_skips_shell_tool(self, captured_spans, monkeypatch):
        """postToolUse with tool_name='shell' is skipped (covered by dedicated handler)."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "toolName": "shell",
                    "command": "ls -la",
                },
            )

        assert len(captured_spans) == 0

    @pytest.mark.parametrize(
        "tool_name",
        ["shell", "Shell", "TERMINAL", "bash", "read_file", "edit_file", "tab_file_read", "mcp"],
    )
    def test_post_tool_use_skips_each_dedicated_tool_name(self, captured_spans, monkeypatch, tool_name):
        """postToolUse short-circuits for each known dedicated tool name (case-insensitive)."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "toolName": tool_name,
                },
            )

        assert len(captured_spans) == 0, f"Expected no span for tool_name={tool_name!r}"

    def test_post_tool_use_emits_for_unknown_tool_name(self, captured_spans, monkeypatch):
        """postToolUse emits a span for tools not in the dedup set."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=3000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
        ):
            _dispatch(
                "postToolUse",
                {
                    "conversation_id": "c1",
                    "generation_id": "g1",
                    "toolName": "glob",
                    "toolInput": '{"pattern": "*.py"}',
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span["name"] == "Tool: glob"
        assert attrs["tool.name"]["stringValue"] == "glob"
        assert attrs["input.value"]["stringValue"] == '{"pattern": "*.py"}'


# ---------------------------------------------------------------------------
# _handle_stop token count tests
# ---------------------------------------------------------------------------


class TestHandleStopTokenCounts:

    def test_stop_captures_token_counts(self, captured_spans, monkeypatch):
        """Stop payload with token fields produces llm.token_count.* attributes."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="root1"),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "stop",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "status": "completed",
                    "input_tokens": 85919,
                    "output_tokens": 1523,
                    "cache_read_tokens": 68000,
                    "cache_write_tokens": 0,
                    "model": "claude-sonnet-4.5",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["llm.token_count.prompt"]["intValue"] == 85919
        assert attrs["llm.token_count.completion"]["intValue"] == 1523
        assert attrs["llm.token_count.cache_read"]["intValue"] == 68000
        assert attrs["llm.token_count.cache_write"]["intValue"] == 0
        assert attrs["llm.token_count.total"]["intValue"] == 87442
        assert attrs["llm.model_name"]["stringValue"] == "claude-sonnet-4.5"

    def test_stop_omits_token_attrs_when_payload_has_none(self, captured_spans, monkeypatch):
        """Stop payload without token fields produces no llm.token_count.* attributes."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "stop",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "status": "completed",
                },
            )

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "llm.token_count.prompt" not in attr_keys
        assert "llm.token_count.completion" not in attr_keys
        assert "llm.token_count.cache_read" not in attr_keys
        assert "llm.token_count.cache_write" not in attr_keys
        assert "llm.token_count.total" not in attr_keys
        assert "llm.model_name" not in attr_keys

    def test_stop_token_count_handles_string_and_dash_values(self, captured_spans, monkeypatch):
        """String token values are coerced; '--' and None are omitted."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=5000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "stop",
                {
                    "conversation_id": "conv-1",
                    "generation_id": "gen-1",
                    "input_tokens": "100",
                    "output_tokens": "--",
                    "cache_read_tokens": None,
                },
            )

        attrs = {
            a["key"]: a["value"]
            for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        assert attrs["llm.token_count.prompt"]["intValue"] == 100
        assert "llm.token_count.completion" not in attrs
        assert "llm.token_count.cache_read" not in attrs
        assert "llm.token_count.total" not in attrs


# ---------------------------------------------------------------------------
# _handle_session_end tests
# ---------------------------------------------------------------------------


class TestHandleSessionEnd:

    def test_session_end_emits_chain_span_with_duration_and_status(self, captured_spans, monkeypatch):
        """sessionEnd produces a CHAIN span with duration, status, and reason."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=9000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="root-se"),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "sessionEnd",
                {
                    "conversation_id": "conv-end",
                    "generation_id": "gen-end",
                    "duration_ms": 7447445,
                    "final_status": "completed",
                    "reason": "window_close",
                },
            )

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert span["name"] == "Session End"
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["cursor.session.duration_ms"]["intValue"] == 7447445
        assert attrs["cursor.session.final_status"]["stringValue"] == "completed"
        assert attrs["cursor.session.reason"]["stringValue"] == "window_close"
        assert attrs["session.id"]["stringValue"] == "conv-end"
        assert span["parentSpanId"] == "root-se"

    def test_session_end_cleans_up_generation(self, captured_spans, monkeypatch):
        """sessionEnd calls state_cleanup_generation with the gen_id."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=9000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation") as cleanup,
        ):
            _dispatch(
                "sessionEnd",
                {
                    "conversation_id": "conv-end",
                    "generation_id": "g-123",
                },
            )

        cleanup.assert_called_once_with("g-123")

    def test_session_end_handles_empty_payload(self, captured_spans, monkeypatch):
        """sessionEnd with only conversation_id emits a span without optional attrs."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=9000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "sessionEnd",
                {
                    "conversation_id": "conv-end",
                },
            )

        assert len(captured_spans) == 1
        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "session.id" in attr_keys
        assert "cursor.conversation.id" in attr_keys
        assert "cursor.session.duration_ms" not in attr_keys
        assert "cursor.session.final_status" not in attr_keys
        assert "cursor.session.reason" not in attr_keys
        assert "llm.token_count.prompt" not in attr_keys


# ---------------------------------------------------------------------------
# cursor.conversation.id attribute tests
# ---------------------------------------------------------------------------


class TestConversationIdAttribute:

    # Minimal payloads per event that produce at least one span
    _EVENT_PAYLOADS = {
        "beforeSubmitPrompt": {
            "hookEventName": "beforeSubmitPrompt",  # CLI path — sends span immediately
            "conversation_id": "conv-abc",
            "generation_id": "gen-abc",
            "prompt": "test",
        },
        "afterAgentResponse": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-aar",
            "text": "response",
        },
        "afterAgentThought": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-aat",
            "thought": "thinking",
        },
        "afterShellExecution": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-ase",
            "command": "ls",
            "output": "ok",
        },
        "afterMCPExecution": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-ame",
            "tool_name": "my_tool",
            "result": "ok",
        },
        "beforeReadFile": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-brf",
            "file_path": "/tmp/a.py",
        },
        "afterFileEdit": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-afe",
            "file_path": "/tmp/a.py",
        },
        "beforeTabFileRead": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-btfr",
            "file_path": "/tmp/a.py",
        },
        "afterTabFileEdit": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-atfe",
            "file_path": "/tmp/a.py",
        },
        "stop": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-stop",
            "status": "completed",
        },
        "sessionStart": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-ss",
            "cwd": "/tmp",
        },
        "sessionEnd": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-se",
        },
        "postToolUse": {
            "conversation_id": "conv-abc",
            "generation_id": "gen-ptu",
            "toolName": "glob",
            "toolInput": "*.py",
        },
    }

    # Events that push state but don't emit a span
    _NO_SPAN_EVENTS = {"beforeShellExecution", "beforeMCPExecution"}

    @pytest.mark.parametrize(
        "event",
        [e for e in _EVENT_PAYLOADS],
    )
    def test_conversation_id_attribute_on_every_handler(self, captured_spans, monkeypatch, event):
        """Every span-producing handler includes cursor.conversation.id."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_save"),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
            mock.patch("tracing.cursor.hooks.handlers.state_pop", return_value=None),
        ):
            _dispatch(event, self._EVENT_PAYLOADS[event])

        assert len(captured_spans) >= 1, f"No spans emitted for {event}"
        for sent in captured_spans:
            span = sent["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            attrs = {a["key"]: a["value"] for a in span["attributes"]}
            assert (
                attrs.get("cursor.conversation.id", {}).get("stringValue") == "conv-abc"
            ), f"cursor.conversation.id missing or wrong on {event} span {span['name']}"

    def test_conversation_id_attribute_omitted_when_missing(self, captured_spans, monkeypatch):
        """When conversation_id is empty, cursor.conversation.id is not set."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value=""),
            mock.patch("tracing.cursor.hooks.handlers.state_cleanup_generation"),
        ):
            _dispatch(
                "stop",
                {
                    "generation_id": "gen-1",
                    "status": "completed",
                },
            )

        attr_keys = {a["key"] for a in captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "cursor.conversation.id" not in attr_keys


# ---------------------------------------------------------------------------
# IDE-safety regression test
# ---------------------------------------------------------------------------


class TestIdeSafety:

    def test_ide_payload_with_no_post_tool_use_unaffected(self, captured_spans, monkeypatch):
        """IDE dispatches before/afterShellExecution without postToolUse — exactly 1 span from after."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=1000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="root-ide"),
        ):
            _dispatch(
                "beforeShellExecution",
                {
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": "conv-ide",
                    "generation_id": "gen-ide",
                    "command": "echo hello",
                    "cwd": "/tmp",
                },
            )

        # beforeShellExecution emits no span
        assert len(captured_spans) == 0

        with (
            mock.patch("tracing.cursor.hooks.handlers.get_timestamp_ms", return_value=2000),
            mock.patch("tracing.cursor.hooks.handlers.gen_root_span_get", return_value="root-ide"),
        ):
            _dispatch(
                "afterShellExecution",
                {
                    "hook_event_name": "afterShellExecution",
                    "conversation_id": "conv-ide",
                    "generation_id": "gen-ide",
                    "command": "echo hello",
                    "output": "hello",
                    "exit_code": "0",
                },
            )

        # afterShellExecution emits exactly one span
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["name"] == "Shell"
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "shell"
