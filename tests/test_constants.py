"""Tests for core.constants module."""

from pathlib import Path

from core.constants import (
    BASE_DIR,
    BIN_DIR,
    CODEX_BUFFER_BIN,
    CODEX_BUFFER_LOG_FILE,
    CODEX_BUFFER_PID_FILE,
    CONFIG_FILE,
    DEFAULT_BUFFER_HOST,
    DEFAULT_BUFFER_PORT,
    HARNESSES,
    LOG_DIR,
    PID_DIR,
    STATE_BASE_DIR,
    VENV_DIR,
)


class TestPaths:
    """All exported path constants are Path objects with expected suffixes."""

    def test_all_paths_are_path_objects(self):
        for name, val in [
            ("BASE_DIR", BASE_DIR),
            ("CONFIG_FILE", CONFIG_FILE),
            ("PID_DIR", PID_DIR),
            ("CODEX_BUFFER_PID_FILE", CODEX_BUFFER_PID_FILE),
            ("LOG_DIR", LOG_DIR),
            ("CODEX_BUFFER_LOG_FILE", CODEX_BUFFER_LOG_FILE),
            ("BIN_DIR", BIN_DIR),
            ("CODEX_BUFFER_BIN", CODEX_BUFFER_BIN),
            ("VENV_DIR", VENV_DIR),
            ("STATE_BASE_DIR", STATE_BASE_DIR),
        ]:
            assert isinstance(val, Path), f"{name} should be a Path, got {type(val)}"

    def test_base_dir_ends_with_arize_harness(self):
        assert BASE_DIR.parts[-2:] == (".arize", "harness")

    def test_config_file_ends_with_config_yaml(self):
        assert CONFIG_FILE.name == "config.yaml"
        assert CONFIG_FILE.parent == BASE_DIR

    def test_pid_file_under_run(self):
        assert CODEX_BUFFER_PID_FILE.parent == PID_DIR
        assert CODEX_BUFFER_PID_FILE.name == "codex-buffer.pid"

    def test_state_base_dir_under_base(self):
        assert STATE_BASE_DIR.parent == BASE_DIR
        assert STATE_BASE_DIR.name == "state"


class TestNetworkDefaults:
    def test_default_host(self):
        assert DEFAULT_BUFFER_HOST == "127.0.0.1"

    def test_default_port(self):
        assert DEFAULT_BUFFER_PORT == 4318


class TestHarnesses:
    """HARNESSES dict has entries for all three supported harnesses."""

    EXPECTED_HARNESSES = ["claude-code", "codex", "cursor"]
    REQUIRED_KEYS = ["service_name", "scope_name", "state_subdir", "default_log_file"]

    def test_has_all_harnesses(self):
        for name in self.EXPECTED_HARNESSES:
            assert name in HARNESSES, f"Missing harness: {name}"

    def test_each_harness_has_required_keys(self):
        for name in self.EXPECTED_HARNESSES:
            entry = HARNESSES[name]
            for key in self.REQUIRED_KEYS:
                assert key in entry, f"Harness '{name}' missing key '{key}'"

    def test_default_log_file_is_path(self):
        for name, entry in HARNESSES.items():
            assert isinstance(entry["default_log_file"], Path), f"Harness '{name}' default_log_file should be a Path"

    def test_state_subdir_matches_key(self):
        for name, entry in HARNESSES.items():
            assert entry["state_subdir"] == name
