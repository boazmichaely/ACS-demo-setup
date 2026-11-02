#!/usr/bin/env bash
# Module: init-demo - RHACS init-container Clean/Dirty/Blue/Red demo
# OpenShift workloads from ACS-init-container-test + DEMO-Init-Test Central policies.
set -euo pipefail

MODULE_ID="init-demo"
NS="acs-init-container-test"
UPSTREAM_RAW="https://raw.githubusercontent.com/boazmichaely/ACS-init-container-test/main"
MANIFEST_URLS=(
  "${UPSTREAM_RAW}/manifests/01-clean.yaml"
  "${UPSTREAM_RAW}/manifests/02-dirty.yaml"
  "${UPSTREAM_RAW}/manifests/03-blue.yaml"
  "${UPSTREAM_RAW}/manifests/04-red.yaml"
)
# clean/dirty must become ready; blue/red may stay 0/1 without privileged SCC.
REQUIRED_READY_DEPLOYS=(clean-app dirty-app)
ALL_DEPLOYS=(clean-app dirty-app blue-app red-app)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${ROOT}/modules/init_demo.py"
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
Usage: $(basename "$0") --help
       $(basename "$0") --status
       $(basename "$0") --run [--dry-run]
       $(basename "$0") --uninstall [--dry-run]

Purpose:
  Install the RHACS init-container demo in OpenShift project
  ${NS}: four small apps (clean / dirty / blue / red)
  that show Central scanning and policy evaluation on init containers,
  not only main containers.

  What each app is for:
    clean-app  Baseline - well-behaved init (no CVEs, not privileged).
    dirty-app  Init image has fixable Important+ CVEs.
    blue-app   Privileged init (legitimate pattern); main has a probe.
    red-app    Privileged init + CVEs; main missing liveness probe.

  Also creates three namespace-scoped Central policies (no enforcement):
    DEMO-Init-Test: Privileged Container (Blue/Red)
    DEMO-Init-Test: Fixable Important+ CVE (Dirty/Red)
    DEMO-Init-Test: Missing Liveness Probe (main only)

  Policy JSON comes from upstream (DEMO-Init-Test names as published).

  Module Status
    Status includes the list of artifacts as well as violations found

  How to use after --run:
    Open Central → search namespace ${NS} for the four
    deployments, init-container findings, and violations from the
    DEMO-Init-Test policies. blue-app/red-app may stay 0/1 Ready until
    someone grants the privileged SCC (expected; RHACS still evaluates
    the Deployment spec).

  Full upstream write-up:
    https://github.com/boazmichaely/ACS-init-container-test/blob/main/README.md

Depends on:
  none (other modules)
  Lab credentials with OpenShift access (“OpenShift for modules”) and
  Central API access (for the three policies).
  oc on PATH.

Environment:
  ACS_LAB_CREDENTIALS_FILE   Override path to lab-credentials.json
  ACS_DEMO_PYTHON            Override Python interpreter

Side effects:
  --run creates project ${NS} if missing, applies the
    four upstream manifests from GitHub, waits for clean-app/dirty-app,
    and upserts the three DEMO-Init-Test policies.
  --uninstall deletes those three policies and deletes project
    ${NS} (waits until gone).

EOF
}

# Export KUBECONFIG for the user-selected OpenShift target (lab credentials).
ensure_oc() {
  local kc errf err
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  errf="$(mktemp)"
  if ! kc="$(
    cd "${ROOT}" || exit 1
    "$PYTHON" -m lib.openshift login --print-kubeconfig 2>"${errf}"
  )"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\n' "${err:-OpenShift access failed}" >&2
    return 1
  fi
  rm -f "${errf}"
  if [[ -z "${kc}" || ! -f "${kc}" ]]; then
    printf 'ensure_oc did not return a kubeconfig path\n' >&2
    return 1
  fi
  export KUBECONFIG="${kc}"
  return 0
}

run_helper() {
  if [[ ! -f "$HELPER" ]]; then
    printf 'missing helper %s\n' "$HELPER" >&2
    return 1
  fi
  (cd "$ROOT" && "$PYTHON" "$HELPER" "$@")
}

