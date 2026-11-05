#!/usr/bin/env bash
# Helpers for splunk-TA (Splunk Operator + Standalone + RHACS TA).
set -euo pipefail

MODULE_ID="splunk-TA"

# Lab defaults (not env-configurable).
readonly STA_NS="splunk-demo"
readonly STA_CR="lab"
readonly STA_POD="splunk-lab-standalone-0"
readonly STA_ROUTE="splunk-web"
readonly STA_SVC="splunk-lab-standalone-service"
readonly STA_ADMIN_SECRET="splunk-lab-standalone-secret-v1"
readonly STA_HELM_RELEASE="splunk-operator"
readonly STA_HELM_CHART_VERSION="3.1.0"
readonly STA_OPERATOR_IMAGE="docker.io/splunk/splunk-operator:3.0.0"
readonly STA_CRD_URL="https://github.com/splunk/splunk-operator/releases/download/3.0.0/splunk-operator-crds.yaml"
readonly STA_TA_DIR_DEFAULT="${HOME}/code/Splunk"

# Set by splunk-TA.sh from flags before calling into this lib.
STA_TA_DIR="${STA_TA_DIR:-$STA_TA_DIR_DEFAULT}"
STA_SKIP_TA="${STA_SKIP_TA:-false}"

sta_python() {
  if [[ -n "${ACS_DEMO_PYTHON:-}" ]]; then
    printf '%s' "$ACS_DEMO_PYTHON"
  elif [[ -n "${SPLUNK_MODULE_ROOT:-}" ]] \
    && [[ -x "${SPLUNK_MODULE_ROOT}/gui/.venv/bin/python" ]]; then
    printf '%s' "${SPLUNK_MODULE_ROOT}/gui/.venv/bin/python"
  else
    command -v python3
  fi
}

sta_need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing command: %s\n' "$1" >&2
    return 1
  }
}

sta_ensure_oc() {
  local py kc err errf
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  if [[ -z "${SPLUNK_MODULE_ROOT:-}" ]]; then
    printf 'SPLUNK_MODULE_ROOT unset\n' >&2
    return 1
  fi
  py="$(sta_python)"
  errf="$(mktemp)"
  if ! kc="$(
    cd "${SPLUNK_MODULE_ROOT}" || exit 1
    "$py" -m lib.openshift login --print-kubeconfig 2>"${errf}"
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

sta_ensure_helm() {
  if command -v helm >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x /opt/homebrew/bin/helm ]]; then
    export PATH="/opt/homebrew/bin:${PATH}"
    return 0
  fi
  if [[ -x /usr/local/bin/helm ]]; then
    export PATH="/usr/local/bin:${PATH}"
    return 0
  fi
  printf 'helm not on PATH (install: brew install helm)\n' >&2
  return 1
}

