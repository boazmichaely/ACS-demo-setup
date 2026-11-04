#!/usr/bin/env bash
# Module: slack-notifier - Central Slack integration for demo alerting
set -euo pipefail

MODULE_ID="slack-notifier"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/slack_notifier.py"
PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

EXTRA_ARGS=()

usage() {
  cat <<EOF
Usage: $(basename "$0") --help
       $(basename "$0") --status [--webhook URL] [--name NAME] [--channel-url URL]
       $(basename "$0") --run [--dry-run] [--webhook URL] [--name NAME] [--channel-url URL]
       $(basename "$0") --uninstall [--dry-run] [--webhook URL] [--name NAME] [--channel-url URL]

Purpose:
  Ensure a Slack notifier in Central (default channel #acs-demo-notifier).
  Defaults ship in config/slack-notifier.defaults.json; Lab credentials may
  override notifier name, webhook, and channel URL.
  --run sends Central's Test notifier message, then a second lab-context
  ping (lab name, Central host, secured cluster) via the Incoming Webhook,
  then attaches this notifier to every Central policy with category DEMO.

Depends on:
  - Central API auth in lab-credentials.json (API token or admin password)
  - DEMO policies from modules such as init-demo / signature-integration
    (re-run those first if policies exist without category DEMO)

Flags:
  --webhook URL       Override Incoming Webhook for this invocation
  --name NAME         Override Central notifier display name
  --channel-url URL   Override Slack channel deep link in status folds

Environment:
  ACS_LAB_CREDENTIALS_FILE   Override path to lab-credentials.json
  ACS_CENTRAL_ENDPOINT       Override Central console URL
  ROX_API_TOKEN / TOKEN      Override Central API token
  ACS_DEMO_PYTHON            Override Python interpreter
  ACS_INSECURE_SKIP_TLS_VERIFY  Skip TLS verify for Central

Side effects:
  --run         create/update Slack notifier; Central test + lab-context
                webhook ping; attach notifier to DEMO-category policies
  --uninstall   detach this notifier from DEMO policies; delete the notifier
                (policies and DEMO category stay)
EOF
}

run_helper() {
  # Parent flags (--webhook etc.) must precede the subcommand for argparse.
  if ((${#EXTRA_ARGS[@]})); then
    "$PYTHON" "$HELPER" "${EXTRA_ARGS[@]}" "$@"
  else
    "$PYTHON" "$HELPER" "$@"
  fi
}

do_status() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER"
    return 0
  fi
  local output
  if ! output="$(run_helper status 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tstatus command failed with no output\n' "$MODULE_ID"
      return 0
    fi
  fi
  printf '%s\n' "$output"
}

do_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper run 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\trun command failed with no output\n' "$MODULE_ID" >&2
      return 1
    fi
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

do_dry_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  run_helper run --dry-run
}

do_uninstall() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper uninstall 2>&1)"; then
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

do_uninstall_dry_run() {
  run_helper uninstall --dry-run
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
    return 0
  fi
  do_run
}

uninstall_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    do_uninstall_dry_run
    return
  fi
  do_uninstall
}

main() {
  local action="" dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --uninstall) action=uninstall ;;
      --dry-run) dry_run=true ;;
      --webhook)
        shift
        EXTRA_ARGS+=(--webhook "${1:-}")
        ;;
      --name)
        shift
        EXTRA_ARGS+=(--name "${1:-}")
        ;;
      --channel-url)
        shift
        EXTRA_ARGS+=(--channel-url "${1:-}")
        ;;
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
    uninstall) uninstall_module "$dry_run" ;;
  esac
}

main "$@"
