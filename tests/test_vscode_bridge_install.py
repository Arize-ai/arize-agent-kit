"""Tests for core.vscode_bridge.install."""

from __future__ import annotations

import types
from unittest import mock

import pytest

from core.vscode_bridge.install import install, uninstall
from core.vscode_bridge.models import HARNESS_KEYS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arize_backend():
    return {
        "target": "arize",
        "endpoint": "https://otlp.arize.com",
        "api_key": "test-key",
        "space_id": "space-123",
    }


def _phoenix_backend():
    return {
        "target": "phoenix",
        "endpoint": "http://localhost:6006",
        "api_key": "",
        "space_id": None,
    }


def _base_request(harness="claude-code", **overrides):
    req = {
        "harness": harness,
        "backend": _arize_backend(),
        "project_name": "my-project",
        "user_id": "user-1",
        "with_skills": False,
        "logging": None,
    }
    req.update(overrides)
    return req


def _fake_module(install_msg="installed", uninstall_msg="uninstalled"):
    """Return a module-like object with install/uninstall_noninteractive."""

    def _install(**kwargs):
        print(install_msg)

    def _uninstall():
        print(uninstall_msg)

    mod = types.ModuleType("fake_install")
    mod.install_noninteractive = _install
    mod.uninstall_noninteractive = _uninstall
    return mod


# ---------------------------------------------------------------------------
# Install — success path per harness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("harness", list(HARNESS_KEYS))
def test_install_success_per_harness(harness):
    fake = _fake_module(install_msg=f"{harness} ok")
    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = install(_base_request(harness=harness))

    assert result["success"] is True
    assert result["error"] is None
    assert result["harness"] == harness
    assert any(f"{harness} ok" in line for line in result["logs"])


# ---------------------------------------------------------------------------
# Install — unknown harness
# ---------------------------------------------------------------------------


def test_install_unknown_harness():
    result = install(_base_request(harness="vim"))
    assert result["success"] is False
    assert result["error"] == "unknown_harness"
    assert result["harness"] is None


# ---------------------------------------------------------------------------
# Install — missing space_id on arize
# ---------------------------------------------------------------------------


def test_install_arize_missing_space_id():
    backend = _arize_backend()
    backend["space_id"] = None
    result = install(_base_request(backend=backend))
    assert result["success"] is False
    assert result["error"] == "missing_credentials"


def test_install_invalid_target():
    backend = _arize_backend()
    backend["target"] = "unknown-target"
    result = install(_base_request(backend=backend))
    assert result["success"] is False
    assert result["error"] == "missing_credentials"


# ---------------------------------------------------------------------------
# Install — phoenix backend (no space_id required)
# ---------------------------------------------------------------------------


def test_install_phoenix_backend():
    fake = _fake_module()
    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = install(_base_request(backend=_phoenix_backend()))
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Install — exception from underlying installer
# ---------------------------------------------------------------------------


def test_install_exception_captured():
    def _boom(**kwargs):
        raise RuntimeError("disk full")

    fake = _fake_module()
    fake.install_noninteractive = _boom

    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = install(_base_request())

    assert result["success"] is False
    assert result["error"] == "install_failed"
    assert result["harness"] == "claude-code"
    assert any("disk full" in line for line in result["logs"])


# ---------------------------------------------------------------------------
# Install — logs captured from stdout/stderr
# ---------------------------------------------------------------------------


def test_install_logs_captured():
    import sys

    def _chatty(**kwargs):
        print("line-1")
        print("line-2", file=sys.stderr)

    fake = _fake_module()
    fake.install_noninteractive = _chatty

    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = install(_base_request())

    assert result["success"] is True
    assert "line-1" in result["logs"]
    assert "line-2" in result["logs"]


# ---------------------------------------------------------------------------
# Install — credentials passed correctly (target stripped)
# ---------------------------------------------------------------------------


def test_install_passes_correct_kwargs():
    captured = {}

    def _spy(**kwargs):
        captured.update(kwargs)

    fake = _fake_module()
    fake.install_noninteractive = _spy

    backend = _arize_backend()
    logging_block = {"prompts": False, "tool_details": True, "tool_content": False}
    req = _base_request(
        backend=backend,
        with_skills=True,
        logging=logging_block,
        user_id="uid-42",
    )

    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = install(req)

    assert result["success"] is True
    assert captured["target"] == "arize"
    assert "target" not in captured["credentials"]
    assert captured["credentials"]["api_key"] == "test-key"
    assert captured["credentials"]["space_id"] == "space-123"
    assert captured["project_name"] == "my-project"
    assert captured["user_id"] == "uid-42"
    assert captured["with_skills"] is True
    assert captured["logging_block"] == logging_block


# ---------------------------------------------------------------------------
# Uninstall — success per harness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("harness", list(HARNESS_KEYS))
def test_uninstall_success_per_harness(harness):
    fake = _fake_module(uninstall_msg=f"{harness} removed")
    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = uninstall(harness)

    assert result["success"] is True
    assert result["error"] is None
    assert result["harness"] == harness
    assert any(f"{harness} removed" in line for line in result["logs"])


# ---------------------------------------------------------------------------
# Uninstall — unknown harness
# ---------------------------------------------------------------------------


def test_uninstall_unknown_harness():
    result = uninstall("vim")
    assert result["success"] is False
    assert result["error"] == "unknown_harness"
    assert result["harness"] is None


# ---------------------------------------------------------------------------
# Uninstall — exception from underlying uninstaller
# ---------------------------------------------------------------------------


def test_uninstall_exception_captured():
    def _boom():
        raise OSError("permission denied")

    fake = _fake_module()
    fake.uninstall_noninteractive = _boom

    with mock.patch("core.vscode_bridge.install._import_installer", return_value=fake):
        result = uninstall("claude-code")

    assert result["success"] is False
    assert result["error"] == "install_failed"
    assert any("permission denied" in line for line in result["logs"])
