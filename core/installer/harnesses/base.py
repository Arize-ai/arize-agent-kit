#!/usr/bin/env python3
"""Base class for harness-specific install/uninstall operations.

Subclasses implement install(), uninstall(), is_installed(), and get_status().
The base class provides shared config manipulation helpers that read/write
the harnesses section of ~/.arize/harness/config.yaml.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.config import delete_value, get_value, load_config, save_config, set_value
from core.constants import BASE_DIR, CONFIG_FILE, HARNESSES, STATE_BASE_DIR, VENV_DIR


class HarnessInstaller:
    """Base class for harness-specific install/uninstall operations."""

    harness_name: str  # e.g. "claude-code", "codex", "cursor"

    def __init__(self, harness_name: str, config_path: Optional[str] = None) -> None:
        self.harness_name = harness_name
        self._config_path = config_path

    # --- Public interface (subclasses must implement) ---

    def install(
        self,
        backend: str = "local",
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        non_interactive: bool = False,
    ) -> None:
        """Register hooks, write harness-specific config, add to config.yaml."""
        raise NotImplementedError

    def uninstall(self, non_interactive: bool = False) -> None:
        """Remove hooks, clean up harness-specific config, remove from config.yaml."""
        raise NotImplementedError

    def is_installed(self) -> bool:
        """Check if this harness is currently configured."""
        raise NotImplementedError

    def get_status(self) -> Dict[str, Any]:
        """Return harness status info (for extension sidebar)."""
        raise NotImplementedError

    # --- Shared config helpers ---

    def _load(self) -> Dict[str, Any]:
        """Load config, forwarding the optional override path."""
        return load_config(self._config_path)

    def _save(self, config: Dict[str, Any]) -> None:
        """Save config, forwarding the optional override path."""
        save_config(config, self._config_path)

    def _add_harness_to_config(self, project_name: str) -> None:
        """Register this harness in config.yaml with the given project name."""
        config = self._load()
        set_value(config, f"harnesses.{self.harness_name}.project_name", project_name)
        self._save(config)

    def _remove_harness_from_config(self) -> None:
        """Remove this harness entry from config.yaml."""
        config = self._load()
        delete_value(config, f"harnesses.{self.harness_name}")
        # Clean up empty harnesses dict
        harnesses = get_value(config, "harnesses")
        if isinstance(harnesses, dict) and len(harnesses) == 0:
            delete_value(config, "harnesses")
        self._save(config)

    def _check_last_harness(self) -> bool:
        """Return True if this is the only remaining harness in config.

        Used by uninstall to decide whether to stop the collector.
        """
        config = self._load()
        harnesses = get_value(config, "harnesses")
        if not isinstance(harnesses, dict):
            return True
        return list(harnesses.keys()) == [self.harness_name]
