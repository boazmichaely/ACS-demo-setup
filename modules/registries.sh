#!/usr/bin/env bash
# Module: registries - ACS image integrations from Central OpenShift pull secret
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
# registries

Configure Central image registry integrations needed for vulnerability scanning.
Credentials come from **Central's OpenShift** \`openshift-config/pull-secret\`
(not from a secured cluster):

- Public Quay.io (robot credentials from that pull-secret)
- registry.redhat.io (from the same pull-secret)
- Public Google Artifact Registry \`us-central1-docker.pkg.dev\` (anonymous;
  so ms-demo Online Boutique images can be scanned)

Catalog: \`impactPlanes: ["central-api", "central-ocp"]\` (not ACSCS-safe).
Pull-secret is read from **Central's OpenShift** (not from a secured cluster).

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central-api|central-ocp] [--secured-cluster-id ID]...
$(basename "$0") --run [--dry-run] [--plane central-api|central-ocp] [--secured-cluster-id ID]...
$(basename "$0") --uninstall [--dry-run] [--plane central-api|central-ocp] [--secured-cluster-id ID]...
\`\`\`

## Flags

- \`--plane central-ocp\` - read Central OpenShift pull-secret via \`oc\`, cache robot credentials for \`central-api\` (no Central API)
- \`--plane central-api\` - create/update Central image integrations from that cache (no \`oc\`; run \`central-ocp\` first when split)
- omit \`--plane\` / legacy \`central\` - both in one process (oc then API; refreshes cache)
- \`--plane secured-cluster\` - ignored (Central-side; warn on stderr)
- \`--secured-cluster-id ID\` - ignored (integrations are Central-global; warn)
- \`--dry-run\` - Print the plan; change nothing

## Status Info

- \`central-ocp\`: Central OpenShift \`openshift-config/pull-secret\` hosts
- \`central-api\` / both: one fold per registry integration in Central
  (\`quay.io\`, \`registry.redhat.io\`, Google Artifact Registry)

## Pre Conditions

none

## Side effects

- \`--run\` (\`central-ocp\`): validates pull-secret and writes \`.cache/registries-pull-secret.json\`
- \`--run\` (\`central-api\`): creates or updates image integrations from the cache (Central API only)
- \`--run\` (both / omit \`--plane\`): oc pull-secret + Central API in one process
- \`--uninstall\` is not supported (refuses rather than guessing how to undo integrations)
EOF
}

# Orchestrator may set --plane central-api|central-ocp (empty = both).
REG_PLANE=""

run_helper() {
  if [[ -n "${REG_PLANE}" ]]; then
    "$PYTHON" "$HELPER" "$@" --plane "${REG_PLANE}"
  else
    "$PYTHON" "$HELPER" "$@"
  fi
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

# Undoing registry integrations is not automated - refuse clearly.
do_uninstall() {
  cat >&2 <<EOF
${MODULE_ID}: uninstall is not supported.
This module creates or updates Central image integrations from Central's
OpenShift pull-secret. Removing them automatically is not safe or well-defined
here (shared integrations, other consumers). Adjust or delete integrations in
the RHACS UI if you need to undo them by hand.
EOF
  printf '%s\terror\tuninstall not supported for registries\n' "$MODULE_ID"
  return 1
}

do_uninstall_dry_run() {
  do_uninstall
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
          central-api|central-ocp) REG_PLANE="$1" ;;
          central) REG_PLANE="" ;; # legacy both
          *) ;; # ignored secured-cluster etc.
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
