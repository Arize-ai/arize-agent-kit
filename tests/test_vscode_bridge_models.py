"""Tests for core.vscode_bridge.models builder functions."""

import json

import pytest

from core.vscode_bridge.models import (
    HARNESS_KEYS,
    build_backend,
    build_codex_buffer,
    build_harness_status_item,
    build_install_request,
    build_operation_result,
    build_status,
)

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class TestBuildBackend:
    def test_arize_backend(self):
        b = build_backend("arize", "https://otlp.arize.com", "key123", "space1")
        assert b == {
            "target": "arize",
            "endpoint": "https://otlp.arize.com",
            "api_key": "key123",
            "space_id": "space1",
        }

    def test_phoenix_backend(self):
        b = build_backend("phoenix", "http://localhost:6006", "")
        assert b == {
            "target": "phoenix",
            "endpoint": "http://localhost:6006",
            "api_key": "",
            "space_id": None,
        }

    def test_phoenix_no_auth(self):
        b = build_backend("phoenix", "http://localhost:6006")
        assert b["api_key"] == ""
        assert b["space_id"] is None

    def test_arize_requires_space_id(self):
        with pytest.raises(ValueError, match="space_id is required"):
            build_backend("arize", "https://otlp.arize.com", "key")

    def test_phoenix_rejects_space_id(self):
        with pytest.raises(ValueError, match="space_id must be None"):
            build_backend("phoenix", "http://localhost:6006", "", "space1")

    def test_unknown_target_rejected(self):
        with pytest.raises(ValueError, match="unknown target"):
            build_backend("other", "http://x")

    def test_empty_endpoint_rejected(self):
        with pytest.raises(ValueError, match="endpoint"):
            build_backend("phoenix", "")


# ---------------------------------------------------------------------------
# HarnessStatusItem
# ---------------------------------------------------------------------------


