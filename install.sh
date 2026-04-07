#!/bin/sh
# Arize Agent Kit installer wrapper
# Usage: curl -sSL <url>/install.sh | sh -s -- claude
#    or: ./install.sh claude
set -e

# Find Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        version=$("$cmd" -c "import sys; print(sys.version_info[0])" 2>/dev/null || echo "")
        if [ "$version" = "3" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 is required but not found in PATH." >&2
    echo "Install Python 3.9+ from https://python.org and try again." >&2
    exit 1
fi

# Download and run install.py
INSTALL_URL="${ARIZE_INSTALL_URL:-https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.py}"
TMPFILE=$(mktemp /tmp/arize-install-XXXXXX.py)
trap 'rm -f "$TMPFILE"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl -sSfL "$INSTALL_URL" -o "$TMPFILE"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMPFILE" "$INSTALL_URL"
else
    echo "Error: curl or wget is required." >&2
    exit 1
fi

"$PYTHON" "$TMPFILE" "$@"