deploy_ready_line() {
  local name="$1"
  local ready want
  if ! oc get deploy "$name" -n "${NS}" >/dev/null 2>&1; then
    printf '%s  MISSING\n' "$name"
    return 1
  fi
  ready="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
  want="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)"
  ready="${ready:-0}"
  want="${want:-0}"
  if [[ "$want" != "0" && "$ready" == "$want" ]]; then
    printf '%s  ready %s/%s\n' "$name" "$ready" "$want"
    return 0
  fi
  printf '%s  not ready %s/%s\n' "$name" "$ready" "$want"
  return 1
}

required_deploys_ready() {
  local name
  for name in "${REQUIRED_READY_DEPLOYS[@]}"; do
    if ! oc get deploy "$name" -n "${NS}" >/dev/null 2>&1; then
      return 1
    fi
    local ready want
    ready="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
    want="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)"
    ready="${ready:-0}"
    want="${want:-0}"
    if [[ "$want" == "0" || "$ready" != "$want" ]]; then
      return 1
    fi
  done
  return 0
}

wait_until_ready() {
  local timeout_s="${1:-120}"
  local deadline=$((SECONDS + timeout_s))
  echo "${MODULE_ID}: waiting for clean-app/dirty-app ready (up to ${timeout_s}s)..."
  while (( SECONDS < deadline )); do
    if required_deploys_ready; then
      echo "${MODULE_ID}: clean-app and dirty-app ready"
      return 0
    fi
    sleep 5
  done
  echo "${MODULE_ID}: timed out waiting for clean-app/dirty-app" >&2
  return 1
}

upsert_all_policies() {
  local url
  while IFS= read -r url; do
    [[ -z "$url" ]] && continue
    run_helper upsert-policy "$url" || return 1
  done < <(run_helper list-upstream-urls)
}

delete_all_policies() {
  local name
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    run_helper delete-policy "$name" || return 1
  done < <(run_helper list-demo-names)
}

