#!/usr/bin/env bash
# Shared helpers for compliance-operator module (phase 1: OLM install only).
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

compliance_operator_emit_status() {
  local ns sub line st msg
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"

  if ! command -v oc >/dev/null 2>&1; then
    printf '%s\terror\toc not on PATH\n' "$MODULE_ID"
    return 1
  fi
  if ! oc whoami >/dev/null 2>&1; then
    printf '%s\terror\toc not logged in (secured cluster)\n' "$MODULE_ID"
    return 1
  fi
  if ! oc get "namespace/${ns}" >/dev/null 2>&1; then
    printf '%s\tneeds-run\tnamespace %s missing\n' "$MODULE_ID" "$ns"
    return 0
  fi
  if ! oc get "subscription/${sub}" -n "${ns}" >/dev/null 2>&1; then
    printf '%s\tneeds-run\tSubscription %s missing in %s\n' "$MODULE_ID" "$sub" "$ns"
    return 0
  fi

  line="$(co_csv_status_line "${ns}")"
  st="${line%%$'\t'*}"
  msg="${line#*$'\t'}"
  if [[ "$st" != "ok" ]]; then
    printf '%s\t%s\t%s\n' "$MODULE_ID" "$st" "$msg"
    return 0
  fi

  printf '%s\tok\tCompliance Operator %s; scan schedule: not configured (phase 2)\n' "$MODULE_ID" "$msg"
}

compliance_operator_plan() {
  local ns sub channel
  ns="$(co_namespace)"
  sub="$(co_subscription_name)"
  channel="$(co_channel)"
  cat <<EOF
Planned changes (phase 1 — OLM install only):
  - Create namespace ${ns}
  - Apply OperatorGroup compliance-operator in ${ns}
  - Apply Subscription ${sub} (compliance-operator, channel ${channel})
  - Wait for CSV Succeeded (timeout $(co_csv_timeout)s)
  - Wait for compliance-operator deployment rollout (timeout $(co_rollout_timeout)s)
Scan schedules are not applied here; phase 2 uses Central API (RHACS UI equivalent).
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

  if [[ "${ACS_COMPLIANCE_PATCH_NODE_SELECTOR:-}" == "1" ]]; then
    echo "Annotate namespace ${ns} (clear default node selector)"
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

compliance_operator_run() {
  local dry_run="${1:-false}"

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
  elif co_csv_succeeded_name "$(co_namespace)" >/dev/null 2>&1 \
    && [[ -n "$(co_main_deployment "$(co_namespace)" 2>/dev/null || true)" ]]; then
    echo "Compliance Operator already installed; verifying rollout"
    compliance_operator_wait_ready
    echo "No changes required."
  else
    compliance_operator_apply_manifests
    compliance_operator_wait_ready
    echo "Compliance Operator installed in $(co_namespace)"
  fi

  local status_line state
  status_line="$(compliance_operator_emit_status)"
  printf '%s\n' "$status_line"
  state="$(printf '%s' "$status_line" | awk -F'\t' '{print $2}')"
  if [[ "$dry_run" == "true" ]]; then
    [[ "$state" != "error" ]]
  else
    [[ "$state" == "ok" ]]
  fi
}
