# GitHub Copilot Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for GitHub Copilot in VS Code and the Copilot CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers VS Code (`.github/hooks/*.json`) and Copilot CLI (`.github/hooks/hooks.json`) hooks.

### Remote setup

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- copilot

curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall copilot
```

Windows (PowerShell):

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat copilot

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
./install.sh copilot

./install.sh uninstall copilot
```

Windows:

```powershell
install.bat copilot

install.bat uninstall copilot
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `copilot` |
| Project name | `copilot` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| VS Code hook config files | `.github/hooks/session-start.json`, `user-prompt.json`, `pre-tool.json`, `post-tool.json`, `stop.json`, `subagent-stop.json` |
| CLI hook config file | `.github/hooks/hooks.json` |
| VS Code hook events | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop` |
| CLI hook events | `sessionStart`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `errorOccurred`, `sessionEnd` |
| State directory | `~/.arize/harness/state/copilot/` |
| Log file | `~/.arize/harness/logs/copilot.log` |
