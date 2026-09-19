#!/bin/sh
set -eu

PROJECT_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
STATE_DIR="${CHATGPT_LOCAL_STATE_DIR:-$HOME/.local/share/chatgpt-local}"
VENV="$STATE_DIR/venv"

mkdir -p "$STATE_DIR"

python_has_ssl() {
  "$1" -c 'import ssl' >/dev/null 2>&1
}

pick_python() {
  if [ -n "${CHATGPT_LOCAL_PYTHON:-}" ]; then
    if [ ! -x "$CHATGPT_LOCAL_PYTHON" ]; then
      echo "CHATGPT_LOCAL_PYTHON is not executable: $CHATGPT_LOCAL_PYTHON" >&2
      return 1
    fi
    if ! python_has_ssl "$CHATGPT_LOCAL_PYTHON"; then
      echo "CHATGPT_LOCAL_PYTHON has no working ssl module: $CHATGPT_LOCAL_PYTHON" >&2
      return 1
    fi
    printf '%s\n' "$CHATGPT_LOCAL_PYTHON"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    candidate=$(command -v python3)
    if python_has_ssl "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
    echo "Ignoring python3 without a working ssl module: $candidate" >&2
  fi

  if command -v brew >/dev/null 2>&1; then
    prefix=$(brew --prefix python 2>/dev/null || true)
    if [ -n "$prefix" ] && [ -x "$prefix/bin/python3" ] && python_has_ssl "$prefix/bin/python3"; then
      printf '%s\n' "$prefix/bin/python3"
      return 0
    fi
  fi

  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$candidate" ] && python_has_ssl "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "No SSL-capable Python 3 installation was found." >&2
  echo "Install Homebrew Python with: brew install python" >&2
  echo "Or set CHATGPT_LOCAL_PYTHON to an SSL-capable python3 executable." >&2
  return 1
}

PYTHON=$(pick_python)

echo "Using Python:"
"$PYTHON" -c 'import sys, ssl; print("  executable:", sys.executable); print("  version:", sys.version.split()[0]); print("  ssl:", ssl.OPENSSL_VERSION)'

# The bridge venv is generated state, not repository state. Recreate it so a
# previous failed setup cannot leave an unusable interpreter behind.
rm -rf "$VENV"

if ! "$PYTHON" -m venv "$VENV"; then
  rm -rf "$VENV"
  exit 1
fi

if ! "$VENV/bin/python" -m pip install --upgrade pip; then
  rm -rf "$VENV"
  exit 1
fi

if ! "$VENV/bin/python" -m pip install -r "$PROJECT_ROOT/tools/chatgpt_local/requirements.txt"; then
  rm -rf "$VENV"
  exit 1
fi

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
