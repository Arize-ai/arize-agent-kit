#!/usr/bin/env python3
"""Tests for tracing.copilot.hooks.handlers — Copilot hook handlers.

Tests cover response printing, session/prompt/tool/stop handlers,
deferred turn helpers, and all CLI entry points.
"""

import io
import json
import sys
from unittest import mock

import pytest

from core.common import StateManager
from tracing.copilot.hooks.handlers import (
    _clear_pending_turn,
    _flush_pending_turn,
    _handle_error_occurred,
    _handle_post_tool_use,
    _handle_pre_tool_use,
    _handle_session_end,
    _handle_session_start,
    _handle_stop,
    _handle_subagent_stop,
    _handle_user_prompt_submitted,
    _print_response,
    _read_stdin,
    _save_pending_turn,
    error_occurred,
    post_tool_use,
    pre_tool_use,
    session_end,
    session_start,
    stop,
    subagent_stop,
    user_prompt_submitted,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vscode_base(extra=None):
    """Return a base VS Code mode payload with sessionId and hookEventName."""
    d = {"sessionId": "sess-vscode-1", "hookEventName": "TestEvent", "cwd": "/tmp/project"}
    if extra:
        d.update(extra)
    return d


def _cli_base(extra=None):
    """Return a base CLI mode payload (no sessionId, no hookEventName)."""
    d = {"cwd": "/tmp/project"}
    if extra:
        d.update(extra)
    return d


def _get_span_attrs(span_payload):
    """Extract attributes dict from OTLP span payload."""
    span = span_payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    return {a["key"]: a["value"] for a in span["attributes"]}


def _get_span(span_payload):
    """Extract span object from OTLP span payload."""
    return span_payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path):
    """Create a StateManager with a temp state file, pre-initialized."""
    sf = tmp_path / "state_test.yaml"
    lp = tmp_path / ".lock_test"
    sm = StateManager(state_dir=tmp_path, state_file=sf, lock_path=lp)
    sm.init_state()
    sm.set("session_id", "test-session-copilot")
    sm.set("project_name", "test-copilot-project")
    sm.set("trace_count", "0")
    sm.set("tool_count", "0")
    sm.set("user_id", "test-user")
    return sm


@pytest.fixture
def mock_resolve(state):
    """Mock resolve_session to return the test state fixture."""
    with mock.patch("tracing.copilot.hooks.handlers.resolve_session", return_value=state) as m:
        yield m


@pytest.fixture
def mock_ensure():
    """Mock ensure_session_initialized."""
    with mock.patch("tracing.copilot.hooks.handlers.ensure_session_initialized") as m:
        yield m


@pytest.fixture
def captured_spans():
    """Mock send_span and collect all payloads sent."""
    sent = []
    with mock.patch("tracing.copilot.hooks.handlers.send_span", side_effect=lambda s: sent.append(s)):
        yield sent


@pytest.fixture
def transcript_file(tmp_path):
    """Write a sample transcript to a temp file and return its path."""
    lines = [
        '{"type": "user", "message": {"role": "user", "content": "fix the bug"}}',
        '{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "I found the issue."}], "model": "gpt-4o", "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5}}}',
    ]
    tf = tmp_path / "transcript.jsonl"
    tf.write_text("\n".join(lines) + "\n")
    return str(tf)


# ---------------------------------------------------------------------------
# _read_stdin tests
# ---------------------------------------------------------------------------


class TestReadStdin:

    def test_empty_stdin(self):
        with mock.patch.object(sys, "stdin", new=io.StringIO("")):
            assert _read_stdin("test") == {}

    def test_malformed_json(self):
        with mock.patch.object(sys, "stdin", new=io.StringIO("not json")):
            assert _read_stdin("test") == {}

    def test_valid_json(self):
        with mock.patch.object(sys, "stdin", new=io.StringIO('{"key": "val"}')):
            assert _read_stdin("test") == {"key": "val"}


# ---------------------------------------------------------------------------
# _print_response tests
# ---------------------------------------------------------------------------


class TestPrintResponse:

    def test_pre_tool_use_emits_permission_decision(self, capsys):

        _print_response({}, "PreToolUse")
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    @pytest.mark.parametrize(
        "event",
        [
            "SessionStart",
            "UserPromptSubmit",
            "PostToolUse",
            "Stop",
            "SubagentStop",
        ],
    )
    def test_non_pre_tool_use_emits_continue(self, event, capsys):

        _print_response({}, event)
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload == {"continue": True}


