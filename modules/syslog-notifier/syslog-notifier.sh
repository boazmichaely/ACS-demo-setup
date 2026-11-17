#!/usr/bin/env bash
# Module: syslog-notifier - SC CEF sink + Central Syslog notifier
set -euo pipefail

MODULE_ID="syslog-notifier"
NS="acs-syslog-demo"
APP="syslog-receiver"
SVC_SYSLOG="syslog-receiver"
SVC_VIEWER="syslog-viewer"
ROUTE_VIEWER="syslog-viewer"
SYSLOG_PORT=5140
HTTP_PORT=8080
LB_WAIT_SECONDS=300
RING_SIZE=100
IMAGE="registry.access.redhat.com/ubi9/python-311:latest"
DEFAULT_NOTIFIER_NAME="acs-demo-syslog"

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${MODULE_DIR}/../.." && pwd)"
[[ -f "$ROOT/config/modules.json" ]] || { echo "ROOT miscomputed: $ROOT" >&2; exit 1; }
ASSET_DIR="${MODULE_DIR}"
RECEIVER_PY="${ASSET_DIR}/receiver.py"
HELPER="${MODULE_DIR}/syslog_notifier.py"

PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

SYSLOG_PLANE=""
SYSLOG_SC_IDS=()
SYSLOG_SC_ID=""
NOTIFIER_NAME="${DEFAULT_NOTIFIER_NAME}"
MESSAGE_FORMAT="CEF"
EXTRA_HELPER=()

want_secured_cluster() {
  [[ -z "${SYSLOG_PLANE}" || "${SYSLOG_PLANE}" == "secured-cluster" || "${SYSLOG_PLANE}" == "openshift" ]]
}
want_central_api() {
  [[ -z "${SYSLOG_PLANE}" || "${SYSLOG_PLANE}" == "central-api" || "${SYSLOG_PLANE}" == "central" ]]
}

