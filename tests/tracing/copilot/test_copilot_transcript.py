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

    def test_null_data_field_does_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "session.start", "data": None}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1
        assert s["copilot_version"] == ""

    def test_missing_type_field_does_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"data": {"something": "here"}}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1


class TestParseTranscriptOverwriteSemantics:
    def test_last_model_change_wins(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "gpt-4"}},
                {"type": "session.model_change", "data": {"newModel": "gpt-5-mini"}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5-mini"

    def test_last_user_prompt_wins(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "first prompt"},
                    },
                },
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "second prompt"},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "second prompt"

    def test_empty_model_name_does_not_overwrite(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "gpt-4"}},
                {"type": "session.model_change", "data": {"newModel": ""}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-4"

    def test_empty_prompt_does_not_overwrite(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "real prompt"},
                    },
                },
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": ""},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "real prompt"


class TestParseTranscriptReturnShape:
    def test_all_expected_keys_present(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "session.start", "data": {}}])
        s = parse_transcript(f)
        assert set(s.keys()) == {
            "model_name",
            "copilot_version",
            "input_text",
            "output_text",
            "tool_count",
            "events_seen",
        }

    def test_output_text_always_empty_string(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.start", "data": {"copilotVersion": "1.0.40"}},
                {"type": "session.model_change", "data": {"newModel": "gpt-5-mini"}},
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "hello"},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["output_text"] == ""

    def test_missing_file_returns_truly_empty_dict(self, tmp_path):
        s = parse_transcript(tmp_path / "nonexistent.jsonl")
        assert s == {}
        assert len(s) == 0
