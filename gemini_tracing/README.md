# Gemini CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for Gemini CLI sessions. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks in `~/.gemini/settings.json`.

### Remote setup

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- gemini

curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall gemini
```

Windows (PowerShell):

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat gemini

iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall gemini
```

### Local setup

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
```

macOS / Linux:

```bash
./install.sh gemini

./install.sh uninstall gemini
```

Windows:

```powershell
install.bat gemini

install.bat uninstall gemini
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `gemini` |
| Project name | `gemini` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `~/.gemini/settings.json` |
| Hook events registered | `SessionStart`, `SessionEnd`, `BeforeAgent`, `AfterAgent`, `BeforeModel`, `AfterModel`, `BeforeTool`, `AfterTool` |
| State directory | `~/.arize/harness/state/gemini/` |
| Log file | `~/.arize/harness/logs/gemini.log` |
