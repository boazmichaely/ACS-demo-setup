#!/usr/bin/env bash
set -euo pipefail

GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$GUI_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo "ACS demo setup GUI: http://127.0.0.1:8765"
exec python -m uvicorn app:app --host 127.0.0.1 --port 8765 --app-dir "$GUI_DIR"
