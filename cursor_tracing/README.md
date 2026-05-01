# Cursor IDE Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the Cursor IDE and Cursor CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup

### Remote setup

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor
```

Windows (PowerShell):

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat cursor
```

### Local setup

macOS / Linux:

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
./install.sh cursor
```

Windows:

```powershell
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
install.bat cursor
```

The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks in `.cursor/hooks.json`.

### Uninstall

```bash
./install.sh uninstall cursor        # macOS / Linux
install.bat uninstall cursor         # Windows
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `cursor` |
| Project name | `cursor` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `.cursor/hooks.json` (per project) |
| IDE hook events registered | `sessionStart`, `sessionEnd`, `beforeSubmitPrompt`, `afterAgentResponse`, `afterAgentThought`, `beforeShellExecution`, `afterShellExecution`, `beforeMCPExecution`, `afterMCPExecution`, `beforeReadFile`, `afterFileEdit`, `beforeTabFileRead`, `afterTabFileEdit`, `postToolUse`, `stop` |
| CLI hook events registered | `sessionStart`, `sessionEnd`, `beforeShellExecution`, `afterShellExecution`, `afterFileEdit`, `postToolUse`, `stop` |
| State directory | `~/.arize/harness/state/cursor/` |
| Log file | `/tmp/arize-cursor.log` |
| Tracing enabled (`ARIZE_TRACE_ENABLED`) | `true` |

See the [root README](../README.md) for backend configuration details.
