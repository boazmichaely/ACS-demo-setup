#!/usr/bin/env bash
# Shared helpers for compliance-operator module (OLM install + Central scan schedule).
set -euo pipefail

MODULE_ID="compliance-operator"

# Lab constants (override only via flags on compliance-operator.sh, not env).
CO_NAMESPACE="openshift-compliance"
CO_SUBSCRIPTION_NAME="compliance-operator-sub"
CO_CHANNEL="stable"
CO_CSV_TIMEOUT_SECONDS=600
CO_ROLLOUT_TIMEOUT_SECONDS=240
CO_PATCH_NODE_SELECTOR=false
CO_SECURED_CLUSTER=""
# Orchestrator plane: "" | central | openshift (empty = both in one process).
CO_PLANE=""
# Lab secured-cluster ids for this invoke (OpenShift: 0-1; Central: 0-N).
CO_SC_IDS=()

co_namespace() {
  printf '%s' "$CO_NAMESPACE"
}

co_subscription_name() {
  printf '%s' "$CO_SUBSCRIPTION_NAME"
}

co_channel() {
  printf '%s' "$CO_CHANNEL"
}

co_csv_timeout() {
  printf '%s' "$CO_CSV_TIMEOUT_SECONDS"
}

co_rollout_timeout() {
  printf '%s' "$CO_ROLLOUT_TIMEOUT_SECONDS"
}

co_python() {
  if [[ -n "${ACS_DEMO_PYTHON:-}" ]]; then
    printf '%s' "$ACS_DEMO_PYTHON"
  elif [[ -n "${COMPLIANCE_MODULE_ROOT:-}" ]] \
    && [[ -x "${COMPLIANCE_MODULE_ROOT}/gui/.venv/bin/python" ]]; then
    printf '%s' "${COMPLIANCE_MODULE_ROOT}/gui/.venv/bin/python"
  else
    command -v python3
  fi
}

