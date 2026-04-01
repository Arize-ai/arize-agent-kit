#!/bin/bash
# Cursor hook handler — all 12 hook events dispatched here.
#
# Cursor's hooks.json routes every event to this single script.
# Input JSON is read from stdin and includes hook_event_name,
# conversation_id, generation_id, and event-specific fields.
#
# Spans are built with build_span() and sent via send_span() from core/common.sh.
# Before/after shell and MCP events are merged via disk-backed state stack.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Load env (backwards compat with standalone arize-cursor repo) ---
# Check project root .env, then legacy location
for env_file in "${HOOK_DIR}/../../.env" "${HOME}/.cursor-phoenix.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    break
  fi
done

# --- Source cursor adapter (which sources core/common.sh) ---
source "${HOOK_DIR}/common.sh"

# --- Read input from stdin ---
INPUT="$(cat 2>/dev/null || echo '{}')"
[[ -z "$INPUT" ]] && INPUT='{}'

EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null || echo "")
CONVERSATION_ID=$(echo "$INPUT" | jq -r '.conversation_id // empty' 2>/dev/null || echo "")
GEN_ID=$(echo "$INPUT" | jq -r '.generation_id // empty' 2>/dev/null || echo "")

# --- Early exit if tracing disabled or no backend ---
if [[ "$ARIZE_TRACE_ENABLED" != "true" ]]; then
  echo '{"continue": true}'
  exit 0
fi

target=$(get_target)
if [[ "$target" == "none" ]]; then
  # Check if collector is reachable before giving up
  if ! curl -sf --max-time 1 "${_COLLECTOR_URL}/health" >/dev/null 2>&1; then
    log "No backend configured and collector not reachable, skipping"
    echo '{"continue": true}'
    exit 0
  fi
fi

# --- Require jq ---
command -v jq &>/dev/null || { echo '{"continue": true}'; exit 0; }

# --- Derive IDs ---
TRACE_ID=""
if [[ -n "$GEN_ID" ]]; then
  TRACE_ID=$(trace_id_from_generation "$GEN_ID")
fi
NOW_MS=$(get_timestamp_ms)

# --- Helper: return permissive JSON response ---
# "before" hooks need {"permission": "allow"}, others need {"continue": true}
permissive() {
  local event="${1:-}"
  case "$event" in
    before*) echo '{"permission": "allow"}' ;;
    *)       echo '{"continue": true}' ;;
  esac
}

# --- Helper: safe jq extraction with default ---
jq_str() {
  echo "$INPUT" | jq -r "$1" 2>/dev/null || echo "${2:-}"
}

