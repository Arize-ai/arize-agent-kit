# Claude Code Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the Claude Code CLI and the Claude Agent SDK. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup

### Remote setup

Claude Code marketplace:

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude
```

Windows (PowerShell):

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat claude
```

### Local setup

macOS / Linux:

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
./install.sh claude
```

Windows:

```powershell
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
install.bat claude
```

The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks in `~/.claude/settings.json`.

### Uninstall

```bash
./install.sh uninstall claude        # macOS / Linux
install.bat uninstall claude         # Windows
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `claude-code` |
| Project name | `claude-code` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `~/.claude/settings.json` |
| Hook events registered | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `Notification`, `PermissionRequest`, `SessionEnd` |
| State directory | `~/.arize/harness/state/claude-code/` |
| Log file | `/tmp/arize-claude-code.log` |
| Tracing enabled (`ARIZE_TRACE_ENABLED`) | `true` |

See the [root README](../README.md) for backend configuration details.
