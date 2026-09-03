#!/usr/bin/env bash
# Launcher for the irobot Gym IDE (tools/irobot_gym_ide/) -- works from any working directory.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    PYTHON=python
fi

# `python -m irobot_gym_ide.app` resolves the package relative to the
# current working directory -- cd into tools/ first, same pattern as
# agent_client.sh.
cd "$SCRIPT_DIR"
exec "$PYTHON" -m irobot_gym_ide.app "$@"
