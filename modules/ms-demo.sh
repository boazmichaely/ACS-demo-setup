#!/usr/bin/env bash
# Module: ms-demo - Mostmark Online Boutique microservices on OpenShift
# Minimal shell example: ensure project, apply upstream YAML, status + uninstall.
set -euo pipefail

MODULE_ID="ms-demo"
NS="ms-demo"
MANIFEST_URL="https://raw.githubusercontent.com/mostmark/microservices-demo/main/application.yaml"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  Deploy the Mostmark microservices demo (Online Boutique) in OpenShift project
  ${NS} for network/policy/violation demos. Creates the project if needed and
  applies the upstream application.yaml from GitHub.

Depends on:
  none (other modules)
  Lab credentials with OpenShift access. Modules use the secured cluster marked
  “OpenShift for modules” in Lab credentials (or Central OpenShift when the lab
  has no secured clusters).
  oc on PATH.

Environment:
  ACS_LAB_CREDENTIALS_FILE   Override path to lab-credentials.json
  ACS_DEMO_PYTHON            Override Python interpreter (for lab oc login)

Side effects:
  --run creates project ${NS} if missing and applies:
    ${MANIFEST_URL}
  --uninstall deletes project ${NS} and waits until it is gone.

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

# Normalize kind/name for set compare (deployment.apps/foo → deployment.apps/foo).
_norm_res() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed 's|^deployments\.|deployment.|; s|^services/|service/|; s|^routes\.|route.|; s|^networkpolicies\.|networkpolicy.|'
}

# Expected demo resources from the upstream manifest (client dry-run).
expected_demo_resources() {
  oc apply -n "${NS}" -f "${MANIFEST_URL}" --dry-run=client -o name 2>/dev/null \
    | while read -r line; do _norm_res "$line"; done \
    | sort -u
}

# Namespaced inventory we care about for demo vs other.
actual_namespace_resources() {
  oc get deploy,svc,route,networkpolicy,cm,secret,sa,role,rolebinding \
    -n "${NS}" -o name 2>/dev/null \
    | while read -r line; do _norm_res "$line"; done \
    | sort -u
}

# OpenShift injects these into every project - not "someone else's" extras.
is_platform_noise() {
  case "$1" in
    configmap/kube-root-ca.crt|configmap/openshift-service-ca.crt) return 0 ;;
    configmap/config-service-cabundle|configmap/config-trusted-cabundle) return 0 ;;
    serviceaccount/default|serviceaccount/builder|serviceaccount/deployer|serviceaccount/pipeline) return 0 ;;
    secret/default-dockercfg-*|secret/builder-dockercfg-*|secret/deployer-dockercfg-*|secret/pipeline-dockercfg-*) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/admin) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/system:deployers) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/system:image-builders) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/system:image-pullers) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/openshift-pipelines-edit) return 0 ;;
    rolebinding.rbac.authorization.k8s.io/pipelines-scc-rolebinding) return 0 ;;
    *) return 1 ;;
  esac
}

demo_deployments_ready() {
  local line kind name ready want
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    kind="${line%%/*}"
    name="${line#*/}"
    [[ "$kind" == deployment.apps || "$kind" == deployment ]] || continue
    ready="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
    want="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)"
    ready="${ready:-0}"
    want="${want:-0}"
    if [[ "$want" == "0" || "$ready" != "$want" ]]; then
      return 1
    fi
  done < <(expected_demo_resources)
  return 0
}

# After apply: wait until status would report ok (deploys + frontend HTTP).
wait_until_ready() {
  local timeout_s="${1:-300}"
  local deadline=$((SECONDS + timeout_s))
  local fe_code fe_url
  echo "${MODULE_ID}: waiting for deployments and store URL (up to ${timeout_s}s)..."
  while (( SECONDS < deadline )); do
    if demo_deployments_ready; then
      IFS=$'\t' read -r fe_code fe_url <<<"$(frontend_http_check)"
      if [[ -n "$fe_url" && "$fe_code" =~ ^[23][0-9][0-9]$ ]]; then
        echo "${MODULE_ID}: ready (store HTTP ${fe_code})"
        return 0
      fi
    fi
    sleep 5
  done
  echo "${MODULE_ID}: timed out waiting for ready state" >&2
  return 1
}

