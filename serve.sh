#!/usr/bin/env bash
# Launch the ACS demo setup GUI (primary entrypoint).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/gui/serve.sh" "$@"
