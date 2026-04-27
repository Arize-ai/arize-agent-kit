"""Integration tests for codex buffer lifecycle with stale daemon eviction."""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
import yaml


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="signal/lsof are POSIX-only")


def _wait_for_health(host, port, timeout=5.0):
    """Poll /health until it responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            url = f"http://{host}:{port}/health"
            urllib.request.urlopen(url, timeout=1.0)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _get_health_json(host, port):
    """GET /health and return parsed JSON."""
    import json

    url = f"http://{host}:{port}/health"
    resp = urllib.request.urlopen(url, timeout=2.0)
    return json.loads(resp.read())


@pytest.fixture
def free_port():
    """Pick a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestStaleBufferEviction:
    @pytest.mark.timeout(15)
    def test_start_evicts_stale_buffer_from_deleted_worktree(
        self, tmp_path, free_port, monkeypatch
    ):
        """End-to-end: a buffer from a deleted worktree is evicted and replaced."""
        import codex_tracing.codex_buffer_ctl as ctl
        import core.constants as c

        port = free_port
        host = "127.0.0.1"

        # Set up temp harness dirs
        base = tmp_path / ".arize" / "harness"
        for subdir in ["bin", "run", "logs"]:
            (base / subdir).mkdir(parents=True)

        monkeypatch.setattr(c, "BASE_DIR", base)
        monkeypatch.setattr(c, "CONFIG_FILE", base / "config.yaml")
        monkeypatch.setattr(c, "PID_DIR", base / "run")
        monkeypatch.setattr(c, "CODEX_BUFFER_PID_FILE", base / "run" / "codex-buffer.pid")
        monkeypatch.setattr(c, "LOG_DIR", base / "logs")
        monkeypatch.setattr(c, "CODEX_BUFFER_LOG_FILE", base / "logs" / "codex-buffer.log")
        monkeypatch.setattr(c, "BIN_DIR", base / "bin")
        monkeypatch.setattr(c, "CODEX_BUFFER_BIN", base / "bin" / "arize-codex-buffer")

        # Patch ctl's local bindings
        monkeypatch.setattr(ctl, "CODEX_BUFFER_PID_FILE", c.CODEX_BUFFER_PID_FILE)
        monkeypatch.setattr(ctl, "PID_DIR", c.PID_DIR)
        monkeypatch.setattr(ctl, "CONFIG_FILE", c.CONFIG_FILE)
        monkeypatch.setattr(ctl, "CODEX_BUFFER_BIN", c.CODEX_BUFFER_BIN)
        monkeypatch.setattr(ctl, "CODEX_BUFFER_LOG_FILE", c.CODEX_BUFFER_LOG_FILE)
        monkeypatch.setattr(ctl, "LOG_DIR", c.LOG_DIR)

        # Write config
        config = {
            "harnesses": {
                "codex": {
                    "project_name": "codex",
                    "collector": {"host": host, "port": port},
                },
            },
        }
        with open(base / "config.yaml", "w") as f:
            yaml.safe_dump(config, f)

        # Read the real codex_buffer.py source and prepare a patched version
        real_buffer = os.path.join(os.path.dirname(__file__), "..", "codex_tracing", "codex_buffer.py")
        real_buffer = os.path.abspath(real_buffer)
        real_src = open(real_buffer).read()
        patched_src = real_src.replace(
            'BASE_DIR = os.path.expanduser("~/.arize/harness")',
            f'BASE_DIR = "{base}"',
        )

        # Create fake worktree with a copy
        fake_worktree = tmp_path / "fake_worktree"
        fake_worktree.mkdir()
        (fake_worktree / "codex_buffer.py").write_text(patched_src)

        # Also create a "canonical" copy that buffer_start() will spawn.
        # Point ctl.__file__ to this location so buffer_start finds it.
        canonical_dir = tmp_path / "canonical_codex_tracing"
        canonical_dir.mkdir()
        (canonical_dir / "codex_buffer.py").write_text(patched_src)
        monkeypatch.setattr(ctl, "__file__", str(canonical_dir / "codex_buffer_ctl.py"))

        # Spawn the fake worktree buffer
        proc = subprocess.Popen(
            [sys.executable, str(fake_worktree / "codex_buffer.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        try:
            # Wait for it to come up
            assert _wait_for_health(host, port, timeout=5.0), "Fake buffer did not start"

            # Verify it's running from the fake worktree
            health = _get_health_json(host, port)
            assert "codex_buffer.py" in health.get("build_path", "")
            assert "fake_worktree" in health.get("build_path", "")

            # Simulate worktree deletion
            shutil.rmtree(fake_worktree)

            # Remove any pidfile the fake buffer wrote (simulate orphaning)
            pid_file = base / "run" / "codex-buffer.pid"
            if pid_file.exists():
                pid_file.unlink()

            # Now call buffer_start — it should evict the stale daemon and start a new one
            from codex_tracing.codex_buffer_ctl import buffer_start, buffer_stop

            ok = buffer_start()
            assert ok is True

            # The original subprocess should have exited
            exit_code = proc.wait(timeout=10)
            assert exit_code is not None

            # The port should now be served by a new process with the canonical build_path
            assert _wait_for_health(host, port, timeout=5.0), "New buffer did not start"
            new_health = _get_health_json(host, port)
            assert new_health["build_path"].endswith("codex_buffer.py")
            assert "fake_worktree" not in new_health["build_path"]

            # Cleanup
            result = buffer_stop()
            assert result == "stopped"

        except Exception:
            # Make sure we clean up the stale process on failure
            proc.kill()
            proc.wait()
            raise
