"""Tests for tracing.kiro.constants — package skeleton, constants, and fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "kiro"
PROBE_DIR = FIXTURES_DIR / "probe_payloads"
SIDECAR_DIR = FIXTURES_DIR / "sidecars"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

PROBE_FILES = [
    "agent_spawn.json",
    "user_prompt_submit.json",
    "pre_tool_use.json",
    "post_tool_use.json",
    "stop.json",
]

SIDECAR_FILES = [
    "session_complete.json",
    "session_no_turns.json",
]

# Expected per-event extra keys beyond the common {hook_event_name, cwd, session_id}.
EVENT_EXTRA_KEYS: dict[str, set[str]] = {
    "agentSpawn": set(),
    "userPromptSubmit": {"prompt"},
    "preToolUse": {"tool_name", "tool_input"},
    "postToolUse": {"tool_name", "tool_input", "tool_response"},
    "stop": {"assistant_response"},
}


# ---------------------------------------------------------------------------
# test_hook_events_match_kiro_schema
# ---------------------------------------------------------------------------


class TestHookEventsMatchKiroSchema:
    """Assert HOOK_EVENTS contains the exact camelCase event names Kiro accepts."""

    def test_hook_events_match_kiro_schema(self):
        from tracing.kiro.constants import HOOK_EVENTS

        assert HOOK_EVENTS == (
            "agentSpawn",
            "userPromptSubmit",
            "preToolUse",
            "postToolUse",
            "stop",
        )

    def test_hook_events_is_tuple(self):
        from tracing.kiro.constants import HOOK_EVENTS

        assert isinstance(HOOK_EVENTS, tuple)

    def test_hook_events_length(self):
        from tracing.kiro.constants import HOOK_EVENTS

        assert len(HOOK_EVENTS) == 5

    def test_harness_name(self):
        from tracing.kiro.constants import HARNESS_NAME

        assert HARNESS_NAME == "kiro"

    def test_display_name(self):
        from tracing.kiro.constants import DISPLAY_NAME

        assert DISPLAY_NAME == "Kiro"

    def test_hook_bin_name(self):
        from tracing.kiro.constants import HOOK_BIN_NAME

        assert HOOK_BIN_NAME == "arize-hook-kiro"

    def test_default_agent_name(self):
        from tracing.kiro.constants import DEFAULT_AGENT_NAME

        assert DEFAULT_AGENT_NAME == "arize-traced"

    def test_harness_home(self):
        from tracing.kiro.constants import HARNESS_HOME

        assert HARNESS_HOME == ".kiro"

    def test_harness_bin(self):
        from tracing.kiro.constants import HARNESS_BIN

        assert HARNESS_BIN == "kiro-cli"

    def test_kiro_agents_dir_is_under_home(self):
        from tracing.kiro.constants import KIRO_AGENTS_DIR

        assert isinstance(KIRO_AGENTS_DIR, Path)
        assert KIRO_AGENTS_DIR == Path.home() / ".kiro" / "agents"

    def test_kiro_sessions_dir_is_under_home(self):
        from tracing.kiro.constants import KIRO_SESSIONS_DIR

        assert isinstance(KIRO_SESSIONS_DIR, Path)
        assert KIRO_SESSIONS_DIR == Path.home() / ".kiro" / "sessions" / "cli"


# ---------------------------------------------------------------------------
# test_agent_skeleton_round_trips_through_kiro_validate
# ---------------------------------------------------------------------------


EXPECTED_SKELETON_KEYS = {
    "name",
    "description",
    "prompt",
    "mcpServers",
    "tools",
    "toolAliases",
    "allowedTools",
    "resources",
    "hooks",
    "toolsSettings",
    "includeMcpJson",
    "model",
}


class TestAgentSkeletonRoundTrips:
    """Write AGENT_SKELETON to a tmp file; assert it round-trips as valid JSON
    with all 12 expected top-level keys."""

    def test_agent_skeleton_round_trips(self, tmp_path):
        from tracing.kiro.constants import AGENT_SKELETON

        # Write with overridden name and empty hooks.
        skeleton = {**AGENT_SKELETON, "name": "probe-validate", "hooks": {}}
        out = tmp_path / "agent.json"
        out.write_text(json.dumps(skeleton))

        # Re-read and validate.
        loaded = json.loads(out.read_text())
        assert set(loaded.keys()) == EXPECTED_SKELETON_KEYS

    def test_agent_skeleton_has_all_keys(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert set(AGENT_SKELETON.keys()) == EXPECTED_SKELETON_KEYS

    def test_agent_skeleton_default_name(self):
        from tracing.kiro.constants import AGENT_SKELETON, DEFAULT_AGENT_NAME

        assert AGENT_SKELETON["name"] == DEFAULT_AGENT_NAME

    def test_agent_skeleton_hooks_is_empty_dict(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert AGENT_SKELETON["hooks"] == {}

    def test_agent_skeleton_tools_wildcard(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert AGENT_SKELETON["tools"] == ["*"]

    def test_agent_skeleton_include_mcp_json_true(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert AGENT_SKELETON["includeMcpJson"] is True

    def test_agent_skeleton_prompt_is_none(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert AGENT_SKELETON["prompt"] is None

    def test_agent_skeleton_model_is_none(self):
        from tracing.kiro.constants import AGENT_SKELETON

        assert AGENT_SKELETON["model"] is None


# ---------------------------------------------------------------------------
# test_probe_payload_fixtures_load
# ---------------------------------------------------------------------------


class TestProbePayloadFixturesLoad:
    """Each probe fixture loads as valid JSON with common and per-event keys."""

    @pytest.mark.parametrize("filename", PROBE_FILES)
    def test_fixture_is_valid_json(self, filename):
        path = PROBE_DIR / filename
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    @pytest.mark.parametrize("filename", PROBE_FILES)
    def test_fixture_has_common_keys(self, filename):
        data = json.loads((PROBE_DIR / filename).read_text())
        assert "hook_event_name" in data
        assert "cwd" in data
        assert "session_id" in data

    @pytest.mark.parametrize("filename", PROBE_FILES)
    def test_fixture_has_event_specific_keys(self, filename):
        data = json.loads((PROBE_DIR / filename).read_text())
        event = data["hook_event_name"]
        expected_extras = EVENT_EXTRA_KEYS[event]
        for key in expected_extras:
            assert key in data, f"Missing key '{key}' for event '{event}'"

    def test_agent_spawn_has_no_extras(self):
        data = json.loads((PROBE_DIR / "agent_spawn.json").read_text())
        common = {"hook_event_name", "cwd", "session_id"}
        assert set(data.keys()) == common

    def test_user_prompt_submit_prompt_value(self):
        data = json.loads((PROBE_DIR / "user_prompt_submit.json").read_text())
        assert isinstance(data["prompt"], str)
        assert len(data["prompt"]) > 0

    def test_pre_tool_use_tool_input_structure(self):
        data = json.loads((PROBE_DIR / "pre_tool_use.json").read_text())
        assert isinstance(data["tool_input"], dict)
        assert "operations" in data["tool_input"]

    def test_post_tool_use_has_tool_response(self):
        data = json.loads((PROBE_DIR / "post_tool_use.json").read_text())
        assert isinstance(data["tool_response"], dict)
        assert "items" in data["tool_response"]

    def test_stop_has_assistant_response(self):
        data = json.loads((PROBE_DIR / "stop.json").read_text())
        assert isinstance(data["assistant_response"], str)
        assert len(data["assistant_response"]) > 0

    def test_session_id_isolation(self):
        """Tool events use a different session_id than non-tool events."""
        spawn = json.loads((PROBE_DIR / "agent_spawn.json").read_text())
        pre = json.loads((PROBE_DIR / "pre_tool_use.json").read_text())
        assert spawn["session_id"] != pre["session_id"]

    def test_cwd_is_sanitized(self):
        """All fixtures use the sanitized test path."""
        for filename in PROBE_FILES:
            data = json.loads((PROBE_DIR / filename).read_text())
            assert data["cwd"] == "/tmp/test-project"


# ---------------------------------------------------------------------------
# test_sidecar_fixtures_load
# ---------------------------------------------------------------------------


class TestSidecarFixturesLoad:
    """Both sidecar fixtures parse and contain the expected structure."""

    @pytest.mark.parametrize("filename", SIDECAR_FILES)
    def test_sidecar_is_valid_json(self, filename):
        data = json.loads((SIDECAR_DIR / filename).read_text())
        assert isinstance(data, dict)

    @pytest.mark.parametrize("filename", SIDECAR_FILES)
    def test_sidecar_has_session_id(self, filename):
        data = json.loads((SIDECAR_DIR / filename).read_text())
        assert "session_id" in data

    @pytest.mark.parametrize("filename", SIDECAR_FILES)
    def test_sidecar_has_model_id(self, filename):
        data = json.loads((SIDECAR_DIR / filename).read_text())
        model_id = data["session_state"]["rts_model_state"]["model_info"]["model_id"]
        assert isinstance(model_id, str)
        assert len(model_id) > 0

    @pytest.mark.parametrize("filename", SIDECAR_FILES)
    def test_sidecar_has_turn_metadatas_list(self, filename):
        data = json.loads((SIDECAR_DIR / filename).read_text())
        turns = data["session_state"]["conversation_metadata"]["user_turn_metadatas"]
        assert isinstance(turns, list)

    def test_complete_sidecar_has_turns(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        turns = data["session_state"]["conversation_metadata"]["user_turn_metadatas"]
        assert len(turns) > 0

    def test_complete_sidecar_has_token_counts(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        turn = data["session_state"]["conversation_metadata"]["user_turn_metadatas"][0]
        assert "input_token_count" in turn
        assert "output_token_count" in turn
        assert turn["input_token_count"] > 0
        assert turn["output_token_count"] > 0

    def test_complete_sidecar_has_metering_usage(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        turn = data["session_state"]["conversation_metadata"]["user_turn_metadatas"][0]
        assert "metering_usage" in turn
        assert isinstance(turn["metering_usage"], list)
        assert len(turn["metering_usage"]) > 0
        for entry in turn["metering_usage"]:
            assert "value" in entry
            assert "unit" in entry

    def test_complete_sidecar_has_turn_duration(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        turn = data["session_state"]["conversation_metadata"]["user_turn_metadatas"][0]
        assert "turn_duration" in turn
        assert "secs" in turn["turn_duration"]
        assert "nanos" in turn["turn_duration"]

    def test_complete_sidecar_model_id(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        model_id = data["session_state"]["rts_model_state"]["model_info"]["model_id"]
        assert model_id == "claude-sonnet-4"

    def test_complete_sidecar_agent_name(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        assert data["session_state"]["agent_name"] == "arize-traced"

    def test_complete_sidecar_context_usage(self):
        data = json.loads((SIDECAR_DIR / "session_complete.json").read_text())
        pct = data["session_state"]["rts_model_state"]["context_usage_percentage"]
        assert isinstance(pct, (int, float))
        assert pct > 0

    def test_no_turns_sidecar_is_empty(self):
        data = json.loads((SIDECAR_DIR / "session_no_turns.json").read_text())
        turns = data["session_state"]["conversation_metadata"]["user_turn_metadatas"]
        assert turns == []

    def test_no_turns_sidecar_model_is_auto(self):
        data = json.loads((SIDECAR_DIR / "session_no_turns.json").read_text())
        model_id = data["session_state"]["rts_model_state"]["model_info"]["model_id"]
        assert model_id == "auto"

    def test_no_turns_sidecar_context_usage_zero(self):
        data = json.loads((SIDECAR_DIR / "session_no_turns.json").read_text())
        pct = data["session_state"]["rts_model_state"]["context_usage_percentage"]
        assert pct == 0.0