usage() {
  cat <<EOF
# syslog-notifier

Deploy a generic TCP syslog/CEF receiver with a ring-buffer HTML viewer on a
**secured cluster**, then configure Central's Syslog notifier to that public
LoadBalancer endpoint and run Central Test.

Catalog: \`impactPlanes: ["central-api","secured-cluster"]\`.
\`securedClusterPolicy: single\` - one SC only (orchestrator refuses multi-SC).

Talk track: \`modules/syslog-notifier/syslog-notifier-demo.md\`

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--plane central-api|secured-cluster] [--secured-cluster-id ID] [--name NAME] [--format CEF|LEGACY]
$(basename "$0") --run [--dry-run] [--plane central-api|secured-cluster] [--secured-cluster-id ID] [--name NAME] [--format CEF|LEGACY]
$(basename "$0") --uninstall [--dry-run] [--plane central-api|secured-cluster] [--secured-cluster-id ID] [--name NAME]
\`\`\`

## Flags

- \`--plane secured-cluster\` - receiver Deployment, LoadBalancer :${SYSLOG_PORT}, viewer Route
- \`--plane central-api\` - Syslog notifier upsert + Central Test
- omit \`--plane\` - both planes in one process
- \`--secured-cluster-id ID\` - secured-cluster plane: at most one lab SC (soft-default when omitted)
- \`--name NAME\` - Central notifier display name (default \`${DEFAULT_NOTIFIER_NAME}\`)
- \`--format CEF|LEGACY\` - Syslog message format (default CEF; LEGACY = CEF legacy field order)
- \`--dry-run\` - Print the plan; change nothing

## Status Info

- \`secured-cluster\`: receiver Ready, syslog LB endpoint, viewer Route URL
- \`central-api\`: notifier host/port/format
- omit \`--plane\`: combined view (message ring lives in the viewer, not Status)

## Pre Conditions

none (OpenShift must allocate a LoadBalancer address on the target SC)

## Side effects

- \`--run\` secured-cluster: namespace \`${NS}\` + receiver + LB + viewer Route
- \`--run\` central-api: Syslog notifier upsert → Central Test
- \`--uninstall\` deletes the notifier (central-api) and/or namespace \`${NS}\` (secured-cluster)
EOF
}

ensure_oc() {
  local sc_id="${1:-${SYSLOG_SC_ID:-}}"
  local kc errf
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  errf="$(mktemp)"
  if ! kc="$(
    cd "${ROOT}" || exit 1
    if [[ -n "$sc_id" ]]; then
      "$PYTHON" -m lib.openshift login --secured-cluster-id "$sc_id" --print-kubeconfig 2>"${errf}"
    else
      "$PYTHON" -m lib.openshift login --print-kubeconfig 2>"${errf}"
    fi
  )"; then
    cat "${errf}" >&2
    rm -f "${errf}"
    return 1
  fi
  rm -f "${errf}"
  export KUBECONFIG="$kc"
}

sc_label() {
  local name="${ACS_DEMO_SC_NAME:-}"
  if [[ -n "$name" ]]; then
    printf '%s' "$name"
    return 0
  fi
  if [[ -n "${SYSLOG_SC_ID}" ]]; then
    printf '%s' "${SYSLOG_SC_ID}"
    return 0
  fi
  printf 'soft-default'
}

lb_host() {
  local host ip
  host="$(oc -n "${NS}" get svc "${SVC_SYSLOG}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  if [[ -n "$host" ]]; then
    printf '%s' "$host"
    return 0
  fi
  ip="$(oc -n "${NS}" get svc "${SVC_SYSLOG}" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  printf '%s' "$ip"
}

viewer_url() {
  local host
  host="$(oc -n "${NS}" get route "${ROUTE_VIEWER}" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
  if [[ -z "$host" ]]; then
    printf ''
    return 0
  fi
  printf 'https://%s' "$host"
}

deploy_ready() {
  local ready
  ready="$(oc -n "${NS}" get deploy "${APP}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)"
  [[ "${ready:-0}" =~ ^[1-9][0-9]*$ ]]
}

wait_lb_address() {
  local elapsed=0 host
  echo "${MODULE_ID}: waiting for LoadBalancer address on svc/${SVC_SYSLOG} (timeout ${LB_WAIT_SECONDS}s)..."
  while (( elapsed < LB_WAIT_SECONDS )); do
    host="$(lb_host)"
    if [[ -n "$host" ]]; then
      echo "${MODULE_ID}: LoadBalancer endpoint ${host}:${SYSLOG_PORT}"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    if (( elapsed % 30 == 0 )); then
      echo "${MODULE_ID}: still waiting for LB... ${elapsed}s"
    fi
  done
  echo "${MODULE_ID}: LoadBalancer address not allocated within ${LB_WAIT_SECONDS}s" >&2
  oc -n "${NS}" get svc "${SVC_SYSLOG}" -o wide >&2 || true
  return 1
}

# Address alone is not enough - Central Test needs the port open.
wait_lb_tcp() {
  local host="$1"
  local elapsed=0
  local timeout=90
  [[ -n "$host" ]] || return 1
  echo "${MODULE_ID}: waiting for TCP ${host}:${SYSLOG_PORT} (timeout ${timeout}s)..."
  while (( elapsed < timeout )); do
    if command -v nc >/dev/null 2>&1; then
      if nc -z -w 2 "$host" "${SYSLOG_PORT}" >/dev/null 2>&1; then
        echo "${MODULE_ID}: TCP ${host}:${SYSLOG_PORT} open"
        return 0
      fi
    elif (echo >/dev/tcp/"$host"/"${SYSLOG_PORT}") >/dev/null 2>&1; then
      echo "${MODULE_ID}: TCP ${host}:${SYSLOG_PORT} open"
      return 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
    if (( elapsed % 15 == 0 )); then
      echo "${MODULE_ID}: still waiting for TCP... ${elapsed}s"
    fi
  done
  echo "${MODULE_ID}: warning: TCP ${host}:${SYSLOG_PORT} not open yet; Central Test may retry" >&2
  return 0
}

apply_receiver() {
  local dry="$1"
  if [[ ! -f "${RECEIVER_PY}" ]]; then
    echo "${MODULE_ID}: missing ${RECEIVER_PY}" >&2
    return 1
  fi
  if [[ "$dry" == "true" ]]; then
    echo "${MODULE_ID}: dry-run would apply namespace/${NS}, ConfigMap, Deployment/${APP},"
    echo "  Service/${SVC_SYSLOG} (LoadBalancer :${SYSLOG_PORT}), Service/${SVC_VIEWER},"
    echo "  Route/${ROUTE_VIEWER} on SC $(sc_label)"
    return 0
  fi

  oc get ns "${NS}" >/dev/null 2>&1 || oc create ns "${NS}"
  oc -n "${NS}" label ns "${NS}" app.kubernetes.io/part-of="${MODULE_ID}" --overwrite >/dev/null

  oc -n "${NS}" create configmap "${APP}-code" \
    --from-file="receiver.py=${RECEIVER_PY}" \
    --dry-run=client -o yaml | oc apply -f -

  oc apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP}
  namespace: ${NS}
  labels:
    app: ${APP}
    app.kubernetes.io/part-of: ${MODULE_ID}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${APP}
  template:
    metadata:
      labels:
        app: ${APP}
        app.kubernetes.io/part-of: ${MODULE_ID}
    spec:
      containers:
        - name: receiver
          image: ${IMAGE}
          imagePullPolicy: IfNotPresent
          command: ["python3", "/app/receiver.py"]
          env:
            - name: RING_SIZE
              value: "${RING_SIZE}"
            - name: SYSLOG_PORT
              value: "${SYSLOG_PORT}"
            - name: HTTP_PORT
              value: "${HTTP_PORT}"
          ports:
            - name: syslog
              containerPort: ${SYSLOG_PORT}
              protocol: TCP
            - name: http
              containerPort: ${HTTP_PORT}
              protocol: TCP
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 10
            periodSeconds: 20
          volumeMounts:
            - name: code
              mountPath: /app
              readOnly: true
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: "500m"
              memory: 256Mi
      volumes:
        - name: code
          configMap:
            name: ${APP}-code
            defaultMode: 0555
---
apiVersion: v1
kind: Service
metadata:
  name: ${SVC_SYSLOG}
  namespace: ${NS}
  labels:
    app: ${APP}
    app.kubernetes.io/part-of: ${MODULE_ID}
spec:
  type: LoadBalancer
  selector:
    app: ${APP}
  ports:
    - name: syslog
      port: ${SYSLOG_PORT}
      targetPort: syslog
      protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: ${SVC_VIEWER}
  namespace: ${NS}
  labels:
    app: ${APP}
    app.kubernetes.io/part-of: ${MODULE_ID}
spec:
  type: ClusterIP
  selector:
    app: ${APP}
  ports:
    - name: http
      port: ${HTTP_PORT}
      targetPort: http
      protocol: TCP
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: ${ROUTE_VIEWER}
  namespace: ${NS}
  labels:
    app: ${APP}
    app.kubernetes.io/part-of: ${MODULE_ID}
spec:
  to:
    kind: Service
    name: ${SVC_VIEWER}
    weight: 100
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  wildcardPolicy: None
EOF

  echo "${MODULE_ID}: waiting for deploy/${APP} Ready..."
  oc -n "${NS}" rollout status "deploy/${APP}" --timeout=180s
  wait_lb_address
  wait_lb_tcp "$(lb_host)"
  echo "${MODULE_ID}: viewer $(viewer_url)"
}

uninstall_receiver() {
  local dry="$1"
  if [[ "$dry" == "true" ]]; then
    echo "${MODULE_ID}: dry-run would delete namespace/${NS} on SC $(sc_label)"
    return 0
  fi
  if ! oc get ns "${NS}" >/dev/null 2>&1; then
    echo "${MODULE_ID}: namespace ${NS} already absent"
    return 0
  fi
  echo "${MODULE_ID}: deleting namespace ${NS}"
  oc delete project "${NS}" --ignore-not-found --wait=true --timeout=10m
}

helper_args() {
  local host port
  host="$(lb_host 2>/dev/null || true)"
  port="${SYSLOG_PORT}"
  # When secured-cluster plane did not run / ns missing, host may be empty.
  EXTRA_HELPER=(--name "${NOTIFIER_NAME}" --format "${MESSAGE_FORMAT}" --port "${port}")
  if [[ -n "$host" ]]; then
    EXTRA_HELPER+=(--host "$host")
  fi
}

run_helper() {
  helper_args
  "$PYTHON" "$HELPER" "${EXTRA_HELPER[@]}" "$@"
}

merge_sections_json() {
  # Merge ACS_SECTIONS_JSON lines from a file (argv). Do not read the script
  # heredoc as the payload - that would swallow a stdin redirect.
  local file="$1"
  "$PYTHON" - "$file" <<'PY'
import json, sys
sections = []
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line.startswith("ACS_SECTIONS_JSON="):
            continue
        raw = line[len("ACS_SECTIONS_JSON=") :]
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        for s in obj.get("sections") or []:
            if isinstance(s, dict):
                sections.append(s)
print("ACS_SECTIONS_JSON=" + json.dumps({"sections": sections}, separators=(",", ":")))
PY
}

emit_sc_sections() {
  local cluster host url ready_tag ready_sum lb_tag lb_sum lb_body route_tag route_sum route_body
  cluster="$(sc_label)"
  if deploy_ready; then
    ready_tag=ok
    ready_sum="Ready"
  elif oc -n "${NS}" get deploy "${APP}" >/dev/null 2>&1; then
    ready_tag=error
    ready_sum="not Ready"
  else
    ready_tag=error
    ready_sum="missing"
  fi
  host="$(lb_host)"
  if [[ -n "$host" ]]; then
    lb_tag=ok
    lb_sum="${host}:${SYSLOG_PORT}"
    lb_body="Cluster: ${cluster}
Namespace: ${NS}
Syslog LoadBalancer: ${host}:${SYSLOG_PORT}
Central must reach this host:port to deliver CEF."
  else
    lb_tag=error
    lb_sum="pending/missing"
    lb_body="Cluster: ${cluster}
Namespace: ${NS}
LoadBalancer address not allocated yet for svc/${SVC_SYSLOG}.
Without a public endpoint, Central cannot deliver CEF."
  fi
  url="$(viewer_url)"
  if [[ -n "$url" ]]; then
    route_tag=ok
    route_sum="${url}"
    route_body="Viewer: ${url}
Open this URL for the CEF ring-buffer reader (raw + parsed).
Message ring is not shown in Status."
  else
    route_tag=error
    route_sum="missing"
    route_body="Viewer Route ${ROUTE_VIEWER} not found in ${NS}."
  fi

  jq -nc \
    --arg cluster "$cluster" \
    --arg ready_sum "$ready_sum" --arg ready_tag "$ready_tag" \
    --arg app "$APP" --arg ns "$NS" \
    --arg lb_sum "$lb_sum" --arg lb_tag "$lb_tag" --arg lb_body "$lb_body" \
    --arg route_sum "$route_sum" --arg route_tag "$route_tag" --arg route_body "$route_body" \
    '{sections:[
      {group:"Receiver", title:"Syslog Deployment", summary:$ready_sum, tag:$ready_tag, cluster:$cluster,
       body:("Deployment " + $app + " in " + $ns + ": " + $ready_sum), bodyFormat:"prose"},
      {group:"Receiver", title:"Syslog endpoint", summary:$lb_sum, tag:$lb_tag, cluster:$cluster,
       body:$lb_body, bodyFormat:"prose"},
      {group:"Access", title:"Viewer Route", summary:$route_sum, tag:$route_tag, cluster:$cluster,
       body:$route_body, bodyFormat:"prose"}
    ]}' | sed 's/^/ACS_SECTIONS_JSON=/'
}

do_status() {
  local tmp worst=ok msg_parts=() sc_ok=true api_state="" api_msg=""
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN

  if want_secured_cluster; then
    if ! ensure_oc; then
      printf '%s\terror\tcannot login to OpenShift via lab credentials\n' "$MODULE_ID"
      return 0
    fi
    emit_sc_sections >>"$tmp"
    if ! deploy_ready || [[ -z "$(lb_host)" ]] || [[ -z "$(viewer_url)" ]]; then
      sc_ok=false
      worst=needs-run
      msg_parts+=("receiver/LB/Route incomplete on $(sc_label)")
    else
      msg_parts+=("receiver Ready on $(sc_label)")
    fi
  fi

  if want_central_api; then
    local out state message
    # Always login to the SC so helper_args can resolve the LoadBalancer host,
    # even on a central-api-only orchestrator invoke.
    ensure_oc || true
    if ! out="$(run_helper status 2>&1)"; then
      :
    fi
    printf '%s\n' "$out" | awk '/^ACS_SECTIONS_JSON=/ {print}' >>"$tmp"
    state="$(printf '%s\n' "$out" | awk -F'\t' 'NF>=3 {s=$2} END{print s}')"
    message="$(printf '%s\n' "$out" | awk -F'\t' 'NF>=3 {m=$3; for(i=4;i<=NF;i++) m=m"\t"$i} END{print m}')"
    api_state="$state"
    api_msg="$message"
    case "$state" in
      error) worst=error ;;
      needs-run) [[ "$worst" != "error" ]] && worst=needs-run ;;
      ok) ;;
      *) [[ "$worst" != "error" ]] && worst=needs-run ;;
    esac
    msg_parts+=("${message:-central-api status unknown}")
  fi

  merge_sections_json "$tmp"

  if want_secured_cluster && want_central_api; then
    if $sc_ok && [[ "$api_state" == "ok" ]]; then
      printf '%s\tok\t%s\n' "$MODULE_ID" "$(IFS='; '; echo "${msg_parts[*]}")"
    elif [[ "$worst" == "error" ]]; then
      printf '%s\terror\t%s\n' "$MODULE_ID" "$(IFS='; '; echo "${msg_parts[*]}")"
    else
      printf '%s\tneeds-run\t%s\n' "$MODULE_ID" "$(IFS='; '; echo "${msg_parts[*]}")"
    fi
  elif want_secured_cluster; then
    if $sc_ok; then
      local url host
      url="$(viewer_url)"
      host="$(lb_host)"
      printf '%s\tok\treceiver Ready; syslog %s:%s; viewer %s\n' \
        "$MODULE_ID" "$host" "$SYSLOG_PORT" "$url"
    else
      printf '%s\tneeds-run\t%s\n' "$MODULE_ID" "${msg_parts[*]-receiver incomplete}"
    fi
  else
    printf '%s\t%s\t%s\n' "$MODULE_ID" "${api_state:-needs-run}" "${api_msg:-central-api status unknown}"
  fi
}

do_run() {
  local dry="$1"
  local -a helper_cmd=(run)
  [[ "$dry" == "true" ]] && helper_cmd+=(--dry-run)
  if want_secured_cluster; then
    if [[ "$dry" != "true" ]]; then
      ensure_oc || return 1
    fi
    apply_receiver "$dry" || return 1
  fi
  if want_central_api; then
    if [[ "$dry" != "true" ]]; then
      ensure_oc || true
      if [[ -z "$(lb_host 2>/dev/null || true)" ]]; then
        echo "${MODULE_ID}: no LoadBalancer host; run secured-cluster plane first" >&2
        return 1
      fi
    fi
    run_helper "${helper_cmd[@]}" || return 1
  fi
  if [[ "$dry" == "true" ]]; then
    return 0
  fi
  local out state
  out="$(do_status 2>/dev/null || true)"
  printf '%s\n' "$out"
  state="$(printf '%s\n' "$out" | awk -F'\t' 'NF>=3 {s=$2} END{print s}')"
  [[ "$state" == "ok" ]]
}

do_uninstall() {
  local dry="$1"
  local -a helper_cmd=(uninstall)
  [[ "$dry" == "true" ]] && helper_cmd+=(--dry-run)
  if want_central_api; then
    run_helper "${helper_cmd[@]}" || return 1
  fi
  if want_secured_cluster; then
    if [[ "$dry" != "true" ]]; then
      ensure_oc || return 1
    fi
    uninstall_receiver "$dry" || return 1
  fi
}

do_dry_run() {
  echo "${MODULE_ID}: dry-run (plane=${SYSLOG_PLANE:-both})"
  if want_secured_cluster; then
    echo "  - Apply ${NS} receiver + LoadBalancer :${SYSLOG_PORT} + viewer Route on SC ${SYSLOG_SC_ID:-soft-default}"
  fi
  if want_central_api; then
    echo "  - Upsert Syslog notifier ${NOTIFIER_NAME} (format ${MESSAGE_FORMAT}), then Central Test"
  fi
}

emit_status() {
  local output state
  output="$(do_status)"
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" != "error" ]]
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
      --plane)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --plane needs central-api|secured-cluster" >&2; exit 1; }
        SYSLOG_PLANE="$1"
        case "$SYSLOG_PLANE" in
          central-api|secured-cluster|central|openshift) ;;
          central-ocp)
            echo "$(basename "$0"): central-ocp is not used (receiver lives on secured-cluster)" >&2
            exit 1
            ;;
          *)
            echo "$(basename "$0"): --plane must be central-api or secured-cluster" >&2
            exit 1
            ;;
        esac
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --secured-cluster-id needs an id" >&2; exit 1; }
        SYSLOG_SC_IDS+=("$1")
        ;;
      --name)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --name needs a value" >&2; exit 1; }
        NOTIFIER_NAME="$1"
        ;;
      --format)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --format needs CEF|LEGACY" >&2; exit 1; }
        MESSAGE_FORMAT="$1"
        ;;
      *)
        echo "$(basename "$0"): unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  if [[ "${SYSLOG_PLANE}" == "secured-cluster" || "${SYSLOG_PLANE}" == "openshift" ]] && ((${#SYSLOG_SC_IDS[@]} > 1)); then
    echo "$(basename "$0"): secured-cluster plane expects at most one --secured-cluster-id" >&2
    exit 1
  fi
  SYSLOG_SC_ID="${SYSLOG_SC_IDS[0]:-${ACS_DEMO_SC_ID:-}}"

  [[ -n "$action" ]] || { usage; exit 0; }
  case "$action" in
    status) emit_status ;;
    run)
      if [[ "$dry_run" == "true" ]]; then do_dry_run; do_run true; else do_run false; fi
      ;;
    uninstall)
      if [[ "$dry_run" == "true" ]]; then do_uninstall true; else do_uninstall false; fi
      ;;
  esac
}

main "$@"
