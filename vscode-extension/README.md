# Arize Agent Kit -- VS Code Extension

## What it does

- **Guided setup wizard** for tracing with `claude-code`, `codex`, `cursor`, `copilot`, and `gemini` harnesses
- **Sidebar view** listing configured harnesses with their project names and backends
- **Reconfigure and uninstall** individual harnesses directly from the sidebar
- **Status bar item** showing current tracing state at a glance
- **Codex buffer service controls** (start/stop) when the Codex harness is configured

## Prerequisites

- **Python >= 3.9** available on `PATH`
- Run `install.sh` (macOS/Linux) or `install.bat` (Windows) from the repo root at least once so that `~/.arize/harness/venv` and the `arize-vscode-bridge` entry point exist

## Usage

1. Open the **Arize Tracing** activity bar view in the sidebar.
2. Click **Set Up Tracing** and follow the wizard to configure a harness.
3. Reconfigure or uninstall a harness using the inline buttons on its sidebar row.
4. Codex buffer state appears in the sidebar automatically when the Codex harness is configured.

## Commands

| Command ID | Title |
|------------|-------|
| `arize.setup` | Arize: Set Up Tracing |
| `arize.reconfigure` | Arize: Reconfigure Tracing |
| `arize.uninstall` | Arize: Uninstall Harness |
| `arize.refreshStatus` | Arize: Refresh Status |
| `arize.startCodexBuffer` | Arize: Start Codex Buffer |
| `arize.stopCodexBuffer` | Arize: Stop Codex Buffer |
| `arize.statusBarMenu` | Arize: Status Menu |

## Filing issues

Please report bugs and feature requests on the [GitHub issue tracker](https://github.com/Arize-ai/arize-agent-kit/issues).
