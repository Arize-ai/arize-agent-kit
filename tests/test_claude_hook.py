#!/usr/bin/env python3
"""Tests for core.hooks.claude.handlers — the 9 Claude Code hook handlers."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from core.hooks.claude.handlers import (
    _read_stdin,
    _handle_session_start,
    _handle_pre_tool_use,
    _handle_post_tool_use,
    _handle_user_prompt_submit,
    _handle_stop,
    _handle_subagent_stop,
    _handle_notification,
    _handle_permission_request,
    _handle_session_end,
    session_start,
    pre_tool_use,
    post_tool_use,
    user_prompt_submit,
    stop,
    subagent_stop,
    notification,
    permission_request,
    session_end,
)
from core.common import StateManager


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
    sm.set("session_id", "test-session-123")
    sm.set("project_name", "test-project")
    sm.set("trace_count", "0")
    sm.set("tool_count", "0")
    sm.set("user_id", "test-user")
    return sm


@pytest.fixture
def mock_resolve(state):
    """Mock resolve_session to return the test state fixture."""
    with mock.patch("core.hooks.claude.handlers.resolve_session", return_value=state) as m:
        yield m


@pytest.fixture
def captured_spans():
    """Mock send_span and collect all payloads sent."""
    sent = []
    with mock.patch("core.hooks.claude.handlers.send_span", side_effect=lambda s: sent.append(s)):
        yield sent


# transcript_file fixture is provided by conftest.py


# ---------------------------------------------------------------------------
# _read_stdin tests
# ---------------------------------------------------------------------------

class TestReadStdin:

    def test_empty_stdin(self):
        """Empty stdin returns {}."""
        with mock.patch.object(sys, "stdin", new=__import__("io").StringIO("")):
            assert _read_stdin() == {}

    def test_malformed_json(self):
        """Malformed JSON returns {}."""
        with mock.patch.object(sys, "stdin", new=__import__("io").StringIO("not json")):
            assert _read_stdin() == {}

    def test_valid_json(self):
        """Valid JSON is parsed."""
        with mock.patch.object(sys, "stdin", new=__import__("io").StringIO('{"a": 1}')):
            assert _read_stdin() == {"a": 1}


# ---------------------------------------------------------------------------
# session_start tests
# ---------------------------------------------------------------------------

class TestSessionStart:

    def test_calls_resolve_and_init(self, state, captured_spans):
        """session_start calls resolve_session and ensure_session_initialized."""
        with mock.patch("core.hooks.claude.handlers.resolve_session", return_value=state) as rs, \
             mock.patch("core.hooks.claude.handlers.ensure_session_initialized") as esi:
            inp = {"session_id": "s1"}
            _handle_session_start(inp)
            rs.assert_called_once_with(inp)
            esi.assert_called_once_with(state, inp)


# ---------------------------------------------------------------------------
# pre_tool_use tests
# ---------------------------------------------------------------------------

class TestPreToolUse:

    def test_sets_tool_start_time(self, mock_resolve, state):
        """pre_tool_use stores tool_{id}_start in state."""
        _handle_pre_tool_use({"tool_use_id": "tool-42"})
        val = state.get("tool_tool-42_start")
        assert val is not None
        assert int(val) > 0

    def test_missing_tool_use_id_generates_one(self, mock_resolve, state):
        """Missing tool_use_id generates a fallback id and still sets start time."""
        with mock.patch("core.hooks.claude.handlers.generate_trace_id", return_value="gen-id-123"):
            _handle_pre_tool_use({})
        val = state.get("tool_gen-id-123_start")
        assert val is not None
        assert int(val) > 0


# ---------------------------------------------------------------------------
# post_tool_use tests
# ---------------------------------------------------------------------------

class TestPostToolUse:

    def test_builds_tool_span(self, mock_resolve, state, captured_spans):
        """post_tool_use builds a TOOL span with correct attributes."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        _handle_post_tool_use({
            "tool_name": "Read",
            "tool_use_id": "t1",
            "tool_input": {"file_path": "/foo/bar.py"},
            "tool_response": "file content",
        })
        assert len(captured_spans) == 1
        span = captured_spans[0]
        attrs = {a["key"]: a["value"] for a in
                 span["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "TOOL"
        assert attrs["tool.name"]["stringValue"] == "Read"
        assert attrs["tool.file_path"]["stringValue"] == "/foo/bar.py"

    def test_bash_tool_sets_command(self, mock_resolve, state, captured_spans):
        """Bash tool sets tool.command attr and description is command[:200]."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        _handle_post_tool_use({
            "tool_name": "Bash",
            "tool_use_id": "t2",
            "tool_input": {"command": "ls -la /tmp"},
            "tool_response": "output",
        })
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["tool.command"]["stringValue"] == "ls -la /tmp"
        assert attrs["tool.description"]["stringValue"] == "ls -la /tmp"

    def test_grep_tool_sets_query_and_path(self, mock_resolve, state, captured_spans):
        """Grep tool sets both tool.query and tool.file_path, description prefixed 'grep: '."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        _handle_post_tool_use({
            "tool_name": "Grep",
            "tool_use_id": "t3",
            "tool_input": {"pattern": "TODO", "path": "/src"},
            "tool_response": "matches",
        })
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["tool.query"]["stringValue"] == "TODO"
        assert attrs["tool.file_path"]["stringValue"] == "/src"
        assert attrs["tool.description"]["stringValue"].startswith("grep: ")

    def test_webfetch_tool_sets_url(self, mock_resolve, state, captured_spans):
        """WebFetch tool sets tool.url attr."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        _handle_post_tool_use({
            "tool_name": "WebFetch",
            "tool_use_id": "t4",
            "tool_input": {"url": "https://example.com"},
            "tool_response": "page",
        })
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["tool.url"]["stringValue"] == "https://example.com"

    def test_unknown_tool_description_is_input(self, mock_resolve, state, captured_spans):
        """Unknown tool_name → description is first 200 chars of input."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        _handle_post_tool_use({
            "tool_name": "CustomTool",
            "tool_use_id": "t5",
            "tool_input": {"data": "hello"},
            "tool_response": "result",
        })
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        desc = attrs["tool.description"]["stringValue"]
        assert len(desc) <= 200
        # Description is the JSON serialization of tool_input, truncated
        assert "hello" in desc

    def test_uses_pre_tool_start_time(self, mock_resolve, state, captured_spans):
        """Timing uses pre_tool_use start time if available in state."""
        state.set("current_trace_id", "trace-abc")
        state.set("current_trace_span_id", "span-parent")
        state.set("tool_t7_start", "1000000")
        _handle_post_tool_use({
            "tool_name": "Read",
            "tool_use_id": "t7",
            "tool_input": {"file_path": "/a.py"},
            "tool_response": "content",
        })
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["startTimeUnixNano"] == "1000000000000"  # 1000000 ms -> ns
        # Verify cleanup
        assert state.get("tool_t7_start") is None

    def test_no_session_id_returns_early(self, state, captured_spans):
        """If session_id is None, returns without sending span."""
        state.delete("session_id")
        with mock.patch("core.hooks.claude.handlers.resolve_session", return_value=state):
            _handle_post_tool_use({"tool_name": "Bash", "tool_use_id": "t8"})
        assert len(captured_spans) == 0


