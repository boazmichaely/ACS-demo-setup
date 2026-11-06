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
       acs-setup.sh --status [--module <id>] [--json] [--secured-cluster-id ID]...
       acs-setup.sh --run [--module <id>] [--dry-run] [--secured-cluster-id ID]...
       acs-setup.sh --uninstall --module <id> [--dry-run] [--secured-cluster-id ID]...
       acs-setup.sh --oc-status
       acs-setup.sh --oc-login [--force]

Options:
  --help          Show this help
  --status        Report module status (all modules, or one with --module)
  --run           Run module(s)
  --uninstall     Uninstall one module (requires --module; some modules refuse)
  --module <id>   Limit to one module id from config/modules.json
  --json          With --status: emit JSON array (for GUI)
  --dry-run       With --run or --uninstall: planned actions only
  --secured-cluster-id ID
                  Repeatable. When set with --module, fan out secured-cluster N
                  then central-ocp / central-api as listed in the catalog
                  (module must accept --plane / --secured-cluster-id).
                  When omitted: one invoke, no new flags (legacy behavior),
                  unless --include-central alone (Central planes only).
  --include-central
                  Run Central planes (central-api / central-ocp) with or without SC ids.
  --skip-central
                  secured-cluster fan-out only; skip Central planes.

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

# Set by main: "" | include | skip
INCLUDE_CENTRAL_MODE=""

# Plan invocations via lib.module_orchestrate. Prints JSON array.
# Args: module_id action sc_id...
plan_invocations_json() {
  local module_id="$1" action="$2"
  shift 2
  local py args=( -m lib.module_orchestrate --module "$module_id" --action "$action" )
  local sid
  for sid in "$@"; do
    [[ -n "$sid" ]] && args+=( --secured-cluster-id "$sid" )
  done
  case "${INCLUDE_CENTRAL_MODE}" in
    include) args+=( --include-central ) ;;
    skip) args+=( --skip-central ) ;;
  esac
  py="$(acs_python)"
  [[ -n "$py" ]] || die "python3 not found (set ACS_DEMO_PYTHON or use gui/.venv)"
  (cd "$ROOT" && "$py" "${args[@]}")
}

# Run one module script once with optional env + argv extras from a plan step.
# Args: script action dry_run env_json argv_json
# env_json / argv_json are JSON objects/arrays from the planner.
invoke_module_once() {
  local script="$1" action_flag="$2" dry_run="$3" env_json="$4" argv_json="$5"
  local args=("$action_flag")
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)

  local extra
  while IFS= read -r extra; do
    [[ -n "$extra" ]] && args+=("$extra")
  done < <(printf '%s' "$argv_json" | jq -r '.[]')

  # Apply planner env for this process only.
  local keys key val
  keys="$(printf '%s' "$env_json" | jq -r 'keys[]' 2>/dev/null || true)"
  if [[ -n "$keys" ]]; then
    local -a export_pairs=()
    while IFS= read -r key; do
      [[ -n "$key" ]] || continue
      val="$(printf '%s' "$env_json" | jq -r --arg k "$key" '.[$k]')"
      export_pairs+=("$key=$val")
    done <<<"$keys"
    env "${export_pairs[@]}" "$script" "${args[@]}"
  else
    "$script" "${args[@]}"
  fi
}

