#!/usr/bin/env bash
# Human-readable snapshot of OpenShift Compliance Operator resources on the secured cluster.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/compliance_co_overview.py" "$@"
