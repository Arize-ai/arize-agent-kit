# Claude Code Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the Claude Code CLI and the Claude Agent SDK. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks in `~/.claude/settings.json`.

### Claude Code marketplace

The marketplace flow registers the hooks but skips the interactive wizard, so backend credentials and content-logging preferences must be set directly in `~/.claude/settings.json` under `env`:

```json
{
  "env": {
    "ARIZE_PROJECT_NAME": "claude-code",
    "ARIZE_API_KEY": "<your-arize-api-key>",
    "ARIZE_SPACE_ID": "<your-arize-space-id>",
    "ARIZE_LOG_PROMPTS": "true",
    "ARIZE_LOG_TOOL_DETAILS": "true",
    "ARIZE_LOG_TOOL_CONTENT": "true"
  }
}
```

For Phoenix, swap the Arize keys for `PHOENIX_ENDPOINT` (and optional `PHOENIX_API_KEY`). Each `ARIZE_LOG_*` flag accepts `"true"` or `"false"` — set to `"false"` to opt out per category. Env values take precedence over `~/.arize/harness/config.yaml`.

```bash
# Install
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit

# Uninstall
claude plugin uninstall claude-code-tracing@arize-agent-kit
claude plugin marketplace remove Arize-ai/arize-agent-kit
```

### Remote setup

macOS / Linux:

```bash
# Install
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude

# Uninstall
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall claude
```

Windows (PowerShell):

```powershell
# Install
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat claude

# Uninstall
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall claude
```

### Local setup

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
```

macOS / Linux:

```bash
# Install
./install.sh claude

# Uninstall
./install.sh uninstall claude
```

Windows:

```powershell
# Install
install.bat claude

# Uninstall
install.bat uninstall claude
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
| Log file | `~/.arize/harness/logs/claude-code.log` |
