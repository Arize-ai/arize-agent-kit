#!/usr/bin/env python3
"""Tests for core.hooks.cursor.handlers — the Cursor hook dispatcher and 12 event handlers."""

import io
import json
import sys
from unittest import mock

import pytest

from core.hooks.cursor import adapter
from core.hooks.cursor.handlers import (
    _dispatch,
    _jq_str,
    _print_permissive,
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
    with mock.patch("core.hooks.cursor.handlers.send_span", side_effect=lambda s: sent.append(s)):
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
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers._handle_before_submit_prompt") as h:
            _dispatch("beforeSubmitPrompt", {
                "conversation_id": "c1",
                "generation_id": "g1",
            })
            h.assert_called_once()

    def test_routes_after_agent_response(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers._handle_after_agent_response") as h:
            _dispatch("afterAgentResponse", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_routes_stop(self, monkeypatch):
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers._handle_stop") as h:
            _dispatch("stop", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_called_once()

    def test_unknown_event_logs_warning(self, monkeypatch):
        """Unknown event logs warning, no crash."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.log") as log_mock:
            _dispatch("unknownEvent", {"conversation_id": "c1", "generation_id": "g1"})
            log_mock.assert_called_once()
            assert "Unknown" in log_mock.call_args[0][0]

    def test_tracing_disabled_returns_early(self, monkeypatch):
        """Tracing disabled -> returns without dispatching."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        with mock.patch("core.hooks.cursor.handlers._handle_before_submit_prompt") as h:
            _dispatch("beforeSubmitPrompt", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_not_called()

    def test_no_backend_no_collector_returns_early(self, monkeypatch):
        """No backend + collector unreachable -> returns early."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_DIRECT_SEND", "false")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="none"), \
             mock.patch("core.hooks.cursor.handlers.urllib.request.urlopen", side_effect=Exception("unreachable")), \
             mock.patch("core.hooks.cursor.handlers._handle_before_submit_prompt") as h:
            _dispatch("beforeSubmitPrompt", {"conversation_id": "c1", "generation_id": "g1"})
            h.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_before_submit_prompt tests
# ---------------------------------------------------------------------------

class TestHandleBeforeSubmitPrompt:

    def test_creates_chain_root_span(self, captured_spans, monkeypatch):
        """Creates CHAIN span with prompt and session.id, calls gen_root_span_save."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=5000), \
             mock.patch("core.hooks.cursor.handlers.span_id_16", return_value="aabb" * 4), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_save") as save_mock:
            _dispatch("beforeSubmitPrompt", {
                "conversation_id": "conv-1",
                "generation_id": "gen-1",
                "prompt": "fix the bug",
                "model_name": "claude-4",
            })

        save_mock.assert_called_once_with("gen-1", "aabb" * 4)
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["input.value"]["stringValue"] == "fix the bug"
        assert attrs["session.id"]["stringValue"] == "conv-1"
        assert attrs["llm.model_name"]["stringValue"] == "claude-4"
        assert span["name"] == "User Prompt"

    def test_uses_fixture(self, captured_spans, monkeypatch, load_fixture):
        """Works with cursor_before_submit.json fixture."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        fixture = load_fixture("cursor_before_submit.json")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_save"):
            _dispatch(fixture["hook_event_name"], fixture)

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["input.value"]["stringValue"] == "fix the bug"

    def test_no_model_omits_attr(self, captured_spans, monkeypatch):
        """When model is empty, llm.model_name is not set."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_save"):
            _dispatch("beforeSubmitPrompt", {
                "conversation_id": "c1",
                "generation_id": "g1",
                "prompt": "test",
            })

        attrs = {a["key"]: a["value"] for a in
                 captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "llm.model_name" not in attrs


# ---------------------------------------------------------------------------
# _handle_after_agent_response tests
# ---------------------------------------------------------------------------

class TestHandleAfterAgentResponse:

    def test_creates_llm_span_with_response(self, captured_spans, monkeypatch):
        """Creates LLM span with response and gets parent from gen_root_span_get."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=2000), \
             mock.patch("core.hooks.cursor.handlers.span_id_16", return_value="ccdd" * 4), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value="parent123") as get_mock:
            _dispatch("afterAgentResponse", {
                "conversation_id": "conv-1",
                "generation_id": "gen-1",
                "response": "I found the issue",
                "model_name": "claude-4",
            })

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
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=2000), \
             mock.patch("core.hooks.cursor.handlers.span_id_16", return_value="eeff" * 4), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value="parent1"), \
             mock.patch("core.hooks.cursor.handlers.state_pop", return_value=popped):
            _dispatch("afterShellExecution", {
                "conversation_id": "conv-1",
                "generation_id": "gen-1",
                "output": "total 0",
                "exit_code": "0",
            })

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
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=2000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value=""), \
             mock.patch("core.hooks.cursor.handlers.state_pop", return_value=popped):
            _dispatch("afterShellExecution", {
                "conversation_id": "c1",
                "generation_id": "g1",
                "command": "new_cmd",
                "output": "ok",
            })

        attrs = {a["key"]: a["value"] for a in
                 captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert attrs["input.value"]["stringValue"] == "new_cmd"

    def test_no_popped_state_uses_now(self, captured_spans, monkeypatch):
        """Without popped state, start_ms defaults to now_ms."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=3000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value=""), \
             mock.patch("core.hooks.cursor.handlers.state_pop", return_value=None):
            _dispatch("afterShellExecution", {
                "conversation_id": "c1",
                "generation_id": "g1",
                "output": "ok",
            })

        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        # start_ms = "3000" -> ns = "3000000000"
        assert span["startTimeUnixNano"] == "3000000000"

    def test_uses_fixture(self, captured_spans, monkeypatch, load_fixture):
        """Works with cursor_after_shell.json fixture."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        fixture = load_fixture("cursor_after_shell.json")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value=""), \
             mock.patch("core.hooks.cursor.handlers.state_pop", return_value=None):
            _dispatch(fixture["hook_event_name"], fixture)

        attrs = {a["key"]: a["value"] for a in
                 captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
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
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=5000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value="root1"), \
             mock.patch("core.hooks.cursor.handlers.state_cleanup_generation") as cleanup:
            _dispatch("stop", {
                "conversation_id": "conv-1",
                "generation_id": "gen-1",
                "status": "completed",
                "loop_count": "3",
            })

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
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value=""), \
             mock.patch("core.hooks.cursor.handlers.state_cleanup_generation") as cleanup:
            _dispatch("stop", {"conversation_id": "c1"})

        cleanup.assert_not_called()
        assert len(captured_spans) == 1

    def test_optional_attrs_omitted(self, captured_spans, monkeypatch):
        """Status and loop_count omitted when empty."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.gen_root_span_get", return_value=""), \
             mock.patch("core.hooks.cursor.handlers.state_cleanup_generation"):
            _dispatch("stop", {"conversation_id": "c1", "generation_id": "g1"})

        attr_keys = {a["key"] for a in
                     captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert "cursor.stop.status" not in attr_keys
        assert "cursor.stop.loop_count" not in attr_keys


# ---------------------------------------------------------------------------
# _handle_before_shell_execution tests
# ---------------------------------------------------------------------------

class TestHandleBeforeShellExecution:

    def test_pushes_state(self, monkeypatch):
        """Pushes command, cwd, start_ms, trace_id, conversation_id to state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.state_push") as push_mock:
            _dispatch("beforeShellExecution", {
                "conversation_id": "c1",
                "generation_id": "gen-1",
                "command": "ls -la",
                "cwd": "/home",
            })

        push_mock.assert_called_once()
        key, value = push_mock.call_args[0]
        assert "gen-1" in key or "gen_1" in key
        assert value["command"] == "ls -la"
        assert value["cwd"] == "/home"
        assert value["start_ms"] == "1000"

    def test_no_gen_id_returns_early(self, monkeypatch):
        """Without gen_id, returns without pushing state."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.cursor.handlers.get_target", return_value="phoenix"), \
             mock.patch("core.hooks.cursor.handlers.get_timestamp_ms", return_value=1000), \
             mock.patch("core.hooks.cursor.handlers.state_push") as push_mock:
            _dispatch("beforeShellExecution", {
                "conversation_id": "c1",
                "command": "ls",
            })

        push_mock.assert_not_called()


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

        with mock.patch("sys.stdin", io.StringIO(json.dumps(input_data))), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.cursor.handlers._dispatch") as dispatch_mock:
            main()

        dispatch_mock.assert_called_once_with("beforeSubmitPrompt", input_data)
        result = json.loads(stdout_buf.getvalue())
        assert result == {"permission": "allow"}

    def test_invalid_json_still_prints_permissive(self, monkeypatch, tmp_path):
        """Invalid JSON on stdin still prints permissive response."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with mock.patch("sys.stdin", io.StringIO("not valid json")), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=True):
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

        with mock.patch("sys.stdin", io.StringIO(json.dumps(input_data))), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.cursor.handlers._dispatch", side_effect=RuntimeError("boom")):
            main()

        result = json.loads(stdout_buf.getvalue())
        assert result == {"continue": True}

    def test_check_requirements_false_still_prints_permissive(self, monkeypatch, tmp_path):
        """When check_requirements returns False, still prints permissive."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "false")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with mock.patch("sys.stdin", io.StringIO('{"hook_event_name":"beforeSubmitPrompt"}')), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=False):
            main()

        result = json.loads(stdout_buf.getvalue())
        # event is "" because we return before reading stdin
        assert result == {"continue": True}

    def test_empty_stdin(self, monkeypatch, tmp_path):
        """Empty stdin produces empty dict, still prints permissive."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        monkeypatch.setenv("ARIZE_LOG_FILE", str(tmp_path / "hook.log"))

        stdout_buf = io.StringIO()

        with mock.patch("sys.stdin", io.StringIO("")), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.cursor.handlers._dispatch") as dispatch_mock:
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

        with mock.patch("sys.stdin", io.StringIO('{"hook_event_name":"stop"}')), \
             mock.patch.object(sys, "__stdout__", stdout_buf), \
             mock.patch("core.hooks.cursor.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.cursor.handlers._dispatch"):
            main()

        # Restore stderr for safety
        sys.stderr = original_stderr
