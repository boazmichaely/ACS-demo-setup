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
# slack-notifier

Ensure a Slack notifier in Central (default channel \`#acs-demo-notifier\`).

Defaults ship in \`config/slack-notifier.defaults.json\`. Lab credentials may
override notifier name, webhook, and channel URL.

\`--run\` sends Central's Test notifier message, then a second lab-context
ping (lab name, Central host, secured cluster) via the Incoming Webhook,
then attaches this notifier to every Central policy with category **DEMO**.

Catalog: \`impactPlanes: ["central-api"]\` (central-api only).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central-api] [--secured-cluster-id ID]... [--webhook URL] [--name NAME] [--channel-url URL]
$(basename "$0") --run [--dry-run] [--plane central-api] [--secured-cluster-id ID]... [--webhook URL] [--name NAME] [--channel-url URL]
$(basename "$0") --uninstall [--dry-run] [--plane central-api] [--secured-cluster-id ID]... [--webhook URL] [--name NAME] [--channel-url URL]
\`\`\`

## Flags

- \`--plane central-api\` - implied; accepted as a no-op (legacy \`central\` also accepted)
- \`--plane secured-cluster\` / \`central-ocp\` - ignored (central-api-only; warn on stderr)
- \`--secured-cluster-id ID\` - ignored (notifier is Central-global; warn)
- \`--webhook URL\` - Override Incoming Webhook for this invocation
- \`--name NAME\` - Override Central notifier display name
- \`--channel-url URL\` - Override Slack channel deep link in status folds
- \`--dry-run\` - Print the plan; change nothing

## Status Info

- Slack notifier name, Central id, webhook source, and channel link
- One fold per Central policy with category **DEMO** (notifier attached or missing)

## Pre Conditions

none

## Side effects

- \`--run\` creates/updates the Slack notifier; Central test + lab-context
  webhook ping; attaches the notifier to DEMO-category policies
- \`--uninstall\` detaches this notifier from DEMO policies and deletes the
  notifier (policies and DEMO category stay)
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

# shellcheck source=_central_only_orch_flags.sh
source "${ROOT}/modules/_central_only_orch_flags.sh"

main() {
  local action="" dry_run=false
  local prog
  prog="$(basename "$0")"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --uninstall) action=uninstall ;;
      --dry-run) dry_run=true ;;
      --plane)
        shift
        [[ $# -gt 0 ]] || { echo "${prog}: --plane needs a value" >&2; exit 1; }
        central_only_handle_plane "$prog" "$1" || exit 1
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "${prog}: --secured-cluster-id needs an id" >&2; exit 1; }
        central_only_ignore_sc_id "$prog" "$1"
        ;;
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
        echo "${prog}: unknown option: $1" >&2
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
