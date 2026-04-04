"""Tests for conftest fixtures and test infrastructure."""
import json
import urllib.request

import yaml

from tests.conftest import load_fixture


class TestTmpHarnessDir:
    """Verify the tmp_harness_dir fixture creates the expected directory tree."""

    EXPECTED_SUBDIRS = [
        "bin", "run", "logs",
        "state/claude-code", "state/codex", "state/cursor",
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
        assert "collector" in sample_config
        assert "backend" in sample_config
        assert "harnesses" in sample_config


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


class TestLoadFixture:
    """Verify load_fixture returns parsed dicts for all fixture files."""

    def test_claude_session_start(self):
        data = load_fixture("claude_session_start.json")
        assert data["session_id"] == "sess-abc123"
        assert "cwd" in data

    def test_claude_stop(self):
        data = load_fixture("claude_stop.json")
        assert data["session_id"] == "sess-abc123"
        assert "transcript_path" in data

    def test_codex_notify(self):
        data = load_fixture("codex_notify.json")
        assert data["type"] == "agent-turn-complete"
        assert data["thread-id"] == "thread-1"

    def test_cursor_before_submit(self):
        data = load_fixture("cursor_before_submit.json")
        assert data["hook_event_name"] == "beforeSubmitPrompt"

    def test_cursor_after_shell(self):
        data = load_fixture("cursor_after_shell.json")
        assert data["hook_event_name"] == "afterShellExecution"
        assert data["exit_code"] == "0"