class TestBuildHarnessStatusItem:
    def test_unconfigured(self):
        h = build_harness_status_item("codex")
        assert h == {
            "name": "codex",
            "configured": False,
            "project_name": None,
            "backend": None,
            "scope": None,
        }

    def test_configured(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        h = build_harness_status_item("cursor", configured=True, project_name="my-proj", backend=backend)
        assert h["configured"] is True
        assert h["project_name"] == "my-proj"
        assert h["backend"]["target"] == "phoenix"

    def test_unknown_harness_rejected(self):
        with pytest.raises(ValueError, match="unknown harness"):
            build_harness_status_item("vim")

    def test_all_harness_keys_accepted(self):
        for key in HARNESS_KEYS:
            h = build_harness_status_item(key)
            assert h["name"] == key

    def test_exact_keys(self):
        h = build_harness_status_item("gemini")
        assert set(h.keys()) == {"name", "configured", "project_name", "backend", "scope"}


# ---------------------------------------------------------------------------
# StatusPayload
# ---------------------------------------------------------------------------


class TestBuildStatus:
    def test_defaults(self):
        s = build_status(success=True)
        assert s["success"] is True
        assert s["error"] is None
        assert s["user_id"] is None
        assert len(s["harnesses"]) == 5
        assert s["logging"] is None
        assert s["codex_buffer"] is None
        names = [h["name"] for h in s["harnesses"]]
        assert tuple(names) == HARNESS_KEYS

    def test_with_logging(self):
        s = build_status(
            success=True,
            logging={"prompts": False, "tool_details": True, "tool_content": False},
        )
        assert s["logging"] == {
            "prompts": False,
            "tool_details": True,
            "tool_content": False,
        }

    def test_logging_defaults_missing_keys(self):
        s = build_status(success=True, logging={})
        assert s["logging"] == {
            "prompts": True,
            "tool_details": True,
            "tool_content": True,
        }

    def test_error_payload(self):
        s = build_status(success=False, error="config_not_found")
        assert s["success"] is False
        assert s["error"] == "config_not_found"

    def test_exact_keys(self):
        s = build_status(success=True)
        assert set(s.keys()) == {
            "success",
            "error",
            "user_id",
            "harnesses",
            "logging",
            "codex_buffer",
        }


# ---------------------------------------------------------------------------
# InstallRequest
# ---------------------------------------------------------------------------


class TestBuildInstallRequest:
    def test_minimal(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        r = build_install_request("codex", backend, "my-project")
        assert r == {
            "harness": "codex",
            "backend": backend,
            "project_name": "my-project",
            "user_id": None,
            "with_skills": False,
            "logging": None,
        }

    def test_full(self):
        backend = build_backend("arize", "https://otlp.arize.com", "k", "s")
        r = build_install_request(
            "claude-code",
            backend,
            "proj",
            user_id="u1",
            with_skills=True,
            logging={"prompts": True, "tool_details": False, "tool_content": True},
        )
        assert r["with_skills"] is True
        assert r["user_id"] == "u1"
        assert r["logging"]["tool_details"] is False

    def test_unknown_harness(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        with pytest.raises(ValueError, match="unknown harness"):
            build_install_request("neovim", backend, "proj")

    def test_empty_project_name(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        with pytest.raises(ValueError, match="project_name"):
            build_install_request("codex", backend, "")

    def test_exact_keys(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        r = build_install_request("copilot", backend, "p")
        assert set(r.keys()) == {
            "harness",
            "backend",
            "project_name",
            "user_id",
            "with_skills",
            "logging",
        }


# ---------------------------------------------------------------------------
# OperationResult
# ---------------------------------------------------------------------------


class TestBuildOperationResult:
    def test_success(self):
        r = build_operation_result(True, harness="cursor", logs=["installed"])
        assert r == {
            "success": True,
            "error": None,
            "harness": "cursor",
            "logs": ["installed"],
        }

    def test_failure(self):
        r = build_operation_result(False, error="install_failed", harness="codex")
        assert r["success"] is False
        assert r["error"] == "install_failed"

    def test_no_harness_for_buffer_ops(self):
        r = build_operation_result(True)
        assert r["harness"] is None
        assert r["logs"] == []

    def test_unknown_harness(self):
        with pytest.raises(ValueError, match="unknown harness"):
            build_operation_result(True, harness="zsh")

    def test_exact_keys(self):
        r = build_operation_result(True)
        assert set(r.keys()) == {"success", "error", "harness", "logs"}


# ---------------------------------------------------------------------------
# CodexBufferPayload
# ---------------------------------------------------------------------------


class TestBuildCodexBuffer:
    def test_running(self):
        c = build_codex_buffer(True, state="running", host="127.0.0.1", port=4318, pid=12345)
        assert c == {
            "success": True,
            "error": None,
            "state": "running",
            "host": "127.0.0.1",
            "port": 4318,
            "pid": 12345,
        }

    def test_unknown_default(self):
        c = build_codex_buffer(False, error="not_running")
        assert c["state"] == "unknown"
        assert c["host"] is None
        assert c["port"] is None
        assert c["pid"] is None

    def test_invalid_state(self):
        with pytest.raises(ValueError, match="unknown codex buffer state"):
            build_codex_buffer(True, state="broken")

    def test_exact_keys(self):
        c = build_codex_buffer(True, state="stopped")
        assert set(c.keys()) == {"success", "error", "state", "host", "port", "pid"}


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_status_roundtrip(self):
        backend = build_backend("arize", "https://otlp.arize.com", "k", "s")
        harnesses = [
            build_harness_status_item("claude-code", True, "proj", backend),
        ] + [build_harness_status_item(k) for k in HARNESS_KEYS if k != "claude-code"]
        codex_buf = build_codex_buffer(True, state="running", host="127.0.0.1", port=4318, pid=1)
        status = build_status(
            success=True,
            user_id="u1",
            harnesses=harnesses,
            logging={"prompts": True, "tool_details": True, "tool_content": False},
            codex_buffer=codex_buf,
        )
        roundtripped = json.loads(json.dumps(status))
        assert roundtripped == status

    def test_install_request_roundtrip(self):
        backend = build_backend("phoenix", "http://localhost:6006")
        req = build_install_request("gemini", backend, "proj", logging={"prompts": False})
        roundtripped = json.loads(json.dumps(req))
        assert roundtripped == req

    def test_operation_result_roundtrip(self):
        r = build_operation_result(False, error="timeout", harness="copilot", logs=["a", "b"])
        roundtripped = json.loads(json.dumps(r))
        assert roundtripped == r

    def test_codex_buffer_roundtrip(self):
        c = build_codex_buffer(True, state="stale", host="127.0.0.1", port=9999, pid=42)
        roundtripped = json.loads(json.dumps(c))
        assert roundtripped == c


# ---------------------------------------------------------------------------
# HARNESS_KEYS constant
# ---------------------------------------------------------------------------


class TestHarnessKeys:
    def test_all_five_present(self):
        assert len(HARNESS_KEYS) == 5

    def test_is_tuple(self):
        assert isinstance(HARNESS_KEYS, tuple)

    def test_expected_values(self):
        assert set(HARNESS_KEYS) == {"claude-code", "codex", "cursor", "copilot", "gemini"}
