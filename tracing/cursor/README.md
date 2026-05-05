# Cursor IDE Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the Cursor IDE and Cursor CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks in `.cursor/hooks.json`.

### Remote setup

macOS / Linux:

```bash
# Install
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor

# Uninstall
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall cursor
```

Windows (PowerShell):

```powershell
# Install
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat cursor

# Uninstall
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall cursor
```

### Local setup

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
```

macOS / Linux:

```bash
# Install
./install.sh cursor

# Uninstall
./install.sh uninstall cursor
```

Windows:

```powershell
# Install
install.bat cursor

# Uninstall
install.bat uninstall cursor
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `cursor` |
| Project name | `cursor` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `.cursor/hooks.json` |
| IDE hook events registered | `sessionStart`, `sessionEnd`, `beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought`, `beforeShellExecution`, `afterShellExecution`, `beforeMCPExecution`, `afterMCPExecution`, `beforeReadFile`, `afterFileEdit`, `beforeTabFileRead`, `afterTabFileEdit`, `postToolUse`, `stop` |
| CLI hook events registered | `sessionStart`, `sessionEnd`, `beforeShellExecution`, `afterShellExecution`, `afterFileEdit`, `postToolUse`, `stop` |
| State directory | `~/.arize/harness/state/cursor/` |
| Log file | `~/.arize/harness/logs/cursor.log` |
