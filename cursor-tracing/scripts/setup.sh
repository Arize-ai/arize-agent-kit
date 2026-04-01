#!/bin/bash
# Arize Cursor Tracing - Interactive Setup
# Run: bash cursor-tracing/scripts/setup.sh

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[arize]${NC} $*"; }
warn() { echo -e "${YELLOW}[arize]${NC} $*"; }
err()  { echo -e "${RED}[arize]${NC} $*" >&2; }

echo ""
echo -e "${GREEN}▸ ARIZE${NC} Cursor Tracing Setup"
echo ""

# --- Prerequisites ---
command -v jq &>/dev/null || { err "jq is required. Install: brew install jq"; exit 1; }

# --- Paths ---
SHARED_BASE="${HOME}/.arize/harness"
SHARED_CONFIG="${SHARED_BASE}/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_SRC="${SCRIPT_DIR}/../hooks"

# --- Check for existing config ---
existing_backend=""
if [[ -f "$SHARED_CONFIG" ]]; then
  existing_backend=$(jq -r '.backend.target // empty' "$SHARED_CONFIG" 2>/dev/null) || true
fi

if [[ -n "$existing_backend" ]]; then
  echo -e "${YELLOW}Existing config found:${NC} backend=${existing_backend} in ${SHARED_CONFIG}"
  echo "Skipping credential prompts — adding cursor harness entry."
  echo ""

  # Add cursor harness entry
  tmp_config="${SHARED_CONFIG}.tmp.$$"
  jq '.harnesses.cursor.project_name = "cursor"' \
    "$SHARED_CONFIG" > "$tmp_config" && mv "$tmp_config" "$SHARED_CONFIG"
  chmod 600 "$SHARED_CONFIG"
  info "Added cursor harness to existing config"
else
  # --- No existing config — prompt for backend ---
  echo "Which backend do you want to use?"
  echo ""
  echo "  1) Phoenix (self-hosted, no Python required)"
  echo "  2) Arize AX (cloud, requires Python)"
  echo ""
  read -rp "Enter choice [1/2]: " choice

  case "$choice" in
    1|phoenix|Phoenix)
      TARGET="phoenix"
      echo ""
      read -rp "Phoenix endpoint [http://localhost:6006]: " phoenix_endpoint
      phoenix_endpoint="${phoenix_endpoint:-http://localhost:6006}"
      info "Target: Phoenix at $phoenix_endpoint"
      ;;
    2|arize|ax|AX)
      TARGET="arize"
      echo ""
      read -rp "Arize API Key: " api_key
      read -rp "Arize Space ID: " space_id

      if [[ -z "$api_key" || -z "$space_id" ]]; then
        err "API key and Space ID are required for Arize AX"
        exit 1
      fi

      echo ""
      echo -e "${YELLOW}OTLP Endpoint${NC} (for hosted Arize instances, leave blank for default):"
      read -rp "OTLP Endpoint [otlp.arize.com:443]: " otlp_endpoint
      otlp_endpoint="${otlp_endpoint:-otlp.arize.com:443}"
      info "Target: Arize AX (endpoint: $otlp_endpoint)"
      ;;
    *)
      err "Invalid choice. Run setup again."
      exit 1
      ;;
  esac

  # --- Write config.json ---
  mkdir -p "${SHARED_BASE}/bin" "${SHARED_BASE}/run" "${SHARED_BASE}/logs"

  case "$TARGET" in
    phoenix)
      cat > "$SHARED_CONFIG" <<EOF
{
  "collector": {
    "host": "127.0.0.1",
    "port": 4318
  },
  "backend": {
    "target": "phoenix",
    "phoenix": {
      "endpoint": "${phoenix_endpoint}",
      "api_key": ""
    },
    "arize": {
      "endpoint": "otlp.arize.com:443",
      "api_key": "",
      "space_id": ""
    }
  },
  "harnesses": {
    "cursor": { "project_name": "cursor" }
  }
}
EOF
      ;;
    arize)
      cat > "$SHARED_CONFIG" <<EOF
{
  "collector": {
    "host": "127.0.0.1",
    "port": 4318
  },
  "backend": {
    "target": "arize",
    "phoenix": {
      "endpoint": "http://localhost:6006",
      "api_key": ""
    },
    "arize": {
      "endpoint": "${otlp_endpoint}",
      "api_key": "${api_key}",
      "space_id": "${space_id}"
    }
  },
  "harnesses": {
    "cursor": { "project_name": "cursor" }
  }
}
EOF
      ;;
  esac

  chmod 600 "$SHARED_CONFIG"
  info "Wrote shared collector config to $SHARED_CONFIG"

  if [[ "$TARGET" == "arize" ]]; then
    echo ""
    echo -e "${YELLOW}Note:${NC} Arize AX backend requires Python dependencies for the collector:"
    echo "  pip install opentelemetry-proto grpcio"
  fi
fi

# --- Optional: User ID ---
echo ""
echo -e "${BLUE}Optional:${NC} Set a user ID to identify your spans (useful for teams)."
read -rp "User ID (leave blank to skip): " user_id
if [[ -n "$user_id" ]]; then
  tmp_config="${SHARED_CONFIG}.tmp.$$"
  jq --arg uid "$user_id" '.user_id = $uid' \
    "$SHARED_CONFIG" > "$tmp_config" && mv "$tmp_config" "$SHARED_CONFIG"
  chmod 600 "$SHARED_CONFIG"
  info "User ID set: $user_id"
fi

# --- Summary ---
echo ""
info "Setup complete!"
echo ""
echo "  Configuration:"
echo "    Config file: ${SHARED_CONFIG}"
echo ""
echo "  Next steps:"
echo "    1. Copy hooks.json into your Cursor settings:"
echo "       cp ${HOOKS_SRC}/hooks.json ~/.cursor/hooks.json"
echo ""
echo "    2. Start the shared collector (if not already running):"
echo "       source ~/.arize/harness/core/collector_ctl.sh && collector_start"
echo ""
echo "    3. Open Cursor — traces will be sent to your configured backend"
echo ""
echo "  To verify setup:"
echo "    ARIZE_VERBOSE=true cursor"
echo ""