# ---------------------------------------------------------------------------
# session_start tests
# ---------------------------------------------------------------------------


class TestSessionStart:

    def test_initializes_state_from_snake_case_payload(self, tmp_path, monkeypatch):
        from tracing.copilot.hooks import adapter as _adapter

        monkeypatch.setattr(_adapter, "STATE_DIR", tmp_path)

        payload = {
            "cwd": "/some/repo",
            "hook_event_name": "SessionStart",
            "session_id": "sess-123",
            "initial_prompt": "kick off",
            "source": "new",
            "timestamp": "2026-05-04T00:00:00Z",
        }
        _handle_session_start(payload)

        from tracing.copilot.hooks.adapter import resolve_session

        state = resolve_session(payload)
        assert state.get("session_id") == "sess-123"
        assert state.get("project_name") == "repo"
        assert state.get("trace_count") == "0"


# ---------------------------------------------------------------------------
# user_prompt_submitted tests
# ---------------------------------------------------------------------------


class TestUserPromptSubmitted:

    def test_creates_trace_root(self, tmp_path, monkeypatch):
        from tracing.copilot.hooks import adapter as _adapter

        monkeypatch.setattr(_adapter, "STATE_DIR", tmp_path)

        payload = {
            "cwd": "/some/repo",
            "hook_event_name": "UserPromptSubmit",
            "session_id": "sess-abc",
            "prompt": "what is the capital of France?",
            "timestamp": "2026-05-04T00:00:00Z",
        }
        _handle_user_prompt_submitted(payload)

        from tracing.copilot.hooks.adapter import resolve_session

        state = resolve_session(payload)
        assert state.get("current_trace_id") not in (None, "")
        assert state.get("current_trace_span_id") not in (None, "")
        assert state.get("current_trace_prompt") == "what is the capital of France?"
        assert state.get("trace_count") == "1"
        assert state.get("tool_count") == "0"

    def test_returns_early_without_session_id(self, mock_resolve, mock_ensure, state, captured_spans):
        """Returns early when session_id is None."""
        state.delete("session_id")
        inp = {"cwd": "/tmp/project", "hook_event_name": "UserPromptSubmit", "prompt": "hello"}
        _handle_user_prompt_submitted(inp)
        assert state.get("current_trace_id") is None


# ---------------------------------------------------------------------------
# pre_tool_use tests
# ---------------------------------------------------------------------------


class TestPreToolUse:

    def test_vscode_records_tool_start(self, mock_resolve, state):
        """VS Code mode records tool_{id}_start in state."""
        inp = _vscode_base({"tool_use_id": "tool-42", "tool_name": "Bash", "tool_input": {}})
        _handle_pre_tool_use(inp)
        val = state.get("tool_tool-42_start")
        assert val is not None
        assert int(val) > 0

    def test_cli_records_tool_start_by_name(self, mock_resolve, state):
        """CLI mode uses toolName as the key for start time."""
        inp = _cli_base({"toolName": "Bash", "toolArgs": '{"command": "ls"}'})
        _handle_pre_tool_use(inp)
        val = state.get("tool_Bash_start")
        assert val is not None
        assert int(val) > 0

    def test_missing_tool_id_generates_fallback(self, mock_resolve, state):
        """Missing tool_use_id generates a fallback ID."""
        with mock.patch("tracing.copilot.hooks.handlers.generate_trace_id", return_value="gen-id-123"):
            inp = _vscode_base({})
            _handle_pre_tool_use(inp)
        val = state.get("tool_gen-id-123_start")
        assert val is not None


# ---------------------------------------------------------------------------
# post_tool_use tests
# ---------------------------------------------------------------------------


