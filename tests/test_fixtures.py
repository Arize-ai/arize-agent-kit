"""Tests for conftest fixtures and test infrastructure."""

import json
import urllib.request

import yaml


class TestTmpHarnessDir:
    """Verify the tmp_harness_dir fixture creates the expected directory tree."""

    EXPECTED_SUBDIRS = [
        "bin",
        "run",
        "logs",
        "state/claude-code",
        "state/codex",
        "state/cursor",
    ]

    def test_creates_all_subdirs(self, tmp_harness_dir):
        for subdir in self.EXPECTED_SUBDIRS:
            path = tmp_harness_dir / subdir
            assert path.is_dir(), f"Expected directory {subdir} to exist"

    def test_monkeypatches_constants(self, tmp_harness_dir):
        import core.constants as c

        assert c.BASE_DIR == tmp_harness_dir
        assert c.CONFIG_FILE == tmp_harness_dir / "config.yaml"
        assert c.STATE_BASE_DIR == tmp_harness_dir / "state"


class TestSampleConfig:
    """Verify sample_config fixture writes valid YAML."""

    def test_round_trips_through_yaml(self, sample_config, tmp_harness_dir):
        config_path = tmp_harness_dir / "config.yaml"
        assert config_path.exists()
        with open(config_path) as f:
            loaded = yaml.safe_load(f)
        assert loaded == sample_config

    def test_has_expected_sections(self, sample_config):
        assert "harnesses" in sample_config
        assert "claude-code" in sample_config["harnesses"]
        assert "codex" in sample_config["harnesses"]
        assert "cursor" in sample_config["harnesses"]
        assert "collector" in sample_config["harnesses"]["codex"]
        # Old top-level keys must NOT be present
        assert "backend" not in sample_config
        assert "collector" not in sample_config


class TestMockCollector:
    """Verify mock_collector accepts POST and responds to GET /health."""

    def test_health_endpoint(self, mock_collector):
        req = urllib.request.Request(f"{mock_collector['url']}/health")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["status"] == "ok"

    def test_post_records_body(self, mock_collector):
        payload = {"spans": [{"name": "test-span"}]}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{mock_collector['url']}/v1/spans",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
        assert len(mock_collector["received"]) == 1
        assert mock_collector["received"][0] == payload


class TestFixtureData:
    """Verify inline fixture data has expected shape."""

    def test_claude_session_start(self, claude_session_start_input):
        assert claude_session_start_input["session_id"] == "sess-abc123"
        assert "cwd" in claude_session_start_input

    def test_claude_stop(self, claude_stop_input):
        assert claude_stop_input["session_id"] == "sess-abc123"
        assert "transcript_path" in claude_stop_input

    def test_codex_notify(self, codex_notify_input):
        assert codex_notify_input["type"] == "agent-turn-complete"
        assert codex_notify_input["thread-id"] == "thread-1"

    def test_cursor_before_submit(self, cursor_before_submit_input):
        assert cursor_before_submit_input["hook_event_name"] == "beforeSubmitPrompt"

    def test_cursor_after_shell(self, cursor_after_shell_input):
        assert cursor_after_shell_input["hook_event_name"] == "afterShellExecution"
        assert cursor_after_shell_input["exit_code"] == "0"

    def test_transcript_file(self, transcript_file):
        from pathlib import Path

        p = Path(transcript_file)
        assert p.exists()
        lines = p.read_text().strip().splitlines()
        assert len(lines) == 3