# --- Dispatch by hook event ---
{
  case "$EVENT" in

    # ---------------------------------------------------------------
    # beforeSubmitPrompt — Root span for the turn
    # ---------------------------------------------------------------
    beforeSubmitPrompt)
      sid=$(span_id_16)

      # Save root span for this generation so child spans can reference it
      if [[ -n "$GEN_ID" ]]; then
        gen_root_span_save "$GEN_ID" "$sid"
      fi

      # Extract prompt text
      prompt=$(jq_str '.prompt // .input // .text // empty')
      prompt=$(truncate_attr "$prompt")

      session_id="$CONVERSATION_ID"
      model=$(jq_str '.model_name // .model // empty')

      attrs=$(jq -nc \
        --arg kind "CHAIN" \
        --arg input "$prompt" \
        --arg session "$session_id" \
        --arg model "$model" \
        '{
          "openinference.span.kind": $kind,
          "input.value": $input,
          "session.id": $session
        }
        + (if $model != "" then {"llm.model_name": $model} else {} end)')

      span=$(build_span "User Prompt" "CHAIN" "$sid" "$TRACE_ID" "" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "beforeSubmitPrompt: root span $sid (trace=$TRACE_ID)"
      ;;

    # ---------------------------------------------------------------
    # afterAgentResponse — LLM response span
    # ---------------------------------------------------------------
    afterAgentResponse)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      response=$(jq_str '.response // .output // .text // empty')
      response=$(truncate_attr "$response")
      model=$(jq_str '.model_name // .model // empty')

      attrs=$(jq -nc \
        --arg kind "LLM" \
        --arg output "$response" \
        --arg model "$model" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "output.value": $output,
          "session.id": $session
        }
        + (if $model != "" then {"llm.model_name": $model} else {} end)')

      span=$(build_span "Agent Response" "LLM" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterAgentResponse: span $sid"
      ;;

    # ---------------------------------------------------------------
    # afterAgentThought — Agent thinking/reasoning span
    # ---------------------------------------------------------------
    afterAgentThought)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      thought=$(jq_str '.thought // .thinking // .text // empty')
      thought=$(truncate_attr "$thought")

      attrs=$(jq -nc \
        --arg kind "CHAIN" \
        --arg output "$thought" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "output.value": $output,
          "session.id": $session
        }')

      span=$(build_span "Agent Thinking" "CHAIN" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterAgentThought: span $sid"
      ;;

    # ---------------------------------------------------------------
    # beforeShellExecution — State push only, no span
    # ---------------------------------------------------------------
    beforeShellExecution)
      if [[ -n "$GEN_ID" ]]; then
        command_text=$(jq_str '.command // .shell_command // empty')
        cwd=$(jq_str '.cwd // .working_directory // empty')

        val=$(jq -nc \
          --arg cmd "$command_text" \
          --arg cwd "$cwd" \
          --arg start "$NOW_MS" \
          --arg trace "$TRACE_ID" \
          --arg conv "$CONVERSATION_ID" \
          '{command: $cmd, cwd: $cwd, start_ms: $start, trace_id: $trace, conversation_id: $conv}')

        state_push "shell_$(sanitize "$GEN_ID")" "$val"
        log "beforeShellExecution: pushed state for gen=$GEN_ID"
      fi
      ;;

    # ---------------------------------------------------------------
    # afterShellExecution — Merge with before state, create span
    # ---------------------------------------------------------------
    afterShellExecution)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      # Pop the before-state
      popped="null"
      if [[ -n "$GEN_ID" ]]; then
        popped=$(state_pop "shell_$(sanitize "$GEN_ID")") || true
      fi

      # Extract before-state fields
      if [[ -n "$popped" && "$popped" != "null" ]]; then
        start_ms=$(echo "$popped" | jq -r '.start_ms // empty' 2>/dev/null || echo "")
        command_text=$(echo "$popped" | jq -r '.command // empty' 2>/dev/null || echo "")
      else
        start_ms=""
        command_text=""
      fi
      [[ -z "$start_ms" ]] && start_ms="$NOW_MS"

      # Override command from after-event if present
      after_cmd=$(jq_str '.command // .shell_command // empty')
      [[ -n "$after_cmd" ]] && command_text="$after_cmd"

      output=$(jq_str '.output // .stdout // .result // empty')
      output=$(truncate_attr "$output")
      command_text=$(truncate_attr "$command_text")
      exit_code=$(jq_str '.exit_code // .exitCode // empty')

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "shell" \
        --arg input "$command_text" \
        --arg output "$output" \
        --arg exit_code "$exit_code" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "output.value": $output,
          "session.id": $session
        }
        + (if $exit_code != "" then {"shell.exit_code": $exit_code} else {} end)')

      span=$(build_span "Shell" "TOOL" "$sid" "$TRACE_ID" "$parent" "$start_ms" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterShellExecution: span $sid (merged)"
      ;;

    # ---------------------------------------------------------------
    # beforeMCPExecution — State push only, no span
    # ---------------------------------------------------------------
    beforeMCPExecution)
      if [[ -n "$GEN_ID" ]]; then
        tool_name=$(jq_str '.tool_name // .toolName // .name // empty')
        tool_input=$(jq_str '.tool_input // .toolInput // .input // .arguments // empty')
        mcp_url=$(jq_str '.url // .server_url // .serverUrl // empty')
        mcp_cmd=$(jq_str '.command // empty')

        val=$(jq -nc \
          --arg tool "$tool_name" \
          --arg input "$tool_input" \
          --arg url "$mcp_url" \
          --arg cmd "$mcp_cmd" \
          --arg start "$NOW_MS" \
          --arg trace "$TRACE_ID" \
          --arg conv "$CONVERSATION_ID" \
          '{tool_name: $tool, tool_input: $input, url: $url, command: $cmd, start_ms: $start, trace_id: $trace, conversation_id: $conv}')

        state_push "mcp_$(sanitize "$GEN_ID")" "$val"
        log "beforeMCPExecution: pushed state for tool=$tool_name gen=$GEN_ID"
      fi
      ;;

    # ---------------------------------------------------------------
    # afterMCPExecution — Merge with before state, create span
    # ---------------------------------------------------------------
    afterMCPExecution)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      # Pop the before-state
      popped="null"
      if [[ -n "$GEN_ID" ]]; then
        popped=$(state_pop "mcp_$(sanitize "$GEN_ID")") || true
      fi

      # Extract before-state fields
      if [[ -n "$popped" && "$popped" != "null" ]]; then
        start_ms=$(echo "$popped" | jq -r '.start_ms // empty' 2>/dev/null || echo "")
        tool_name=$(echo "$popped" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
        tool_input=$(echo "$popped" | jq -r '.tool_input // empty' 2>/dev/null || echo "")
      else
        start_ms=""
        tool_name=""
        tool_input=""
      fi
      [[ -z "$start_ms" ]] && start_ms="$NOW_MS"

      # Override tool name from after-event if present
      after_tool=$(jq_str '.tool_name // .toolName // .name // empty')
      [[ -n "$after_tool" ]] && tool_name="$after_tool"
      [[ -z "$tool_name" ]] && tool_name="unknown"

      result=$(jq_str '.result // .output // .result_json // empty')
      result=$(truncate_attr "$result")
      tool_input=$(truncate_attr "$tool_input")

      span_name="MCP: ${tool_name}"

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "$tool_name" \
        --arg input "$tool_input" \
        --arg output "$result" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "output.value": $output,
          "session.id": $session
        }')

      span=$(build_span "$span_name" "TOOL" "$sid" "$TRACE_ID" "$parent" "$start_ms" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterMCPExecution: span $sid tool=$tool_name (merged)"
      ;;

    # ---------------------------------------------------------------
    # beforeReadFile — Read file span
    # ---------------------------------------------------------------
    beforeReadFile)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      file_path=$(jq_str '.file_path // .filePath // .path // empty')
      file_path=$(truncate_attr "$file_path")

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "read_file" \
        --arg input "$file_path" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "session.id": $session
        }')

      span=$(build_span "Read File" "TOOL" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "beforeReadFile: span $sid path=$file_path"
      ;;

    # ---------------------------------------------------------------
    # afterFileEdit — File edit span
    # ---------------------------------------------------------------
    afterFileEdit)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      file_path=$(jq_str '.file_path // .filePath // .path // empty')
      edits=$(jq_str '.edits // .changes // .diff // empty')
      input_val="${file_path}"
      if [[ -n "$edits" ]]; then
        input_val="${file_path}: ${edits}"
      fi
      input_val=$(truncate_attr "$input_val")

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "edit_file" \
        --arg input "$input_val" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "session.id": $session
        }')

      span=$(build_span "File Edit" "TOOL" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterFileEdit: span $sid path=$file_path"
      ;;

    # ---------------------------------------------------------------
    # beforeTabFileRead — Tab read file span
    # ---------------------------------------------------------------
    beforeTabFileRead)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      file_path=$(jq_str '.file_path // .filePath // .path // empty')
      file_path=$(truncate_attr "$file_path")

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "read_file_tab" \
        --arg input "$file_path" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "session.id": $session
        }')

      span=$(build_span "Tab Read File" "TOOL" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "beforeTabFileRead: span $sid path=$file_path"
      ;;

    # ---------------------------------------------------------------
    # afterTabFileEdit — Tab file edit span
    # ---------------------------------------------------------------
    afterTabFileEdit)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      file_path=$(jq_str '.file_path // .filePath // .path // empty')
      edits=$(jq_str '.edits // .changes // .diff // empty')
      input_val="${file_path}"
      if [[ -n "$edits" ]]; then
        input_val="${file_path}: ${edits}"
      fi
      input_val=$(truncate_attr "$input_val")

      attrs=$(jq -nc \
        --arg kind "TOOL" \
        --arg tool "edit_file_tab" \
        --arg input "$input_val" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "tool.name": $tool,
          "input.value": $input,
          "session.id": $session
        }')

      span=$(build_span "Tab File Edit" "TOOL" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true
      log "afterTabFileEdit: span $sid path=$file_path"
      ;;

    # ---------------------------------------------------------------
    # stop — Agent stop span + cleanup
    # ---------------------------------------------------------------
    stop)
      sid=$(span_id_16)
      parent=$(gen_root_span_get "${GEN_ID:-}")

      status=$(jq_str '.status // .reason // empty')
      loop_count=$(jq_str '.loop_count // .loopCount // .iterations // empty')

      attrs=$(jq -nc \
        --arg kind "CHAIN" \
        --arg status "$status" \
        --arg loops "$loop_count" \
        --arg session "$CONVERSATION_ID" \
        '{
          "openinference.span.kind": $kind,
          "session.id": $session
        }
        + (if $status != "" then {"cursor.stop.status": $status} else {} end)
        + (if $loops != "" then {"cursor.stop.loop_count": $loops} else {} end)')

      span=$(build_span "Agent Stop" "CHAIN" "$sid" "$TRACE_ID" "$parent" "$NOW_MS" "$NOW_MS" "$attrs")
      send_span "$span" || true

      # Clean up generation state
      if [[ -n "$GEN_ID" ]]; then
        state_cleanup_generation "$GEN_ID"
      fi
      log "stop: span $sid, cleaned up gen=$GEN_ID"
      ;;

    # ---------------------------------------------------------------
    # Unknown event — log and ignore
    # ---------------------------------------------------------------
    *)
      log "Unknown hook event: $EVENT"
      ;;
  esac
} 2>>"$ARIZE_LOG_FILE" || true

# --- Always return a permissive response ---
permissive "$EVENT"
exit 0
