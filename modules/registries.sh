#!/usr/bin/env bash
# Module: registries - ACS image integrations from secured-cluster pull secret
# Entrypoint shape matches templates/module-skeleton.sh; logic in registries.py
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
  - lab-credentials.json Central API token and/or admin password (or ROX_API_TOKEN)
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

# Print status lines from the helper; last tab-separated row is id/state/message.
do_status() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER"
    return 0
  fi
  local output
  if ! output="$(run_helper status --cli 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tstatus command failed with no output\n' "$MODULE_ID"
      return 0
    fi
  fi
  printf '%s\n' "$output"
}

# Apply integrations via the helper. Safe to run twice.
do_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper run --cli 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\trun command failed with no output\n' "$MODULE_ID" >&2
      return 1
    fi
    printf '%s\n' "$output"
    return 1
  fi
  if [[ -z "$output" ]]; then
    printf '%s\terror\trun command failed with no output\n' "$MODULE_ID" >&2
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

# Plan only (helper --dry-run). No Central mutations.
do_dry_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper run --cli --dry-run 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tdry-run failed with no output\n' "$MODULE_ID" >&2
      return 1
    fi
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" != "error" ]]
}

emit_status() {
  local output state
  output="$(do_status)"
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" != "error" ]]
}

run_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    do_dry_run
    return
  fi
  do_run
}

main() {
  local action="" dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --dry-run) dry_run=true ;;
      *)
        echo "$(basename "$0"): unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
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
