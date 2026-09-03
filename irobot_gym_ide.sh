#!/usr/bin/env bash
# Launcher for the irobot Gym IDE (irobot_gym_ide/) -- works from any working directory.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    PYTHON=python
fi

# `python -m irobot_gym_ide.app` resolves the package relative to the
# current working directory -- cd into the repo root first (this script's
# own directory), same pattern as tools/agent_client.sh.
cd "$SCRIPT_DIR"
exec "$PYTHON" -m irobot_gym_ide.app "$@"
