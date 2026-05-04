"""Tests for tracing.copilot.hooks.transcript.parse_transcript."""

from __future__ import annotations

import json

from tracing.copilot.hooks.transcript import parse_transcript


def _write_jsonl(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


class TestParseTranscriptHappyPath:
    def test_extracts_model_from_session_model_change(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.start", "data": {"copilotVersion": "1.0.40"}},
                {"type": "session.model_change", "data": {"newModel": "gpt-5-mini"}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5-mini"
        assert s["copilot_version"] == "1.0.40"

    def test_extracts_user_prompt_from_hook_start(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "do the thing"},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "do the thing"

    def test_counts_pretool_use_events(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "hook.start", "data": {"hookType": "preToolUse", "input": {}}},
                {"type": "hook.start", "data": {"hookType": "preToolUse", "input": {}}},
                {"type": "hook.start", "data": {"hookType": "postToolUse", "input": {}}},
            ],
        )
        s = parse_transcript(f)
        assert s["tool_count"] == 2


class TestParseTranscriptDefensive:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert parse_transcript(tmp_path / "nope.jsonl") == {}

    def test_blank_file_returns_zeroed_summary(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text("", encoding="utf-8")
        s = parse_transcript(f)
        assert s["events_seen"] == 0
        assert s["model_name"] == ""

    def test_malformed_lines_are_skipped(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text(
            "not json\n"
            + json.dumps({"type": "session.model_change", "data": {"newModel": "gpt-5"}})
            + "\nalso not json\n",
            encoding="utf-8",
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5"
        assert s["events_seen"] == 1

    def test_unknown_event_kinds_do_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "something.exotic", "data": {"x": 1}}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1