# ---------------------------------------------------------------------------
# user_prompt_submit tests
# ---------------------------------------------------------------------------

class TestUserPromptSubmit:

    def test_sets_trace_state(self, mock_resolve, state, captured_spans):
        """user_prompt_submit sets current_trace_id, span_id, start_time, prompt."""
        with mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            _handle_user_prompt_submit({"prompt": "hello world"})
        assert state.get("current_trace_id") is not None
        assert len(state.get("current_trace_id")) == 32
        assert state.get("current_trace_span_id") is not None
        assert len(state.get("current_trace_span_id")) == 16
        assert state.get("current_trace_start_time") is not None
        assert state.get("current_trace_prompt") == "hello world"

    def test_increments_trace_count(self, mock_resolve, state, captured_spans):
        """user_prompt_submit increments trace_count."""
        with mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            _handle_user_prompt_submit({"prompt": "test"})
        assert state.get("trace_count") == "1"

    def test_records_trace_start_line(self, mock_resolve, state, captured_spans, transcript_file):
        """Records trace_start_line from transcript file line count."""
        with mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            _handle_user_prompt_submit({
                "prompt": "test",
                "transcript_path": transcript_file,
            })
        # sample_transcript.jsonl has 3 lines
        assert state.get("trace_start_line") == "3"

    def test_no_transcript_sets_zero(self, mock_resolve, state, captured_spans):
        """Missing transcript sets trace_start_line to 0."""
        with mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            _handle_user_prompt_submit({"prompt": "test"})
        assert state.get("trace_start_line") == "0"

    def test_failsafe_closes_orphan(self, mock_resolve, state, captured_spans):
        """If current_trace_id already in state, sends fail-safe LLM span."""
        state.set("current_trace_id", "old-trace-id-00000000000000000000")
        state.set("current_trace_span_id", "old-span-1234567")
        state.set("current_trace_start_time", "999000")
        state.set("current_trace_prompt", "old prompt")
        with mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            _handle_user_prompt_submit({"prompt": "new prompt"})
        # Should have sent a fail-safe span
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "LLM"
        assert "fail-safe" in attrs["output.value"]["stringValue"]
        # New trace should be set up
        assert state.get("current_trace_id") != "old-trace-id-00000000000000000000"


