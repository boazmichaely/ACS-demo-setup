#!/usr/bin/env bash
# Module: compliance-operator - OLM install + Central compliance scan schedule
# Entrypoint shape matches templates/module-skeleton.sh; logic in compliance_operator_lib.sh
set -euo pipefail

MODULE_ID="compliance-operator"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB="${ROOT}/modules/compliance_operator_lib.sh"

usage() {
  cat <<EOF
# compliance-operator

Installs the OpenShift Compliance Operator (OLM) on selected secured
cluster(s) and maintains one Central scan schedule
(\`ocp4-cis-scan-schedule\`, profiles \`ocp4-cis\` + \`ocp4-cis-node\`, daily 02:00).

Does not apply ScanSetting/ScanSettingBinding CRs on the cluster.

\`impactPlanes: ["central-api","secured-cluster"]\`. Prefer the orchestrator:

\`\`\`
./scripts/acs-setup.sh --run --module compliance-operator \\
  --secured-cluster-id <id1> --secured-cluster-id <id2>
\`\`\`

That runs OpenShift once per id, then Central once with the full selection.
With no \`--secured-cluster-id\`, default is the lab soft-default SC
(\`activeSecuredClusterId\`) only (not every lab SC).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central-api|secured-cluster] [--secured-cluster-id ID]...
$(basename "$0") --run [--dry-run] [--plane central-api|secured-cluster] [--secured-cluster-id ID]... [--patch-node-selector]
$(basename "$0") --uninstall [--dry-run] [--plane central-api|secured-cluster] [--secured-cluster-id ID]...
\`\`\`

## Flags

- \`--plane secured-cluster\` - Compliance Operator OLM install/status/uninstall on **one** SC (legacy \`openshift\`)
- \`--plane central-api\` - Central CIS scan schedule membership for the **selection** (legacy \`central\`)
- omit \`--plane\` - both in one process (legacy; may still loop SCs internally)
- \`--secured-cluster-id ID\` - repeatable lab SC id. secured-cluster plane: exactly one
  per invoke (orchestrator fans out). Central plane: full selection for schedule merge/drop.
  Soft-default SC when none passed
- \`--secured-cluster NAME\` - legacy name filter (prefer \`--secured-cluster-id\`)
- \`--patch-node-selector\` - Clear \`openshift.io/node-selector\` on
  \`openshift-compliance\` during OLM install
- \`--dry-run\` - Print the plan; change nothing

## Status Info

Per selected secured cluster: Compliance Operator overview and Central schedule
membership for the selection.

## Pre Conditions

none

## Side effects

- \`--run\` (secured-cluster): install/verify OLM on the selected SC
- \`--run\` (central-api): merge selected clusters into the shared scan schedule
- \`--uninstall\` (secured-cluster): remove OLM on the selected SC
- \`--uninstall\` (central-api): drop selected clusters from the schedule (delete if empty)
EOF
}

if [[ ! -f "$LIB" ]]; then
  printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$LIB"
  exit 1
fi

# shellcheck source=compliance_operator_lib.sh
COMPLIANCE_MODULE_ROOT="$ROOT"
source "$LIB"

do_status() {
  compliance_operator_emit_status
}

do_run() {
  compliance_operator_run false
}

do_dry_run() {
  compliance_operator_run true
}

do_uninstall() {
  compliance_operator_uninstall false
}

do_uninstall_dry_run() {
  compliance_operator_uninstall true
}

emit_status() {
  # Lib prints status (and optional sections) and sets the exit code.
  do_status
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
      --patch-node-selector) CO_PATCH_NODE_SELECTOR=true ;;
      --plane)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --plane needs central-api|secured-cluster" >&2; exit 1; }
        CO_PLANE="$1"
        case "$CO_PLANE" in
          central-api|secured-cluster|central|openshift) ;;
          *)
            echo "$(basename "$0"): --plane must be central-api or secured-cluster" >&2
            exit 1
            ;;
        esac
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --secured-cluster-id needs an id" >&2; exit 1; }
        CO_SC_IDS+=("$1")
        ;;
      --secured-cluster)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --secured-cluster needs a name" >&2; exit 1; }
        CO_SECURED_CLUSTER="$1"
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