# List secured clusters for this invoke as id<TAB>name.
# Preference: CO_SC_IDS → CO_SECURED_CLUSTER name filter → Target cluster only.
co_list_sc_targets() {
  local py
  py="$(co_python)"
  if [[ ${#CO_SC_IDS[@]} -gt 0 ]]; then
    (
      cd "${COMPLIANCE_MODULE_ROOT}" || exit 1
      "$py" -m lib.openshift list-secured-clusters
    ) | "$py" -c '
import json, sys
want = set(sys.argv[1:])
rows = json.load(sys.stdin)
for r in rows:
    rid = (r.get("id") or "").strip()
    if rid in want:
        print("%s\t%s" % (rid, (r.get("name") or rid).strip()))
' "${CO_SC_IDS[@]}"
    return
  fi
  (
    cd "${COMPLIANCE_MODULE_ROOT}" || exit 1
    if [[ -n "$CO_SECURED_CLUSTER" ]]; then
      "$py" -m lib.openshift list-secured-clusters --name "$CO_SECURED_CLUSTER"
    else
      # Soft-default SC only (not every lab SC).
      "$py" - <<'PY'
from lib.lab_doc import active_lab, preferred_secured_cluster
from lib.central import load_lab_document
import json
lab = active_lab(load_lab_document())
sc = preferred_secured_cluster(lab)
print(json.dumps([{
  "id": (sc.get("id") or "").strip(),
  "name": (sc.get("name") or sc.get("id") or "").strip(),
}]))
PY
    fi
  ) | "$py" -c '
import json, sys
rows = json.load(sys.stdin)
for r in rows:
    rid = (r.get("id") or "").strip()
    if not rid:
        continue
    print("%s\t%s" % (rid, (r.get("name") or rid).strip()))
'
}

# Login to one secured cluster; export KUBECONFIG. Args: sc_id.
co_ensure_oc_sc() {
  local sc_id="$1"
  local py kc err errf
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  if [[ -z "${COMPLIANCE_MODULE_ROOT:-}" ]]; then
    printf 'COMPLIANCE_MODULE_ROOT unset\n' >&2
    return 1
  fi
  if [[ -z "$sc_id" ]]; then
    printf 'secured cluster id required\n' >&2
    return 1
  fi
  py="$(co_python)"
  errf="$(mktemp)"
  if ! kc="$(
    cd "${COMPLIANCE_MODULE_ROOT}" || exit 1
    "$py" -m lib.openshift login --secured-cluster-id "$sc_id" --print-kubeconfig 2>"${errf}"
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

# Backward-compatible: first listed SC (or filtered). Prefer co_ensure_oc_sc in loops.
co_ensure_oc() {
  local sc_id sc_name
  IFS=$'\t' read -r sc_id sc_name < <(co_list_sc_targets | head -n 1) || true
  if [[ -z "$sc_id" ]]; then
    printf 'no secured clusters listed for this lab\n' >&2
    return 1
  fi
  co_ensure_oc_sc "$sc_id"
}

co_scan_helper() {
  printf '%s' "${COMPLIANCE_MODULE_ROOT}/modules/compliance_scan.py"
}

co_parse_scan_status() {
  local output="$1"
  printf '%s\n' "$output" | awk -F'\t' '$1=="scan-status"{print $2"\t"$3; exit}'
}

co_operator_status_line() {
  local ns sub line st msg
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"

  if ! command -v oc >/dev/null 2>&1; then
    printf 'error\toc not on PATH\n'
    return 1
  fi
  if ! co_ensure_oc; then
    printf 'error\tOpenShift access failed\n'
    return 1
  fi
  if ! oc get "namespace/${ns}" >/dev/null 2>&1; then
    printf 'needs-run\tnamespace %s missing\n' "$ns"
    return 0
  fi
  if ! oc get "subscription/${sub}" -n "${ns}" >/dev/null 2>&1; then
    printf 'needs-run\tSubscription %s missing in %s\n' "$sub" "$ns"
    return 0
  fi

  line="$(co_csv_status_line "${ns}")"
  st="${line%%$'\t'*}"
  msg="${line#*$'\t'}"
  if [[ "$st" != "ok" ]]; then
    printf '%s\t%s\n' "$st" "$msg"
    return 0
  fi

  printf 'ok\tCompliance Operator %s\n' "$msg"
}

co_scan_status_line() {
  local helper py output parsed scan_st scan_msg
  local -a args=(status --cli)
  helper="$(co_scan_helper)"
  py="$(co_python)"
  if [[ ! -f "$helper" ]]; then
    printf 'error\tmissing helper %s\n' "$helper"
    return 1
  fi
  [[ -n "$CO_SECURED_CLUSTER" ]] && args+=(--secured-cluster "$CO_SECURED_CLUSTER")
  if ! output="$("$py" "$helper" "${args[@]}" 2>&1)"; then
    parsed="$(co_parse_scan_status "$output")"
    if [[ -n "$parsed" ]]; then
      printf '%s\n' "$parsed"
      return 1
    fi
    printf 'error\tscan status failed\n'
    return 1
  fi
  parsed="$(co_parse_scan_status "$output")"
  if [[ -z "$parsed" ]]; then
    printf 'error\tscan status produced no scan-status row\n'
    return 1
  fi
  printf '%s\n' "$parsed"
}

co_combine_status() {
  local op_st op_msg scan_st scan_msg combined_st combined_msg
  op_st="${1%%$'\t'*}"
  op_msg="${1#*$'\t'}"
  scan_st="${2%%$'\t'*}"
  scan_msg="${2#*$'\t'}"

  if [[ "$op_st" == "error" || "$scan_st" == "error" ]]; then
    combined_st="error"
  elif [[ "$op_st" == "needs-run" || "$scan_st" == "needs-run" ]]; then
    combined_st="needs-run"
  else
    combined_st="ok"
  fi

  if [[ "$op_st" != "ok" ]]; then
    combined_msg="$op_msg"
  else
    combined_msg="$op_msg; $scan_msg"
  fi

  printf '%s\t%s\t%s\n' "$MODULE_ID" "$combined_st" "$combined_msg"
}

co_emit_access_error_section() {
  local cluster_name="$1" body="$2" py
  py="$(co_python)"
  "$py" -c '
import json, sys
name, body = sys.argv[1], sys.argv[2]
payload = {
    "sections": [
        {
            "cluster": name,
            "group": "Access",
            "title": "OpenShift",
            "summary": "failed",
            "tag": "error",
            "tagLabel": "error",
            "body": body,
            "bodyFormat": "prose",
        }
    ]
}
print("ACS_SECTIONS_JSON=" + json.dumps(payload, separators=(",", ":")))
' "$cluster_name" "$body"
}

co_merge_sections_json_lines() {
  local py
  py="$(co_python)"
  "$py" -c '
import json, sys
sections = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("ACS_SECTIONS_JSON="):
        continue
    try:
        payload = json.loads(line.split("=", 1)[1])
    except Exception:
        continue
    sections.extend(payload.get("sections") or [])
if sections:
    print("ACS_SECTIONS_JSON=" + json.dumps({"sections": sections}, separators=(",", ":")))
'
}

compliance_operator_emit_overview_sections() {
  local overview py sc_id sc_name line errf err merged
  overview="${COMPLIANCE_MODULE_ROOT}/scripts/compliance_co_overview.py"
  py="$(co_python)"
  if [[ ! -f "$overview" ]]; then
    return 0
  fi
  if ! command -v oc >/dev/null 2>&1; then
    return 0
  fi

  merged="$(mktemp)"
  while IFS=$'\t' read -r sc_id sc_name; do
    [[ -n "$sc_id" ]] || continue
    errf="$(mktemp)"
    if ! co_ensure_oc_sc "$sc_id" 2>"${errf}"; then
      err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
      rm -f "${errf}"
      co_emit_access_error_section "${sc_name:-$sc_id}" "${err:-OpenShift access failed}" >>"$merged"
      continue
    fi
    rm -f "${errf}"
    line="$("$py" "$overview" --sections-json --cluster "${sc_name:-$sc_id}" 2>/dev/null || true)"
    if [[ -n "$line" ]]; then
      printf '%s\n' "$line" >>"$merged"
    fi
  done < <(co_list_sc_targets)

  if [[ -s "$merged" ]]; then
    co_merge_sections_json_lines <"$merged"
  fi
  rm -f "$merged"
}

# Worst OLM status across all target SCs: st<TAB>msg
co_operator_status_all() {
  local sc_id sc_name line st msg parts=() worst=ok
  local errf err
  while IFS=$'\t' read -r sc_id sc_name; do
    [[ -n "$sc_id" ]] || continue
    errf="$(mktemp)"
    if ! co_ensure_oc_sc "$sc_id" 2>"${errf}"; then
      err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
      rm -f "${errf}"
      worst=error
      parts+=("${sc_name}: ${err:-OpenShift access failed}")
      continue
    fi
    rm -f "${errf}"
    line="$(co_operator_status_line)" || true
    st="${line%%$'\t'*}"
    msg="${line#*$'\t'}"
    parts+=("${sc_name}: ${msg}")
    if [[ "$st" == "error" ]]; then
      worst=error
    elif [[ "$st" == "needs-run" && "$worst" != "error" ]]; then
      worst=needs-run
    fi
  done < <(co_list_sc_targets)

  if [[ ${#parts[@]} -eq 0 ]]; then
    printf 'error\tno secured clusters listed for this lab\n'
    return 1
  fi
  local joined
  joined="$(IFS='; '; printf '%s' "${parts[*]}")"
  printf '%s\t%s\n' "$worst" "$joined"
}

compliance_operator_emit_status() {
  local op_line scan_line op_st
  compliance_operator_emit_overview_sections
  if ! op_line="$(co_operator_status_all)"; then
    :
  fi
  op_st="${op_line%%$'\t'*}"
  if [[ "$op_st" == "error" ]]; then
    printf '%s\terror\t%s\n' "$MODULE_ID" "${op_line#*$'\t'}"
    return 1
  fi
  if [[ "$op_st" != "ok" ]]; then
    printf '%s\t%s\t%s\n' "$MODULE_ID" "$op_st" "${op_line#*$'\t'}"
    return 0
  fi

  if ! scan_line="$(co_scan_status_line)"; then
    co_combine_status "$op_line" "error\tscan status failed"
    return 0
  fi
  co_combine_status "$op_line" "$scan_line"
}

co_csv_succeeded_name() {
  local ns="$1"
  oc get csv -n "${ns}" -o json 2>/dev/null | "$(co_python)" -c '
import json, sys
try:
    j = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for it in j.get("items") or []:
    n = (it.get("metadata") or {}).get("name") or ""
    ph = (it.get("status") or {}).get("phase") or ""
    if n.startswith("compliance-operator.") and ph == "Succeeded":
        print(n)
        sys.exit(0)
sys.exit(1)
'
}

co_csv_status_line() {
  local ns="$1"
  oc get csv -n "${ns}" -o json 2>/dev/null | "$(co_python)" -c '
import json, sys
try:
    j = json.load(sys.stdin)
except Exception:
    print("error\tcould not read CSV list")
    sys.exit(0)
best = ("", "")
for it in j.get("items") or []:
    n = (it.get("metadata") or {}).get("name") or ""
    ph = (it.get("status") or {}).get("phase") or ""
    ver = (it.get("spec") or {}).get("version") or (it.get("status") or {}).get("version") or ""
    if not n.startswith("compliance-operator."):
        continue
    if ph == "Succeeded":
        print("ok\t%s (%s)" % (n, ver or "?"))
        sys.exit(0)
    best = (ph, n)
if best[0]:
    print("needs-run\tCSV %s phase=%s" % (best[1], best[0]))
else:
    print("needs-run\tno compliance-operator CSV yet")
'
}

co_main_deployment() {
  local ns="$1"
  oc get deploy -n "${ns}" -o json 2>/dev/null | "$(co_python)" -c '
import json, sys
try:
    j = json.load(sys.stdin)
except Exception:
    sys.exit(1)
cands = []
for it in j.get("items") or []:
    n = (it.get("metadata") or {}).get("name") or ""
    if not n:
        continue
    if n.startswith("compliance-operator") and "catalog" not in n.lower():
        cands.append(n)
if cands:
    print(sorted(cands)[0])
'
}

compliance_operator_plan() {
  local ns sub channel
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  channel="$(co_channel)"
  cat <<EOF
Planned changes (phase 1 — OLM install):
  - Create namespace ${ns}
  - Apply OperatorGroup compliance-operator in ${ns}
  - Apply Subscription ${sub} (compliance-operator, channel ${channel})
  - Wait for CSV Succeeded (timeout $(co_csv_timeout)s)
  - Wait for compliance-operator deployment rollout (timeout $(co_rollout_timeout)s)
EOF
}

co_apply_labeled_yaml() {
  # Stdin YAML → apply-labeled for current CO_SC_IDS[0] / Target.
  local py sc_id="${CO_SC_IDS[0]:-}"
  py="$(co_python)"
  if [[ -n "$sc_id" ]]; then
    (cd "${COMPLIANCE_MODULE_ROOT}" && "$py" -m lib.openshift apply-labeled --secured-cluster-id "$sc_id" -f -)
  else
    (cd "${COMPLIANCE_MODULE_ROOT}" && "$py" -m lib.openshift apply-labeled -f -)
  fi
}

compliance_operator_apply_manifests() {
  local ns sub channel
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  channel="$(co_channel)"

  echo "Create namespace ${ns}"
  co_apply_labeled_yaml <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${ns}
  labels:
    openshift.io/cluster-monitoring: "true"
EOF

  # OpenShift may stamp openshift.io/node-selector on new namespaces when the
  # cluster defines a default project node selector. Compliance Operator pods
  # do not require a dedicated node pool; on restrictive clusters the operator
  # or profile-parser workloads can sit Pending even after CSV Succeeded.
  # Default: leave scheduling alone. Pass --patch-node-selector to clear the
  # annotation for broader scheduling in this namespace.
  if [[ "$CO_PATCH_NODE_SELECTOR" == "true" ]]; then
    echo "Annotate namespace ${ns} (clear openshift.io/node-selector for broader scheduling)"
    oc annotate namespace "${ns}" openshift.io/node-selector="" --overwrite 2>/dev/null \
      || echo "  (annotate openshift.io/node-selector skipped)"
  fi

  echo "Apply OperatorGroup + Subscription ${sub} (channel ${channel})"
  co_apply_labeled_yaml <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: compliance-operator
  namespace: ${ns}
spec:
  targetNamespaces:
  - ${ns}
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: ${sub}
  namespace: ${ns}
spec:
  channel: "${channel}"
  installPlanApproval: Automatic
  name: compliance-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
}

compliance_operator_wait_ready() {
  local ns sub csv_timeout rollout_timeout start csv_name main_deploy
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  csv_timeout="$(co_csv_timeout)"
  rollout_timeout="$(co_rollout_timeout)"

  if co_csv_succeeded_name "${ns}" >/dev/null 2>&1; then
    csv_name="$(co_csv_succeeded_name "${ns}")"
    echo "CSV already Succeeded: ${csv_name}"
  else
    echo "Waiting for CSV Succeeded (timeout ${csv_timeout}s)"
    start=$SECONDS
    while true; do
      if [[ $((SECONDS - start)) -ge "${csv_timeout}" ]]; then
        echo "Last CSV status:" >&2
        oc get csv -n "${ns}" -o wide 2>/dev/null || true
        echo "Compliance Operator CSV not Succeeded within ${csv_timeout}s" >&2
        return 1
      fi
      if csv_name="$(co_csv_succeeded_name "${ns}" 2>/dev/null)"; then
        echo "CSV Succeeded: ${csv_name}"
        break
      fi
      echo "Waiting for Compliance Operator CSV… ($((SECONDS - start))s elapsed)" >&2
      sleep 10
    done
  fi

  main_deploy="$(co_main_deployment "${ns}" 2>/dev/null || true)"
  if [[ -z "${main_deploy}" ]]; then
    echo "No compliance-operator deployment found; CSV succeeded — verify: oc get deploy -n ${ns}"
    return 0
  fi

  echo "Waiting for deployment/${main_deploy} rollout (timeout ${rollout_timeout}s)"
  oc rollout status "deploy/${main_deploy}" -n "${ns}" --timeout="${rollout_timeout}s"
}

co_scan_common_args() {
  # Emit argv tokens (one per line) for the Central scan helper.
  local sid
  if [[ -n "$CO_SECURED_CLUSTER" ]]; then
    printf '%s\n' --secured-cluster
    printf '%s\n' "$CO_SECURED_CLUSTER"
  fi
  for sid in "${CO_SC_IDS[@]+"${CO_SC_IDS[@]}"}"; do
    if [[ -n "$sid" ]]; then
      printf '%s\n' --secured-cluster-id
      printf '%s\n' "$sid"
    fi
  done
}

compliance_operator_run_scan() {
  local dry_run="${1:-false}"
  local helper py
  local -a args=(run --cli)
  local flag
  helper="$(co_scan_helper)"
  py="$(co_python)"
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && args+=("$flag")
  done < <(co_scan_common_args)

  echo "Configure compliance scan schedule in Central"
  if [[ ! -f "$helper" ]]; then
    echo "missing helper: $helper" >&2
    return 1
  fi
  if ! "$py" "$helper" "${args[@]}"; then
    return 1
  fi
}

compliance_operator_run_olm_one() {
  # Current KUBECONFIG must already target one SC. dry_run true|false
  local dry_run="${1:-false}"
  local sc_label="${2:-}"
  local rc=0

  if [[ -n "$sc_label" ]]; then
    echo "=== Compliance Operator OLM on secured cluster: ${sc_label} ==="
  fi

  if [[ "$dry_run" == "true" ]]; then
    compliance_operator_plan
    return 0
  fi

  if co_csv_succeeded_name "$(co_namespace)" >/dev/null 2>&1 \
    && [[ -n "$(co_main_deployment "$(co_namespace)" 2>/dev/null || true)" ]]; then
    echo "Compliance Operator already installed; verifying rollout"
    compliance_operator_wait_ready || rc=1
    if [[ "$rc" -eq 0 ]]; then
      echo "No operator changes required on ${sc_label:-this cluster}."
    fi
  else
    compliance_operator_apply_manifests || rc=1
    if [[ "$rc" -eq 0 ]]; then
      compliance_operator_wait_ready || rc=1
    fi
    if [[ "$rc" -eq 0 ]]; then
      echo "Compliance Operator installed in $(co_namespace) on ${sc_label:-cluster}"
    fi
  fi
  return "$rc"
}

compliance_operator_run() {
  local dry_run="${1:-false}"
  local rc=0 sc_id sc_name errf err any=false
  local do_oc=true do_central=true

  case "${CO_PLANE}" in
    openshift) do_central=false ;;
    central) do_oc=false ;;
  esac

  if [[ "$do_oc" == "true" ]]; then
    if ! command -v oc >/dev/null 2>&1; then
      echo "oc not on PATH" >&2
      compliance_operator_emit_status
      return 1
    fi

    while IFS=$'\t' read -r sc_id sc_name; do
      [[ -n "$sc_id" ]] || continue
      any=true
      CO_SC_IDS=("$sc_id")
      errf="$(mktemp)"
      if ! co_ensure_oc_sc "$sc_id" 2>"${errf}"; then
        err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
        rm -f "${errf}"
        echo "Skip OLM on ${sc_name}: ${err:-OpenShift access failed}" >&2
        rc=1
        continue
      fi
      rm -f "${errf}"
      compliance_operator_run_olm_one "$dry_run" "$sc_name" || rc=1
    done < <(co_list_sc_targets)

    if [[ "$any" != "true" ]]; then
      echo "no secured clusters listed for this lab" >&2
      compliance_operator_emit_status
      return 1
    fi
  fi

  if [[ "$do_central" == "true" ]]; then
    compliance_operator_run_scan "$dry_run" || rc=1
  fi

  local status_out module_row state
  status_out="$(compliance_operator_emit_status || true)"
  printf '%s\n' "$status_out"
  module_row="$(printf '%s\n' "$status_out" | awk -F'\t' -v id="$MODULE_ID" '$1 == id { print; exit }')"
  state="$(printf '%s' "$module_row" | awk -F'\t' '{ print $2 }')"

  if [[ "$dry_run" == "true" ]]; then
    [[ "$state" != "error" ]] && [[ "$rc" -eq 0 ]]
    return
  fi

  # Plane-scoped runs: OLM-only may be needs-run for schedule; treat operator ok as success.
  if [[ "$do_central" != "true" ]]; then
    [[ "$rc" -eq 0 ]]
    return
  fi
  if [[ "$do_oc" != "true" ]]; then
    [[ "$rc" -eq 0 ]]
    return
  fi
  [[ "$state" == "ok" ]] && [[ "$rc" -eq 0 ]]
}

compliance_operator_uninstall_plan() {
  local ns sub
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  cat <<EOF
Planned uninstall:
  - Delete Central scan configuration for this module (if present)
  - Delete Subscription/${sub} in ${ns} (if present)
  - Delete compliance-operator ClusterServiceVersion(s) in ${ns} (if present)
  - Delete OperatorGroup/compliance-operator in ${ns} (if present)
  - Delete namespace ${ns} (removes remaining CO CRs in that namespace)
EOF
}

compliance_operator_uninstall_scan() {
  local dry_run="${1:-false}"
  local helper py flag
  local -a args=(uninstall --cli)
  helper="$(co_scan_helper)"
  py="$(co_python)"
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && args+=("$flag")
  done < <(co_scan_common_args)

  echo "Remove compliance scan schedule from Central (if present)"
  if [[ ! -f "$helper" ]]; then
    echo "missing helper: $helper" >&2
    return 1
  fi
  if ! "$py" "$helper" "${args[@]}"; then
    return 1
  fi
}

compliance_operator_uninstall_olm() {
  local dry_run="${1:-false}"
  local ns sub
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"

  if [[ "$dry_run" == "true" ]]; then
    compliance_operator_uninstall_plan
    return 0
  fi

  if oc get "subscription/${sub}" -n "${ns}" >/dev/null 2>&1; then
    echo "Delete Subscription/${sub} in ${ns}"
    oc delete "subscription/${sub}" -n "${ns}" --wait=true --timeout=120s || true
  else
    echo "Subscription/${sub} not present in ${ns}"
  fi

  # Delete CSVs this operator owns (name prefix from OLM).
  local csvs
  csvs="$(oc get csv -n "${ns}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
  if [[ -n "${csvs}" ]]; then
    while IFS= read -r csv; do
      [[ -n "$csv" ]] || continue
      case "$csv" in
        compliance-operator.*)
          echo "Delete ClusterServiceVersion/${csv} in ${ns}"
          oc delete "csv/${csv}" -n "${ns}" --wait=true --timeout=180s || true
          ;;
      esac
    done <<<"${csvs}"
  fi

  if oc get operatorgroup/compliance-operator -n "${ns}" >/dev/null 2>&1; then
    echo "Delete OperatorGroup/compliance-operator in ${ns}"
    oc delete operatorgroup/compliance-operator -n "${ns}" --wait=true --timeout=60s || true
  else
    echo "OperatorGroup/compliance-operator not present in ${ns}"
  fi

  # ProfileBundles keep namespace finalizers after the operator CSV is gone; clear them
  # so namespace deletion can finish.
  local pbs
  pbs="$(oc get profilebundle.compliance -n "${ns}" -o name 2>/dev/null || true)"
  if [[ -n "${pbs}" ]]; then
    while IFS= read -r pb; do
      [[ -n "$pb" ]] || continue
      echo "Clear finalizers on ${pb}"
      oc patch "${pb}" -n "${ns}" --type=merge -p '{"metadata":{"finalizers":[]}}' || true
      oc delete "${pb}" -n "${ns}" --wait=false || true
    done <<<"${pbs}"
  fi

  if oc get "namespace/${ns}" >/dev/null 2>&1; then
    echo "Delete namespace ${ns}"
    oc delete "namespace/${ns}" --wait=true --timeout=300s
  else
    echo "Namespace ${ns} already absent"
  fi
}

compliance_operator_uninstall() {
  local dry_run="${1:-false}"
  local rc=0 sc_id sc_name errf err any=false
  local do_oc=true do_central=true

  case "${CO_PLANE}" in
    openshift) do_central=false ;;
    central) do_oc=false ;;
  esac

  # Orchestrator order for both: OpenShift N then Central. Single-process
  # (no --plane): OpenShift then Central as well.
  if [[ "$do_oc" == "true" ]]; then
    if ! command -v oc >/dev/null 2>&1; then
      echo "oc not on PATH" >&2
      return 1
    fi

    if [[ "$dry_run" == "true" ]]; then
      while IFS=$'\t' read -r sc_id sc_name; do
        [[ -n "$sc_id" ]] || continue
        any=true
        echo "=== dry-run uninstall OLM on ${sc_name} ==="
        if co_ensure_oc_sc "$sc_id" 2>/dev/null; then
          compliance_operator_uninstall_plan
        else
          echo "  (would skip ${sc_name}: OpenShift access unavailable)"
        fi
      done < <(co_list_sc_targets)
    else
      while IFS=$'\t' read -r sc_id sc_name; do
        [[ -n "$sc_id" ]] || continue
        any=true
        errf="$(mktemp)"
        if ! co_ensure_oc_sc "$sc_id" 2>"${errf}"; then
          err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
          rm -f "${errf}"
          echo "Skip OLM uninstall on ${sc_name}: ${err:-OpenShift access failed}" >&2
          rc=1
          continue
        fi
        rm -f "${errf}"
        echo "=== Uninstall Compliance Operator OLM on ${sc_name} ==="
        compliance_operator_uninstall_olm false || rc=1
      done < <(co_list_sc_targets)
    fi

    if [[ "$any" != "true" ]]; then
      echo "no secured clusters listed for this lab" >&2
      return 1
    fi
  fi

  if [[ "$do_central" == "true" ]]; then
    compliance_operator_uninstall_scan "$dry_run" || rc=1
  fi

  if [[ "$rc" -eq 0 && "$dry_run" != "true" ]]; then
    echo "Compliance Operator module uninstall finished (plane=${CO_PLANE:-both})."
  fi
  return "$rc"
}