# ---------------------------------------------------------------------------
# stop tests
# ---------------------------------------------------------------------------

class TestStop:

    def test_parses_transcript_array_content(self, mock_resolve, state, captured_spans, transcript_file):
        """Parses transcript, extracts text from content array format."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "fix the bug")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file})
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert "I found the issue." in attrs["output.value"]["stringValue"]

    def test_parses_transcript_string_content(self, mock_resolve, state, captured_spans, tmp_path):
        """Parses transcript with string content format."""
        tf = tmp_path / "transcript_str.jsonl"
        entry = {"message": {
            "role": "assistant",
            "content": "Hello from string format",
            "model": "claude-test",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }}
        tf.write_text(json.dumps(entry) + "\n")

        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": str(tf)})
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["output.value"]["stringValue"] == "Hello from string format"

    def test_accumulates_tokens(self, mock_resolve, state, captured_spans, transcript_file):
        """Accumulates tokens: input + cache_read + cache_creation → prompt."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "fix the bug")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file})
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        # input_tokens=100, cache_read=10, cache_creation=5 → 115 prompt
        assert attrs["llm.token_count.prompt"]["intValue"] == 115
        # output_tokens=50
        assert attrs["llm.token_count.completion"]["intValue"] == 50
        # total
        assert attrs["llm.token_count.total"]["intValue"] == 165

    def test_skips_lines_before_trace_start_line(self, mock_resolve, state, captured_spans, transcript_file):
        """Skips lines before trace_start_line."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        # Set start_line past all entries (3 lines in fixture)
        state.set("trace_start_line", "3")
        _handle_stop({"transcript_path": transcript_file})
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["output.value"]["stringValue"] == "(No response)"

    def test_no_transcript_file(self, mock_resolve, state, captured_spans):
        """No transcript file → output is '(No response)'."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": "/nonexistent/file.jsonl"})
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["output.value"]["stringValue"] == "(No response)"

    def test_cleans_up_trace_state(self, mock_resolve, state, captured_spans, transcript_file):
        """Cleans up current_trace_* state keys after sending."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "fix the bug")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file})
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
        with mock.patch("core.hooks.claude.handlers.gc_stale_state_files") as gc_mock:
            _handle_stop({})
            gc_mock.assert_called_once()

    def test_gc_not_called_off_cycle(self, mock_resolve, state, captured_spans):
        """GC not called when trace_count is not multiple of 5."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "test")
        state.set("trace_count", "3")
        state.set("trace_start_line", "0")
        with mock.patch("core.hooks.claude.handlers.gc_stale_state_files") as gc_mock:
            _handle_stop({})
            gc_mock.assert_not_called()

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → returns without sending."""
        _handle_stop({})
        assert len(captured_spans) == 0

    def test_golden_transcript(self, mock_resolve, state, captured_spans, transcript_file):
        """Golden test: exact token counts and output from sample_transcript.jsonl."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        state.set("current_trace_start_time", "1000")
        state.set("current_trace_prompt", "fix the bug")
        state.set("trace_start_line", "0")
        _handle_stop({"transcript_path": transcript_file})

        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}

        # Token counts: input=100 + cache_read=10 + cache_creation=5 = 115 prompt
        assert attrs["llm.token_count.prompt"]["intValue"] == 115
        assert attrs["llm.token_count.completion"]["intValue"] == 50
        assert attrs["llm.token_count.total"]["intValue"] == 165
        # Output text
        assert attrs["output.value"]["stringValue"] == "I found the issue."
        # Model
        assert attrs["llm.model_name"]["stringValue"] == "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# subagent_stop tests
