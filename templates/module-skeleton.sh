#!/usr/bin/env bash
# Copy this file to modules/<id>.sh, then search for TODO and fill them in.
# Example: cp templates/module-skeleton.sh modules/my-feature.sh && chmod +x modules/my-feature.sh
set -euo pipefail

# TODO: set to the same id you put in config/modules.json (and in the filename).
MODULE_ID="my-feature"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# When this file lives in modules/, ROOT is the repo root.
# If you are still editing under templates/, adjust paths after you copy.

# Set by orchestrator / CLI when impactPlanes includes openshift or both.
PLANE=""
# Lab secured-cluster id(s). OpenShift plane: at most one. Central: zero or more.
SC_IDS=()

usage() {
  cat <<EOF
# ${MODULE_ID}

TODO: one short paragraph - what this module sets up in the demo lab.

Prefer flags and constants over module-specific environment variables.
Do not dump tool-wide \`ACS_*\` credential paths in Usage.

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central|openshift] [--secured-cluster-id ID]...
$(basename "$0") --run [--dry-run] [--plane central|openshift] [--secured-cluster-id ID]...
$(basename "$0") --uninstall [--dry-run] [--plane central|openshift] [--secured-cluster-id ID]...
\`\`\`

## Flags

- \`--plane central|openshift\` - which plane this invocation owns (orchestrator sets for \`both\` modules)
- \`--secured-cluster-id ID\` - lab SC id (OpenShift: exactly one; Central: selection set)

## Status Info

TODO: what Status folds show after install (summary, or one bullet per fold).

## Pre Conditions

none

## Side effects

- \`--run\` TODO: what gets created or updated
- \`--uninstall\` TODO: what gets removed, or say "not supported"
EOF
}

# ---------------------------------------------------------------------------
# Implement these functions. Keep the flag parsing in main() as-is.
# ---------------------------------------------------------------------------

# --status must print BOTH:
#   1) ACS_SECTIONS_JSON={"sections":[...]}   (mandatory Status folds for the GUI)
#   2) id<TAB>state<TAB>message               (summary; state: ok | needs-run | error)
# See ADDING-A-MODULE.md ("Status output").
#
# Build the sections object with jq (readable), then emit one compact line.
# Supported bodyFormat values in the GUI: "prose" (default) and "json" only.
emit_status_sections() {
  # TODO: replace this object with real fold data for the lab.
  local sections_json prose_multiline
  prose_multiline="$(
    cat <<'EOF'
Body of a multi-line prose blob.
Each newline becomes a line break in the GUI.

Use bodyFormat "prose" for normal readable text (this is the default if omitted).
EOF
  )"
  sections_json="$(
    jq -nc \
      --arg prose_multi "$prose_multiline" \
      '{
        sections: [
          {
            group: "Group 1 header. e.g. Overview",
            title: "Title of first blob. e.g. Installed components",
            summary: "(optional) right hand side info (1/1 ready)",
            body: "Body of the first blob. e.g.: Installed network-policy.yaml, application.yaml",
            bodyFormat: "prose"
          },
          {
            group: "Group 2 header. e.g. Notes",
            title: "Title of second blob. e.g. Multi-line prose",
            summary: "(optional) right hand side info",
            body: $prose_multi,
            bodyFormat: "prose"
          },
          {
            group: "Group 3 header. e.g. Config",
            title: "Title of third blob. e.g. Config object",
            summary: "(optional) right hand side info (matched)",
            tag: "ok",
            tagLabel: "(optional) badge text; tag sets color (ok/ready, error/fail)",
            body: {
              note: "Body of the third blob. bodyFormat json pretty-prints this object in a monospace block",
              replicas: 1,
              image: "quay.io/example/app:1.0"
            },
            bodyFormat: "json"
          },
          {
            group: "Group 4 header. e.g. Workloads",
            title: "Title of fourth blob. e.g. Deployment",
            summary: "(optional) right hand side info (0/1 ready)",
            tag: "error",
            tagLabel: "(optional) badge text; tag sets color (ok/ready, error/fail)",
            body: {
              note: "Body of the fourth blob. e.g. status detail"
            },
            bodyFormat: "json"
          }
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  # TODO: replace fold body + summary with real checks against the lab.
  emit_status_sections
  printf '%s\tneeds-run\tTODO: implement do_status in modules/%s.sh\n' \
    "$MODULE_ID" "$MODULE_ID"
}

# Apply the desired state. Must be safe to run twice.
# Exit 0 on success; non-zero on failure (message on stderr).
do_run() {
  # TODO: create/update whatever this module owns, then preferably re-check.
  # OpenShift manifests MUST go through apply-labeled (see ADDING-A-MODULE Planes):
  #   local sc_id="${SC_IDS[0]:-}"
  #   local PYTHON="${ROOT}/gui/.venv/bin/python"
  #   local kc
  #   kc="$(cd "$ROOT" && "$PYTHON" -m lib.openshift login --print-kubeconfig ${sc_id:+--secured-cluster-id "$sc_id"})" || return 1
  #   export KUBECONFIG="$kc"
  #   "$PYTHON" -m lib.openshift apply-labeled ${sc_id:+--secured-cluster-id "$sc_id"} -f path/to.yaml
  echo "${MODULE_ID}: TODO: implement do_run (plane=${PLANE:-implied} sc_ids=${SC_IDS[*]:-none})" >&2
  return 1
}

# Print the plan only. Do not change the cluster or Central. Exit 0.
do_dry_run() {
  # TODO: describe what do_run would change.
  cat <<EOF
${MODULE_ID}: dry-run
  plane: ${PLANE:-implied}
  secured-cluster-ids: ${SC_IDS[*]:-none}
  TODO: describe planned changes here (no mutations).
EOF
}

# Remove what --run created. Safe to run when already absent when possible.
# If uninstall is not supported, fail with a clear message (do not pretend success).
do_uninstall() {
  # TODO: implement real uninstall, or keep this graceful refusal.
  # Prefer: python -m lib.openshift delete-by-demo-labels --secured-cluster-id "$sc_id" -n <ns>
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
      --plane)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --plane needs central|openshift" >&2; exit 1; }
        PLANE="$1"
        case "$PLANE" in
          central|openshift) ;;
          *)
            echo "$(basename "$0"): --plane must be central or openshift (got ${PLANE})" >&2
            exit 1
            ;;
        esac
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --secured-cluster-id needs an id" >&2; exit 1; }
        SC_IDS+=("$1")
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
