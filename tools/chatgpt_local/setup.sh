#!/bin/sh
set -eu

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
STATE_DIR="${CHATGPT_LOCAL_STATE_DIR:-$HOME/.local/share/chatgpt-local}"
VENV="$STATE_DIR/venv"

mkdir -p "$STATE_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$PROJECT_ROOT/tools/chatgpt_local/requirements.txt"

echo
echo "ChatGPT Local bridge environment installed at:"
echo "  $VENV"
echo
if command -v tunnel-client >/dev/null 2>&1; then
  echo "tunnel-client: $(command -v tunnel-client)"
else
  echo "tunnel-client is not installed."
  echo "Install the official OpenAI client, for example:"
  echo "  brew install openai/tools/tunnel-client"
fi
echo
echo "Next:"
echo "  1. Create the dedicated ChatGPT worktree if needed."
echo "  2. Provision a Secure MCP Tunnel in ChatGPT Developer Mode."
echo "  3. Export CONTROL_PLANE_API_KEY and CONTROL_PLANE_TUNNEL_ID."
echo "  4. Run tools/chatgpt_local/run_tunnel.sh from the ChatGPT worktree."
