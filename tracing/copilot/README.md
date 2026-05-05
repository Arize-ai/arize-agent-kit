# GitHub Copilot Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for GitHub Copilot in VS Code. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers Copilot Chat hooks at `.github/hooks/hooks.json`.

### Remote setup

macOS / Linux:

```bash
# Install
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- copilot

# Uninstall
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall copilot
```

Windows (PowerShell):

```powershell
# Install
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat copilot

# Uninstall
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall copilot
```

### Local setup

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
```

macOS / Linux:

```bash
# Install
./install.sh copilot

# Uninstall
./install.sh uninstall copilot
```

Windows:

```powershell
# Install
install.bat copilot

# Uninstall
install.bat uninstall copilot
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `copilot` |
| Project name | `copilot` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `.github/hooks/hooks.json` |
| Hook events | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop` |
| State directory | `~/.arize/harness/state/copilot/` |
| Log file | `~/.arize/harness/logs/copilot.log` |
