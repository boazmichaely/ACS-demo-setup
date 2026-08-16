#!/usr/bin/env bash
# ACS demo setup orchestrator — dispatches to modules/NN-<id>.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULES_JSON="${ROOT}/config/modules.json"
MODULE_LAST_SECTIONS_JSON=""
MODULE_LAST_CAPTURE_ROW=""

usage() {
  cat <<'EOF'
Usage: acs-setup.sh --help
       acs-setup.sh --status [--module <id>] [--json]
       acs-setup.sh --run [--module <id>] [--dry-run]

Options:
  --help          Show this help
  --status        Report module status (all modules, or one with --module)
  --run           Run module(s)
  --module <id>   Limit to one module id from config/modules.json
  --json          With --status: emit JSON array (for GUI)
  --dry-run       With --run: pass through to module (planned actions only)
EOF
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
  local num
  num="$(module_meta "$id" number)"
  [[ -n "$num" && "$num" != "null" ]] || die "unknown module id: $id"
  printf '%s/modules/%02d-%s.sh' "$ROOT" "$num" "$id"
}

module_ids_sorted() {
  jq -r '.modules | sort_by(.number) | .[].id' "$MODULES_JSON"
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
    mapfile -t ids < <(module_ids_sorted)
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
    num="$(module_meta "$id" number)"
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
    mapfile -t ids < <(module_ids_sorted)
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
  need_jq

  local action="" module_id="" json=false dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --module) shift; module_id="${1:-}"; [[ -n "$module_id" ]] || die "--module requires an id" ;;
      --json) json=true ;;
      --dry-run) dry_run=true ;;
      *) die "unknown option: $1" ;;
    esac
    shift
  done

  [[ -n "$action" ]] || { usage; exit 0; }

  if [[ -n "$module_id" ]]; then
    module_meta "$module_id" id >/dev/null || die "unknown module id: $module_id"
  fi

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
  esac
}

main "$@"
