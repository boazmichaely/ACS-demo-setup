#!/usr/bin/env bash
# Module: splunk-TA - Splunk Operator + Standalone lab + RHACS Technology Add-on
set -euo pipefail

MODULE_ID="splunk-TA"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB="${ROOT}/modules/splunk_ta_lib.sh"

usage() {
  cat <<EOF
# splunk-TA

Deploy Splunk Operator and a Splunk Free Standalone on the lab OpenShift
cluster, expose Splunk Web, and install the RHACS Splunkbase Technology
Add-on (TA) from a local \`.tgz\`.

Central endpoint, API token, and modular inputs are configured in the
Splunk UI after install - see
[modules/splunk-TA-demo.md](https://github.com/boazmichaely/ACS-demo-setup/blob/main/modules/splunk-TA-demo.md).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status
$(basename "$0") --run [--dry-run] [--ta-dir DIR] [--skip-ta]
$(basename "$0") --uninstall [--dry-run]
\`\`\`

## Flags

- \`--ta-dir DIR\` - Directory with the Splunkbase \`.tgz\` (default \`~/code/Splunk\`)
- \`--skip-ta\` - Install Operator + Standalone + Route only (no TA package)
- \`--dry-run\` - Print the plan; change nothing

## Installation (TA package)

The \`.tgz\` is **not** in this repo (Splunkbase license). Do not commit it.

1. Download **Red Hat Advanced Cluster Security** from
   [Splunkbase app 5315](https://splunkbase.splunk.com/app/5315)
   (keep the Splunkbase filename).
2. Place it under \`~/code/Splunk/\` (or pass \`--ta-dir\`).
3. \`$(basename "$0") --run\`
4. In Splunk Web, set Central endpoint + API token and create modular inputs.
   Product doc:
   [RHACS 4.10 - Integrating with Splunk](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.10/html/integrating/integrate-with-splunk)

## Depends on

- \`oc\` via lab-credentials.json (per-lab kubeconfig)
- \`helm\` on PATH
- RHACS TA \`.tgz\` under \`--ta-dir\` (unless \`--skip-ta\`)

## Side effects

- \`--run\` applies cluster-scoped CRDs, Helm operator, Standalone + PVCs, Route,
  and installs the TA into the Splunk pod (unless \`--skip-ta\`).
- \`--uninstall\` deletes Standalone, Helm release, and namespace; leaves CRDs.
EOF
}

if [[ ! -f "$LIB" ]]; then
  printf '%s\terror\tmissing helper %s\n' "$MODULE_ID" "$LIB"
  exit 1
fi

# shellcheck source=splunk_ta_lib.sh
SPLUNK_MODULE_ROOT="$ROOT"
# shellcheck disable=SC1090
source "$LIB"

emit_status() {
  sta_emit_status
}

run_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    sta_run_plan
    return
  fi
  sta_run
}

uninstall_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    sta_uninstall_plan
    return
  fi
  sta_uninstall
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
      --skip-ta) STA_SKIP_TA=true ;;
      --ta-dir)
        shift
        [[ -n "${1:-}" ]] || {
          echo "$(basename "$0"): --ta-dir needs a directory" >&2
          exit 1
        }
        STA_TA_DIR="$1"
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
