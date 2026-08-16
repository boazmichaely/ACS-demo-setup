#!/usr/bin/env bash
# Shared helpers for compliance-operator module (OLM install + Central scan schedule).
set -euo pipefail

MODULE_ID="compliance-operator"

co_namespace() {
  printf '%s' "${COMPLIANCE_OPERATOR_NAMESPACE:-openshift-compliance}"
}

co_subscription_name() {
  printf '%s' "${COMPLIANCE_SUBSCRIPTION_NAME:-compliance-operator-sub}"
}

co_channel() {
  printf '%s' "${COMPLIANCE_OPERATOR_CHANNEL:-stable}"
}

co_csv_timeout() {
  printf '%s' "${COMPLIANCE_CSV_TIMEOUT_SECONDS:-600}"
}

co_rollout_timeout() {
  printf '%s' "${COMPLIANCE_ROLLOUT_TIMEOUT_SECONDS:-240}"
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
  if ! oc whoami >/dev/null 2>&1; then
    printf 'error\toc not logged in (secured cluster)\n'
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
  helper="$(co_scan_helper)"
  py="$(co_python)"
  if [[ ! -f "$helper" ]]; then
    printf 'error\tmissing helper %s\n' "$helper"
    return 1
  fi
  if ! output="$("$py" "$helper" status --cli 2>&1)"; then
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

compliance_operator_emit_status() {
  local op_line scan_line op_st
  if ! op_line="$(co_operator_status_line)"; then
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

compliance_operator_apply_manifests() {
  local ns sub channel
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  channel="$(co_channel)"

  echo "Create namespace ${ns}"
  oc apply -f - <<EOF
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
  # Default: do not touch namespace scheduling (respect cluster policy).
  # ACS_COMPLIANCE_PATCH_NODE_SELECTOR=1: clear the annotation so CO workloads
  # are not pinned by that inherited selector (broader scheduling in this NS).
  if [[ "${ACS_COMPLIANCE_PATCH_NODE_SELECTOR:-}" == "1" ]]; then
    echo "Annotate namespace ${ns} (clear openshift.io/node-selector for broader scheduling)"
    oc annotate namespace "${ns}" openshift.io/node-selector="" --overwrite 2>/dev/null \
      || echo "  (annotate openshift.io/node-selector skipped)"
  fi

  echo "Apply OperatorGroup + Subscription ${sub} (channel ${channel})"
  oc apply -f - <<EOF
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
      echo "Waiting for Compliance Operator CSV… (${SECONDS - start}s elapsed)" >&2
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

compliance_operator_run_scan() {
  local dry_run="${1:-false}"
  local helper py args=()
  helper="$(co_scan_helper)"
  py="$(co_python)"
  args=(run --cli)
  [[ "$dry_run" == "true" ]] && args+=(--dry-run)

  echo "Configure compliance scan schedule in Central (phase 2)"
  if [[ ! -f "$helper" ]]; then
    echo "missing helper: $helper" >&2
    return 1
  fi
  if ! "$py" "$helper" "${args[@]}"; then
    return 1
  fi
}

compliance_operator_run() {
  local dry_run="${1:-false}"
  local rc=0

  if ! command -v oc >/dev/null 2>&1; then
    echo "oc not on PATH" >&2
    compliance_operator_emit_status
    return 1
  fi
  if ! oc whoami >/dev/null 2>&1; then
    echo "oc not logged in — log in to the secured cluster" >&2
    compliance_operator_emit_status
    return 1
  fi

  if [[ "$dry_run" == "true" ]]; then
    compliance_operator_plan
    compliance_operator_run_scan true || rc=1
  elif co_csv_succeeded_name "$(co_namespace)" >/dev/null 2>&1 \
    && [[ -n "$(co_main_deployment "$(co_namespace)" 2>/dev/null || true)" ]]; then
    echo "Compliance Operator already installed; verifying rollout"
    compliance_operator_wait_ready || rc=1
    if [[ "$rc" -eq 0 ]]; then
      echo "No operator changes required."
    fi
  else
    compliance_operator_apply_manifests || rc=1
    if [[ "$rc" -eq 0 ]]; then
      compliance_operator_wait_ready || rc=1
    fi
    if [[ "$rc" -eq 0 ]]; then
      echo "Compliance Operator installed in $(co_namespace)"
    fi
  fi

  if [[ "$rc" -eq 0 ]]; then
    compliance_operator_run_scan "$dry_run" || rc=1
  fi

  local status_line state
  status_line="$(compliance_operator_emit_status || true)"
  printf '%s\n' "$status_line"

  if [[ "$dry_run" == "true" ]]; then
    state="$(printf '%s' "$status_line" | awk -F'\t' '{print $2}')"
    [[ "$state" != "error" ]] && [[ "$rc" -eq 0 ]]
    return
  fi

  state="$(printf '%s' "$status_line" | awk -F'\t' '{print $2}')"
  [[ "$state" == "ok" ]] && [[ "$rc" -eq 0 ]]
}
