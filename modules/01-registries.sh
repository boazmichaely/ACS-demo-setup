#!/usr/bin/env bash
# Module: registries — ACS image integrations from secured-cluster pull secret
set -euo pipefail

MODULE_ID="registries"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/registries.py"
PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

usage() {
  cat <<EOF
Usage: $(basename "$0") --help
       $(basename "$0") --status
       $(basename "$0") --run [--dry-run]

Purpose:
  Configure Central image registry integrations needed for vulnerability scanning:
    - Public Quay.io (robot credentials from pull-secret quay.io)
    - registry.redhat.io (docker registry from pull-secret)

Depends on:
  - lab-credentials.json Central API token (or ROX_API_TOKEN)
  - oc logged into the secured OpenShift cluster (pull-secret in openshift-config)

Environment:
  ACS_LAB_CREDENTIALS_FILE   Override credentials JSON path
  ACS_CENTRAL_ENDPOINT       Override Central console URL
  ROX_API_TOKEN / TOKEN      Override Central API token
  ACS_DEMO_PYTHON            Override Python interpreter

Side effects:
  --run updates or creates image integrations in Central via /v1/imageintegrations
EOF
}

run_helper() {
  "$PYTHON" "$HELPER" "$@"
}

emit_status() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER"
    return 1
  fi
  local output
  if ! output="$(run_helper status --cli 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tstatus command failed with no output\n' "$MODULE_ID"
      return 1
    fi
  fi
  printf '%s\n' "$output"
  local state
  state="$(printf '%s\n' "$output" | tail -1 | awk -F'\t' '{print $2}')"
  [[ "$state" != "error" ]]
}

run_module() {
  local dry_run="${1:-false}"
  local args=(run --cli)
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)
  local output rc=0
  if ! output="$(run_helper "${args[@]}" 2>&1)"; then
    rc=1
  fi
  if [[ -z "$output" ]]; then
    printf '%s\terror\trun command failed with no output\n' "$MODULE_ID" >&2
    return 1
  fi
  printf '%s\n' "$output"
  local state
  state="$(printf '%s\n' "$output" | tail -1 | awk -F'\t' '{print $2}')"
  if [[ "$dry_run" == "true" ]]; then
    [[ "$state" != "error" ]]
    return
  fi
  [[ "$state" == "ok" ]] || return 1
}

main() {
  local action=""
  local dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --dry-run) dry_run=true ;;
      *) echo "$(basename "$0"): unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
    shift
  done

  [[ -n "$action" ]] || { usage; exit 0; }

  case "$action" in
    status) emit_status ;;
    run) run_module "$dry_run" ;;
  esac
}

main "$@"