# Fan-out when SC ids and/or --include-central; else single legacy invoke.
# Args: action_flag ( --run | --uninstall | --status ) module_id dry_run sc_id...
run_module_planned() {
  local action_flag="$1" filter_id="$2" dry_run="$3"
  shift 3
  local -a sc_ids=()
  if [[ $# -gt 0 ]]; then
    sc_ids=("$@")
  fi
  local script plan n i plane env_json argv_json
  script="$(module_script_path "$filter_id")"
  if [[ ! -x "$script" ]]; then
    echo "acs-setup: module script not installed: $script" >&2
    return 1
  fi

  local planned=false
  if [[ ${#sc_ids[@]} -gt 0 || "${INCLUDE_CENTRAL_MODE}" == "include" || "${INCLUDE_CENTRAL_MODE}" == "skip" ]]; then
    planned=true
  fi

  if [[ "$planned" != "true" ]]; then
    local args=("$action_flag")
    [[ "$dry_run" == "true" && "$action_flag" != "--status" ]] && args+=(--dry-run)
    "$script" "${args[@]}"
    return
  fi

  local orch_action=run
  case "$action_flag" in
    --uninstall) orch_action=uninstall ;;
    --status) orch_action=status ;;
    *) orch_action=run ;;
  esac

  if [[ ${#sc_ids[@]} -gt 0 ]]; then
    plan="$(plan_invocations_json "$filter_id" "$orch_action" "${sc_ids[@]}")" || return 1
  else
    plan="$(plan_invocations_json "$filter_id" "$orch_action")" || return 1
  fi
  n="$(printf '%s' "$plan" | jq 'length')"
  for ((i = 0; i < n; i++)); do
    plane="$(printf '%s' "$plan" | jq -r --argjson i "$i" '.[$i].plane // empty')"
    env_json="$(printf '%s' "$plan" | jq -c --argjson i "$i" '.[$i].env')"
    argv_json="$(printf '%s' "$plan" | jq -c --argjson i "$i" '.[$i].argv_extra')"
    echo "acs-setup: ${filter_id} ${action_flag} plane=${plane:-none} ($((i + 1))/${n})" >&2
    if [[ "$action_flag" == "--status" ]]; then
      # Status: capture output of each invoke; last TSV wins for summary unless we merge later.
      invoke_module_once "$script" --status false "$env_json" "$argv_json" || true
    else
      invoke_module_once "$script" "$action_flag" "$dry_run" "$env_json" "$argv_json" || return 1
    fi
  done
}

run_modules() {
  local filter_id="${1:-}"
  local dry_run="${2:-false}"
  shift 2 || true
  local -a sc_ids=()
  if [[ $# -gt 0 ]]; then
    sc_ids=("$@")
  fi
  local ids=()
  local failed=0

  if [[ ${#sc_ids[@]} -gt 0 && -z "$filter_id" ]]; then
    die "--secured-cluster-id requires --module <id>"
  fi

  if [[ -n "$filter_id" ]]; then
    ids=("$filter_id")
  else
    # Bash 3.2 (macOS /bin/bash) has no mapfile
    while IFS= read -r id; do
      [[ -n "$id" ]] && ids+=("$id")
    done < <(module_ids_sorted)
  fi

  local id
  for id in "${ids[@]}"; do
    if [[ ${#sc_ids[@]} -gt 0 ]]; then
      if ! run_module_planned --run "$id" "$dry_run" "${sc_ids[@]}"; then
        failed=1
      fi
    else
      local script args=(--run)
      script="$(module_script_path "$id")"
      if [[ ! -x "$script" ]]; then
        echo "acs-setup: module script not installed: $script" >&2
        failed=1
        continue
      fi
      [[ "$dry_run" == "true" ]] && args+=(--dry-run)
      if ! "$script" "${args[@]}"; then
        failed=1
      fi
    fi
  done
  return "$failed"
}

uninstall_module() {
  local filter_id="${1:-}"
  local dry_run="${2:-false}"
  shift 2 || true
  local -a sc_ids=()
  if [[ $# -gt 0 ]]; then
    sc_ids=("$@")
  fi
  [[ -n "$filter_id" ]] || die "uninstall requires --module <id>"

  if [[ ${#sc_ids[@]} -gt 0 ]]; then
    run_module_planned --uninstall "$filter_id" "$dry_run" "${sc_ids[@]}"
    return
  fi

  local script args=(--uninstall)
  script="$(module_script_path "$filter_id")"
  if [[ ! -x "$script" ]]; then
    echo "acs-setup: module script not installed: $script" >&2
    return 1
  fi
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)
  "$script" "${args[@]}"
}

main() {
  [[ -f "$MODULES_JSON" ]] || die "missing $MODULES_JSON"

  local action="" module_id="" json=false dry_run=false force=false
  local -a sc_ids=()
  INCLUDE_CENTRAL_MODE=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --uninstall) action=uninstall ;;
      --module) shift; module_id="${1:-}"; [[ -n "$module_id" ]] || die "--module requires an id" ;;
      --secured-cluster-id)
        shift
        [[ -n "${1:-}" ]] || die "--secured-cluster-id requires an id"
        sc_ids+=("$1")
        ;;
      --include-central)
        [[ -z "$INCLUDE_CENTRAL_MODE" || "$INCLUDE_CENTRAL_MODE" == "include" ]] \
          || die "--include-central and --skip-central are mutually exclusive"
        INCLUDE_CENTRAL_MODE=include
        ;;
      --skip-central)
        [[ -z "$INCLUDE_CENTRAL_MODE" || "$INCLUDE_CENTRAL_MODE" == "skip" ]] \
          || die "--include-central and --skip-central are mutually exclusive"
        INCLUDE_CENTRAL_MODE=skip
        ;;
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
      if [[ ${#sc_ids[@]} -gt 0 && -z "$module_id" ]]; then
        die "--secured-cluster-id requires --module <id>"
      fi
      if [[ -n "$INCLUDE_CENTRAL_MODE" && -z "$module_id" ]]; then
        die "--include-central / --skip-central requires --module <id>"
      fi
      ;;
  esac

  case "$action" in
    status)
      if [[ ${#sc_ids[@]} -gt 0 || -n "$INCLUDE_CENTRAL_MODE" ]]; then
        [[ -n "$module_id" ]] || die "planned status requires --module <id>"
        if [[ ${#sc_ids[@]} -gt 0 ]]; then
          run_module_planned --status "$module_id" false "${sc_ids[@]}"
        else
          run_module_planned --status "$module_id" false
        fi
      elif [[ "$json" == true ]]; then
        status_json "$module_id"
      else
        status_tsv "$module_id"
      fi
      ;;
    run)
      if [[ ${#sc_ids[@]} -gt 0 || -n "$INCLUDE_CENTRAL_MODE" ]]; then
        [[ -n "$module_id" ]] || die "planned run requires --module <id>"
        if [[ ${#sc_ids[@]} -gt 0 ]]; then
          run_modules "$module_id" "$dry_run" "${sc_ids[@]}"
        else
          # Central-only / skip-central with no SC ids still needs planned path.
          run_module_planned --run "$module_id" "$dry_run"
        fi
      else
        run_modules "$module_id" "$dry_run"
      fi
      ;;
    uninstall)
      if [[ ${#sc_ids[@]} -gt 0 || -n "$INCLUDE_CENTRAL_MODE" ]]; then
        [[ -n "$module_id" ]] || die "planned uninstall requires --module <id>"
        if [[ ${#sc_ids[@]} -gt 0 ]]; then
          uninstall_module "$module_id" "$dry_run" "${sc_ids[@]}"
        else
          run_module_planned --uninstall "$module_id" "$dry_run"
        fi
      else
        uninstall_module "$module_id" "$dry_run"
      fi
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