class TestPostToolUse:

    def test_vscode_builds_tool_span(self, mock_resolve, state, captured_spans):
        """VS Code mode builds a TOOL span with correct attributes."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "Read",
                "tool_use_id": "t1",
                "tool_input": {"file_path": "/foo/bar.py"},
                "tool_response": "file content",
            }
        )
        _handle_post_tool_use(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "Read"
        assert attrs["tool.file_path"]["stringValue"] == "/foo/bar.py"
        assert attrs["output.value"]["stringValue"] == "file content"

    def test_cli_builds_tool_span_with_json_args(self, mock_resolve, state, captured_spans):
        """CLI mode parses toolArgs JSON string and builds TOOL span."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _cli_base(
            {
                "toolName": "Bash",
                "toolArgs": '{"command": "ls -la"}',
                "toolResult": {"resultType": "success", "textResultForLlm": "total 42"},
            }
        )
        _handle_post_tool_use(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "Bash"
        assert attrs["tool.command"]["stringValue"] == "ls -la"
        assert attrs["output.value"]["stringValue"] == "total 42"
        assert attrs["tool.result_type"]["stringValue"] == "success"

    def test_cli_extracts_text_result_for_llm(self, mock_resolve, state, captured_spans):
        """CLI mode extracts textResultForLlm from nested toolResult."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _cli_base(
            {
                "toolName": "Read",
                "toolArgs": '{"file_path": "/foo.py"}',
                "toolResult": {"resultType": "success", "textResultForLlm": "file contents here"},
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["output.value"]["stringValue"] == "file contents here"

    def test_cli_result_type_attribute(self, mock_resolve, state, captured_spans):
        """CLI mode sets tool.result_type from toolResult.resultType."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _cli_base(
            {
                "toolName": "Edit",
                "toolArgs": "{}",
                "toolResult": {"resultType": "failure", "textResultForLlm": "error"},
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["tool.result_type"]["stringValue"] == "failure"

    def test_vscode_no_result_type(self, mock_resolve, state, captured_spans):
        """VS Code mode does not set tool.result_type."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "Bash",
                "tool_use_id": "t1",
                "tool_input": {"command": "echo hi"},
                "tool_response": "hi",
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert "tool.result_type" not in attrs

    def test_cli_malformed_tool_args(self, mock_resolve, state, captured_spans):
        """CLI mode handles malformed toolArgs gracefully."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _cli_base(
            {
                "toolName": "CustomTool",
                "toolArgs": "not valid json",
                "toolResult": {"textResultForLlm": "result"},
            }
        )
        _handle_post_tool_use(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["tool.name"]["stringValue"] == "CustomTool"
        assert attrs["input.value"]["stringValue"] == "not valid json"

    def test_vscode_bash_tool_description(self, mock_resolve, state, captured_spans):
        """VS Code Bash tool sets command and description."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "Bash",
                "tool_use_id": "t1",
                "tool_input": {"command": "git status"},
                "tool_response": "clean",
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["tool.command"]["stringValue"] == "git status"
        assert attrs["tool.description"]["stringValue"] == "git status"

    def test_no_session_id_returns_early(self, state, captured_spans):
        """If session_id is None, returns without sending span."""
        state.delete("session_id")
        with mock.patch("tracing.copilot.hooks.handlers.resolve_session", return_value=state):
            _handle_post_tool_use(_vscode_base({"tool_name": "Bash", "tool_use_id": "t1"}))
        assert len(captured_spans) == 0

    def test_uses_pre_tool_start_time(self, mock_resolve, state, captured_spans):
        """Timing uses pre_tool_use start time if available in state."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        state.set("tool_t7_start", "1000000")
        inp = _vscode_base(
            {
                "tool_name": "Read",
                "tool_use_id": "t7",
                "tool_input": {"file_path": "/a.py"},
                "tool_response": "content",
            }
        )
        _handle_post_tool_use(inp)
        span = _get_span(captured_spans[0])
        assert span["startTimeUnixNano"] == "1000000000000"
        assert state.get("tool_t7_start") is None

    def test_grep_tool_enrichment(self, mock_resolve, state, captured_spans):
        """Grep tool sets query, file_path, and description."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "Grep",
                "tool_use_id": "t1",
                "tool_input": {"pattern": "TODO", "path": "/src"},
                "tool_response": "matches",
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["tool.query"]["stringValue"] == "TODO"
        assert attrs["tool.file_path"]["stringValue"] == "/src"
        assert attrs["tool.description"]["stringValue"].startswith("grep: ")

    def test_webfetch_tool_enrichment(self, mock_resolve, state, captured_spans):
        """WebFetch tool sets url."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "WebFetch",
                "tool_use_id": "t1",
                "tool_input": {"url": "https://example.com"},
                "tool_response": "page",
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["tool.url"]["stringValue"] == "https://example.com"

    def test_cli_input_value_normalized_like_vscode(self, mock_resolve, state, captured_spans):
        """CLI mode re-serializes parsed toolArgs so input.value matches VS Code json.dumps format."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        tool_dict = {"file_path": "/foo.py"}
        inp = _cli_base(
            {
                "toolName": "Read",
                "toolArgs": json.dumps(tool_dict),
                "toolResult": {"textResultForLlm": "ok"},
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        # Should match json.dumps of the parsed dict (same as VS Code mode)
        assert attrs["input.value"]["stringValue"] == json.dumps(tool_dict)


# ---------------------------------------------------------------------------
# stop tests (VS Code only)
# ---------------------------------------------------------------------------


class TestStop:

    def test_parses_transcript_and_builds_llm_span(self, mock_resolve, state, captured_spans, transcript_file):
        """Parses transcript and builds LLM span with output and tokens."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "fix the bug")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file, "sessionId": "s1", "hookEventName": "Stop"})
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert "I found the issue." in attrs["output.value"]["stringValue"]
        assert attrs["openinference.span.kind"]["stringValue"] == "LLM"
        assert attrs["llm.model_name"]["stringValue"] == "gpt-4o"
        # Token counts: input=100, cache_read=10, cache_creation=5 = 115
        assert attrs["llm.token_count.prompt"]["intValue"] == 115
        assert attrs["llm.token_count.completion"]["intValue"] == 50
        assert attrs["llm.token_count.total"]["intValue"] == 165

    def test_no_transcript_no_response(self, mock_resolve, state, captured_spans):
        """No transcript → output is '(No response)'."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "0")
        _handle_stop({"sessionId": "s1", "hookEventName": "Stop"})
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["output.value"]["stringValue"] == "(No response)"

    def test_cleans_up_trace_state(self, mock_resolve, state, captured_spans, transcript_file):
        """Cleans up current_trace_* state keys after sending."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file, "sessionId": "s1"})
        assert state.get("current_trace_id") is None
        assert state.get("current_trace_span_id") is None
        assert state.get("current_trace_start_time") is None
        assert state.get("current_trace_prompt") is None

    def test_gc_every_5_turns(self, mock_resolve, state, captured_spans):
        """GC runs every 5 turns."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_count", "5")
        state.set("trace_start_line", "0")
        with mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files") as gc_mock:
            _handle_stop({"sessionId": "s1"})
            gc_mock.assert_called_once()

    def test_gc_not_called_off_cycle(self, mock_resolve, state, captured_spans):
        """GC not called when trace_count is not multiple of 5."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_count", "3")
        state.set("trace_start_line", "0")
        with mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files") as gc_mock:
            _handle_stop({"sessionId": "s1"})
            gc_mock.assert_not_called()

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → returns without sending."""
        _handle_stop({"sessionId": "s1"})
        assert len(captured_spans) == 0

    def test_skips_lines_before_trace_start_line(self, mock_resolve, state, captured_spans, transcript_file):
        """Skips transcript lines before trace_start_line."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "2")  # past all lines
        _handle_stop({"transcript_path": transcript_file, "sessionId": "s1"})
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["output.value"]["stringValue"] == "(No response)"

    def test_string_content_format(self, mock_resolve, state, captured_spans, tmp_path):
        """Handles transcript with string content format."""
        tf = tmp_path / "t.jsonl"
        entry = {
            "message": {
                "role": "assistant",
                "content": "Hello string",
                "model": "gpt-4o",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        }
        tf.write_text(json.dumps(entry) + "\n")
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": str(tf), "sessionId": "s1"})
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["output.value"]["stringValue"] == "Hello string"


# ---------------------------------------------------------------------------
# error_occurred tests
# ---------------------------------------------------------------------------


class TestErrorOccurred:

    def test_cli_nested_error_object(self, mock_resolve, state, captured_spans):
        """CLI mode extracts error from nested object."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        inp = _cli_base(
            {
                "error": {"message": "Something failed", "name": "TypeError", "stack": "at line 42"},
            }
        )
        _handle_error_occurred(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["error.message"]["stringValue"] == "Something failed"
        assert attrs["error.name"]["stringValue"] == "TypeError"
        assert attrs["error.stack"]["stringValue"] == "at line 42"

    def test_vscode_error(self, mock_resolve, state, captured_spans):
        """VS Code error with nested error object."""
        state.set("current_trace_id", "t" * 32)
        inp = _vscode_base(
            {
                "error": {"message": "Oops", "name": "RuntimeError"},
            }
        )
        _handle_error_occurred(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["error.message"]["stringValue"] == "Oops"
        assert attrs["error.name"]["stringValue"] == "RuntimeError"

    def test_fallback_top_level_fields(self, mock_resolve, state, captured_spans):
        """Falls back to top-level fields when error object is missing."""
        state.set("current_trace_id", "t" * 32)
        inp = _cli_base({"message": "top-level msg", "name": "top-level name"})
        _handle_error_occurred(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["error.message"]["stringValue"] == "top-level msg"
        assert attrs["error.name"]["stringValue"] == "top-level name"

    def test_no_session_id_returns_early(self, state, captured_spans):
        """No session_id → no span sent."""
        state.delete("session_id")
        with mock.patch("tracing.copilot.hooks.handlers.resolve_session", return_value=state):
            _handle_error_occurred(_cli_base({"error": {"message": "fail"}}))
        assert len(captured_spans) == 0

    def test_generates_trace_id_if_missing(self, mock_resolve, state, captured_spans):
        """Generates trace_id if not set in state."""
        # No current_trace_id set
        inp = _cli_base({"error": {"message": "oops", "name": "Error"}})
        _handle_error_occurred(inp)
        assert len(captured_spans) == 1
        span = _get_span(captured_spans[0])
        assert len(span["traceId"]) == 32  # generated


# ---------------------------------------------------------------------------
# session_end tests
# ---------------------------------------------------------------------------


class TestSessionEnd:

    def test_cli_flushes_pending_turn(self, mock_resolve, state, captured_spans):
        """CLI session_end flushes any pending turn."""
        state.set("pending_turn_prompt", "last prompt")
        state.set("pending_turn_trace_id", "t" * 32)
        state.set("pending_turn_span_id", "s" * 16)
        state.set("pending_turn_start_time", "1000")
        state.set("pending_turn_trace_count", "3")
        with mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files"):
            inp = _cli_base({"reason": "complete"})
            _handle_session_end(inp)
        # Pending turn was flushed
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["input.value"]["stringValue"] == "last prompt"

    def test_vscode_does_not_flush_pending_turn(self, mock_resolve, state, captured_spans):
        """VS Code session_end does NOT flush pending turns."""
        state.set("pending_turn_prompt", "should not flush")
        state.set("pending_turn_trace_id", "t" * 32)
        state.set("pending_turn_span_id", "s" * 16)
        with mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files"):
            inp = _vscode_base({"reason": "complete"})
            _handle_session_end(inp)
        assert len(captured_spans) == 0

    def test_logs_session_summary(self, mock_resolve, state):
        """Logs session summary via error()."""
        state.set("trace_count", "10")
        state.set("tool_count", "25")
        with (
            mock.patch("tracing.copilot.hooks.handlers.error") as err_mock,
            mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files"),
        ):
            _handle_session_end(_cli_base({"reason": "complete"}))
        calls = [c[0][0] for c in err_mock.call_args_list]
        assert any("10 traces" in c for c in calls)
        assert any("25 tools" in c for c in calls)

    def test_removes_state_file(self, mock_resolve, state, tmp_path):
        """Removes state file."""
        assert state.state_file.exists()
        with (
            mock.patch("tracing.copilot.hooks.handlers.error"),
            mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files"),
        ):
            _handle_session_end(_cli_base({"reason": "complete"}))
        assert not state.state_file.exists()

    def test_calls_gc(self, mock_resolve, state):
        """Calls gc_stale_state_files."""
        with (
            mock.patch("tracing.copilot.hooks.handlers.error"),
            mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files") as gc_mock,
        ):
            _handle_session_end(_cli_base())
        gc_mock.assert_called_once()

    def test_no_session_id_returns_early(self, state):
        """Returns early when session_id is None."""
        state.delete("session_id")
        with (
            mock.patch("tracing.copilot.hooks.handlers.resolve_session", return_value=state),
            mock.patch("tracing.copilot.hooks.handlers.error") as err_mock,
            mock.patch("tracing.copilot.hooks.handlers.gc_stale_state_files") as gc_mock,
        ):
            _handle_session_end(_cli_base())
        err_mock.assert_not_called()
        gc_mock.assert_not_called()


# ---------------------------------------------------------------------------
# subagent_stop tests (VS Code only)
# ---------------------------------------------------------------------------


class TestSubagentStop:

    def test_builds_llm_span_for_subagent(self, mock_resolve, state, captured_spans, transcript_file):
        """Builds LLM span for subagent with agent_type using transcript_path (VS Code base field)."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        inp = _vscode_base(
            {
                "agent_type": "code-review",
                "agent_id": "agent-1",
                "transcript_path": transcript_file,
            }
        )
        _handle_subagent_stop(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["openinference.span.kind"]["stringValue"] == "LLM"
        assert attrs["copilot.agent.type"]["stringValue"] == "code-review"
        assert attrs["subagent.type"]["stringValue"] == "code-review"
        assert "I found the issue." in attrs["output.value"]["stringValue"]

    def test_falls_back_to_agent_transcript_path(self, mock_resolve, state, captured_spans, transcript_file):
        """Falls back to agent_transcript_path if transcript_path not present."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        inp = _vscode_base(
            {
                "agent_type": "code-review",
                "agent_id": "agent-1",
                "agent_transcript_path": transcript_file,
            }
        )
        _handle_subagent_stop(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert "I found the issue." in attrs["output.value"]["stringValue"]

    def test_skips_empty_agent_type(self, mock_resolve, state, captured_spans):
        """Skips when agent_type is empty."""
        state.set("current_trace_id", "t" * 32)
        _handle_subagent_stop(_vscode_base({"agent_type": ""}))
        assert len(captured_spans) == 0

    def test_skips_unknown_agent_type(self, mock_resolve, state, captured_spans):
        """Skips when agent_type is 'unknown'."""
        state.set("current_trace_id", "t" * 32)
        _handle_subagent_stop(_vscode_base({"agent_type": "unknown"}))
        assert len(captured_spans) == 0

    def test_skips_null_agent_type(self, mock_resolve, state, captured_spans):
        """Skips when agent_type is 'null'."""
        state.set("current_trace_id", "t" * 32)
        _handle_subagent_stop(_vscode_base({"agent_type": "null"}))
        assert len(captured_spans) == 0

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → returns without sending."""
        _handle_subagent_stop(_vscode_base({"agent_type": "explorer"}))
        assert len(captured_spans) == 0

    def test_no_transcript_no_output(self, mock_resolve, state, captured_spans):
        """No transcript → no output.value attribute."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        inp = _vscode_base(
            {
                "agent_type": "explorer",
                "agent_id": "a1",
            }
        )
        _handle_subagent_stop(inp)
        assert len(captured_spans) == 1
        attrs = _get_span_attrs(captured_spans[0])
        assert "output.value" not in attrs

    def test_parent_span_id(self, mock_resolve, state, captured_spans):
        """Subagent span has parent_span_id from current trace."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "parentspan1234567")
        _handle_subagent_stop(
            _vscode_base(
                {
                    "agent_type": "test-agent",
                    "agent_id": "a1",
                }
            )
        )
        span = _get_span(captured_spans[0])
        assert span.get("parentSpanId") == "parentspan1234567"


# ---------------------------------------------------------------------------
# CLI deferred turn pattern integration tests
# ---------------------------------------------------------------------------


class TestDeferredTurnPattern:
    """Tests for deferred turn helpers (still used by _handle_session_end)."""

    def test_flush_pending_turn_no_op_when_empty(self, state):
        """_flush_pending_turn is no-op when no pending turn exists."""
        with mock.patch("tracing.copilot.hooks.handlers.send_span") as send_mock:
            _flush_pending_turn(state)
        send_mock.assert_not_called()

    def test_flush_pending_turn_clears_invalid(self, state):
        """_flush_pending_turn clears invalid pending turn (no trace/span id)."""
        state.set("pending_turn_prompt", "orphan")
        with mock.patch("tracing.copilot.hooks.handlers.send_span") as send_mock:
            _flush_pending_turn(state)
        send_mock.assert_not_called()
        assert state.get("pending_turn_prompt") is None

    def test_consecutive_prompts_each_open_fresh_trace(self, mock_resolve, mock_ensure, state, captured_spans):
        """Each user_prompt_submitted opens a fresh trace without sending spans."""
        _handle_user_prompt_submitted({"cwd": "/tmp/project", "prompt": "first"})
        first_trace = state.get("current_trace_id")
        _handle_user_prompt_submitted({"cwd": "/tmp/project", "prompt": "second"})
        second_trace = state.get("current_trace_id")
        assert first_trace != second_trace
        assert state.get("current_trace_prompt") == "second"
        assert state.get("trace_count") == "2"
        assert len(captured_spans) == 0


# ---------------------------------------------------------------------------
# _save_pending_turn and _clear_pending_turn tests
# ---------------------------------------------------------------------------


class TestPendingTurnHelpers:

    def test_save_pending_turn(self, state):
        """_save_pending_turn sets all pending turn keys."""
        _save_pending_turn(state, "hello world")
        assert state.get("pending_turn_prompt") == "hello world"
        assert state.get("pending_turn_trace_id") is not None
        assert len(state.get("pending_turn_trace_id")) == 32
        assert state.get("pending_turn_span_id") is not None
        assert len(state.get("pending_turn_span_id")) == 16
        assert state.get("pending_turn_start_time") is not None
        assert state.get("pending_turn_trace_count") is not None
        assert state.get("trace_count") == "1"
        # current trace context set
        assert state.get("current_trace_id") == state.get("pending_turn_trace_id")
        assert state.get("current_trace_span_id") == state.get("pending_turn_span_id")

    def test_clear_pending_turn(self, state):
        """_clear_pending_turn removes all pending turn keys."""
        _save_pending_turn(state, "test")
        _clear_pending_turn(state)
        assert state.get("pending_turn_prompt") is None
        assert state.get("pending_turn_trace_id") is None
        assert state.get("pending_turn_span_id") is None
        assert state.get("pending_turn_start_time") is None
        assert state.get("pending_turn_trace_count") is None


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:

    def test_entry_point_catches_exception(self, monkeypatch, capsys):
        """Exception in handler → entry point catches, calls error()."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value={}),
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.copilot.hooks.handlers._handle_session_start", side_effect=RuntimeError("boom")),
        ):
            session_start()
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_malformed_stdin_no_crash(self, monkeypatch):
        """Malformed stdin JSON doesn't crash entry point."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch.object(sys, "stdin", new=io.StringIO("not json")),
            mock.patch("tracing.copilot.hooks.handlers.resolve_session") as rs,
            mock.patch("tracing.copilot.hooks.handlers.ensure_session_initialized"),
        ):
            session_start()
        rs.assert_called_once_with({})


# ---------------------------------------------------------------------------
# Entry point tests (all 8 CLI wrappers)
# ---------------------------------------------------------------------------

ENTRY_POINTS = [
    ("session_start", session_start, "_handle_session_start", "SessionStart"),
    ("user_prompt_submitted", user_prompt_submitted, "_handle_user_prompt_submitted", "UserPromptSubmit"),
    ("pre_tool_use", pre_tool_use, "_handle_pre_tool_use", "PreToolUse"),
    ("post_tool_use", post_tool_use, "_handle_post_tool_use", "PostToolUse"),
    ("stop", stop, "_handle_stop", "Stop"),
    ("error_occurred", error_occurred, "_handle_error_occurred", "ErrorOccurred"),
    ("session_end", session_end, "_handle_session_end", "SessionEnd"),
    ("subagent_stop", subagent_stop, "_handle_subagent_stop", "SubagentStop"),
]


class TestEntryPoints:

    @pytest.mark.parametrize("name,entry_fn,handler_name,event", ENTRY_POINTS)
    def test_happy_path_calls_handler(self, name, entry_fn, handler_name, event):
        """Entry point calls the corresponding _handle_* with parsed stdin JSON."""
        input_data = {"sessionId": "s1", "hookEventName": event}
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value=input_data),
            mock.patch(f"tracing.copilot.hooks.handlers.{handler_name}") as handler_mock,
            mock.patch("tracing.copilot.hooks.handlers._print_response"),
        ):
            entry_fn()
        handler_mock.assert_called_once_with(input_data)

    @pytest.mark.parametrize("name,entry_fn,handler_name,event", ENTRY_POINTS)
    def test_requirements_not_met_skips_handler(self, name, entry_fn, handler_name, event):
        """When check_requirements returns False, handler is NOT called but response is still printed."""
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=False),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value={}),
            mock.patch(f"tracing.copilot.hooks.handlers.{handler_name}") as handler_mock,
            mock.patch("tracing.copilot.hooks.handlers._print_response") as pr_mock,
        ):
            entry_fn()
        handler_mock.assert_not_called()
        pr_mock.assert_called_once_with({}, event)

    @pytest.mark.parametrize("name,entry_fn,handler_name,event", ENTRY_POINTS)
    def test_exception_caught_and_logged(self, name, entry_fn, handler_name, event, capsys):
        """Handler exception is caught; error is logged to stderr, response still printed."""
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value={}),
            mock.patch(f"tracing.copilot.hooks.handlers.{handler_name}", side_effect=RuntimeError("test-boom")),
            mock.patch("tracing.copilot.hooks.handlers._print_response") as pr_mock,
        ):
            entry_fn()  # should not raise
        captured = capsys.readouterr()
        assert "test-boom" in captured.err
        pr_mock.assert_called_once_with({}, event)

    @pytest.mark.parametrize("name,entry_fn,handler_name,event", ENTRY_POINTS)
    def test_prints_response(self, name, entry_fn, handler_name, event):
        """Entry point calls _print_response with correct event name."""
        input_data = {"sessionId": "s1", "hookEventName": event}
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value=input_data),
            mock.patch(f"tracing.copilot.hooks.handlers.{handler_name}"),
            mock.patch("tracing.copilot.hooks.handlers._print_response") as pr_mock,
        ):
            entry_fn()
        pr_mock.assert_called_once_with(input_data, event)

    def test_pre_tool_use_prints_permission_on_exception(self, capsys):
        """pre_tool_use MUST print permission response even when handler crashes."""
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=True),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value={}),
            mock.patch("tracing.copilot.hooks.handlers._handle_pre_tool_use", side_effect=RuntimeError("boom")),
        ):
            pre_tool_use()
        out = capsys.readouterr().out.strip()
        # CLI mode (empty input_json) → flat permission response
        assert json.loads(out) == {"permissionDecision": "allow"}

    def test_pre_tool_use_prints_permission_when_disabled(self, capsys):
        """pre_tool_use MUST print permission response even when tracing disabled."""
        with (
            mock.patch("tracing.copilot.hooks.handlers.check_requirements", return_value=False),
            mock.patch("tracing.copilot.hooks.handlers._read_stdin", return_value={}),
        ):
            pre_tool_use()
        out = capsys.readouterr().out.strip()
        assert json.loads(out) == {"permissionDecision": "allow"}


