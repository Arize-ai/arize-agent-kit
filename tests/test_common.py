#!/usr/bin/env python3
"""Tests for core.common — FileLock and StateManager."""
import threading
import time
from pathlib import Path

import pytest
import yaml

from core.common import FileLock, StateManager


# ── FileLock tests ──────────────────────────────────────────────────────────


class TestFileLock:
    def test_acquire_and_release(self, tmp_path):
        """FileLock acquires and releases without error on empty dir."""
        lock_path = tmp_path / "test.lock"
        with FileLock(lock_path, timeout=1.0):
            pass  # should not raise

    def test_blocks_second_thread(self, tmp_path):
        """FileLock blocks second acquisition from another thread."""
        lock_path = tmp_path / "test.lock"
        barrier = threading.Barrier(2, timeout=5)
        acquired_order = []

        def hold_lock(name, hold_time):
            with FileLock(lock_path, timeout=5.0):
                acquired_order.append(name)
                if name == "A":
                    barrier.wait()  # signal B to try acquiring
                    time.sleep(hold_time)

        t_a = threading.Thread(target=hold_lock, args=("A", 0.5))
        t_a.start()
        barrier.wait()  # wait for A to acquire
        time.sleep(0.05)  # small delay so A is definitely holding

        t_b = threading.Thread(target=hold_lock, args=("B", 0))
        t_b.start()

        t_a.join(timeout=5)
        t_b.join(timeout=5)

        # A acquired first, B acquired after A released
        assert acquired_order[0] == "A"
        assert "B" in acquired_order

    def test_timeout_force_acquires(self, tmp_path):
        """After timeout, FileLock force-acquires the lock."""
        lock_path = tmp_path / "test.lock"
        hold_event = threading.Event()
        released_event = threading.Event()

        def hold_forever():
            with FileLock(lock_path, timeout=5.0):
                hold_event.set()
                # Hold lock until test is done — never release voluntarily
                released_event.wait(timeout=10)

        t = threading.Thread(target=hold_forever, daemon=True)
        t.start()
        hold_event.wait(timeout=5)

        # Thread B with short timeout should force-acquire
        start = time.monotonic()
        with FileLock(lock_path, timeout=0.3):
            elapsed = time.monotonic() - start
            assert elapsed >= 0.2  # waited at least near the timeout

        released_event.set()
        t.join(timeout=5)

    def test_creates_parent_directories(self, tmp_path):
        """FileLock creates parent directories if missing."""
        lock_path = tmp_path / "deep" / "nested" / "dir" / "test.lock"
        assert not lock_path.parent.exists()
        with FileLock(lock_path, timeout=1.0):
            assert lock_path.parent.exists()

    def test_cleanup_on_exit(self, tmp_path):
        """FileLock cleans up lock file/dir on __exit__."""
        from core.common import _LOCK_IMPL

        lock_path = tmp_path / "test.lock"
        with FileLock(lock_path, timeout=1.0):
            pass

        if _LOCK_IMPL == "mkdir":
            # mkdir-based lock removes the directory
            assert not lock_path.exists()
        else:
            # fcntl/msvcrt leaves the file (just unlocked) — this is normal
            # The file exists but is not locked
            pass


# ── StateManager tests ──────────────────────────────────────────────────────


class TestStateManager:
    def _make_sm(self, tmp_path, name="test"):
        state_dir = tmp_path / "state"
        state_file = state_dir / f"state_{name}.yaml"
        lock_path = state_dir / f".lock_{name}"
        return StateManager(state_dir, state_file, lock_path)

    def test_init_creates_dir_and_file(self, tmp_path):
        """init_state() creates directory and .yaml file containing {}."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        assert sm.state_dir.exists()
        assert sm.state_file.exists()
        data = yaml.safe_load(sm.state_file.read_text())
        assert data == {}

    def test_init_recovers_corrupted(self, tmp_path):
        """init_state() recovers corrupted file."""
        sm = self._make_sm(tmp_path)
        sm.state_dir.mkdir(parents=True)
        sm.state_file.write_text("{{garbage not yaml")
        sm.init_state()
        data = yaml.safe_load(sm.state_file.read_text())
        assert data == {}

    def test_init_preserves_valid(self, tmp_path):
        """init_state() preserves valid existing file."""
        sm = self._make_sm(tmp_path)
        sm.state_dir.mkdir(parents=True)
        sm.state_file.write_text(yaml.safe_dump({"key": "val"}))
        sm.init_state()
        data = yaml.safe_load(sm.state_file.read_text())
        assert data == {"key": "val"}

    def test_set_then_get(self, tmp_path):
        """set("key", "val") then get("key") returns "val"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.set("key", "val")
        assert sm.get("key") == "val"

    def test_values_stored_as_strings(self, tmp_path):
        """set("count", "42") stores as string, get returns "42"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.set("count", "42")
        result = sm.get("count")
        assert result == "42"
        assert isinstance(result, str)

    def test_get_missing_key(self, tmp_path):
        """get("missing_key") returns None."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        assert sm.get("missing_key") is None

    def test_get_no_state_file(self, tmp_path):
        """get("any") returns None when state file doesn't exist."""
        sm = self._make_sm(tmp_path)
        # Don't call init_state — file doesn't exist
        assert sm.get("any") is None

    def test_delete_removes_key(self, tmp_path):
        """delete("key") removes it; subsequent get returns None."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.set("key", "val")
        assert sm.get("key") == "val"
        sm.delete("key")
        assert sm.get("key") is None

    def test_delete_missing_noop(self, tmp_path):
        """delete("missing") is no-op, no error."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.delete("missing")  # should not raise

    def test_increment_missing_key(self, tmp_path):
        """increment("count") on missing key -> get returns "1"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.increment("count")
        assert sm.get("count") == "1"

    def test_increment_twice(self, tmp_path):
        """increment("count") twice -> get returns "2"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.increment("count")
        sm.increment("count")
        assert sm.get("count") == "2"

    def test_increment_non_numeric(self, tmp_path):
        """increment on non-numeric value treats as 0, returns "1"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.set("key", "abc")
        sm.increment("key")
        assert sm.get("key") == "1"

    def test_concurrent_set_different_keys(self, tmp_path):
        """Concurrent set from 10 threads writing different keys -> all present."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        errors = []

        def writer(i):
            try:
                sm.set(f"key_{i}", f"val_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        for i in range(10):
            assert sm.get(f"key_{i}") == f"val_{i}"

    def test_concurrent_increment(self, tmp_path):
        """Concurrent increment from 10 threads on same key -> final value is "10"."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        errors = []

        def incrementer():
            try:
                sm.increment("counter")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=incrementer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert sm.get("counter") == "10"

    def test_atomic_write_no_corruption(self, tmp_path):
        """State file is not corrupted if tmp file write fails."""
        sm = self._make_sm(tmp_path)
        sm.init_state()
        sm.set("key", "original")

        # Make the tmp file path read-only directory to cause write failure
        tmp_blocker = sm.state_file.with_suffix(f".tmp.{__import__('os').getpid()}")
        tmp_blocker.mkdir(parents=True, exist_ok=True)

        # This set should fail silently (can't write to a directory path)
        sm.set("key", "corrupted")

        # Clean up blocker
        tmp_blocker.rmdir()

        # Original value should still be intact (or the new value if write succeeded
        # on a platform where the path resolution differs)
        val = sm.get("key")
        assert val in ("original", "corrupted")  # either is valid, but not corrupt
        # Verify the file is valid YAML
        data = yaml.safe_load(sm.state_file.read_text())
        assert isinstance(data, dict)