emit_status_sections() {
  local project_present="$1"
  local wl_body="$2"
  local wl_sum="$3"
  local wl_tag="$4"
  local pol_body="$5"
  local pol_sum="$6"
  local pol_tag="$7"
  local viol_body="$8"
  local viol_sum="$9"
  local viol_tag="${10}"
  local sections_json

  sections_json="$(
    jq -nc \
      --arg ns "$NS" \
      --arg proj_sum "$([[ "$project_present" == "yes" ]] && echo present || echo missing)" \
      --arg proj_tag "$([[ "$project_present" == "yes" ]] && echo ok || echo warn)" \
      --arg proj_body "Namespace: ${NS}" \
      --arg wl_body "$wl_body" \
      --arg wl_sum "$wl_sum" \
      --arg wl_tag "$wl_tag" \
      --arg pol_body "$pol_body" \
      --arg pol_sum "$pol_sum" \
      --arg pol_tag "$pol_tag" \
      --arg viol_body "$viol_body" \
      --arg viol_sum "$viol_sum" \
      --arg viol_tag "$viol_tag" \
      '{
        sections: [
          {
            group: "Namespace",
            title: $ns,
            summary: $proj_sum,
            tag: $proj_tag,
            tagLabel: $proj_sum,
            body: $proj_body,
            bodyFormat: "prose"
          },
          {
            group: "Workloads",
            title: "Deployments",
            summary: $wl_sum,
            tag: $wl_tag,
            tagLabel: (if $wl_tag == "ok" then "ready" elif $wl_tag == "error" then "error" else "needs run" end),
            body: $wl_body,
            bodyFormat: "prose"
          },
          {
            group: "Central",
            title: "DEMO-Init-Test policies",
            summary: $pol_sum,
            tag: $pol_tag,
            tagLabel: $pol_sum,
            body: $pol_body,
            bodyFormat: "prose"
          },
          {
            group: "Central",
            title: "Violations",
            summary: $viol_sum,
            tag: $viol_tag,
            tagLabel: $viol_sum,
            body: $viol_body,
            bodyFormat: "prose"
          }
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  local errf err project_present="no"
  local wl_body wl_sum wl_tag
  local pol_body pol_sum pol_tag pol_json
  local viol_body viol_sum viol_tag viol_json
  local name line present=0 required_ok=1
  local state message

  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    emit_status_sections "no" "OpenShift login failed." "error" "error" \
      "—" "error" "error" \
      "${err:-OpenShift access failed}" "error" "error"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 0
  fi
  rm -f "${errf}"

  if oc get project "${NS}" >/dev/null 2>&1; then
    project_present="yes"
  fi

  wl_body=""
  if [[ "$project_present" != "yes" ]]; then
    wl_sum="0/4 present"
    wl_tag="warn"
    wl_body="Project missing. Expected deployments: ${ALL_DEPLOYS[*]}"
    required_ok=0
  else
    for name in "${ALL_DEPLOYS[@]}"; do
      if oc get deploy "$name" -n "${NS}" >/dev/null 2>&1; then
        present=$((present + 1))
      fi
      line="$(deploy_ready_line "$name" || true)"
      wl_body+="${line}"$'\n'
      case "$name" in
        clean-app|dirty-app)
          if ! printf '%s' "$line" | grep -q ' ready '; then
            required_ok=0
          fi
          ;;
      esac
    done
    wl_body+=$'\n'"Note: blue-app/red-app may stay 0/1 without privileged SCC (expected)."
    wl_sum="${present}/4 present"
    if [[ "$required_ok" -eq 1 && "$present" -eq 4 ]]; then
      wl_tag="ok"
      wl_sum+="; clean/dirty ready"
    elif [[ "$required_ok" -eq 1 ]]; then
      wl_tag="warn"
      wl_sum+="; clean/dirty ready (some deploys missing)"
    else
      wl_tag="warn"
      wl_sum+="; clean/dirty not ready"
    fi
  fi

  pol_json="$(run_helper policy-status 2>/dev/null || echo '{"ok":false,"error":"helper failed"}')"
  if ! printf '%s' "$pol_json" | jq -e . >/dev/null 2>&1; then
    pol_tag="error"
    pol_sum="error"
    pol_body="Could not read policy status from helper."
  elif [[ "$(printf '%s' "$pol_json" | jq -r '.ok')" != "true" ]]; then
    pol_tag="error"
    pol_sum="error"
    pol_body="$(printf '%s' "$pol_json" | jq -r '.error // "Central unreachable"')"
  else
    pol_body="$(printf '%s' "$pol_json" | jq -r '.policies[] | "\(.name): \(if .present then "present" else "MISSING" end)"')"
    local present_n total_n
    present_n="$(printf '%s' "$pol_json" | jq '[.policies[] | select(.present)] | length')"
    total_n="$(printf '%s' "$pol_json" | jq '.policies | length')"
    pol_sum="${present_n}/${total_n} present"
    if [[ "$(printf '%s' "$pol_json" | jq -r '.allPresent')" == "true" ]]; then
      pol_tag="ok"
    else
      pol_tag="warn"
    fi
  fi

  viol_json="$(run_helper violations --namespace "$NS" 2>/dev/null || echo '{"ok":false,"error":"helper failed","alerts":[]}')"
  if ! printf '%s' "$viol_json" | jq -e . >/dev/null 2>&1; then
    viol_tag="warn"
    viol_sum="unavailable"
    viol_body="Could not list violations."
  elif [[ "$(printf '%s' "$viol_json" | jq -r '.ok')" != "true" ]]; then
    viol_tag="warn"
    viol_sum="unavailable"
    viol_body="$(printf '%s' "$viol_json" | jq -r '.error // "Central unreachable"')"
  else
    local n
    n="$(printf '%s' "$viol_json" | jq '.alerts | length')"
    viol_sum="${n} active"
    if [[ "$n" -eq 0 ]]; then
      viol_tag="ok"
      viol_body="No active alerts in ${NS} yet (Sensor delay is normal after a fresh apply)."
    else
      viol_tag="ok"
      # One block per alert: label line + Central console deep link (GUI linkifies https://).
      viol_body="$(printf '%s' "$viol_json" | jq -r '
        .alerts[] |
        "\(.policy // "?") → \(.deployment // "?") (\(.state // "?"))"
        + (if (.url // "") != "" then "\n\(.url)" else "" end)
        + "\n"
      ' | sed '/^$/d')"
    fi
  fi

  emit_status_sections "$project_present" "$wl_body" "$wl_sum" "$wl_tag" \
    "$pol_body" "$pol_sum" "$pol_tag" \
    "$viol_body" "$viol_sum" "$viol_tag"

  if [[ "$wl_tag" == "ok" && "$pol_tag" == "ok" ]]; then
    state="ok"
    message="init-demo ready in ${NS}; policies present"
  elif [[ "$pol_tag" == "error" && "$project_present" != "yes" ]]; then
    state="needs-run"
    message="project ${NS} missing; Central: ${pol_sum}"
  elif [[ "$pol_tag" == "error" ]]; then
    state="error"
    message="workloads ${wl_sum}; Central ${pol_sum}"
  else
    state="needs-run"
    message="workloads ${wl_sum}; policies ${pol_sum}"
  fi
  printf '%s\t%s\t%s\n' "$MODULE_ID" "$state" "$message"
}

do_run() {
  local errf err url
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"

  if ! oc get project "${NS}" >/dev/null 2>&1; then
    oc new-project "${NS}" --display-name="ACS init-container demo"
  fi

  for url in "${MANIFEST_URLS[@]}"; do
    echo "${MODULE_ID}: applying ${url}"
    oc apply -f "${url}"
  done

  if ! wait_until_ready 120; then
    printf '%s\tneeds-run\tapplied but clean/dirty not ready yet (check Status)\n' "$MODULE_ID"
    # Still try policies so a partial lab is useful.
    upsert_all_policies || true
    return 1
  fi

  if ! upsert_all_policies; then
    printf '%s\terror\tworkloads ready but policy upsert failed\n' "$MODULE_ID"
    return 1
  fi

  printf '%s\tok\tinit-demo ready in %s (DEMO-Init-Test policies upserted)\n' "$MODULE_ID" "$NS"
  return 0
}

do_dry_run() {
  local errf err have="missing" url name
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"
  if oc get project "${NS}" >/dev/null 2>&1; then
    have="present"
  fi
  cat <<EOF
${MODULE_ID}: dry-run
  Project ${NS}: ${have} (would create if missing)
  Would apply:
EOF
  for url in "${MANIFEST_URLS[@]}"; do
    echo "    ${url}"
    oc apply -f "${url}" --dry-run=client -o name >/dev/null || true
  done
  echo "  Would upsert Central policies:"
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    echo "    ${name}"
  done < <(run_helper list-demo-names)
  echo "  OpenShift target: lab “OpenShift for modules” secured cluster (via ensure_oc)"
  printf '%s\tok\tdry-run only\n' "$MODULE_ID"
}

do_uninstall() {
  local errf err
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"

  delete_all_policies || {
    printf '%s\terror\tfailed deleting DEMO-Init-Test policies\n' "$MODULE_ID"
    return 1
  }

  if ! oc get project "${NS}" >/dev/null 2>&1; then
    printf '%s\tok\tpolicies removed; project %s already absent\n' "$MODULE_ID" "$NS"
    return 0
  fi
  oc delete project "${NS}" --wait=true
  local i
  for i in $(seq 1 60); do
    if ! oc get project "${NS}" >/dev/null 2>&1; then
      printf '%s\tok\tdeleted DEMO-Init-Test policies and project %s\n' "$MODULE_ID" "$NS"
      return 0
    fi
    sleep 2
  done
  printf '%s\terror\tproject %s still present after delete wait\n' "$MODULE_ID" "$NS"
  return 1
}

do_uninstall_dry_run() {
  local errf err have="absent" name
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"
  if oc get project "${NS}" >/dev/null 2>&1; then
    have="present (would delete and wait)"
  fi
  cat <<EOF
${MODULE_ID}: uninstall dry-run
  Would delete Central policies:
EOF
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    echo "    ${name}"
  done < <(run_helper list-demo-names)
  echo "  Project ${NS}: ${have}"
  printf '%s\tok\tuninstall dry-run only\n' "$MODULE_ID"
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
