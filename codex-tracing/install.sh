#!/bin/bash
# Codex tracing installer — delegates to the root installer.
# For standalone setup, use: install.sh codex
# For marketplace plugin setup, use: codex-tracing/scripts/setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ "${1:-}" == "uninstall" ]]; then
  exec bash "$REPO_ROOT/install.sh" uninstall
else
  exec bash "$REPO_ROOT/install.sh" codex
fi
