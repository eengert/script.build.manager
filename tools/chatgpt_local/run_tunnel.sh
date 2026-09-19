#!/bin/sh
set -eu

BRIDGE_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
STATE_DIR="${CHATGPT_LOCAL_STATE_DIR:-$HOME/.local/share/chatgpt-local}"
PYTHON="$STATE_DIR/venv/bin/python"

: "${CONTROL_PLANE_API_KEY:?CONTROL_PLANE_API_KEY must be set}"
: "${CONTROL_PLANE_TUNNEL_ID:?CONTROL_PLANE_TUNNEL_ID must be set}"

if [ ! -x "$PYTHON" ]; then
  echo "ChatGPT Local venv not found. Run tools/chatgpt_local/setup.sh first." >&2
  exit 1
fi

if ! command -v tunnel-client >/dev/null 2>&1; then
  echo "tunnel-client not found. Install the official OpenAI tunnel-client first." >&2
  exit 1
fi

WORKSPACE="${CHATGPT_LOCAL_WORKSPACE:-$BRIDGE_ROOT}"
if [ ! -e "$WORKSPACE/.git" ]; then
  echo "CHATGPT_LOCAL_WORKSPACE is not a git worktree: $WORKSPACE" >&2
  exit 1
fi

export CHATGPT_LOCAL_WORKSPACE="$WORKSPACE"
export PYTHONPATH="$BRIDGE_ROOT"

cd "$BRIDGE_ROOT"
exec tunnel-client run   --mcp.command "$PYTHON -m tools.chatgpt_local.server"   --log.level=info   --log.format=struct-text
