#!/usr/bin/env bash
# GUI server — prefer launching via repo-root ./serve.sh
set -euo pipefail

GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${ACS_GUI_HOST:-127.0.0.1}"
START_PORT="${ACS_GUI_PORT:-8765}"
MAX_TRIES="${ACS_GUI_PORT_TRIES:-20}"

usage() {
  cat <<EOF
Usage: ./serve.sh [options]
       ./gui/serve.sh [options]

Start the ACS demo setup GUI (FastAPI + uvicorn) on localhost.

Options:
  -h, --h, --help   Show this help

Environment:
  ACS_GUI_HOST         Bind address (default: 127.0.0.1)
  ACS_GUI_PORT         First port to try (default: 8765)
  ACS_GUI_PORT_TRIES   How many consecutive ports to try if busy (default: 20)

If the chosen port is already in use, the next free port is used automatically.
Open the URL printed at startup (host and port may differ from the default).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--h|--help) usage; exit 0 ;;
    *)
      echo "serve.sh: unknown option: $1" >&2
      echo "Try './serve.sh --help'." >&2
      exit 1
      ;;
  esac
  # unreachable today; kept for future flags
  shift
done

cd "$GUI_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

port_free() {
  local port="$1"
  python - "$HOST" "$port" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind((host, port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
sys.exit(0)
PY
}

PORT=""
candidate="$START_PORT"
tries=0
while (( tries < MAX_TRIES )); do
  if port_free "$candidate"; then
    PORT="$candidate"
    break
  fi
  echo "serve.sh: port ${HOST}:${candidate} in use — trying next" >&2
  candidate=$((candidate + 1))
  tries=$((tries + 1))
done

if [[ -z "$PORT" ]]; then
  echo "serve.sh: no free port in ${START_PORT}..$((START_PORT + MAX_TRIES - 1)) on ${HOST}" >&2
  exit 1
fi

if [[ "$PORT" != "$START_PORT" ]]; then
  echo "serve.sh: using port ${PORT} (default ${START_PORT} was busy)" >&2
fi

echo "ACS demo setup GUI: http://${HOST}:${PORT}"
exec python -m uvicorn app:app --host "$HOST" --port "$PORT" --app-dir "$GUI_DIR"