frontend_http_check() {
  local host code
  host="$(oc get route frontend -n "${NS}" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
  if [[ -z "$host" ]]; then
    printf 'none\t\n'
    return 0
  fi
  code="$(
    curl -k -sS -o /dev/null -w '%{http_code}' --max-time 10 "https://${host}/" 2>/dev/null \
      || printf '000'
  )"
  printf '%s\t%s\n' "$code" "https://${host}/"
}

emit_status_sections() {
  local project_present="$1"
  local demo_body="$2"
  local demo_sum="$3"
  local demo_tag="$4"
  local other_body="$5"
  local other_sum="$6"
  local fe_body="$7"
  local fe_sum="$8"
  local fe_tag="$9"
  local sections_json

  sections_json="$(
    jq -nc \
      --arg ns "$NS" \
      --arg proj_sum "$([[ "$project_present" == "yes" ]] && echo present || echo missing)" \
      --arg proj_tag "$([[ "$project_present" == "yes" ]] && echo ok || echo warn)" \
      --arg proj_body "Namespace: ${NS}" \
      --arg demo_body "$demo_body" \
      --arg demo_sum "$demo_sum" \
      --arg demo_tag "$demo_tag" \
      --arg other_body "$other_body" \
      --arg other_sum "$other_sum" \
      --arg fe_body "$fe_body" \
      --arg fe_sum "$fe_sum" \
      --arg fe_tag "$fe_tag" \
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
            group: "Namespace",
            title: "Demo resources",
            summary: $demo_sum,
            tag: $demo_tag,
            tagLabel: (if $demo_tag == "ok" then "ready" elif $demo_tag == "error" then "error" else "needs run" end),
            body: $demo_body,
            bodyFormat: "prose"
          },
          {
            group: "Namespace",
            title: "Other resources",
            summary: $other_sum,
            tag: (if $other_sum == "none" then "ok" else "warn" end),
            tagLabel: $other_sum,
            body: $other_body,
            bodyFormat: "prose"
          },
          {
            group: "Frontend",
            title: "Store URL",
            summary: $fe_sum,
            tag: $fe_tag,
            tagLabel: $fe_sum,
            body: $fe_body,
            bodyFormat: "prose"
          }
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  local errf err project_present="no"
  local expected actual demo_lines other_lines
  local demo_present=0 demo_total=0 demo_ready=0 demo_deploy_total=0
  local demo_body other_body fe_body fe_sum fe_tag fe_code fe_url
  local demo_sum demo_tag other_sum state message
  local line kind name ready want

  # Do not wrap ensure_oc in $() - export KUBECONFIG must stick in this shell.
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    emit_status_sections "no" "OpenShift login failed." "error" "error" "—" "—" \
      "${err:-OpenShift access failed}" "error" "error"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 0
  fi
  rm -f "${errf}"

  if oc get project "${NS}" >/dev/null 2>&1; then
    project_present="yes"
  fi

  if ! expected="$(expected_demo_resources)"; then
    emit_status_sections "$project_present" "Could not read demo manifest from ${MANIFEST_URL}" \
      "error" "error" "—" "—" "—" "error" "error"
    printf '%s\terror\tcould not fetch demo manifest\n' "$MODULE_ID"
    return 0
  fi

  if [[ "$project_present" != "yes" ]]; then
    demo_total="$(printf '%s\n' "$expected" | grep -c . || true)"
    emit_status_sections "no" \
      "Project missing. Expected demo resources (${demo_total}):"$'\n'"${expected}" \
      "0/${demo_total} present" "warn" \
      "n/a (project missing)" "n/a" \
      "No route (project missing)." "no route" "warn"
    printf '%s\tneeds-run\tproject %s missing\n' "$MODULE_ID" "$NS"
    return 0
  fi

  actual="$(actual_namespace_resources || true)"

  demo_lines=""
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    demo_total=$((demo_total + 1))
    if printf '%s\n' "$actual" | grep -qxF "$line"; then
      demo_present=$((demo_present + 1))
      kind="${line%%/*}"
      name="${line#*/}"
      if [[ "$kind" == deployment.apps || "$kind" == deployment ]]; then
        demo_deploy_total=$((demo_deploy_total + 1))
        ready="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
        want="$(oc get deploy "$name" -n "${NS}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)"
        ready="${ready:-0}"
        want="${want:-0}"
        if [[ "$ready" == "$want" && "$want" != "0" ]]; then
          demo_ready=$((demo_ready + 1))
          demo_lines+="${line}  ready ${ready}/${want}"$'\n'
        else
          demo_lines+="${line}  not ready ${ready}/${want}"$'\n'
        fi
      else
        demo_lines+="${line}  present"$'\n'
      fi
    else
      demo_lines+="${line}  MISSING"$'\n'
    fi
  done <<<"$expected"

  other_lines=""
  local other_count=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if printf '%s\n' "$expected" | grep -qxF "$line"; then
      continue
    fi
    if is_platform_noise "$line"; then
      continue
    fi
    other_count=$((other_count + 1))
    other_lines+="${line}"$'\n'
  done <<<"$actual"

  demo_sum="${demo_present}/${demo_total} present"
  if [[ "$demo_deploy_total" -gt 0 ]]; then
    demo_sum+="; deploys ${demo_ready}/${demo_deploy_total} ready"
  fi
  if [[ "$demo_present" -eq "$demo_total" && "$demo_ready" -eq "$demo_deploy_total" ]]; then
    demo_tag="ok"
  else
    demo_tag="warn"
  fi
  demo_body="$(printf '%s' "$demo_lines" | sed '/^$/d')"
  [[ -n "$demo_body" ]] || demo_body="(none)"

  if [[ "$other_count" -eq 0 ]]; then
    other_sum="none"
    other_body="No resources beyond the demo manifest."
  else
    other_sum="${other_count} extra"
    other_body="$(printf '%s' "$other_lines" | sed '/^$/d')"
  fi

  IFS=$'\t' read -r fe_code fe_url <<<"$(frontend_http_check)"
  if [[ -z "$fe_url" ]]; then
    fe_sum="no route"
    fe_tag="warn"
    fe_body="Route frontend not found in ${NS}."
  elif [[ "$fe_code" =~ ^[23][0-9][0-9]$ ]]; then
    fe_sum="HTTP ${fe_code}"
    fe_tag="ok"
    fe_body="${fe_url}"$'\n'"curl -k → ${fe_code}"
  else
    fe_sum="HTTP ${fe_code}"
    fe_tag="warn"
    fe_body="${fe_url}"$'\n'"curl -k → ${fe_code}"
  fi

  emit_status_sections "$project_present" "$demo_body" "$demo_sum" "$demo_tag" \
    "$other_body" "$other_sum" "$fe_body" "$fe_sum" "$fe_tag"

  if [[ "$demo_tag" == "ok" && "$fe_tag" == "ok" ]]; then
    state="ok"
    message="ms-demo ready; store HTTP ${fe_code}"
  else
    state="needs-run"
    message="demo ${demo_sum}; frontend ${fe_sum}"
  fi
  printf '%s\t%s\t%s\n' "$MODULE_ID" "$state" "$message"
}

