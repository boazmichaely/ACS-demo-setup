#!/usr/bin/env bash
# ACS demo setup orchestrator - dispatches to modules/<id>.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULES_JSON="${ROOT}/config/modules.json"
MODULE_LAST_SECTIONS_JSON=""
MODULE_LAST_CAPTURE_ROW=""

usage() {
  cat <<'EOF'
Usage: acs-setup.sh --help
       acs-setup.sh --status [--module <id>] [--json]
       acs-setup.sh --run [--module <id>] [--dry-run]
       acs-setup.sh --oc-status
       acs-setup.sh --oc-login [--force]

Options:
  --help          Show this help
  --status        Report module status (all modules, or one with --module)
  --run           Run module(s)
  --module <id>   Limit to one module id from config/modules.json
  --json          With --status: emit JSON array (for GUI)
  --dry-run       With --run: pass through to module (planned actions only)

OpenShift (active lab; lab-credentials.json is source of truth):
  --oc-status     Is oc ready for the active lab? (OK/PROBLEM + next step)
  --oc-login      Create/refresh the active lab kubeconfig from lab-credentials
  --force         With --oc-login: force a fresh oc login
EOF
}

acs_python() {
  if [[ -n "${ACS_DEMO_PYTHON:-}" ]]; then
    printf '%s' "$ACS_DEMO_PYTHON"
  elif [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    printf '%s' "${ROOT}/gui/.venv/bin/python"
  else
    command -v python3
  fi
}

run_openshift_cli() {
  # Args are forwarded to: python -m lib.openshift …
  local py
  py="$(acs_python)"
  [[ -n "$py" ]] || die "python3 not found (set ACS_DEMO_PYTHON or use gui/.venv)"
  (cd "$ROOT" && "$py" -m lib.openshift "$@")
}

die() {
  echo "acs-setup: $*" >&2
  exit 1
}

need_jq() {
  command -v jq >/dev/null 2>&1 || die "jq is required"
}

module_meta() {
  local id="$1" field="$2"
  jq -r --arg id "$id" --arg f "$field" '
    .modules[] | select(.id == $id) | .[$f]
  ' "$MODULES_JSON"
}

module_script_path() {
  local id="$1"
  local found
  found="$(module_meta "$id" id)"
  [[ -n "$found" && "$found" != "null" ]] || die "unknown module id: $id"
  printf '%s/modules/%s.sh' "$ROOT" "$id"
}

# Catalog order in modules.json (1-based index for display / JSON "number").
module_display_number() {
  local id="$1"
  jq -r --arg id "$id" '
    .modules
    | to_entries
    | map(select(.value.id == $id) | .key + 1)
    | first // empty
  ' "$MODULES_JSON"
}

module_ids_sorted() {
  jq -r '.modules[].id' "$MODULES_JSON"
}

module_status_capture() {
  local id="$1"
  local script output tsv_line sections_json=""
  MODULE_LAST_SECTIONS_JSON=""
  MODULE_LAST_CAPTURE_ROW=""

  script="$(module_script_path "$id")"
  if [[ ! -x "$script" ]]; then
    MODULE_LAST_CAPTURE_ROW="${id}"$'\t'"needs-run"$'\t'"module script not installed"
    printf '%s\n' "$MODULE_LAST_CAPTURE_ROW"
    return 0
  fi

  output="$("$script" --status 2>&1 || true)"
  if [[ -z "$output" ]]; then
    MODULE_LAST_CAPTURE_ROW="${id}"$'\t'"error"$'\t'"module status produced no output"
    printf '%s\n' "$MODULE_LAST_CAPTURE_ROW"
    return 0
  fi

  sections_json="$(printf '%s\n' "$output" | awk '/^ACS_SECTIONS_JSON=/ { sub(/^ACS_SECTIONS_JSON=/, ""); print; exit }')"
  if [[ -n "$sections_json" ]] && printf '%s' "$sections_json" | jq -e '.sections | type == "array"' >/dev/null 2>&1; then
    MODULE_LAST_SECTIONS_JSON="$sections_json"
  fi

  tsv_line="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { line = $0 } END { print line }')"
  if [[ -z "$tsv_line" ]]; then
    MODULE_LAST_CAPTURE_ROW="${id}"$'\t'"error"$'\t'"module status produced no TSV row"
    printf '%s\n' "$MODULE_LAST_CAPTURE_ROW"
    return 0
  fi
  MODULE_LAST_CAPTURE_ROW="$tsv_line"
  printf '%s\n' "$MODULE_LAST_CAPTURE_ROW"
}

module_status_row() {
  module_status_capture "$1"
}

module_status_sections() {
  local payload="$MODULE_LAST_SECTIONS_JSON"
  if [[ -n "$payload" ]]; then
    jq -c '.sections' <<<"$payload"
  fi
}

status_tsv() {
  local filter_id="${1:-}"
  echo -e "id\tstate\tmessage"
  if [[ -n "$filter_id" ]]; then
    module_status_row "$filter_id"
  else
    while IFS= read -r id; do
      module_status_row "$id"
    done < <(module_ids_sorted)
  fi
}

status_json() {
  local filter_id="${1:-}"
  local ids=()
  if [[ -n "$filter_id" ]]; then
    ids=("$filter_id")
  else
    # Bash 3.2 (macOS /bin/bash) has no mapfile
    while IFS= read -r id; do
      [[ -n "$id" ]] && ids+=("$id")
    done < <(module_ids_sorted)
  fi

  local rows=()
  local id row state message num label depends base_row
  for id in "${ids[@]}"; do
    # Avoid $(module_status_capture): command substitution runs in a subshell and
    # drops MODULE_LAST_SECTIONS_JSON before we build JSON rows.
    module_status_capture "$id" >/dev/null
    row="$MODULE_LAST_CAPTURE_ROW"
    state="$(printf '%s' "$row" | awk -F'\t' '{print $2}')"
    message="$(printf '%s' "$row" | awk -F'\t' '{for (i=3;i<=NF;i++) {if (i>3) printf "\t"; printf "%s", $i}}')"
    num="$(module_display_number "$id")"
    [[ -n "$num" ]] || die "unknown module id: $id"
    label="$(module_meta "$id" label)"
    depends="$(jq -c --arg id "$id" '.modules[] | select(.id == $id) | .dependsOn' "$MODULES_JSON")"
    base_row="$(jq -nc \
      --arg id "$id" \
      --argjson number "$num" \
      --arg label "$label" \
      --arg state "$state" \
      --arg message "$message" \
      --argjson dependsOn "$depends" \
      '{id: $id, number: $number, label: $label, state: $state, message: $message, dependsOn: $dependsOn}')"
    if [[ -n "$MODULE_LAST_SECTIONS_JSON" ]]; then
      sections="$(printf '%s' "$MODULE_LAST_SECTIONS_JSON" | jq -c '.sections' || true)"
      if [[ -n "$sections" ]]; then
        rows+=("$(jq -nc --argjson base "$base_row" --argjson sections "$sections" '$base + {sections: $sections}')")
      else
        rows+=("$base_row")
      fi
    else
      rows+=("$base_row")
    fi
  done

  local joined=""
  local i
  for i in "${!rows[@]}"; do
    [[ -n "$joined" ]] && joined+=","
    joined+="${rows[$i]}"
  done
  printf '[%s]\n' "$joined"
}

run_modules() {
  local filter_id="${1:-}"
  local dry_run="${2:-false}"
  local ids=()
  local failed=0

  if [[ -n "$filter_id" ]]; then
    ids=("$filter_id")
  else
    # Bash 3.2 (macOS /bin/bash) has no mapfile
    while IFS= read -r id; do
      [[ -n "$id" ]] && ids+=("$id")
    done < <(module_ids_sorted)
  fi

  local id script args=()
  for id in "${ids[@]}"; do
    script="$(module_script_path "$id")"
    if [[ ! -x "$script" ]]; then
      echo "acs-setup: module script not installed: $script" >&2
      failed=1
      continue
    fi
    args=(--run)
    [[ "$dry_run" == "true" ]] && args+=(--dry-run)
    if ! "$script" "${args[@]}"; then
      failed=1
    fi
  done
  return "$failed"
}

main() {
  [[ -f "$MODULES_JSON" ]] || die "missing $MODULES_JSON"

  local action="" module_id="" json=false dry_run=false force=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --module) shift; module_id="${1:-}"; [[ -n "$module_id" ]] || die "--module requires an id" ;;
      --json) json=true ;;
      --dry-run) dry_run=true ;;
      --force) force=true ;;
      --oc-status) action=oc-status ;;
      --oc-login) action=oc-login ;;
      *) die "unknown option: $1" ;;
    esac
    shift
  done

  [[ -n "$action" ]] || { usage; exit 0; }

  case "$action" in
    oc-status|oc-login) ;;
    *)
      need_jq
      if [[ -n "$module_id" ]]; then
        module_meta "$module_id" id >/dev/null || die "unknown module id: $module_id"
      fi
      ;;
  esac

  case "$action" in
    status)
      if [[ "$json" == true ]]; then
        status_json "$module_id"
      else
        status_tsv "$module_id"
      fi
      ;;
    run)
      run_modules "$module_id" "$dry_run"
      ;;
    oc-status) run_openshift_cli status ;;
    oc-login)
      if [[ "$force" == true ]]; then
        run_openshift_cli login --force
      else
        run_openshift_cli login
      fi
      ;;
  esac
}

main "$@"