# ---------------------------------------------------------------------------

class TestSubagentStop:

    def test_skips_empty_agent_type(self, mock_resolve, state, captured_spans):
        """Skips when agent_type is empty."""
        state.set("current_trace_id", "t" * 32)
        _handle_subagent_stop({"agent_type": ""})
        assert len(captured_spans) == 0

    def test_skips_unknown_agent_type(self, mock_resolve, state, captured_spans):
        """Skips when agent_type is 'unknown'."""
        state.set("current_trace_id", "t" * 32)
        _handle_subagent_stop({"agent_type": "unknown"})
        assert len(captured_spans) == 0

    def test_parses_subagent_transcript(self, mock_resolve, state, captured_spans, transcript_file):
        """Parses subagent transcript same as stop."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        _handle_subagent_stop({
            "agent_type": "code-review",
            "agent_id": "agent-1",
            "agent_transcript_path": transcript_file,
        })
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["subagent.type"]["stringValue"] == "code-review"
        assert "I found the issue." in attrs["output.value"]["stringValue"]

    def test_uses_file_creation_time(self, mock_resolve, state, captured_spans, transcript_file):
        """Uses file creation time (st_birthtime) for start_time."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)

        real_stat = Path(transcript_file).stat()
        mock_stat = mock.MagicMock(wraps=real_stat)
        mock_stat.st_birthtime = 1700000.0  # seconds → 1700000000 ms
        mock_stat.st_mode = real_stat.st_mode

        with mock.patch.object(Path, "stat", return_value=mock_stat):
            _handle_subagent_stop({
                "agent_type": "explorer",
                "agent_id": "a2",
                "agent_transcript_path": transcript_file,
            })

        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["startTimeUnixNano"] == "1700000000000000"  # 1700000000 ms -> ns

    def test_falls_back_to_ctime(self, mock_resolve, state, captured_spans, transcript_file):
        """Falls back to st_ctime when st_birthtime unavailable."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)

        real_stat = Path(transcript_file).stat()

        class FakeStat:
            """Stat result without st_birthtime."""
            st_mode = real_stat.st_mode
            st_size = real_stat.st_size
            st_ctime = 1600000.0

        with mock.patch.object(Path, "stat", return_value=FakeStat()):
            _handle_subagent_stop({
                "agent_type": "explorer",
                "agent_id": "a3",
                "agent_transcript_path": transcript_file,
            })

        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["startTimeUnixNano"] == "1600000000000000"

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → returns without sending."""
        _handle_subagent_stop({"agent_type": "explorer"})
        assert len(captured_spans) == 0