do_run() {
  local errf err
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"
  if ! oc get project "${NS}" >/dev/null 2>&1; then
    oc new-project "${NS}"
  fi
  oc apply -n "${NS}" -f "${MANIFEST_URL}"
  # Apply alone is not "ready" - wait so GUI status after Run matches Last action.
  if wait_until_ready 300; then
    printf '%s\tok\tms-demo ready in %s\n' "$MODULE_ID" "$NS"
    return 0
  fi
  printf '%s\tneeds-run\tapplied but not ready yet (check Status)\n' "$MODULE_ID"
  return 1
}

do_dry_run() {
  local errf err have="missing"
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
  Would apply: ${MANIFEST_URL}
  OpenShift target: lab “OpenShift for modules” secured cluster (via ensure_oc)
EOF
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
  if ! oc get project "${NS}" >/dev/null 2>&1; then
    printf '%s\tok\tproject %s already absent\n' "$MODULE_ID" "$NS"
    return 0
  fi
  oc delete project "${NS}" --wait=true
  # Confirm gone (some clusters return before finalization finishes).
  local i
  for i in $(seq 1 60); do
    if ! oc get project "${NS}" >/dev/null 2>&1; then
      printf '%s\tok\tdeleted project %s\n' "$MODULE_ID" "$NS"
      return 0
    fi
    sleep 2
  done
  printf '%s\terror\tproject %s still present after delete wait\n' "$MODULE_ID" "$NS"
  return 1
}

do_uninstall_dry_run() {
  local errf err have="absent"
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
  Project ${NS}: ${have}
EOF
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