# Prints absolute path of chosen .tgz on stdout. Returns 1 if none.
sta_pick_ta_tgz() {
  local dir f
  local -a files=()
  dir="${STA_TA_DIR}"
  if [[ ! -d "$dir" ]]; then
    return 1
  fi
  shopt -s nullglob
  files=("${dir}"/*.tgz)
  shopt -u nullglob
  if ((${#files[@]} == 0)); then
    return 1
  fi
  if ((${#files[@]} > 1)); then
    printf 'WARN: multiple .tgz in %s; using preference order\n' "$dir" >&2
  fi
  for f in "${files[@]}"; do
    case "$(basename "$f" | tr '[:upper:]' '[:lower:]')" in
      *advanced*cluster*security*|*stackrox*|*acs*)
        printf '%s' "$f"
        return 0
        ;;
    esac
  done
  printf '%s' "${files[0]}"
}

sta_default_storage_class() {
  oc get storageclass -o json 2>/dev/null | python3 -c '
import json, sys
try:
    j = json.load(sys.stdin)
except Exception:
    sys.exit(1)
items = j.get("items") or []
for it in items:
    ann = (it.get("metadata") or {}).get("annotations") or {}
    if ann.get("storageclass.kubernetes.io/is-default-class") == "true":
        print((it.get("metadata") or {}).get("name") or "")
        sys.exit(0)
if items:
    print((items[0].get("metadata") or {}).get("name") or "")
else:
    sys.exit(1)
' || {
    printf 'could not determine StorageClass\n' >&2
    return 1
  }
}

sta_route_host() {
  oc get "route/${STA_ROUTE}" -n "${STA_NS}" -o jsonpath='{.spec.host}' 2>/dev/null || true
}

sta_operator_ok() {
  oc get deploy/splunk-operator-controller-manager -n "${STA_NS}" -o name >/dev/null 2>&1
}

sta_pod_phase_ready() {
  local out
  out="$(oc get "pod/${STA_POD}" -n "${STA_NS}" -o json 2>/dev/null)" || {
    printf 'missing\tfalse\tfalse\n'
    return 0
  }
  printf '%s' "$out" | python3 -c '
import json, sys
dj = json.load(sys.stdin)
st = dj.get("status") or {}
phase = (st.get("phase") or "").strip() or "Unknown"
ready = False
failed = phase == "Failed"
for c in st.get("conditions") or []:
    if c.get("type") == "Ready" and c.get("status") == "True":
        ready = True
        break
bad = frozenset(("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"))
for cs in st.get("containerStatuses") or []:
    w = (cs.get("state") or {}).get("waiting") or {}
    if (w.get("reason") or "") in bad:
        failed = True
        break
print("%s\t%s\t%s" % (phase, "true" if ready else "false", "true" if failed else "false"))
'
}

sta_ta_installed() {
  oc exec -n "${STA_NS}" "${STA_POD}" -- test -d /opt/splunk/etc/apps/TA-stackrox >/dev/null 2>&1
}

sta_emit_status() {
  local host web ta_path
  local tag_ns tag_op tag_pod tag_route tag_ta_local tag_ta_pod
  local sum_ns sum_op sum_pod sum_route sum_ta_local sum_ta_pod
  local sec_ns sec_op sec_pod sec_route sec_ta_local sec_ta_pod
  local op_ok phase ready failed state msg sections_json

  if ! command -v oc >/dev/null 2>&1; then
    printf 'ACS_SECTIONS_JSON=%s\n' '{"sections":[]}'
    printf '%s\terror\toc not on PATH\n' "$MODULE_ID"
    return 1
  fi
  if ! sta_ensure_oc; then
    printf 'ACS_SECTIONS_JSON=%s\n' '{"sections":[{"group":"OpenShift","title":"Lab access","summary":"failed","tag":"error","tagLabel":"error","body":"Could not build per-lab kubeconfig from lab-credentials.json.","bodyFormat":"prose"}]}'
    printf '%s\terror\tOpenShift access failed\n' "$MODULE_ID"
    return 1
  fi

  if ! oc get "namespace/${STA_NS}" >/dev/null 2>&1; then
    tag_ns=error
    sum_ns="missing"
    sec_ns="Namespace ${STA_NS} not found."
  else
    tag_ns=ok
    sum_ns="present"
    sec_ns="Namespace ${STA_NS} exists."
  fi

  if [[ "${tag_ns}" == "ok" ]] && sta_operator_ok; then
    tag_op=ok
    sum_op="available"
    sec_op="Deployment splunk-operator-controller-manager present in ${STA_NS}."
    op_ok=true
  else
    tag_op=error
    sum_op="missing"
    sec_op="Splunk Operator deployment not found in ${STA_NS}."
    op_ok=false
  fi

  IFS=$'\t' read -r phase ready failed <<<"$(sta_pod_phase_ready)"
  if [[ "$phase" == "missing" ]]; then
    tag_pod=error
    sum_pod="missing"
    sec_pod="Pod ${STA_POD} not found."
  elif [[ "$failed" == "true" ]]; then
    tag_pod=error
    sum_pod="$phase"
    sec_pod="Pod ${STA_POD} failed (phase=${phase})."
  elif [[ "$ready" == "true" || "$phase" == "Running" ]]; then
    tag_pod=ok
    if [[ "$ready" == "true" ]]; then
      sum_pod="${phase} · Ready"
    else
      sum_pod="${phase}"
    fi
    sec_pod="Pod ${STA_POD}: phase=${phase}, Ready=${ready}."
  else
    tag_pod=error
    sum_pod="$phase"
    sec_pod="Pod ${STA_POD}: phase=${phase}, Ready=${ready}."
  fi

  host="$(sta_route_host)"
  if [[ -n "$host" ]]; then
    web="https://${host}"
    tag_route=ok
    sum_route="present"
    sec_route="Route ${STA_ROUTE} → ${web}"
  else
    web=""
    tag_route=error
    sum_route="missing"
    sec_route="Route ${STA_ROUTE} not found in ${STA_NS}."
  fi

  if ta_path="$(sta_pick_ta_tgz)"; then
    tag_ta_local=ok
    sum_ta_local="found"
    sec_ta_local="Using ${ta_path}"
  else
    tag_ta_local=error
    sum_ta_local="missing"
    sec_ta_local="No .tgz under ${STA_TA_DIR}. Download from https://splunkbase.splunk.com/app/5315 (see --help)."
  fi

  if [[ "$tag_pod" == "ok" ]] && sta_ta_installed; then
    tag_ta_pod=ok
    sum_ta_pod="TA-stackrox"
    sec_ta_pod="App directory /opt/splunk/etc/apps/TA-stackrox present in pod."
  elif [[ "$tag_pod" != "ok" ]]; then
    tag_ta_pod=error
    sum_ta_pod="n/a"
    sec_ta_pod="Cannot check TA until Standalone pod is Ready."
  else
    tag_ta_pod=error
    sum_ta_pod="not installed"
    sec_ta_pod="TA-stackrox not found in the Splunk pod. Place the .tgz under ${STA_TA_DIR} and --run."
  fi

  if [[ "$tag_ns" != "ok" ]]; then
    state=needs-run
    msg="namespace ${STA_NS} missing"
  elif [[ "$op_ok" != "true" || "$tag_pod" != "ok" || "$tag_route" != "ok" ]]; then
    state=needs-run
    msg="Splunk lab incomplete"
    [[ -n "$web" ]] && msg="${msg} · ${web}"
  elif [[ "$tag_ta_pod" != "ok" ]]; then
    state=needs-run
    msg="Splunk up; TA not installed"
    [[ -n "$web" ]] && msg="${msg} · ${web}"
  else
    state=ok
    msg="${web:-Splunk + TA ready}"
  fi

  sections_json="$(
    jq -nc \
      --arg ns_body "$sec_ns" --arg ns_sum "$sum_ns" --arg ns_tag "$tag_ns" \
      --arg op_body "$sec_op" --arg op_sum "$sum_op" --arg op_tag "$tag_op" \
      --arg pod_body "$sec_pod" --arg pod_sum "$sum_pod" --arg pod_tag "$tag_pod" \
      --arg route_body "$sec_route" --arg route_sum "$sum_route" --arg route_tag "$tag_route" \
      --arg tal_body "$sec_ta_local" --arg tal_sum "$sum_ta_local" --arg tal_tag "$tag_ta_local" \
      --arg tap_body "$sec_ta_pod" --arg tap_sum "$sum_ta_pod" --arg tap_tag "$tag_ta_pod" \
      --arg pod "$STA_POD" \
      '{
        sections: [
          {group:"Cluster", title:"Namespace", summary:$ns_sum, tag:$ns_tag, tagLabel:$ns_tag, body:$ns_body, bodyFormat:"prose"},
          {group:"Splunk Operator", title:"Controller", summary:$op_sum, tag:$op_tag, tagLabel:$op_tag, body:$op_body, bodyFormat:"prose"},
          {group:"Standalone", title:("Pod " + $pod), summary:$pod_sum, tag:$pod_tag, tagLabel:$pod_tag, body:$pod_body, bodyFormat:"prose"},
          {group:"Access", title:"Splunk Web Route", summary:$route_sum, tag:$route_tag, tagLabel:$route_tag, body:$route_body, bodyFormat:"prose"},
          {group:"RHACS TA", title:"Local .tgz", summary:$tal_sum, tag:$tal_tag, tagLabel:$tal_tag, body:$tal_body, bodyFormat:"prose"},
          {group:"RHACS TA", title:"Installed in Splunk", summary:$tap_sum, tag:$tap_tag, tagLabel:$tap_tag, body:$tap_body, bodyFormat:"prose"}
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
  printf '%s\t%s\t%s\n' "$MODULE_ID" "$state" "$msg"
  [[ "$state" != "error" ]]
}

sta_run_plan() {
  local ta_path sc
  ta_path=""
  if [[ "$STA_SKIP_TA" == "true" ]]; then
    ta_path="(skipped via --skip-ta)"
  elif ta_path="$(sta_pick_ta_tgz 2>/dev/null)"; then
    :
  else
    ta_path="(MISSING - place RHACS TA .tgz under ${STA_TA_DIR})"
  fi
  sc="(resolve default StorageClass via oc)"
  if sta_ensure_oc 2>/dev/null; then
    sc="$(sta_default_storage_class 2>/dev/null || printf '%s' "$sc")"
  fi

  cat <<EOF
${MODULE_ID}: dry-run (--run)
  1. Ensure namespace ${STA_NS}
  2. Apply Splunk Operator CRDs: ${STA_CRD_URL}
  3. Helm upgrade --install ${STA_HELM_RELEASE} (chart ${STA_HELM_CHART_VERSION}, image ${STA_OPERATOR_IMAGE})
  4. Bind SCC nonroot-v2; wait for operator
  5. Apply Standalone ${STA_CR} (Free; StorageClass ${sc}; PVCs 10Gi+20Gi; 500m/4Gi req)
  6. Wait for pod ${STA_POD} Ready; Route ${STA_ROUTE} if missing
  7. Install RHACS TA from: ${ta_path}
  Notes: CRDs stay on uninstall; Splunk UI Central/token/inputs are manual (demo notes).
EOF
}

sta_uninstall_plan() {
  cat <<EOF
${MODULE_ID}: dry-run (--uninstall)
  1. Delete Standalone ${STA_CR} in ${STA_NS}
  2. Helm uninstall ${STA_HELM_RELEASE} -n ${STA_NS}
  3. Delete namespace ${STA_NS}
  CRDs are left in place.
EOF
}

sta_install_ta() {
  local ta_local remote admin_pass
  remote=/tmp/rhacs_ta.tgz

  if [[ "$STA_SKIP_TA" == "true" ]]; then
    echo "==> [splunk-TA] Skipping TA install (--skip-ta)"
    return 0
  fi

  if ! ta_local="$(sta_pick_ta_tgz)"; then
    printf 'ERROR: No RHACS TA .tgz under %s\n' "${STA_TA_DIR}" >&2
    printf 'Download: https://splunkbase.splunk.com/app/5315\n' >&2
    printf 'Place the .tgz there, or pass --skip-ta for stack-only. See --help.\n' >&2
    return 1
  fi

  echo "==> [splunk-TA] Install TA from ${ta_local}"
  oc cp "${ta_local}" "${STA_NS}/${STA_POD}:${remote}"
  admin_pass="$(oc get secret "${STA_ADMIN_SECRET}" -n "${STA_NS}" -o jsonpath='{.data.password}' | base64 -d)"
  oc exec -n "${STA_NS}" "${STA_POD}" -- /opt/splunk/bin/splunk install app "${remote}" \
    -auth "admin:${admin_pass}" -update 1 \
    || {
      printf 'splunk install app failed\n' >&2
      return 1
    }
  echo "==> [splunk-TA] Restart Splunk (session may disconnect)"
  oc exec -n "${STA_NS}" "${STA_POD}" -- /opt/splunk/bin/splunk restart -auth "admin:${admin_pass}" || true
  oc wait --for=condition=ready "pod/${STA_POD}" -n "${STA_NS}" --timeout=600s \
    || printf 'WARN: pod not Ready after restart - check: oc get pods -n %s\n' "$STA_NS" >&2
  return 0
}

sta_run() {
  local sc tmpv _wait_start
  sta_need_cmd oc
  sta_need_cmd python3
  sta_ensure_helm
  sta_ensure_oc || return 1

  if [[ "$STA_SKIP_TA" != "true" ]] && ! sta_pick_ta_tgz >/dev/null; then
    printf 'ERROR: No RHACS TA .tgz under %s\n' "${STA_TA_DIR}" >&2
    printf 'Download: https://splunkbase.splunk.com/app/5315\n' >&2
    printf 'Place the .tgz there, or pass --skip-ta for stack-only. See --help.\n' >&2
    return 1
  fi

  echo "==> [splunk-TA] OpenShift context"
  oc whoami >/dev/null || {
    printf 'oc whoami failed\n' >&2
    return 1
  }

  echo "==> [splunk-TA] Namespace ${STA_NS}"
  oc new-project "${STA_NS}" 2>/dev/null || oc project "${STA_NS}" >/dev/null

  echo "==> [splunk-TA] Splunk Operator CRDs"
  oc apply -f "${STA_CRD_URL}" --server-side || {
    printf 'CRD apply failed\n' >&2
    return 1
  }

  echo "==> [splunk-TA] Helm repo + operator"
  helm repo add splunk https://splunk.github.io/splunk-operator/ >/dev/null 2>&1 || true
  helm repo update
  tmpv="$(mktemp)"
  {
    echo "splunkOperator:"
    echo "  splunkGeneralTerms: \"--accept-sgt-current-at-splunk-com\""
  } >"${tmpv}"
  helm upgrade --install "${STA_HELM_RELEASE}" splunk/splunk-operator -n "${STA_NS}" \
    -f "${tmpv}" --version "${STA_HELM_CHART_VERSION}" \
    --set "splunkOperator.image.repository=${STA_OPERATOR_IMAGE}" || {
    rm -f "${tmpv}"
    printf 'helm install operator failed\n' >&2
    return 1
  }
  rm -f "${tmpv}"

  echo "==> [splunk-TA] SCC bindings (nonroot-v2)"
  oc adm policy add-scc-to-user nonroot-v2 -z splunk-operator-controller-manager -n "${STA_NS}" 2>/dev/null || true
  oc adm policy add-scc-to-user nonroot-v2 -z default -n "${STA_NS}" 2>/dev/null || true

  echo "==> [splunk-TA] Wait for operator deployment"
  oc wait --for=condition=available "deployment/splunk-operator-controller-manager" -n "${STA_NS}" --timeout=300s \
    || {
      printf 'operator deployment not available\n' >&2
      return 1
    }

  oc adm policy add-scc-to-user nonroot-v2 -z splunk-operator-controller-manager -n "${STA_NS}" 2>/dev/null || true
  oc adm policy add-scc-to-user nonroot-v2 -z default -n "${STA_NS}" 2>/dev/null || true

  sc="$(sta_default_storage_class)"
  echo "==> [splunk-TA] Standalone CR (${STA_CR}) StorageClass ${sc}"
  oc apply -f - <<EOF
apiVersion: enterprise.splunk.com/v4
kind: Standalone
metadata:
  name: ${STA_CR}
  namespace: ${STA_NS}
  finalizers:
    - enterprise.splunk.com/delete-pvc
spec:
  etcVolumeStorageConfig:
    storageClassName: ${sc}
    storageCapacity: 10Gi
  varVolumeStorageConfig:
    storageClassName: ${sc}
    storageCapacity: 20Gi
  resources:
    requests:
      cpu: 500m
      memory: 4Gi
    limits:
      cpu: "2"
      memory: 6Gi
  extraEnv:
    - name: SPLUNK_START_ARGS
      value: "--accept-license"
    - name: SPLUNK_LICENSE_URI
      value: "Free"
EOF

  echo "==> [splunk-TA] Wait for Standalone pod ${STA_POD}"
  _wait_start=$SECONDS
  while ! oc get "pod/${STA_POD}" -n "${STA_NS}" -o name >/dev/null 2>&1; do
    if ((SECONDS - _wait_start >= 600)); then
      echo "    Pods:" >&2
      oc get pods -n "${STA_NS}" -o wide 2>&1 >&2 || true
      echo "    Standalone / PVC:" >&2
      oc get standalone,pvc -n "${STA_NS}" 2>&1 >&2 || true
      printf 'pod %s not created after 600s\n' "$STA_POD" >&2
      return 1
    fi
    sleep 5
  done
  oc wait --for=condition=ready "pod/${STA_POD}" -n "${STA_NS}" --timeout=600s \
    || {
      printf 'pod %s not ready\n' "$STA_POD" >&2
      return 1
    }

  if ! oc get route "${STA_ROUTE}" -n "${STA_NS}" >/dev/null 2>&1; then
    echo "==> [splunk-TA] Route ${STA_ROUTE}"
    oc expose svc "${STA_SVC}" -n "${STA_NS}" --port=8000 --name="${STA_ROUTE}"
    oc patch "route/${STA_ROUTE}" -n "${STA_NS}" \
      -p '{"spec":{"tls":{"termination":"edge","insecureEdgeTerminationPolicy":"Redirect"}}}' || true
  else
    echo "    Route ${STA_ROUTE} already exists"
  fi

  sta_install_ta || return 1

  echo ""
  echo "=== splunk-TA: done ==="
  echo "Splunk Web: https://$(sta_route_host)"
  echo "Admin password: oc get secret ${STA_ADMIN_SECRET} -n ${STA_NS} -o go-template='{{index .data \"password\" | base64decode}}{{println}}'"
}

sta_uninstall() {
  sta_need_cmd oc
  sta_ensure_helm
  sta_ensure_oc || return 1

  if ! oc get "namespace/${STA_NS}" >/dev/null 2>&1; then
    echo "==> [splunk-TA] Namespace ${STA_NS} already absent"
    return 0
  fi

  echo "==> [splunk-TA] Delete Standalone ${STA_CR}"
  oc delete standalone "${STA_CR}" -n "${STA_NS}" --ignore-not-found=true --wait=true --timeout=300s || true

  echo "==> [splunk-TA] Helm uninstall ${STA_HELM_RELEASE}"
  helm uninstall "${STA_HELM_RELEASE}" -n "${STA_NS}" 2>/dev/null || true

  echo "==> [splunk-TA] Delete namespace ${STA_NS}"
  oc delete namespace "${STA_NS}" --ignore-not-found=true --wait=true --timeout=300s || true

  echo "=== splunk-TA: uninstall finished (CRDs left in place) ==="
}
