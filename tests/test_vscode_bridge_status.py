"""Tests for core.vscode_bridge.status.load_status."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.vscode_bridge.models import HARNESS_KEYS
from core.vscode_bridge.status import load_status


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Point CONFIG_FILE at a temp directory and return the config path."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr("core.vscode_bridge.status.CONFIG_FILE", config_path)
    return config_path


# ---- helpers ----


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f)


def _all_unconfigured(harnesses: list[dict]) -> bool:
    return (
        len(harnesses) == len(HARNESS_KEYS)
        and all(h["name"] in HARNESS_KEYS for h in harnesses)
        and all(not h["configured"] for h in harnesses)
        and all(h["backend"] is None for h in harnesses)
        and all(h["project_name"] is None for h in harnesses)
    )


# ---- missing / empty config ----


def test_missing_config(config_dir):
    """No config file → success, all unconfigured, no user_id, no logging."""
    result = load_status()

    assert result["success"] is True
    assert result["error"] is None
    assert result["user_id"] is None
    assert result["logging"] is None
    assert result["codex_buffer"] is None
    assert _all_unconfigured(result["harnesses"])


def test_empty_config(config_dir):
    """Empty YAML file → success, all unconfigured."""
    config_dir.write_text("")
    result = load_status()

    assert result["success"] is True
    assert _all_unconfigured(result["harnesses"])
    assert result["user_id"] is None
    assert result["logging"] is None


# ---- malformed YAML ----


def test_malformed_yaml(config_dir):
    """Invalid YAML → success=False, error='config_malformed'."""
    config_dir.write_text("{{bad yaml: [")
    result = load_status()

    assert result["success"] is False
    assert result["error"] == "config_malformed"
    assert _all_unconfigured(result["harnesses"])
    assert result["codex_buffer"] is None


# ---- one configured harness ----


def test_one_harness_configured(config_dir):
    """Single harness configured, rest unconfigured."""
    _write_yaml(
        config_dir,
        {
            "harnesses": {
                "claude-code": {
                    "project_name": "my-project",
                    "target": "arize",
                    "endpoint": "https://otlp.arize.com",
                    "api_key": "key123",
                    "space_id": "sp-1",
                },
            },
        },
    )

    result = load_status()
    assert result["success"] is True

    by_name = {h["name"]: h for h in result["harnesses"]}
    assert len(by_name) == 5

    cc = by_name["claude-code"]
    assert cc["configured"] is True
    assert cc["project_name"] == "my-project"
    assert cc["backend"]["target"] == "arize"
    assert cc["backend"]["endpoint"] == "https://otlp.arize.com"
    assert cc["backend"]["api_key"] == "key123"
    assert cc["backend"]["space_id"] == "sp-1"

    for name in ("codex", "cursor", "copilot", "gemini"):
        assert by_name[name]["configured"] is False
        assert by_name[name]["backend"] is None


# ---- all five configured ----


def test_all_five_configured(config_dir):
    """All five harnesses configured."""
    harnesses = {}
    for i, key in enumerate(HARNESS_KEYS):
        harnesses[key] = {
            "project_name": f"proj-{key}",
            "target": "arize",
            "endpoint": "https://otlp.arize.com",
            "api_key": f"key-{i}",
            "space_id": f"sp-{i}",
        }
    _write_yaml(config_dir, {"harnesses": harnesses})

    result = load_status()
    assert result["success"] is True
    assert all(h["configured"] for h in result["harnesses"])
    assert [h["name"] for h in result["harnesses"]] == list(HARNESS_KEYS)


# ---- arize vs phoenix backend ----


def test_arize_backend(config_dir):
    """Arize backend includes space_id."""
    _write_yaml(
        config_dir,
        {
            "harnesses": {
                "cursor": {
                    "project_name": "p",
                    "target": "arize",
                    "endpoint": "https://otlp.arize.com",
                    "api_key": "k",
                    "space_id": "sp",
                },
            },
        },
    )
    result = load_status()
    be = {h["name"]: h for h in result["harnesses"]}["cursor"]["backend"]
    assert be["target"] == "arize"
    assert be["space_id"] == "sp"


def test_phoenix_backend(config_dir):
    """Phoenix backend has space_id=None."""
    _write_yaml(
        config_dir,
        {
            "harnesses": {
                "codex": {
                    "project_name": "p",
                    "target": "phoenix",
                    "endpoint": "http://localhost:6006",
                    "api_key": "",
                },
            },
        },
    )
    result = load_status()
    be = {h["name"]: h for h in result["harnesses"]}["codex"]["backend"]
    assert be["target"] == "phoenix"
    assert be["space_id"] is None


# ---- logging block ----


def test_logging_present(config_dir):
    """Top-level logging block is forwarded."""
    _write_yaml(
        config_dir,
        {
            "logging": {
                "prompts": False,
                "tool_details": True,
                "tool_content": False,
            },
        },
    )

    result = load_status()
    assert result["success"] is True
    assert result["logging"] == {
        "prompts": False,
        "tool_details": True,
        "tool_content": False,
    }


def test_logging_absent(config_dir):
    """No logging block → None."""
    _write_yaml(config_dir, {"harnesses": {}})
    result = load_status()
    assert result["logging"] is None


# ---- user_id ----


def test_user_id_present(config_dir):
    _write_yaml(config_dir, {"user_id": "alice"})
    result = load_status()
    assert result["user_id"] == "alice"


# ---- codex_buffer always None ----


def test_codex_buffer_always_none(config_dir):
    """codex_buffer is always None from status module."""
    _write_yaml(
        config_dir,
        {
            "harnesses": {
                "codex": {
                    "project_name": "p",
                    "target": "phoenix",
                    "endpoint": "http://localhost:6006",
                    "api_key": "",
                },
            },
        },
    )
    result = load_status()
    assert result["codex_buffer"] is None


# ---- harness order is always HARNESS_KEYS ----


def test_harness_order(config_dir):
    """Harnesses are always returned in HARNESS_KEYS order."""
    _write_yaml(
        config_dir,
        {
            "harnesses": {
                "gemini": {"project_name": "g", "target": "phoenix", "endpoint": "http://x", "api_key": ""},
                "claude-code": {"project_name": "c", "target": "phoenix", "endpoint": "http://x", "api_key": ""},
            },
        },
    )
    result = load_status()
    names = [h["name"] for h in result["harnesses"]]
    assert names == list(HARNESS_KEYS)
