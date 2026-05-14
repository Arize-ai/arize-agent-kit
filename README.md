# Arize Coding Harness Tracing

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method |
|---------|-------------|----------------|
| [Claude Code CLI / Agent SDK](tracing/claude_code/README.md) | `claude-code-tracing` | Marketplace or `install.sh` / `install.bat` |
| [OpenAI Codex CLI](tracing/codex/README.md) | `codex-tracing` | `install.sh` / `install.bat` |
| [Cursor IDE / CLI](tracing/cursor/README.md) | `cursor-tracing` | `install.sh` / `install.bat` |
| [GitHub Copilot (VS Code + CLI)](tracing/copilot/README.md) | `copilot-tracing` | `install.sh` / `install.bat` |
| [Gemini CLI](tracing/gemini/README.md) | `gemini-tracing` | `install.sh` / `install.bat` |
| [Kiro CLI](tracing/kiro/README.md) | `kiro-tracing` | `install.sh` / `install.bat` |

Claude Code CLI and the Claude Agent SDK share the same plugin, hooks, and configuration — one install covers both.

## Install

### Quickstart

**macOS / Linux:**

```bash
INSTALL_URL="https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh"

curl -sSL "$INSTALL_URL" | bash -s -- claude    # Claude Code / Agent SDK
curl -sSL "$INSTALL_URL" | bash -s -- codex     # OpenAI Codex
curl -sSL "$INSTALL_URL" | bash -s -- cursor    # Cursor IDE / CLI
curl -sSL "$INSTALL_URL" | bash -s -- copilot   # GitHub Copilot (VS Code + CLI)
curl -sSL "$INSTALL_URL" | bash -s -- gemini    # Gemini CLI
curl -sSL "$INSTALL_URL" | bash -s -- kiro      # Kiro CLI

curl -sSL "$INSTALL_URL" | bash -s -- uninstall claude    # Remove Claude Code tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall codex     # Remove Codex tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall cursor    # Remove Cursor tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall copilot   # Remove Copilot tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall gemini    # Remove Gemini tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall kiro      # Remove Kiro tracing
curl -sSL "$INSTALL_URL" | bash -s -- uninstall           # Remove all installed harnesses
```

**Windows:**

```powershell
$INSTALL_URL = "https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat"
iwr -useb $INSTALL_URL -OutFile $env:TEMP\install.bat

& $env:TEMP\install.bat claude    # Claude Code / Agent SDK
& $env:TEMP\install.bat codex     # OpenAI Codex
& $env:TEMP\install.bat cursor    # Cursor IDE / CLI
& $env:TEMP\install.bat copilot   # GitHub Copilot (VS Code + CLI)
& $env:TEMP\install.bat gemini    # Gemini CLI
& $env:TEMP\install.bat kiro      # Kiro CLI

& $env:TEMP\install.bat uninstall claude    # Remove Claude Code tracing
& $env:TEMP\install.bat uninstall codex     # Remove Codex tracing
& $env:TEMP\install.bat uninstall cursor    # Remove Cursor tracing
& $env:TEMP\install.bat uninstall copilot   # Remove Copilot tracing
& $env:TEMP\install.bat uninstall gemini    # Remove Gemini tracing
& $env:TEMP\install.bat uninstall kiro      # Remove Kiro tracing
& $env:TEMP\install.bat uninstall           # Remove all installed harnesses
```

### Local Copy

```bash
git clone https://github.com/Arize-ai/coding-harness-tracing.git
cd coding-harness-tracing
```

**macOS / Linux**
```bash
./install.sh claude    # Claude Code / Agent SDK
./install.sh codex     # OpenAI Codex
./install.sh cursor    # Cursor IDE / CLI
./install.sh copilot   # GitHub Copilot (VS Code + CLI)
./install.sh gemini    # Gemini CLI
./install.sh kiro      # Kiro CLI

./install.sh uninstall claude    # Remove Claude Code tracing
./install.sh uninstall codex     # Remove Codex tracing
./install.sh uninstall cursor    # Remove Cursor tracing
./install.sh uninstall copilot   # Remove Copilot tracing
./install.sh uninstall gemini    # Remove Gemini tracing
./install.sh uninstall kiro      # Remove Kiro tracing
./install.sh uninstall           # Remove all installed harnesses
```

**Windows**
```powershell
install.bat claude    # Claude Code / Agent SDK
install.bat codex     # OpenAI Codex
install.bat cursor    # Cursor IDE / CLI
install.bat copilot   # GitHub Copilot (VS Code + CLI)
install.bat gemini    # Gemini CLI
install.bat kiro      # Kiro CLI

install.bat uninstall claude    # Remove Claude Code tracing
install.bat uninstall codex     # Remove Codex tracing
install.bat uninstall cursor    # Remove Cursor tracing
install.bat uninstall copilot   # Remove Copilot tracing
install.bat uninstall gemini    # Remove Gemini tracing
install.bat uninstall kiro      # Remove Kiro tracing
install.bat uninstall           # Remove all installed harnesses
```

Uninstall removes the harness configuration and cleans up runtime files. For Codex, the buffer service is stopped. You will be prompted before any user-owned config (credentials, state files) is deleted.

## Configuration

All configuration lives in `~/.arize/harness/config.yaml`, written by the installer. This file is the single source of truth for backend credentials and per-harness settings.

### config.yaml Fields

**Per-harness settings** (under `harnesses.<name>`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `harnesses.<name>.project_name` | No | harness name | Project name in Arize/Phoenix |
| `harnesses.<name>.target` | Yes | — | `phoenix` or `arize` |
| `harnesses.<name>.endpoint` | Yes | — | Phoenix server URL or Arize OTLP gRPC endpoint |
| `harnesses.<name>.api_key` | Arize: Yes | — | Arize AX API key (or optional Phoenix API key) |
| `harnesses.<name>.space_id` | Arize: Yes | — | Arize AX space ID |

**Codex-only** (under `harnesses.codex.collector`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `harnesses.codex.collector.host` | No | `127.0.0.1` | Codex buffer service listen address |
| `harnesses.codex.collector.port` | No | `4318` | Codex buffer service listen port |

**Content logging** (under top-level `logging`, applies to all harnesses)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `logging.prompts` | No | `true` | Include user prompt text in spans |
| `logging.tool_details` | No | `true` | Include tool arguments (commands, file paths, URLs, queries) |
| `logging.tool_content` | No | `true` | Include tool input/output content (file contents, command output) |

**User**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `user_id` | No | — | User identifier added to all spans as `user.id` |

Each harness owns its full backend configuration directly — there is no shared global backend block. This allows different harnesses to use different backends or credentials.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)

## License

MIT
