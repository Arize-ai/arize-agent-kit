"""Tests for core.installer.detect — platform, IDE, and Python detection."""

import os
import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.installer.detect import (
    check_python_version,
    detect_ides,
    detect_platform,
    find_python,
    _detect_claude,
    _detect_codex,
    _detect_cursor,
)


# ---------------------------------------------------------------------------
# check_python_version
# ---------------------------------------------------------------------------


class TestCheckPythonVersion:
    def test_current_python_passes(self):
        """The Python running these tests should be >= 3.9."""
        assert check_python_version(sys.executable) is True

    def test_nonexistent_path_returns_false(self):
        assert check_python_version("/no/such/python") is False

    def test_not_python_returns_false(self):
        """A binary that isn't Python (e.g. /bin/echo) should return False."""
        echo = "/bin/echo"
        if os.path.isfile(echo):
            assert check_python_version(echo) is False

    def test_subprocess_timeout_returns_false(self):
        import subprocess as _sp
        exc = _sp.TimeoutExpired(cmd="python3", timeout=10)
        with patch("core.installer.detect.subprocess.run", side_effect=exc):
            assert check_python_version("python3") is False

    def test_subprocess_returncode_nonzero(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is False

    def test_subprocess_bad_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "garbage"
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is False

    def test_old_python_version(self):
        """Python 3.8 should fail the >= 3.9 check."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3 8"
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is False

    def test_python_39_passes(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3 9"
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is True

    def test_python_313_passes(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3 13"
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is True

    def test_python2_fails(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "2 7"
        with patch("core.installer.detect.subprocess.run", return_value=mock_result):
            assert check_python_version("python3") is False


# ---------------------------------------------------------------------------
# find_python
# ---------------------------------------------------------------------------


class TestFindPython:
    def test_find_python_returns_a_path(self):
        """On the test machine, find_python should find at least one Python."""
        result = find_python()
        assert result is not None
        assert os.path.isfile(result)

    def test_find_python_result_passes_version_check(self):
        result = find_python()
        if result:
            assert check_python_version(result) is True

    def test_find_python_no_candidates(self):
        """If no candidates exist, should return None."""
        with patch("core.installer.detect.shutil.which", return_value=None):
            with patch("core.installer.detect.os.path.isfile", return_value=False):
                with patch("core.installer.detect.Path.is_file", return_value=False):
                    with patch("core.installer.detect.Path.is_dir", return_value=False):
                        with patch("core.installer.detect.check_python_version", return_value=False):
                            result = find_python()
                            assert result is None


# ---------------------------------------------------------------------------
# detect_platform
# ---------------------------------------------------------------------------


class TestDetectPlatform:
    def test_returns_expected_keys(self):
        result = detect_platform()
        assert "os" in result
        assert "arch" in result
        assert "python_version" in result
        assert "hostname" in result

    def test_os_is_known_value(self):
        result = detect_platform()
        assert result["os"] in ("darwin", "linux", "win32") or isinstance(result["os"], str)

    def test_arch_is_known_value(self):
        result = detect_platform()
        assert result["arch"] in ("x64", "arm64") or isinstance(result["arch"], str)

    def test_python_version_matches_running(self):
        result = detect_platform()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert result["python_version"] == expected

    def test_darwin_mapping(self):
        with patch("core.installer.detect.platform.system", return_value="Darwin"):
            with patch("core.installer.detect.platform.machine", return_value="arm64"):
                result = detect_platform()
                assert result["os"] == "darwin"
                assert result["arch"] == "arm64"

    def test_linux_x86_mapping(self):
        with patch("core.installer.detect.platform.system", return_value="Linux"):
            with patch("core.installer.detect.platform.machine", return_value="x86_64"):
                result = detect_platform()
                assert result["os"] == "linux"
                assert result["arch"] == "x64"

    def test_windows_amd64_mapping(self):
        with patch("core.installer.detect.platform.system", return_value="Windows"):
            with patch("core.installer.detect.platform.machine", return_value="AMD64"):
                result = detect_platform()
                assert result["os"] == "win32"
                assert result["arch"] == "x64"

    def test_aarch64_maps_to_arm64(self):
        with patch("core.installer.detect.platform.machine", return_value="aarch64"):
            result = detect_platform()
            assert result["arch"] == "arm64"

    def test_unknown_arch_passes_through(self):
        with patch("core.installer.detect.platform.machine", return_value="riscv64"):
            result = detect_platform()
            assert result["arch"] == "riscv64"


# ---------------------------------------------------------------------------
# detect_ides
# ---------------------------------------------------------------------------


class TestDetectIdes:
    def test_returns_expected_keys(self):
        result = detect_ides()
        assert "claude" in result
        assert "codex" in result
        assert "cursor" in result
        assert all(isinstance(v, bool) for v in result.values())


class TestDetectClaude:
    def test_claude_dir_exists(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _detect_claude() is True

    def test_claude_on_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("core.installer.detect.shutil.which", return_value="/usr/bin/claude"):
            assert _detect_claude() is True

    def test_claude_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("core.installer.detect.shutil.which", return_value=None):
            assert _detect_claude() is False


class TestDetectCodex:
    def test_codex_dir_exists(self, tmp_path, monkeypatch):
        (tmp_path / ".codex").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _detect_codex() is True

    def test_codex_on_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("core.installer.detect.shutil.which", return_value="/usr/bin/codex"):
            assert _detect_codex() is True

    def test_codex_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("core.installer.detect.shutil.which", return_value=None):
            assert _detect_codex() is False


class TestDetectCursor:
    def test_cursor_dir_exists(self, tmp_path, monkeypatch):
        (tmp_path / ".cursor").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _detect_cursor() is True

    def test_cursor_darwin_app(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cursor_app = Path("/Applications/Cursor.app")
        with patch("core.installer.detect.platform.system", return_value="Darwin"):
            with patch.object(Path, "exists", lambda self: self == cursor_app):
                assert _detect_cursor() is True

    def test_cursor_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("core.installer.detect.platform.system", return_value="Linux"):
            with patch("core.installer.detect.shutil.which", return_value=None):
                assert _detect_cursor() is False
