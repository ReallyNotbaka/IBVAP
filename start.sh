#!/usr/bin/env bash
set -e

echo "=================================================================="
echo "Starting IBVAP Platform..."
echo "=================================================================="

if command -v uv >/dev/null 2>&1; then
    uv run python run.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    python3 run.py "$@"
else
    echo "[ERROR] Neither 'uv' nor 'python3' was found on your system PATH."
    echo "Please install uv (https://astral.sh/uv) or Python 3.12+."
    exit 1
fi
