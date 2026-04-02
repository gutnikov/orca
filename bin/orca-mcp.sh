#!/bin/bash
# Launch orca MCP server.
# Usage: orca-mcp.sh [repo-root]
#   repo-root: optional repo root path (passed as --root to orca mcp)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORCA_BIN="${SCRIPT_DIR}/../.venv/bin/orca"

if [ ! -f "$ORCA_BIN" ]; then
  echo "orca binary not found at $ORCA_BIN — run 'uv sync' in $(dirname "$SCRIPT_DIR")" >&2
  exit 1
fi

if [ -n "$1" ]; then
  exec "$ORCA_BIN" --root "$1" mcp
else
  exec "$ORCA_BIN" mcp
fi
