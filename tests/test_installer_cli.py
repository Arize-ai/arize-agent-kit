"""Tests for core.installer.cli — the arize-install CLI entry point."""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixture: patch CONFIG_FILE everywhere it's imported as a local name
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_config_file(tmp_harness_dir, monkeypatch):
    """Ensure all modules that imported CONFIG_FILE from core.constants
    also see the monkeypatched temp path."""
    import core.config as _cfg
    import core.installer.cli as _cli
    cfg_path = tmp_harness_dir / "config.yaml"
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(_cli, "CONFIG_FILE", cfg_path)


from core.installer.cli import (
    EXIT_ERROR,
    EXIT_MISSING_ARGS,
    EXIT_OK,
    _collector_cmd,
    _resolve_backend,
    _resolve_user_id,
    _setup_cursor,
    _status,
    _uninstall,
    build_parser,
    main,
)


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


class TestBuildParser:
    """Test that build_parser() creates correct subcommands and flags."""

    def test_all_subcommands_registered(self):
        parser = build_parser()
        # Parse each subcommand with --help to verify registration
        for cmd in ("claude", "codex", "cursor", "uninstall", "status", "collector"):
            with pytest.raises(SystemExit) as exc:
                parser.parse_args([cmd, "--help"])
            assert exc.value.code == 0

    def test_claude_has_scope_flag(self):
        parser = build_parser()
        args = parser.parse_args(["claude", "--scope", "global", "--non-interactive", "--backend", "phoenix"])
        assert args.scope == "global"
        assert args.command == "claude"

    def test_claude_scope_default_is_local(self):
        parser = build_parser()
        args = parser.parse_args(["claude", "--non-interactive", "--backend", "phoenix"])
        assert args.scope == "local"

    def test_codex_has_no_scope_flag(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["codex", "--scope", "global"])

    def test_harness_common_flags(self):
        parser = build_parser()
        for cmd in ("claude", "codex", "cursor"):
            args = parser.parse_args([
                cmd,
                "--backend", "arize",
                "--api-key", "sk-test",
                "--space-id", "sp-123",
                "--otlp-endpoint", "custom:443",
                "--phoenix-endpoint", "http://custom:6006",
                "--user-id", "testuser",
                "--non-interactive",
            ])
            assert args.backend == "arize"
            assert args.api_key == "sk-test"
            assert args.space_id == "sp-123"
            assert args.otlp_endpoint == "custom:443"
            assert args.phoenix_endpoint == "http://custom:6006"
            assert args.user_id == "testuser"
            assert args.non_interactive is True

    def test_uninstall_flags(self):
        parser = build_parser()
        args = parser.parse_args(["uninstall", "--harness", "claude", "--non-interactive"])
        assert args.harness == "claude"
        assert args.non_interactive is True

    def test_uninstall_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["uninstall", "--all", "--non-interactive"])
        assert args.all is True

    def test_collector_action_choices(self):
        parser = build_parser()
        for action in ("start", "stop", "status", "restart"):
            args = parser.parse_args(["collector", action])
            assert args.action == action
            assert args.command == "collector"

    def test_collector_invalid_action_rejected(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["collector", "invalid"])

    def test_backend_choices_enforced(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["claude", "--backend", "invalid"])

    def test_no_subcommand_prints_help_and_exits(self):
        """main() should exit(2) when no subcommand is given."""
        with patch("sys.argv", ["arize-install"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == EXIT_MISSING_ARGS


# ---------------------------------------------------------------------------
# _resolve_backend
# ---------------------------------------------------------------------------


class TestResolveBackend:
    """Test _resolve_backend for non-interactive and interactive modes."""

    def test_non_interactive_arize_full(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="arize",
            api_key="sk-xxx",
            space_id="sp-1",
            otlp_endpoint="custom:443",
            phoenix_endpoint=None,
        )
        target, creds = _resolve_backend(args)
        assert target == "arize"
        assert creds["api_key"] == "sk-xxx"
        assert creds["space_id"] == "sp-1"
        assert creds["endpoint"] == "custom:443"

    def test_non_interactive_arize_default_endpoint(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="arize",
            api_key="sk-xxx",
            space_id="sp-1",
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        target, creds = _resolve_backend(args)
        assert creds["endpoint"] == "otlp.arize.com:443"

    def test_non_interactive_phoenix_full(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="phoenix",
            api_key=None,
            space_id=None,
            otlp_endpoint=None,
            phoenix_endpoint="http://custom:6006",
        )
        target, creds = _resolve_backend(args)
        assert target == "phoenix"
        assert creds["endpoint"] == "http://custom:6006"
        assert creds["api_key"] == ""

    def test_non_interactive_phoenix_default_endpoint(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="phoenix",
            api_key=None,
            space_id=None,
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        target, creds = _resolve_backend(args)
        assert creds["endpoint"] == "http://localhost:6006"

    def test_non_interactive_missing_backend_exits_2(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend=None,
            api_key=None,
            space_id=None,
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        with pytest.raises(SystemExit) as exc:
            _resolve_backend(args)
        assert exc.value.code == EXIT_MISSING_ARGS

    def test_non_interactive_arize_missing_api_key_exits_2(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="arize",
            api_key=None,
            space_id="sp-1",
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        with pytest.raises(SystemExit) as exc:
            _resolve_backend(args)
        assert exc.value.code == EXIT_MISSING_ARGS

    def test_non_interactive_arize_missing_space_id_exits_2(self):
        args = argparse.Namespace(
            non_interactive=True,
            backend="arize",
            api_key="sk-xxx",
            space_id=None,
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        with pytest.raises(SystemExit) as exc:
            _resolve_backend(args)
        assert exc.value.code == EXIT_MISSING_ARGS

    def test_interactive_delegates_to_prompt(self):
        args = argparse.Namespace(
            non_interactive=False,
            backend=None,
            api_key=None,
            space_id=None,
            otlp_endpoint=None,
            phoenix_endpoint=None,
        )
        mock_result = ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""})
        with patch("core.installer.cli.prompt_backend", return_value=mock_result) as mock_pb:
            target, creds = _resolve_backend(args)
            mock_pb.assert_called_once()
            assert target == "phoenix"


# ---------------------------------------------------------------------------
# _resolve_user_id
# ---------------------------------------------------------------------------


class TestResolveUserId:
    def test_non_interactive_with_flag(self):
        args = argparse.Namespace(non_interactive=True, user_id="alice")
        assert _resolve_user_id(args) == "alice"

    def test_non_interactive_without_flag(self):
        args = argparse.Namespace(non_interactive=True, user_id=None)
        assert _resolve_user_id(args) == ""

    def test_interactive_with_flag_skips_prompt(self):
        args = argparse.Namespace(non_interactive=False, user_id="bob")
        # Should use provided value without calling prompt
        with patch("core.installer.cli.prompt_user_id") as mock_p:
            result = _resolve_user_id(args)
            mock_p.assert_not_called()
            assert result == "bob"

    def test_interactive_without_flag_calls_prompt(self):
        args = argparse.Namespace(non_interactive=False, user_id=None)
        with patch("core.installer.cli.prompt_user_id", return_value="charlie") as mock_p:
            result = _resolve_user_id(args)
            mock_p.assert_called_once()
            assert result == "charlie"


# ---------------------------------------------------------------------------
# Status subcommand
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_outputs_valid_json(self, tmp_harness_dir, capsys):
        """status should print valid JSON with expected keys."""
        _status(argparse.Namespace())
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "config_file" in data
        assert "config_exists" in data
        assert "backend" in data
        assert "collector" in data
        assert "harnesses" in data
        assert "user_id" in data

    def test_status_with_sample_config(self, sample_config, capsys):
        """status should reflect config contents."""
        _status(argparse.Namespace())
        data = json.loads(capsys.readouterr().out)
        assert data["backend"] == "phoenix"
        assert "claude-code" in data["harnesses"]
        assert "codex" in data["harnesses"]
        assert "cursor" in data["harnesses"]

    def test_status_empty_config(self, tmp_harness_dir, capsys):
        """status with no config file should show empty state."""
        _status(argparse.Namespace())
        data = json.loads(capsys.readouterr().out)
        assert data["config_exists"] is False
        assert data["backend"] == ""
        assert data["harnesses"] == {}

    def test_status_collector_fields(self, tmp_harness_dir, capsys):
        """status collector section should have status, pid, address."""
        _status(argparse.Namespace())
        data = json.loads(capsys.readouterr().out)
        coll = data["collector"]
        assert "status" in coll
        assert "pid" in coll
        assert "address" in coll


# ---------------------------------------------------------------------------
# Uninstall subcommand
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_uninstall_no_args_exits_2(self, tmp_harness_dir):
        args = argparse.Namespace(harness=None, all=False, purge=False, non_interactive=True)
        with pytest.raises(SystemExit) as exc:
            _uninstall(args)
        assert exc.value.code == EXIT_MISSING_ARGS

    def test_uninstall_single_harness(self, sample_config, tmp_harness_dir):
        args = argparse.Namespace(harness="codex", all=False, purge=False, non_interactive=True)
        _uninstall(args)
        # Verify codex removed from config
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.codex") is None
        # Others remain
        assert get_value(config, "harnesses.claude-code") is not None
        assert get_value(config, "harnesses.cursor") is not None

    def test_uninstall_claude_maps_to_claude_code(self, sample_config, tmp_harness_dir):
        """'claude' CLI name should map to 'claude-code' config key."""
        args = argparse.Namespace(harness="claude", all=False, purge=False, non_interactive=True)
        _uninstall(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.claude-code") is None

    def test_uninstall_missing_harness_exits_1(self, tmp_harness_dir):
        """Uninstalling a harness that isn't configured should exit(1)."""
        # Write a config with no harnesses
        config_path = tmp_harness_dir / "config.yaml"
        config_path.write_text(yaml.safe_dump({"harnesses": {}}))

        args = argparse.Namespace(harness="codex", all=False, purge=False, non_interactive=True)
        with pytest.raises(SystemExit) as exc:
            _uninstall(args)
        assert exc.value.code == EXIT_ERROR

    def test_uninstall_all_non_interactive(self, sample_config, tmp_harness_dir):
        args = argparse.Namespace(harness=None, all=True, purge=False, non_interactive=True)
        with patch("core.installer.cli.collector_stop") as mock_stop:
            _uninstall(args)
            mock_stop.assert_called_once()
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses") == {}

    def test_uninstall_all_interactive_confirmed(self, sample_config, tmp_harness_dir):
        args = argparse.Namespace(harness=None, all=True, purge=False, non_interactive=False)
        with patch("builtins.input", return_value="y"):
            with patch("core.installer.cli.collector_stop"):
                _uninstall(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses") == {}

    def test_uninstall_all_interactive_cancelled(self, sample_config, tmp_harness_dir, capsys):
        args = argparse.Namespace(harness=None, all=True, purge=False, non_interactive=False)
        with patch("builtins.input", return_value="n"):
            _uninstall(args)
        # Config should be unchanged
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.claude-code") is not None

    def test_uninstall_single_interactive_cancelled(self, sample_config, tmp_harness_dir, capsys):
        args = argparse.Namespace(harness="codex", all=False, purge=False, non_interactive=False)
        with patch("builtins.input", return_value="n"):
            _uninstall(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.codex") is not None


# ---------------------------------------------------------------------------
# Collector subcommand
# ---------------------------------------------------------------------------


class TestCollectorCmd:
    def test_collector_start_success(self):
        args = argparse.Namespace(action="start")
        with patch("core.installer.cli.collector_start", return_value=True):
            with patch("core.installer.cli.collector_status", return_value=("running", 1234, "127.0.0.1:4318")):
                _collector_cmd(args)  # should not raise

    def test_collector_start_failure_exits_1(self):
        args = argparse.Namespace(action="start")
        with patch("core.installer.cli.collector_start", return_value=False):
            with pytest.raises(SystemExit) as exc:
                _collector_cmd(args)
            assert exc.value.code == EXIT_ERROR

    def test_collector_stop(self):
        args = argparse.Namespace(action="stop")
        with patch("core.installer.cli.collector_stop") as mock_stop:
            _collector_cmd(args)
            mock_stop.assert_called_once()

    def test_collector_status_running(self, capsys):
        args = argparse.Namespace(action="status")
        with patch("core.installer.cli.collector_status", return_value=("running", 5678, "127.0.0.1:4318")):
            _collector_cmd(args)
        out = capsys.readouterr().out
        assert "running" in out
        assert "5678" in out

    def test_collector_status_stopped(self, capsys):
        args = argparse.Namespace(action="status")
        with patch("core.installer.cli.collector_status", return_value=("stopped", None, None)):
            _collector_cmd(args)
        assert "stopped" in capsys.readouterr().out

    def test_collector_restart_success(self):
        args = argparse.Namespace(action="restart")
        with patch("core.installer.cli.collector_stop") as mock_stop:
            with patch("core.installer.cli.collector_start", return_value=True):
                with patch("core.installer.cli.collector_status", return_value=("running", 9999, "127.0.0.1:4318")):
                    _collector_cmd(args)
                    mock_stop.assert_called_once()

    def test_collector_restart_failure_exits_1(self):
        args = argparse.Namespace(action="restart")
        with patch("core.installer.cli.collector_stop"):
            with patch("core.installer.cli.collector_start", return_value=False):
                with pytest.raises(SystemExit) as exc:
                    _collector_cmd(args)
                assert exc.value.code == EXIT_ERROR


# ---------------------------------------------------------------------------
# Harness setup: cursor (simplest, no external file writes)
# ---------------------------------------------------------------------------


class TestSetupCursor:
    def test_cursor_non_interactive_phoenix(self, tmp_harness_dir):
        parser = build_parser()
        args = parser.parse_args([
            "cursor", "--backend", "phoenix", "--non-interactive",
        ])
        args.func(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.cursor.project_name") == "cursor"
        assert get_value(config, "backend.target") == "phoenix"

    def test_cursor_non_interactive_arize(self, tmp_harness_dir):
        parser = build_parser()
        args = parser.parse_args([
            "cursor", "--backend", "arize",
            "--api-key", "sk-test", "--space-id", "sp-test",
            "--non-interactive",
        ])
        args.func(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.cursor.project_name") == "cursor"
        assert get_value(config, "backend.target") == "arize"
        assert get_value(config, "backend.arize.api_key") == "sk-test"

    def test_cursor_with_user_id(self, tmp_harness_dir):
        parser = build_parser()
        args = parser.parse_args([
            "cursor", "--backend", "phoenix",
            "--user-id", "alice", "--non-interactive",
        ])
        args.func(args)
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "user_id") == "alice"


# ---------------------------------------------------------------------------
# main() entry point routing
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_routes_to_subcommand(self, tmp_harness_dir):
        """main() should parse argv and call the subcommand handler."""
        with patch("sys.argv", [
            "arize-install", "cursor",
            "--backend", "phoenix", "--non-interactive",
        ]):
            main()
        from core.config import load_config, get_value
        config = load_config()
        assert get_value(config, "harnesses.cursor.project_name") == "cursor"

    def test_main_keyboard_interrupt_exits_1(self):
        """KeyboardInterrupt during handler should exit(1)."""
        with patch("sys.argv", ["arize-install", "status"]):
            with patch("core.installer.cli._status", side_effect=KeyboardInterrupt):
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == EXIT_ERROR

    def test_main_eof_error_exits_1(self):
        """EOFError (e.g., piped stdin ended) should exit(1)."""
        with patch("sys.argv", ["arize-install", "status"]):
            with patch("core.installer.cli._status", side_effect=EOFError):
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == EXIT_ERROR


# ---------------------------------------------------------------------------
# Exit code constants
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_exit_code_values(self):
        assert EXIT_OK == 0
        assert EXIT_ERROR == 1
        assert EXIT_MISSING_ARGS == 2
