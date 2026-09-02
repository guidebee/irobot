#!/usr/bin/env bash
# Launcher for agent_client.py -- works from any working directory.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    PYTHON=python
fi

exec "$PYTHON" "$SCRIPT_DIR/agent_client.py" "$@"
