#!/usr/bin/env bash
# Module: acs-lightspeed - OpenShift Lightspeed on Central OCP + RHACS risk AI
set -euo pipefail

MODULE_ID="acs-lightspeed"
MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${MODULE_DIR}/../.." && pwd)"
[[ -f "$ROOT/config/modules.json" ]] || { echo "ROOT miscomputed: $ROOT" >&2; exit 1; }
HELPER="${MODULE_DIR}/acs_lightspeed.py"
PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

LS_PLANE=""

usage() {
  cat <<EOF
# acs-lightspeed

Installs and configures **OpenShift Lightspeed** on Central’s OpenShift cluster
(with a real LLM via lab Integration Secrets), grants Central’s ServiceAccount
\`ols-user\`, allows Central traffic to OLS, then verifies RHACS 5.0 Lightspeed
connectivity (\`ROX_LIGHTSPEED_RISK_SUMMARY\` + \`GET /v1/lightspeed/status\`).

Talk track: [\`acs-lightspeed-demo.md\`](/help?doc=acs-lightspeed-demo)

Catalog: \`impactPlanes: ["central-ocp", "central-api"]\` (not ACSCS-safe).
Not related to OpenShift MCP / mcp-gateway / ACS MCP modules.

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central-api|central-ocp]
$(basename "$0") --run [--dry-run] [--plane central-api|central-ocp]
$(basename "$0") --uninstall [--dry-run] [--plane central-api|central-ocp]
\`\`\`

## Flags

- \`--plane central-ocp\` - Operator, LLM Secret, OLSConfig, ols-user binding, NetworkPolicy
- \`--plane central-api\` - verify feature flag + Lightspeed status against Central
- omit \`--plane\` - both (oc then API)
- \`--plane secured-cluster\` - ignored (Central-side; warn on stderr)
- \`--secured-cluster-id ID\` - ignored
- \`--dry-run\` - print the plan; change nothing

## Status Info

- \`central-ocp\`: namespace, Subscription/CSV, Secret present, OLSConfig, NetworkPolicy, binding, OLS pods
- \`central-api\`: \`ROX_LIGHTSPEED_RISK_SUMMARY\`, \`/v1/lightspeed/status\`
- ok summary includes Central Risk URL when available

## Pre Conditions

- RHACS 5.0+ Central running on OpenShift (same cluster that will host OLS)
- Lab credentials: Central OpenShift access + LLM API token under Integration Secrets → OpenShift Lightspeed LLM

## Side effects

- \`--run\` (\`central-ocp\`): creates \`openshift-lightspeed\` Operator Subscription, Secret, OLSConfig, NetworkPolicy, ClusterRoleBinding
- \`--run\` (\`central-api\`): read-only verification (waits until Lightspeed status is available)
- \`--uninstall\` (\`central-ocp\`): removes demo-owned OLS resources and the Operator Subscription/namespace this module installed
EOF
}

run_helper() {
  if [[ -n "$LS_PLANE" ]]; then
    "$PYTHON" "$HELPER" --plane "$LS_PLANE" "$@"
  else
    "$PYTHON" "$HELPER" "$@"
  fi
}

do_status() {
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
  local output state
  if ! output="$(run_helper uninstall --cli --dry-run 2>&1)"; then
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

# shellcheck source=_central_side_orch_flags.sh
source "${ROOT}/modules/_central_side_orch_flags.sh"

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
        central_side_handle_plane "$prog" "$1" || exit 1
        case "$1" in
          central-api|central-ocp) LS_PLANE="$1" ;;
          central) LS_PLANE="" ;;
          *) ;;
        esac
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "${prog}: --secured-cluster-id needs an id" >&2; exit 1; }
        central_side_ignore_sc_id "$prog" "$1"
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
