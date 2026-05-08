# Kiro tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the Kiro CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix). Each traced session emits LLM turns, tool calls, cost in credits, model information, and turn duration. Token counts (`llm.token_count.prompt`, `llm.token_count.completion`) are included only when Kiro CLI reports them — currently Kiro bills via credits, not tokens.

## Quick start

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- kiro
# or, from a clone:
./install.sh kiro
```

## What gets installed

- Hook entries written into `~/.kiro/agents/<agent>.json` (default agent: `arize-traced`)
- State directory: `~/.arize/harness/state/kiro/`
- Config block under `harnesses.kiro` in `~/.arize/harness/config.yaml`

## Install flow

The installer prompts you through the following steps:

1. **Agent name** — name of the Kiro agent to install hooks into (default: `arize-traced`)
2. **Set as default** — whether to run `kiro-cli agent set-default <name>` so the agent is used by default
3. **Backend** — Phoenix or Arize AX, plus endpoint and credentials
4. **Project name** — project name in your backend (default: `kiro`)
5. **User ID** — optional user identifier added to all spans
6. **Logging** — whether to include prompt text, tool content, and tool details in spans

## Usage

```bash
# If you set arize-traced as Kiro's default during install:
kiro-cli chat
# Otherwise:
kiro-cli chat --agent arize-traced
```

## Span shape

### LLM span

| Attribute | Description |
|-----------|-------------|
| `session.id` | Kiro session UUID |
| `openinference.span.kind` | `LLM` |
| `input.value` | User prompt |
| `output.value` | Assistant response |
| `llm.output_messages` | Structured assistant response |
| `llm.model_name` | Model ID from the session sidecar (e.g. `auto`) |
| `llm.token_count.prompt` | Prompt token count (when reported, omitted when 0) |
| `llm.token_count.completion` | Completion token count (when reported, omitted when 0) |
| `llm.token_count.total` | Total token count (when reported, omitted when 0) |
| `kiro.cost.credits` | Cost in credits from metering data |
| `kiro.metering_usage` | Full metering usage JSON |
| `kiro.turn_duration_ms` | Turn duration in milliseconds |
| `kiro.agent_name` | Name of the Kiro agent |
| `kiro.context_usage_percentage` | Context window usage percentage |

LLM spans are enriched from the session sidecar at `~/.kiro/sessions/cli/<session_id>.json`. Enrichment is fail-soft — if the sidecar is unavailable, the span is emitted with basic attributes only.

### TOOL span

| Attribute | Description |
|-----------|-------------|
| `tool.name` | Tool name (alias form) |
| `tool.description` | Purpose of the tool call (from `__tool_use_purpose` in tool input) |
| `input.value` | Serialized tool input JSON |
| `output.value` | Serialized tool response JSON |

TOOL spans are parented to the LLM turn they belong to.

## Known limitations

- **Token counts are 0.** `input_token_count` and `output_token_count` are reported as 0 in current Kiro CLI versions. Kiro meters in credits instead — see `kiro.cost.credits`. Token count attributes are omitted when 0.
- **FIFO tool matching.** Kiro does not expose a tool-call ID, so pre/post tool events are matched using a FIFO stack. This assumes serial tool execution within a session.
- **Sidecar read is fail-soft.** The session sidecar may not exist or may lag behind hook events due to a flush race. When this happens, the LLM span is emitted without enrichment attributes (model name, cost, duration).

## Uninstall

```bash
./install.sh uninstall kiro
```

Uninstall removes hook entries from the agent config. If the `arize-traced` agent was created by the installer, the agent file is deleted. If hooks were added to a pre-existing agent, the hooks are removed but the agent file is preserved.