# ---------------------------------------------------------------------------
# project.name attribute tests
# ---------------------------------------------------------------------------


class TestProjectNameOnAllSpans:

    def test_tool_span_has_project_name(self, mock_resolve, state, captured_spans):
        """TOOL spans include project.name."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        inp = _vscode_base(
            {
                "tool_name": "Bash",
                "tool_use_id": "t1",
                "tool_input": {"command": "ls"},
                "tool_response": "output",
            }
        )
        _handle_post_tool_use(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["project.name"]["stringValue"] == "test-copilot-project"

    def test_error_span_has_project_name(self, mock_resolve, state, captured_spans):
        """Error CHAIN spans include project.name."""
        state.set("current_trace_id", "t" * 32)
        inp = _cli_base({"error": {"message": "fail", "name": "Err"}})
        _handle_error_occurred(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["project.name"]["stringValue"] == "test-copilot-project"

    def test_subagent_span_has_project_name(self, mock_resolve, state, captured_spans):
        """Subagent LLM spans include project.name."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        inp = _vscode_base({"agent_type": "test-agent", "agent_id": "a1"})
        _handle_subagent_stop(inp)
        attrs = _get_span_attrs(captured_spans[0])
        assert attrs["project.name"]["stringValue"] == "test-copilot-project"

    def test_user_prompt_sets_trace_state(self, mock_resolve, mock_ensure, state, captured_spans):
        """user_prompt_submitted sets trace state with project context."""
        inp = {"cwd": "/tmp/project", "prompt": "new prompt"}
        _handle_user_prompt_submitted(inp)
        assert state.get("current_trace_id") is not None
        assert state.get("current_trace_prompt") == "new prompt"
        assert state.get("trace_count") == "1"
        assert state.get("tool_count") == "0"
