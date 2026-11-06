#!/usr/bin/env bash
# Module: users-part2-oauth - Central OpenShift auth provider (Users Part 2)
set -euo pipefail

MODULE_ID="users-part2-oauth"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/users_part2_oauth.py"
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
# users-part2-oauth

Configure Central to accept OpenShift login (openshift auth provider)
so the Users Part 1 people can sign into ACS with **Login with OpenShift**.

Part of the Users series:

- Part 1 (OCP) - OpenShift users + RBAC (\`users-part1-ocp\`)
- Part 2 (OAuth) - this module
- Part 3 (ACS) - ACS roles and scopes (\`users-part3-acs\`)

Demo script: \`modules/users-part1-ocp-demo.md\`
(GUI: \`/help?doc=users-part1-ocp-demo\`). Status → Demo also links there.

Catalog: \`impactPlanes: ["central"]\` (Central API only).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central] [--secured-cluster-id ID]...
$(basename "$0") --run [--dry-run] [--plane central] [--secured-cluster-id ID]...
$(basename "$0") --uninstall [--dry-run] [--plane central] [--secured-cluster-id ID]...
\`\`\`

## Flags

- \`--plane central\` - implied; accepted as a no-op
- \`--plane openshift\` - ignored (Central-only; warn on stderr)
- \`--secured-cluster-id ID\` - ignored (auth provider is Central-global; warn)
- \`--dry-run\` - Print the plan; change nothing

## Status Info

- Central API reachability
- OpenShift auth provider present (name and type)

## Pre Conditions

- \`users-part1-ocp\` installed (OpenShift users for the login demo)

## Side effects

- \`--run\` ensures one openshift-type auth provider on Central
  (creates name OpenShift when missing)
- \`--uninstall\` deletes that openshift-type auth provider
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
  if [[ -z "$output" ]]; then
    printf '%s\terror\trun command failed with no output\n' "$MODULE_ID" >&2
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

do_uninstall() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper uninstall --cli 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tuninstall failed with no output\n' "$MODULE_ID" >&2
      return 1
    fi
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" == "ok" ]]
}

do_uninstall_dry_run() {
  if [[ ! -f "$HELPER" ]]; then
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$HELPER" >&2
    return 1
  fi
  local output state
  if ! output="$(run_helper uninstall --cli --dry-run 2>&1)"; then
    if [[ -z "$output" ]]; then
      printf '%s\terror\tuninstall dry-run failed with no output\n' "$MODULE_ID" >&2
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
