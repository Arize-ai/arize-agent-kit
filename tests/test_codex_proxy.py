#!/usr/bin/env python3
"""Tests for core.hooks.codex.proxy — the Codex proxy wrapper."""

import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

from core.hooks.codex.proxy import _find_real_codex, _load_env_file, main


# ---------------------------------------------------------------------------
# _find_real_codex tests
# ---------------------------------------------------------------------------

class TestFindRealCodex:
    """Tests for _find_real_codex PATH scanning."""

    def test_finds_codex_on_path(self, tmp_path):
        """A real codex binary on PATH is returned."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            result = _find_real_codex()

        assert result is not None
        assert os.path.realpath(result) == os.path.realpath(str(codex))

    def test_skips_self_path(self, tmp_path):
        """Entries resolving to the proxy module itself are skipped."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # Create a symlink pointing at our own module file
        proxy_link = bin_dir / "codex"
        proxy_link.symlink_to(Path(__file__).resolve().parent.parent / "core" / "hooks" / "codex" / "proxy.py")

        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            result = _find_real_codex()

        assert result is None

    def test_skips_self_argv0(self, tmp_path):
        """Entries resolving to sys.argv[0] are skipped."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        # Make sys.argv[0] resolve to the same file
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}), \
             mock.patch.object(sys, "argv", [str(codex)]):
            result = _find_real_codex()

        assert result is None

    def test_returns_none_when_no_codex(self, tmp_path):
        """Returns None when PATH has no codex binary."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with mock.patch.dict(os.environ, {"PATH": str(empty_dir)}):
            result = _find_real_codex()

        assert result is None

    def test_skips_non_executable(self, tmp_path):
        """Files that aren't executable are skipped."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("not executable")
        # Don't set executable bit

        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            result = _find_real_codex()

        assert result is None

    def test_picks_first_match(self, tmp_path):
        """When multiple codex binaries exist, the first one wins."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        for d in (dir_a, dir_b):
            codex = d / "codex"
            codex.write_text("#!/bin/sh\nexit 0\n")
            codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        path_str = os.pathsep.join([str(dir_a), str(dir_b)])
        with mock.patch.dict(os.environ, {"PATH": path_str}):
            result = _find_real_codex()

        assert result is not None
        assert os.path.realpath(result) == os.path.realpath(str(dir_a / "codex"))


# ---------------------------------------------------------------------------
# _load_env_file tests
# ---------------------------------------------------------------------------

class TestLoadEnvFile:
    """Tests for _load_env_file."""

    def test_loads_simple_vars(self, tmp_path):
        env_file = tmp_path / "env.sh"
        env_file.write_text("FOO=bar\nexport BAZ=qux\n")

        with mock.patch.dict(os.environ, {}, clear=True):
            _load_env_file(env_file)
            assert os.environ["FOO"] == "bar"
            assert os.environ["BAZ"] == "qux"

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / "env.sh"
        env_file.write_text('SINGLE=\'hello\'\nDOUBLE="world"\n')

        with mock.patch.dict(os.environ, {}, clear=True):
            _load_env_file(env_file)
            assert os.environ["SINGLE"] == "hello"
            assert os.environ["DOUBLE"] == "world"

    def test_skips_comments_and_blanks(self, tmp_path):
        env_file = tmp_path / "env.sh"
        env_file.write_text("# comment\n\nKEY=val\n")

        with mock.patch.dict(os.environ, {}, clear=True):
            _load_env_file(env_file)
            assert os.environ.get("KEY") == "val"
            assert "#" not in "".join(os.environ.keys())

    def test_missing_file_no_error(self, tmp_path):
        """Missing env file is silently ignored."""
        _load_env_file(tmp_path / "nonexistent")
        # No exception raised


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the main() entry point."""

    def test_load_env_before_buffer_ensure(self, tmp_path):
        """Env file is loaded before buffer_ensure is called."""
        call_order = []

        env_file = tmp_path / ".codex" / "arize-env.sh"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("TRACED=1\n")

        original_load = _load_env_file

        def tracking_load(path):
            call_order.append("load_env")
            original_load(path)

        def fake_ensure():
            call_order.append("buffer_ensure")

        # Create a fake codex binary so main() can find it
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        with mock.patch("os.path.expanduser", return_value=str(tmp_path)), \
             mock.patch("core.hooks.codex.proxy._load_env_file", side_effect=tracking_load), \
             mock.patch("core.hooks.codex.proxy._quick_health_check", return_value=False), \
             mock.patch("core.codex_buffer_ctl.buffer_ensure", side_effect=fake_ensure), \
             mock.patch("core.hooks.codex.proxy._find_real_codex", return_value=str(codex)), \
             mock.patch("os.execvp"):
            main()

        assert call_order == ["load_env", "buffer_ensure"]

    def test_buffer_ensure_failure_still_execs(self, tmp_path):
        """If buffer_ensure raises, the real codex is still exec'd."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        with mock.patch("core.hooks.codex.proxy._quick_health_check", return_value=False), \
             mock.patch("core.codex_buffer_ctl.buffer_ensure", side_effect=RuntimeError("boom")), \
             mock.patch("core.hooks.codex.proxy._find_real_codex", return_value=str(codex)), \
             mock.patch("os.execvp") as mock_exec:
            main()

        mock_exec.assert_called_once()
        assert str(codex) in mock_exec.call_args[0]

    def test_no_codex_found_exits_1(self):
        """When no real codex is found, exit with code 1."""
        with mock.patch("core.codex_buffer_ctl.buffer_ensure"), \
             mock.patch("core.hooks.codex.proxy._find_real_codex", return_value=None), \
             pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_missing_env_file_proceeds(self, tmp_path):
        """If the env file doesn't exist, main proceeds normally."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        with mock.patch("core.codex_buffer_ctl.buffer_ensure"), \
             mock.patch("core.hooks.codex.proxy._find_real_codex", return_value=codex), \
             mock.patch("os.execvp") as mock_exec:
            # Default home won't have .codex/arize-env.sh
            main()

        mock_exec.assert_called_once()

    def test_windows_uses_subprocess_run(self, tmp_path):
        """On Windows (os.name == 'nt'), subprocess.run is used instead of execvp."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

        fake_result = mock.Mock()
        fake_result.returncode = 42

        with mock.patch("core.hooks.codex.proxy._quick_health_check", return_value=True), \
             mock.patch("core.hooks.codex.proxy._find_real_codex", return_value=str(codex)), \
             mock.patch("os.name", "nt"), \
             mock.patch("subprocess.run", return_value=fake_result) as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            main()

        mock_run.assert_called_once()
        assert str(codex) == mock_run.call_args[0][0][0]
        assert exc_info.value.code == 42
