#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=${PORT:-9000}

# Use uv if available, otherwise fall back to .venv
if command -v uv &>/dev/null; then
    echo "Starting LCA MCP server on port $PORT (via uv)..."
    exec uv run --project "$SCRIPT_DIR" python "$SCRIPT_DIR/sse_server.py"
else
    echo "Starting LCA MCP server on port $PORT (via .venv)..."
    exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/sse_server.py"
fi
