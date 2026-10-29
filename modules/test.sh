#!/usr/bin/env bash
# Copy this file to modules/<id>.sh, then search for TODO and fill them in.
# Example: cp templates/module-skeleton.sh modules/my-feature.sh && chmod +x modules/my-feature.sh
set -euo pipefail

MODULE_ID="test"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

do_run() {
  echo "${MODULE_ID}: TODO: implement do_run" >&2
  return 1
}

do_dry_run() {
  cat <<EOF
${MODULE_ID}: dry-run
  TODO: describe planned changes here (no mutations).
EOF
}

do_uninstall() {
  echo "${MODULE_ID}: uninstall is not implemented for this module." >&2
  printf '%s\terror\tuninstall not implemented\n' "$MODULE_ID"
  return 1
}

do_uninstall_dry_run() {
  echo "${MODULE_ID}: uninstall is not implemented for this module." >&2
  printf '%s\terror\tuninstall not implemented\n' "$MODULE_ID"
  return 1
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
