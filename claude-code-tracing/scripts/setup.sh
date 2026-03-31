#!/bin/bash
# Arize Claude Code Plugin - Interactive Setup
# Run after: claude plugin install claude-code-tracing@arize-agent-kit

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}▸ ARIZE${NC} Claude Code Tracing Setup"
echo ""

GLOBAL_SETTINGS_FILE="${HOME}/.claude/settings.json"
LOCAL_SETTINGS_FILE=".claude/settings.local.json"
SETTINGS_FILE=""

ensure_settings_file() {
  mkdir -p "$(dirname "$SETTINGS_FILE")"
  [[ -f "$SETTINGS_FILE" ]] || echo '{}' > "$SETTINGS_FILE"
}

check_existing_configuration() {
  if [[ -f "$SETTINGS_FILE" ]]; then
    existing_phoenix=$(jq -r '.env.PHOENIX_ENDPOINT // empty' "$SETTINGS_FILE" 2>/dev/null)
    existing_arize=$(jq -r '.env.ARIZE_API_KEY // empty' "$SETTINGS_FILE" 2>/dev/null)
    if [[ -n "$existing_phoenix" ]]; then
      echo -e "${YELLOW}Existing config found in ${SETTINGS_FILE}:${NC} Phoenix at $existing_phoenix"
      read -p "Overwrite? [y/N]: " overwrite
      [[ "$overwrite" =~ ^[Yy]$ ]] || { echo "Setup cancelled."; exit 0; }
      echo ""
    elif [[ -n "$existing_arize" ]]; then
      echo -e "${YELLOW}Existing config found in ${SETTINGS_FILE}:${NC} Arize AX"
      read -p "Overwrite? [y/N]: " overwrite
      [[ "$overwrite" =~ ^[Yy]$ ]] || { echo "Setup cancelled."; exit 0; }
      echo ""
    fi
  fi
}

echo "Where should Claude tracing env vars be stored?"
echo ""
echo "  1) Project-local (.claude/settings.local.json)"
echo "  2) Global (~/.claude/settings.json)"
echo ""
read -p "Enter choice [1/2]: " settings_choice

case "$settings_choice" in
  1|"")
    SETTINGS_FILE="$LOCAL_SETTINGS_FILE"
    ;;
  2)
    SETTINGS_FILE="$GLOBAL_SETTINGS_FILE"
    ;;
  *)
    echo "Invalid choice. Run setup again."
    exit 1
    ;;
esac

check_existing_configuration

# Ask for target
echo "Which backend do you want to use?"
echo ""
echo "  1) Phoenix (self-hosted, no Python required)"
echo "  2) Arize AX (cloud, requires Python)"
echo ""
read -p "Enter choice [1/2]: " choice

case "$choice" in
  1|phoenix|Phoenix)
    echo ""
    read -p "Phoenix endpoint [http://localhost:6006]: " phoenix_endpoint
    phoenix_endpoint="${phoenix_endpoint:-http://localhost:6006}"

    # Merge into existing settings
    ensure_settings_file
    jq --arg endpoint "$phoenix_endpoint" \
      '.env = (.env // {}) + {"PHOENIX_ENDPOINT": $endpoint, "ARIZE_TRACE_ENABLED": "true"}' \
      "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo ""
    echo -e "${GREEN}✓${NC} Configured for Phoenix at $phoenix_endpoint"
    ;;

  2|arize|ax|AX)
    echo ""
    read -p "Arize API Key: " api_key
    read -p "Arize Space ID: " space_id

    if [[ -z "$api_key" || -z "$space_id" ]]; then
      echo "Error: API key and Space ID are required for Arize AX"
      exit 1
    fi

    echo ""
    echo -e "${YELLOW}OTLP Endpoint${NC} (for hosted Arize instances, leave blank for default):"
    read -p "OTLP Endpoint [otlp.arize.com:443]: " otlp_endpoint
    otlp_endpoint="${otlp_endpoint:-otlp.arize.com:443}"

    # Merge into existing settings
    ensure_settings_file
    jq --arg key "$api_key" --arg space "$space_id" --arg endpoint "$otlp_endpoint" \
      '.env = (.env // {}) + {"ARIZE_API_KEY": $key, "ARIZE_SPACE_ID": $space, "ARIZE_OTLP_ENDPOINT": $endpoint, "ARIZE_TRACE_ENABLED": "true"}' \
      "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo ""
    echo -e "${GREEN}✓${NC} Configured for Arize AX (endpoint: $otlp_endpoint)"
    echo ""
    echo -e "${YELLOW}Note:${NC} Arize AX requires Python dependencies:"
    echo "  pip install opentelemetry-proto grpcio"
    ;;

  *)
    echo "Invalid choice. Run setup again."
    exit 1
    ;;
esac

# Optional: User ID for span attribution
echo ""
echo -e "${BLUE}Optional:${NC} Set a user ID to identify your spans (useful for teams)."
read -p "User ID (leave blank to skip): " user_id
if [[ -n "$user_id" ]]; then
  ensure_settings_file
  jq --arg uid "$user_id" \
    '.env = (.env // {}) + {"ARIZE_USER_ID": $uid}' \
    "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
  echo -e "${GREEN}✓${NC} User ID set: $user_id"
fi

echo ""
echo "Configuration saved to $SETTINGS_FILE"
echo ""
echo "Start a new Claude Code session to begin tracing!"
echo ""
