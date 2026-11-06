#!/usr/bin/env bash
# Module: signature-integration - Red Hat Public Cosign trust + Inform policy + image priming
set -euo pipefail

MODULE_ID="signature-integration"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/signature_integration.py"
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
# signature-integration

Ensure Signature Integration **Red Hat Public** (release key 3), an Inform
Build+Deploy policy **Images must be signed by Red Hat Public**, and prime
three signed images via Central image scan (no deploy).

Catalog: \`impactPlanes: ["central"]\` (Central API only).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central] [--secured-cluster-id ID]...
$(basename "$0") --run [--dry-run] [--plane central] [--secured-cluster-id ID]...
$(basename "$0") --uninstall [--dry-run] [--plane central] [--secured-cluster-id ID]...
$(basename "$0") --hard-delete [--dry-run]
\`\`\`

## Flags

- \`--plane central\` - implied; accepted as a no-op
- \`--plane openshift\` - ignored (Central-only; warn on stderr)
- \`--secured-cluster-id ID\` - ignored (no OpenShift work; warn)
- \`--dry-run\` - Print the plan; change nothing
- \`--hard-delete\` - Remove Inform policy and Red Hat Public (CLI only)

## Status Info

- **Red Hat Public** - signature integration present
- **Images must be signed by Red Hat Public** - Inform policy present
- **Signed digests** - primed image digests Central has scanned

## Pre Conditions

none

## Side effects

- \`--run\` ensures Red Hat Public + Inform policy; primes images
- \`--uninstall\` removes the Inform policy only (leaves Red Hat Public;
  \`--status\` stays needs-run until \`--run\` or \`--hard-delete\`)
- \`--hard-delete\` removes the Inform policy and **Red Hat Public**
  (CLI only, not GUI). Shows inventory, then requires typing \`DELETE\`
  in an interactive terminal
- Does not modify Signature Integration **Red Hat**
- Does not delete images from Central
EOF
}

run_helper() {
  "$PYTHON" "$HELPER" "$@"
}

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
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

do_dry_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  run_helper run --dry-run --cli
}

do_uninstall() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper uninstall --cli 2>&1)"; then
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

do_uninstall_dry_run() {
  run_helper uninstall --dry-run --cli
}

do_hard_delete() {
  local dry_run="${1:-false}"

  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi

  if [[ ! -t 0 ]] || [[ -n "${CI:-}" ]]; then
    echo "${MODULE_ID}: --hard-delete requires an interactive terminal (human confirmation)." >&2
    printf '%s\terror\thard-delete requires interactive TTY\n' "$MODULE_ID"
    return 1
  fi

  local inventory
  if ! inventory="$(run_helper hard-delete-inventory --cli 2>&1)"; then
    printf '%s\n' "$inventory" >&2
    printf '%s\terror\thard-delete inventory failed\n' "$MODULE_ID"
    return 1
  fi
  # Show inventory to the human (strip machine trailer from display if needed)
  printf '%s\n' "$inventory" | grep -v '^ACS_HARD_DELETE_JSON=' || true
  # Always flush before prompt
  sync 2>/dev/null || true

  if [[ "$dry_run" == "true" ]]; then
    echo "${MODULE_ID}: dry-run hard-delete — inventory shown; nothing deleted."
    printf '%s\tok\thard-delete dry-run (inventory only)\n' "$MODULE_ID"
    return 0
  fi

  local answer
  printf 'Type DELETE to confirm: '
  IFS= read -r answer || true
  if [[ "$answer" != "DELETE" ]]; then
    echo "${MODULE_ID}: aborted (expected DELETE)." >&2
    printf '%s\terror\thard-delete aborted\n' "$MODULE_ID"
    return 1
  fi

  local output state
  if ! output="$(run_helper hard-delete-apply --cli 2>&1)"; then
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
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
      --hard-delete) action=hard-delete ;;
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
    hard-delete) do_hard_delete "$dry_run" ;;
  esac
}

main "$@"