# ---------------------------------------------------------------------------
# notification tests
# ---------------------------------------------------------------------------

class TestNotification:

    def test_builds_chain_span(self, mock_resolve, state, captured_spans):
        """Builds CHAIN span with notification attributes."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        _handle_notification({
            "message": "Build succeeded",
            "title": "CI",
            "type": "success",
        })
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["notification.message"]["stringValue"] == "Build succeeded"
        assert attrs["notification.title"]["stringValue"] == "CI"
        assert attrs["notification.type"]["stringValue"] == "success"

    def test_default_notification_type(self, mock_resolve, state, captured_spans):
        """Default notification_type is 'info'."""
        state.set("current_trace_id", "t" * 32)
        _handle_notification({"message": "hello"})
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["notification.type"]["stringValue"] == "info"

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → no span sent."""
        _handle_notification({"message": "test"})
        assert len(captured_spans) == 0


# ---------------------------------------------------------------------------
# permission_request tests
# ---------------------------------------------------------------------------

class TestPermissionRequest:

    def test_builds_chain_span(self, mock_resolve, state, captured_spans):
        """Builds CHAIN span with permission attributes."""
        state.set("current_trace_id", "t" * 32)
        state.set("current_trace_span_id", "s" * 16)
        _handle_permission_request({
            "permission": "allow",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        })
        assert len(captured_spans) == 1
        span = captured_spans[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["openinference.span.kind"]["stringValue"] == "CHAIN"
        assert attrs["permission.type"]["stringValue"] == "allow"
        assert attrs["permission.tool"]["stringValue"] == "Bash"
        assert "command" in attrs["input.value"]["stringValue"]

    def test_logs_debug_input(self, mock_resolve, state, captured_spans):
        """Logs debug input via log()."""
        state.set("current_trace_id", "t" * 32)
        with mock.patch("core.hooks.claude.handlers.log") as log_mock:
            _handle_permission_request({"permission": "deny", "tool_name": "Edit"})
        log_mock.assert_called_once()
        assert "permission_request" in log_mock.call_args[0][0]

    def test_no_trace_id_returns_early(self, mock_resolve, state, captured_spans):
        """No current_trace_id → no span sent."""
        _handle_permission_request({"permission": "allow"})
        assert len(captured_spans) == 0


# ---------------------------------------------------------------------------
# session_end tests
# ---------------------------------------------------------------------------

class TestSessionEnd:

    def test_logs_session_summary(self, mock_resolve, state):
        """Logs session summary via error()."""
        state.set("trace_count", "10")
        state.set("tool_count", "25")
        with mock.patch("core.hooks.claude.handlers.error") as err_mock, \
             mock.patch("core.hooks.claude.handlers.gc_stale_state_files"):
            _handle_session_end({})
        calls = [c[0][0] for c in err_mock.call_args_list]
        assert any("10 traces" in c for c in calls)
        assert any("25 tools" in c for c in calls)

    def test_removes_state_file(self, mock_resolve, state, tmp_path):
        """Removes state file and lock dir."""
        assert state.state_file.exists()
        with mock.patch("core.hooks.claude.handlers.error"), \
             mock.patch("core.hooks.claude.handlers.gc_stale_state_files"):
            _handle_session_end({})
        assert not state.state_file.exists()

    def test_calls_gc(self, mock_resolve, state):
        """Calls gc_stale_state_files."""
        with mock.patch("core.hooks.claude.handlers.error"), \
             mock.patch("core.hooks.claude.handlers.gc_stale_state_files") as gc_mock:
            _handle_session_end({})
        gc_mock.assert_called_once()

    def test_graceful_when_session_id_none(self, state):
        """Returns early when session_id is None."""
        state.delete("session_id")
        with mock.patch("core.hooks.claude.handlers.resolve_session", return_value=state), \
             mock.patch("core.hooks.claude.handlers.error") as err_mock, \
             mock.patch("core.hooks.claude.handlers.gc_stale_state_files") as gc_mock:
            _handle_session_end({})
        err_mock.assert_not_called()
        gc_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_exception_caught_by_entry_point(self, monkeypatch, capsys):
        """Exception in _handle_session_start → entry point catches, calls error()."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.claude.handlers._read_stdin", return_value={}), \
             mock.patch("core.hooks.claude.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.claude.handlers._handle_session_start",
                        side_effect=RuntimeError("boom")):
            session_start()
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_malformed_stdin_no_crash(self, monkeypatch, capsys):
        """Malformed stdin JSON in entry point doesn't crash."""
        monkeypatch.setenv("ARIZE_TRACE_ENABLED", "true")
        with mock.patch("core.hooks.claude.handlers.check_requirements", return_value=True), \
             mock.patch.object(sys, "stdin",
                               new=__import__("io").StringIO("not valid json")), \
             mock.patch("core.hooks.claude.handlers.resolve_session") as rs, \
             mock.patch("core.hooks.claude.handlers.ensure_session_initialized"):
            session_start()
        # _read_stdin returns {} on invalid JSON, so resolve_session is called with {}
        rs.assert_called_once_with({})


# ---------------------------------------------------------------------------
# Entry point tests (all 9 CLI wrappers)
# ---------------------------------------------------------------------------

ENTRY_POINTS = [
    ("session_start", session_start, "_handle_session_start"),
    ("pre_tool_use", pre_tool_use, "_handle_pre_tool_use"),
    ("post_tool_use", post_tool_use, "_handle_post_tool_use"),
    ("user_prompt_submit", user_prompt_submit, "_handle_user_prompt_submit"),
    ("stop", stop, "_handle_stop"),
    ("subagent_stop", subagent_stop, "_handle_subagent_stop"),
    ("notification", notification, "_handle_notification"),
    ("permission_request", permission_request, "_handle_permission_request"),
    ("session_end", session_end, "_handle_session_end"),
]


class TestEntryPoints:

    @pytest.mark.parametrize("name,entry_fn,handler_name", ENTRY_POINTS)
    def test_happy_path_calls_handler(self, name, entry_fn, handler_name):
        """Entry point calls the corresponding _handle_* with parsed stdin JSON."""
        input_data = {"session_id": "s1"}
        with mock.patch("core.hooks.claude.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.claude.handlers._read_stdin", return_value=input_data), \
             mock.patch(f"core.hooks.claude.handlers.{handler_name}") as handler_mock:
            entry_fn()
        handler_mock.assert_called_once_with(input_data)

    @pytest.mark.parametrize("name,entry_fn,handler_name", ENTRY_POINTS)
    def test_requirements_not_met_skips_handler(self, name, entry_fn, handler_name):
        """When check_requirements returns False, handler is NOT called."""
        with mock.patch("core.hooks.claude.handlers.check_requirements", return_value=False), \
             mock.patch(f"core.hooks.claude.handlers.{handler_name}") as handler_mock:
            entry_fn()
        handler_mock.assert_not_called()

    @pytest.mark.parametrize("name,entry_fn,handler_name", ENTRY_POINTS)
    def test_exception_caught_and_logged(self, name, entry_fn, handler_name, capsys):
        """Handler exception is caught; error is logged to stderr, no raise."""
        with mock.patch("core.hooks.claude.handlers.check_requirements", return_value=True), \
             mock.patch("core.hooks.claude.handlers._read_stdin", return_value={}), \
             mock.patch(f"core.hooks.claude.handlers.{handler_name}",
                        side_effect=RuntimeError("test-boom")):
            entry_fn()  # should not raise
        captured = capsys.readouterr()
        assert "test-boom" in captured.err
