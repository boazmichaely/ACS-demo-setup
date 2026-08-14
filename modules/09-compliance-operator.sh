#!/usr/bin/env bash
# Module: compliance-operator — OLM install + Central compliance scan schedule
set -euo pipefail

MODULE_ID="compliance-operator"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB="${ROOT}/modules/compliance_operator_lib.sh"

usage() {
  cat <<EOF
Usage: $(basename "$0") --help
       $(basename "$0") --status
       $(basename "$0") --run [--dry-run]

Purpose:
  Install OpenShift Compliance Operator via OLM on the secured cluster, then
  create/update a compliance scan configuration in Central (RHACS UI equivalent).
  Does not apply ScanSetting/ScanSettingBinding CRs on the cluster.

Depends on:
  - oc logged into the lab secured OpenShift cluster
  - lab-credentials.json Central API token and console URL

Environment:
  COMPLIANCE_OPERATOR_NAMESPACE           Default openshift-compliance
  COMPLIANCE_SUBSCRIPTION_NAME            Default compliance-operator-sub
  COMPLIANCE_OPERATOR_CHANNEL             Default stable
  COMPLIANCE_CSV_TIMEOUT_SECONDS          Default 600
  COMPLIANCE_ROLLOUT_TIMEOUT_SECONDS      Default 240
  ACS_COMPLIANCE_PATCH_NODE_SELECTOR      Set to 1 to clear namespace node selector
  ACS_COMPLIANCE_SCAN_NAME                Default acs-demo-setup
  ACS_COMPLIANCE_CLUSTER_NAME             Secured cluster name in Central (auto from SecuredCluster CR)
  ACS_COMPLIANCE_PROFILE_SYNC_TIMEOUT_SECONDS  Default 600 (poll every 3s on --run)

Side effects:
  --run applies OLM resources on the secured cluster and scan configuration via Central API
EOF
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
  [[ -f "$LIB" ]] || {
    printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$LIB"
    exit 1
  }

  # shellcheck source=compliance_operator_lib.sh
  COMPLIANCE_MODULE_ROOT="$ROOT"
  source "$LIB"

  case "$action" in
    status)
      compliance_operator_emit_status
      ;;
    run)
      compliance_operator_run "$dry_run"
      ;;
  esac
}

main "$@"
