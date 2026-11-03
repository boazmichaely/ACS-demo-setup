#!/usr/bin/env bash
# Module: users-part3-acs - ACS roles and access scopes for demo users (Users Part 3)
set -euo pipefail

MODULE_ID="users-part3-acs"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/users_part3_acs.py"
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
       $(basename "$0") --uninstall [--dry-run]

Purpose:
  Map the OpenShift logins adam, boaz, and chris to ACS roles and
  access scopes for Central. The OpenShift console Security plugin
  still follows OpenShift RBAC from Part 1; this module does not change
  that.

  Part 1 gives boaz and chris different OpenShift roles. Part 3 adds
  ACS roles and scopes for Central login. Adam becomes Admin in ACS.
  Boaz and chris become Analysts in ACS, scoped to ms-demo only.

  Act 2 of the demo compares console vs ACS Central:
    boaz  aligned    - both sides cover ms-demo only
    chris misaligned - OCP admin on ms-demo and acs-init-container-test,
                       ACS only ms-demo (init-demo missing in Central)

  This module is Part 3 of the Users series. Part 1 (OCP) creates the
  OpenShift users and RBAC in users-part1-ocp. Part 2 (OAuth) configures
  Central OpenShift login in users-part2-oauth. Part 3 (ACS) is this
  module.

  Adam maps to the built-in Admin role with full ACS access. Boaz maps
  to boaz-in-acs as an Analyst with access scope limited to ms-demo.
  Chris maps to chris-in-acs as an Analyst with access scope limited to
  ms-demo, which is incomplete compared with his two OpenShift
  administrator namespaces.

  Demo script (Act 1 console / Act 2 console vs Central):
    modules/users-part1-ocp-demo.md
    GUI: /help?doc=users-part1-ocp-demo
  (Status → Demo also links there.)

Depends on:
  users-part2-oauth, which provides an openshift-type auth provider on Central
  Lab credentials with Central API access
  Exactly one secured cluster in Central, or ACS_SECURED_CLUSTER_NAME

Environment:
  ACS_LAB_CREDENTIALS_FILE     Override path to lab-credentials.json
  ACS_DEMO_PYTHON              Override Python interpreter
  ACS_SECURED_CLUSTER_NAME     Override ACS cluster name used in the scope

Side effects:
  --run reconciles access scope ms-demo, roles boaz-in-acs and
    chris-in-acs, and OpenShift auth group rules for adam, boaz, and chris
  --uninstall removes those roles, that scope, and those name rules.
    It does not remove the Part 2 auth provider. It also does not remove
    the default rule that maps unmatched users to None

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

main() {
  local action="" dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --uninstall) action=uninstall ;;
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
    uninstall) uninstall_module "$dry_run" ;;
  esac
}

main "$@"
