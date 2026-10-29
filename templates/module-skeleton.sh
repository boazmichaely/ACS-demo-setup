#!/usr/bin/env bash
# Copy this file to modules/<id>.sh, then search for TODO and fill them in.
# Example: cp templates/module-skeleton.sh modules/my-feature.sh && chmod +x modules/my-feature.sh
set -euo pipefail

# TODO: set to the same id you put in config/modules.json (and in the filename).
MODULE_ID="my-feature"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# When this file lives in modules/, ROOT is the repo root.
# If you are still editing under templates/, adjust paths after you copy.

usage() {
  cat <<EOF
Usage: $(basename "$0") --help
       $(basename "$0") --status
       $(basename "$0") --run [--dry-run]
       $(basename "$0") --uninstall [--dry-run]

Purpose:
  TODO: one short paragraph - what this module sets up in the demo lab.

Depends on:
  TODO: list other module ids, or "none".
  TODO: Central credentials / oc / pull-secret / etc. as needed.

Environment:
  ACS_LAB_CREDENTIALS_FILE   Override path to lab-credentials.json
  TODO: list any module-specific env vars (or delete this line).

Side effects:
  --run TODO: what gets created or updated (Central API paths, namespaces, …).
  --uninstall TODO: what gets removed, or say "not supported" if you leave it unimplemented.
EOF
}

# ---------------------------------------------------------------------------
# Implement these functions. Keep the flag parsing in main() as-is.
# ---------------------------------------------------------------------------

# Print exactly one status line with three fields separated by tabs:
#   id<TAB>state<TAB>message
# state must be: ok | needs-run | error
# Example: printf '%s\tok\tall set\n' "$MODULE_ID"
do_status() {
  # TODO: replace with a real check against the lab.
  printf '%s\tneeds-run\tTODO: implement do_status in modules/%s.sh\n' \
    "$MODULE_ID" "$MODULE_ID"
}

# Apply the desired state. Must be safe to run twice.
# Exit 0 on success; non-zero on failure (message on stderr).
do_run() {
  # TODO: create/update whatever this module owns, then preferably re-check.
  echo "${MODULE_ID}: TODO: implement do_run" >&2
  return 1
}

# Print the plan only. Do not change the cluster or Central. Exit 0.
do_dry_run() {
  # TODO: describe what do_run would change.
  cat <<EOF
${MODULE_ID}: dry-run
  TODO: describe planned changes here (no mutations).
EOF
}

# Remove what --run created. Safe to run when already absent when possible.
# If uninstall is not supported, fail with a clear message (do not pretend success).
do_uninstall() {
  # TODO: implement real uninstall, or keep this graceful refusal.
  echo "${MODULE_ID}: uninstall is not implemented for this module." >&2
  printf '%s\terror\tuninstall not implemented\n' "$MODULE_ID"
  return 1
}

# Print uninstall plan only. Exit non-zero if uninstall is not supported.
do_uninstall_dry_run() {
  # TODO: describe what do_uninstall would remove, or keep this refusal.
  echo "${MODULE_ID}: uninstall is not implemented for this module." >&2
  printf '%s\terror\tuninstall not implemented\n' "$MODULE_ID"
  return 1
}

# ---------------------------------------------------------------------------
# Optional: call a Python helper for Central API / heavy JSON.
# Copy templates/module-helper.py to modules/<id_with_underscores>.py only if
# you need it. Example for id "my-feature" → modules/my_feature.py
#
#   HELPER="${ROOT}/modules/my_feature.py"
#   PYTHON="${ACS_DEMO_PYTHON:-}"
#   if [[ -z "$PYTHON" ]]; then
#     if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
#       PYTHON="${ROOT}/gui/.venv/bin/python"
#     else
#       PYTHON="$(command -v python3)"
#     fi
#   fi
#   run_helper() { "$PYTHON" "$HELPER" "$@"; }
#   # Then in do_status / do_run / do_uninstall, call run_helper and print status.
# ---------------------------------------------------------------------------

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
