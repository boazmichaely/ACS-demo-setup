#!/usr/bin/env bash
# Module: virt-vm-demo - OCP Virtualization + 2 dnf-primed RHEL VMs + ACS guest CVEs
set -euo pipefail

MODULE_ID="virt-vm-demo"
NS="acs-virt-demo"
CNV_NS="openshift-cnv"
HCO_NAME="kubevirt-hyperconverged"
VM_NAMES=(rhel9-1 rhel9-2)
VM_EXPECTED="${#VM_NAMES[@]}"
SSH_USER="cloud-user"
VM_PASSWORD="password"
CONTAINER_IMAGE="quay.io/rhacs-eng/vm-images:rhel9-dnf-primed-latest"
CENTRAL_NAME="stackrox-central-services"
SECURED_NAME="stackrox-secured-cluster-services"
STACKROX_NS="stackrox"
POLL_INTERVAL="1m"
RESCAN_INTERVAL="30m"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSET_DIR="${ROOT}/modules/virt-vm-demo"
HELPER="${ROOT}/modules/virt_vm_demo.py"
CACHE_DIR="${ROOT}/.cache/virt-vm-demo"
BIN_DIR="${ROOT}/.cache/bin"
KEY_PATH="${CACHE_DIR}/id_ed25519"
AGENT_BIN_CACHE="${CACHE_DIR}/roxagent"

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
  Prepare an ACS guest-vulnerability demo on OpenShift Virtualization:
    1) Enable ROX_VIRTUAL_MACHINES (Central + SecuredCluster) and a short
       scraper poll interval for demos
    2) Install OpenShift Virtualization with VSOCK + KVM_EMULATION
       (works on infra / nested clusters without bare metal)
    3) Deploy 2 RHEL 9 VMs (${VM_NAMES[*]}) in project ${NS} using the
       dnf-primed eng guest image (Scanner V4 matching without a live DNF txn)
    4) Install roxagent (from Sensor image) in each guest and start it
    5) Wait until Central shows CVE findings on both VMs

  Talk track: modules/virt-vm-demo.md

Depends on:
  ACS Central + Secured Cluster already installed
  oc on PATH; virtctl (auto-downloaded to .cache/bin if missing)
  Cluster pull access to ${CONTAINER_IMAGE} (via openshift-config/pull-secret)

Side effects:
  --run mutates Central/SecuredCluster CRs, may install CNV, creates
    ${NS} and VMs, installs guest agent. Idempotent where practical.
  --uninstall deletes project ${NS}. Leaves CNV and ACS flags in place.

EOF
}

ensure_oc() {
  local kc errf
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  errf="$(mktemp)"
  if ! kc="$(
    cd "${ROOT}" || exit 1
    "$PYTHON" -m lib.openshift login --print-kubeconfig 2>"${errf}"
  )"; then
    cat "${errf}" >&2
    rm -f "${errf}"
    return 1
  fi
  rm -f "${errf}"
  export KUBECONFIG="$kc"
}

ensure_virtctl() {
  if command -v virtctl >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x "${BIN_DIR}/virtctl" ]]; then
    export PATH="${BIN_DIR}:${PATH}"
    return 0
  fi
  mkdir -p "${BIN_DIR}"
  local arch os url
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "$arch" in
    arm64|aarch64) arch=arm64 ;;
    x86_64|amd64) arch=amd64 ;;
  esac
  local kvver="v1.8.4"
  kvver="$(oc get kubevirt.kubevirt.io -A -o jsonpath='{.items[0].status.observedKubeVirtVersion}' 2>/dev/null || true)"
  [[ -n "$kvver" ]] || kvver="v1.8.4"
  [[ "$kvver" == v* ]] || kvver="v${kvver}"
  url="https://github.com/kubevirt/kubevirt/releases/download/${kvver}/virtctl-${kvver}-${os}-${arch}"
  echo "${MODULE_ID}: downloading virtctl from ${url}" >&2
  if ! curl -fsSL -o "${BIN_DIR}/virtctl" "$url"; then
    echo "${MODULE_ID}: failed to download virtctl ${kvver}, trying v1.8.4" >&2
    url="https://github.com/kubevirt/kubevirt/releases/download/v1.8.4/virtctl-v1.8.4-${os}-${arch}"
    curl -fsSL -o "${BIN_DIR}/virtctl" "$url" || {
      echo "${MODULE_ID}: failed to download virtctl" >&2
      return 1
    }
  fi
  chmod +x "${BIN_DIR}/virtctl"
  export PATH="${BIN_DIR}:${PATH}"
}

ensure_ssh_key() {
  mkdir -p "${CACHE_DIR}"
  if [[ ! -f "${KEY_PATH}" ]]; then
    ssh-keygen -t ed25519 -N '' -f "${KEY_PATH}" -C "acs-virt-vm-demo" >/dev/null
  fi
}

ssh_pubkey() {
  ensure_ssh_key
  cat "${KEY_PATH}.pub"
}

run_helper() {
  (cd "${ROOT}" && "$PYTHON" "$HELPER" "$@")
}

vm_names() {
  printf '%s\n' "${VM_NAMES[@]}"
}

# --- ACS feature flags / scraper -------------------------------------------------

acs_flags_applied() {
  local central_env secured_env poll
  central_env="$(oc -n "${STACKROX_NS}" get central "${CENTRAL_NAME}" -o jsonpath='{.spec.customize.envVars[?(@.name=="ROX_VIRTUAL_MACHINES")].value}' 2>/dev/null || true)"
  secured_env="$(oc -n "${STACKROX_NS}" get securedcluster "${SECURED_NAME}" -o jsonpath='{.spec.customize.envVars[?(@.name=="ROX_VIRTUAL_MACHINES")].value}' 2>/dev/null || true)"
  poll="$(oc -n "${STACKROX_NS}" get securedcluster "${SECURED_NAME}" -o jsonpath='{.spec.virtualMachines.scraper.pollInterval}' 2>/dev/null || true)"
  [[ "$central_env" == "true" && "$secured_env" == "true" && -n "$poll" ]]
}

apply_acs_flags() {
  local dry="$1"
  if [[ "$dry" == "true" ]]; then
    echo "Would patch Central/SecuredCluster: ROX_VIRTUAL_MACHINES=true, scraper.pollInterval=${POLL_INTERVAL}"
    return 0
  fi
  oc -n "${STACKROX_NS}" patch central "${CENTRAL_NAME}" --type merge -p \
    "{\"spec\":{\"customize\":{\"envVars\":[{\"name\":\"ROX_VIRTUAL_MACHINES\",\"value\":\"true\"}]}}}"

  oc -n "${STACKROX_NS}" patch securedcluster "${SECURED_NAME}" --type merge -p "$(
    cat <<EOF
{
  "spec": {
    "customize": {
      "envVars": [
        {"name": "ROX_VIRTUAL_MACHINES", "value": "true"}
      ]
    },
    "virtualMachines": {
      "scraper": {
        "pollInterval": "${POLL_INTERVAL}",
        "concurrency": 20
      }
    }
  }
}
EOF
  )"
  # Collector must stay on the pod network: hostNetwork makes traffic look like
  # the node IP, and the stock Sensor NetworkPolicy then drops Collector→Sensor.
  # Clear any leftover overlay from older module runs.
  if oc -n "${STACKROX_NS}" get securedcluster "${SECURED_NAME}" -o jsonpath='{.spec.overlays}' 2>/dev/null | grep -q .; then
    echo "${MODULE_ID}: removing SecuredCluster collector hostNetwork overlay (breaks Sensor NetworkPolicy)"
    oc -n "${STACKROX_NS}" patch securedcluster "${SECURED_NAME}" --type json -p '[{"op":"remove","path":"/spec/overlays"}]'
  fi
}

# --- OpenShift Virtualization ----------------------------------------------------

cnv_healthy() {
  local avail prog degr
  avail="$(oc -n "${CNV_NS}" get hyperconverged "${HCO_NAME}" -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "")"
  prog="$(oc -n "${CNV_NS}" get hyperconverged "${HCO_NAME}" -o jsonpath='{.status.conditions[?(@.type=="Progressing")].status}' 2>/dev/null || echo "")"
  degr="$(oc -n "${CNV_NS}" get hyperconverged "${HCO_NAME}" -o jsonpath='{.status.conditions[?(@.type=="Degraded")].status}' 2>/dev/null || echo "")"
  [[ "$avail" == "True" && "$prog" == "False" && "$degr" == "False" ]]
}

ensure_kvm_emulation() {
  local cur
  cur="$(oc -n "${CNV_NS}" get subscription kubevirt-hyperconverged -o jsonpath='{.spec.config.env[?(@.name=="KVM_EMULATION")].value}' 2>/dev/null || true)"
  if [[ "$cur" == "true" ]]; then
    return 0
  fi
  oc -n "${CNV_NS}" patch subscription kubevirt-hyperconverged --type merge -p \
    '{"spec":{"config":{"env":[{"name":"KVM_EMULATION","value":"true"}]}}}'
}

install_cnv() {
  local dry="$1"
  if [[ "$dry" == "true" ]]; then
    echo "Would install OpenShift Virtualization in ${CNV_NS} with VSOCK + KVM_EMULATION"
    return 0
  fi
  if cnv_healthy; then
    echo "${MODULE_ID}: CNV already healthy; ensuring KVM_EMULATION"
    ensure_kvm_emulation
    return 0
  fi

  cat <<EOF | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: ${CNV_NS}
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-cnv
  namespace: ${CNV_NS}
spec:
  targetNamespaces:
  - ${CNV_NS}
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: kubevirt-hyperconverged
  namespace: ${CNV_NS}
spec:
  channel: stable
  name: kubevirt-hyperconverged
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
  config:
    env:
    - name: KVM_EMULATION
      value: "true"
EOF

  echo "${MODULE_ID}: waiting for Subscription installedCSV..."
  local i csv phase
  for i in $(seq 1 60); do
    csv="$(oc -n "${CNV_NS}" get sub kubevirt-hyperconverged -o jsonpath='{.status.installedCSV}' 2>/dev/null || true)"
    [[ -n "$csv" ]] && break
    sleep 5
  done
  [[ -n "$csv" ]] || { echo "${MODULE_ID}: timeout waiting for installedCSV" >&2; return 1; }

  echo "${MODULE_ID}: waiting for CSV ${csv} Succeeded..."
  for i in $(seq 1 180); do
    phase="$(oc -n "${CNV_NS}" get csv "$csv" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    [[ "$phase" == "Succeeded" ]] && break
    sleep 5
  done
  [[ "$phase" == "Succeeded" ]] || { echo "${MODULE_ID}: CSV phase=${phase}" >&2; return 1; }

  ensure_kvm_emulation

  cat <<EOF | oc apply -f -
apiVersion: hco.kubevirt.io/v1beta1
kind: HyperConverged
metadata:
  name: ${HCO_NAME}
  namespace: ${CNV_NS}
  annotations:
    kubevirt.kubevirt.io/jsonpatch: |-
      [
        {
          "op":"add",
          "path":"/spec/configuration/developerConfiguration/featureGates/-",
          "value":"VSOCK"
        }
      ]
spec: {}
EOF

  echo "${MODULE_ID}: waiting for HyperConverged healthy (up to 30m)..."
  local elapsed=0
  while ! cnv_healthy; do
    if [[ $elapsed -ge 1800 ]]; then
      echo "${MODULE_ID}: HyperConverged not healthy after ${elapsed}s" >&2
      return 1
    fi
    if (( elapsed % 60 == 0 && elapsed > 0 )); then
      echo "${MODULE_ID}: still waiting for HyperConverged... ${elapsed}s"
    fi
    sleep 10
    elapsed=$((elapsed + 10))
  done
  echo "${MODULE_ID}: HyperConverged healthy"
}

# --- VMs + agent -----------------------------------------------------------------

count_running_vmis() {
  local n=0 name
  for name in "${VM_NAMES[@]}"; do
    if [[ "$(oc -n "${NS}" get vmi "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)" == "Running" ]]; then
      n=$((n + 1))
    fi
  done
  echo "$n"
}

render_vm() {
  local name="$1"
  local pubkey
  pubkey="$(ssh_pubkey)"
  "$PYTHON" - "$name" "$pubkey" <<'PY'
import os, sys
name, pubkey = sys.argv[1], sys.argv[2]
path = os.path.join(os.environ["ASSET_DIR"], "vm.yaml.tmpl")
text = open(path, encoding="utf-8").read()
repl = {
    "${VM_NAME}": name,
    "${NAMESPACE}": os.environ["NS"],
    "${CONTAINER_IMAGE}": os.environ["CONTAINER_IMAGE"],
    "${SSH_USER}": os.environ["SSH_USER"],
    "${VM_PASSWORD}": os.environ["VM_PASSWORD"],
    "${SSH_PUBKEY}": pubkey,
}
for k, v in repl.items():
    text = text.replace(k, v)
sys.stdout.write(text)
PY
}

ensure_vm_pull_secret() {
  if oc -n "${NS}" get secret acs-vm-pull-secret >/dev/null 2>&1; then
    return 0
  fi
  echo "${MODULE_ID}: creating acs-vm-pull-secret from openshift-config/pull-secret (quay.io)"
  oc get ns "${NS}" >/dev/null 2>&1 || oc create ns "${NS}"
  "$PYTHON" - <<'PY'
import base64, json, os, subprocess, sys
ns = os.environ["NS"]
raw = subprocess.check_output(
    ["oc", "-n", "openshift-config", "get", "secret", "pull-secret", "-o", "json"]
)
sec = json.loads(raw)
cfg = json.loads(base64.b64decode(sec["data"][".dockerconfigjson"]))
auths = {k: v for k, v in (cfg.get("auths") or {}).items() if "quay.io" in k}
if not auths:
    print("ERROR: no quay.io auths in openshift-config/pull-secret", file=sys.stderr)
    sys.exit(1)
path = "/tmp/acs-vm-pull.json"
open(path, "w", encoding="utf-8").write(json.dumps({"auths": auths}))
subprocess.check_call(
    [
        "oc", "-n", ns, "create", "secret", "generic", "acs-vm-pull-secret",
        f"--from-file=.dockerconfigjson={path}",
        "--type=kubernetes.io/dockerconfigjson",
        "--dry-run=client", "-o", "yaml",
    ],
    stdout=open("/tmp/acs-vm-pull-secret.yaml", "w", encoding="utf-8"),
)
subprocess.check_call(["oc", "apply", "-f", "/tmp/acs-vm-pull-secret.yaml"])
os.remove(path)
os.remove("/tmp/acs-vm-pull-secret.yaml")
print("acs-vm-pull-secret ready; registries:", ", ".join(sorted(auths)))
PY
}

deploy_vms() {
  local dry="$1" name
  if [[ "$dry" == "true" ]]; then
    echo "Would create project ${NS} and VMs: ${VM_NAMES[*]} image=${CONTAINER_IMAGE}"
    return 0
  fi
  oc get ns "${NS}" >/dev/null 2>&1 || oc create ns "${NS}"
  export ASSET_DIR NS CONTAINER_IMAGE SSH_USER VM_PASSWORD
  ensure_vm_pull_secret
  for name in "${VM_NAMES[@]}"; do
    echo "${MODULE_ID}: applying VM ${name} (${CONTAINER_IMAGE})"
    render_vm "$name" | oc apply -f -
  done
}

wait_vms_running() {
  local dry="$1"
  if [[ "$dry" == "true" ]]; then
    echo "Would wait for ${VM_EXPECTED} VMIs Running in ${NS}"
    return 0
  fi
  local elapsed=0
  echo "${MODULE_ID}: waiting for VMs Running (emulation can be slow)..."
  while true; do
    local ready
    ready="$(count_running_vmis)"
    if [[ "$ready" -ge "$VM_EXPECTED" ]]; then
      echo "${MODULE_ID}: ${ready}/${VM_EXPECTED} VMIs Running"
      return 0
    fi
    if [[ $elapsed -ge 2400 ]]; then
      echo "${MODULE_ID}: only ${ready}/${VM_EXPECTED} Running after ${elapsed}s" >&2
      oc -n "${NS}" get vm,vmi 2>&1 || true
      return 1
    fi
    if (( elapsed % 60 == 0 )); then
      echo "${MODULE_ID}: ${ready}/${VM_EXPECTED} Running... ${elapsed}s"
      oc -n "${NS}" get vmi 2>&1 || true
    fi
    sleep 15
    elapsed=$((elapsed + 15))
  done
}

extract_roxagent() {
  if [[ -x "${AGENT_BIN_CACHE}" ]]; then
    return 0
  fi
  mkdir -p "${CACHE_DIR}"
  local pod
  pod="$(oc -n "${STACKROX_NS}" get pods -l app=sensor -o jsonpath='{.items[0].metadata.name}')"
  echo "${MODULE_ID}: copying roxagent from sensor pod ${pod}"
  oc -n "${STACKROX_NS}" cp -c sensor "${pod}:/stackrox/bin/roxagent" "${AGENT_BIN_CACHE}"
  chmod +x "${AGENT_BIN_CACHE}"
}

virt_ssh_opts() {
  VIRT_SSH_OPTS=(
    --namespace "${NS}"
    --local-ssh-opts="-o StrictHostKeyChecking=no"
    --local-ssh-opts="-o UserKnownHostsFile=/dev/null"
    --local-ssh-opts="-o IdentitiesOnly=yes"
    --local-ssh-opts="-o IdentityFile=${KEY_PATH}"
    --local-ssh-opts="-o ConnectTimeout=20"
  )
  if command -v sshpass >/dev/null 2>&1; then
    export SSHPASS="${VM_PASSWORD}"
    VIRT_SSH_OPTS+=(--local-ssh-opts="-o PreferredAuthentications=publickey,password")
  fi
}

virt_ssh() {
  local vmi="$1"
  shift
  virt_ssh_opts
  if command -v sshpass >/dev/null 2>&1; then
    sshpass -e virtctl ssh "${VIRT_SSH_OPTS[@]}" "$@" "${SSH_USER}@vmi/${vmi}"
  else
    virtctl ssh "${VIRT_SSH_OPTS[@]}" "$@" "${SSH_USER}@vmi/${vmi}"
  fi
}

virt_scp() {
  local src="$1" vmi="$2" dest="$3"
  virt_ssh_opts
  if command -v sshpass >/dev/null 2>&1; then
    sshpass -e virtctl scp "${VIRT_SSH_OPTS[@]}" "$src" "${SSH_USER}@vmi/${vmi}:${dest}"
  else
    virtctl scp "${VIRT_SSH_OPTS[@]}" "$src" "${SSH_USER}@vmi/${vmi}:${dest}"
  fi
}

agent_active_on_vm() {
  local vmi="$1" out
  out="$(virt_ssh "$vmi" --command "pgrep -x roxagent >/dev/null && echo running || echo stopped" 2>/dev/null || echo stopped)"
  out="$(printf '%s' "$out" | tr -d '\r' | awk 'NF{print; exit}')"
  [[ "$out" == "running" ]]
}

install_agent_on_vm() {
  local vmi="$1"
  local helper
  echo "${MODULE_ID}: installing roxagent on ${vmi}"
  local i
  for i in $(seq 1 40); do
    if virt_ssh "$vmi" --command "echo ok" >/dev/null 2>&1; then
      break
    fi
    sleep 15
  done
  virt_ssh "$vmi" --command "echo ok" >/dev/null

  virt_scp "${AGENT_BIN_CACHE}" "$vmi" "roxagent"

  # Under KVM_EMULATION, guest systemd dbus is often too slow/flaky for
  # enable/start. Run the agent under nohup as root instead (demo-stable).
  helper="$(mktemp)"
  cat >"$helper" <<EOF
#!/bin/bash
set -euo pipefail
sudo cp -f /home/cloud-user/roxagent /usr/local/bin/roxagent
sudo chmod 755 /usr/local/bin/roxagent
sudo chcon -t bin_t /usr/local/bin/roxagent 2>/dev/null || true
sudo bash -lc '
pkill -x roxagent || true
sleep 1
rm -f /tmp/roxagent.log
nohup /usr/local/bin/roxagent serve --port 818 --host-path / --rescan-interval ${RESCAN_INTERVAL} >/tmp/roxagent.log 2>&1 &
echo \$! > /tmp/roxagent.pid
sleep 2
pgrep -a roxagent
tail -n 20 /tmp/roxagent.log || true
'
EOF
  virt_scp "$helper" "$vmi" "install-roxagent.sh"
  rm -f "$helper"
  virt_ssh "$vmi" --command "bash ~/install-roxagent.sh"
}

agent_has_desired_rescan() {
  local vmi="$1" out
  out="$(virt_ssh "$vmi" --command "pgrep -a roxagent 2>/dev/null || true" 2>/dev/null || true)"
  out="$(printf '%s' "$out" | tr -d '\r')"
  grep -q -- "--rescan-interval ${RESCAN_INTERVAL}" <<<"$out"
}

install_agents() {
  local dry="$1" name
  if [[ "$dry" == "true" ]]; then
    echo "Would install roxagent on each VM from Sensor image /stackrox/bin/roxagent (--rescan-interval ${RESCAN_INTERVAL})"
    return 0
  fi
  ensure_virtctl
  extract_roxagent
  for name in "${VM_NAMES[@]}"; do
    if agent_active_on_vm "$name" && agent_has_desired_rescan "$name"; then
      echo "${MODULE_ID}: agent already active on ${name} with --rescan-interval ${RESCAN_INTERVAL}"
      continue
    fi
    install_agent_on_vm "$name"
  done
}

# --- Central readiness -----------------------------------------------------------

probe_central_json() {
  run_helper probe-vms --namespace "${NS}" 2>/dev/null || echo '{"ok":false,"count":0,"scanned":0,"withFindings":0}'
}

central_findings_count() {
  probe_central_json | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("withFindings") or 0))' 2>/dev/null || echo 0
}

central_scanned_count() {
  probe_central_json | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("scanned") or 0))' 2>/dev/null || echo 0
}

central_vm_count() {
  probe_central_json | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("count") or 0))' 2>/dev/null || echo 0
}

wait_central_vms() {
  local dry="$1"
  if [[ "$dry" == "true" ]]; then
    echo "Would wait for Central CVE findings on both VMs in ${NS}"
    return 0
  fi
  local elapsed=0 out count scanned findings
  echo "${MODULE_ID}: waiting for Central CVE findings on ${VM_EXPECTED} VMs (scraper ${POLL_INTERVAL})..."
  echo "${MODULE_ID}: dnf-primed image; initial agent scan under emulation can take 10-20+ min"
  while true; do
    out="$(probe_central_json)"
    count="$(printf '%s' "$out" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("count") or 0))' 2>/dev/null || echo 0)"
    scanned="$(printf '%s' "$out" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("scanned") or 0))' 2>/dev/null || echo 0)"
    findings="$(printf '%s' "$out" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("withFindings") or 0))' 2>/dev/null || echo 0)"
    if [[ "${findings}" -ge "${VM_EXPECTED}" && "${count}" -ge "${VM_EXPECTED}" ]]; then
      echo "${MODULE_ID}: Central sees ${count} VM(s), ${scanned} scanned, ${findings} with CVE counts"
      printf '%s\n' "$out" | head -c 1600
      echo
      return 0
    fi
    if [[ $elapsed -ge 3600 ]]; then
      echo "${MODULE_ID}: after ${elapsed}s: count=${count} scanned=${scanned} findings=${findings} (need ${VM_EXPECTED} with CVEs)" >&2
      printf '%s\n' "$out" >&2
      return 1
    fi
    if (( elapsed % 60 == 0 )); then
      echo "${MODULE_ID}: Central VMs=${count} scanned=${scanned} findings=${findings}/${VM_EXPECTED}... ${elapsed}s"
    fi
    sleep 20
    elapsed=$((elapsed + 20))
  done
}

# --- status ----------------------------------------------------------------------

emit_status_sections() {
  local cnv="missing" flags="missing" vms_ready="0" central_json talk
  talk="${ROOT}/modules/virt-vm-demo.md"
  if cnv_healthy 2>/dev/null; then cnv="healthy"; elif oc get ns "${CNV_NS}" >/dev/null 2>&1; then cnv="installing/unhealthy"; fi
  if acs_flags_applied 2>/dev/null; then flags="applied"; fi
  vms_ready="$(count_running_vmis 2>/dev/null || echo 0)"
  central_json="$(probe_central_json)"
  local central_count central_scanned central_findings
  central_count="$(printf '%s' "$central_json" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("count","?"))' 2>/dev/null || echo "?")"
  central_scanned="$(printf '%s' "$central_json" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("scanned","?"))' 2>/dev/null || echo "?")"
  central_findings="$(printf '%s' "$central_json" | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("withFindings","?"))' 2>/dev/null || echo "?")"

  local sections_json
  sections_json="$(
    jq -nc \
      --arg cnv "$cnv" \
      --arg flags "$flags" \
      --arg vms "${vms_ready}/${VM_EXPECTED}" \
      --arg cc "$central_count" \
      --arg cs "$central_scanned" \
      --arg cf "$central_findings" \
      --arg ns "$NS" \
      --arg talk "$talk" \
      --argjson central "$central_json" \
      '{
        sections: [
          {
            group: "Cluster",
            title: "OpenShift Virtualization",
            summary: $cnv,
            tag: (if $cnv == "healthy" then "ok" else "error" end),
            body: ("HyperConverged in openshift-cnv: " + $cnv + " (KVM_EMULATION expected on infra)"),
            bodyFormat: "prose"
          },
          {
            group: "ACS",
            title: "Feature flags / scraper",
            summary: $flags,
            tag: (if $flags == "applied" then "ok" else "error" end),
            body: ("ROX_VIRTUAL_MACHINES on Central+SecuredCluster; scraper poll short for demos. State: " + $flags),
            bodyFormat: "prose"
          },
          {
            group: "Workloads",
            title: "Demo VMs",
            summary: $vms,
            tag: (if ($vms | split("/")[0] | tonumber) >= ($vms | split("/")[1] | tonumber) then "ok" else "error" end),
            body: ("Namespace " + $ns + " Running VMIs (rhel9-1, rhel9-2): " + $vms),
            bodyFormat: "prose"
          },
          {
            group: "Central",
            title: "Virtual Machine inventory",
            summary: ($cc + " VMs / " + $cs + " scanned / " + ($cf|tostring) + " with CVE counts"),
            body: $central,
            bodyFormat: "json"
          },
          {
            group: "Demo",
            title: "Talk track",
            body: ("Walkthrough: " + $talk),
            bodyFormat: "prose"
          }
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  ensure_oc || {
    printf '%s\terror\tcannot login to OpenShift via lab credentials\n' "$MODULE_ID"
    return 0
  }
  emit_status_sections
  local cnv_ok=false flags_ok=false vms_ok=false
  cnv_healthy && cnv_ok=true
  acs_flags_applied && flags_ok=true
  local ready scanned findings count
  ready="$(count_running_vmis || echo 0)"
  [[ "$ready" -ge "$VM_EXPECTED" ]] && vms_ok=true
  count="$(central_vm_count)"
  scanned="$(central_scanned_count)"
  findings="$(central_findings_count)"

  if $cnv_ok && $flags_ok && $vms_ok && [[ "${findings}" -ge "${VM_EXPECTED}" && "${count}" -ge "${VM_EXPECTED}" ]]; then
    printf '%s\tok\t%s/%s VMs Running; CVE findings on %s/%s VMs in Central\n' \
      "$MODULE_ID" "$ready" "$VM_EXPECTED" "$findings" "$VM_EXPECTED"
  elif $cnv_ok && $flags_ok && $vms_ok && [[ "${findings}" -ge 1 ]]; then
    printf '%s\tneeds-run\tCVE findings on %s/%s VMs (need both)\n' \
      "$MODULE_ID" "$findings" "$VM_EXPECTED"
  elif $cnv_ok && $flags_ok && $vms_ok && [[ "${scanned}" -ge 1 ]]; then
    printf '%s\tneeds-run\tVMs inventoried but no CVE results yet (packages NOT_SCANNED / OS_UNKNOWN)\n' \
      "$MODULE_ID"
  elif $cnv_ok && $flags_ok && $vms_ok; then
    printf '%s\tneeds-run\tVMs up but Central package scan still pending (emulation is slow)\n' \
      "$MODULE_ID"
  elif $cnv_ok && $flags_ok; then
    printf '%s\tneeds-run\tCNV+flags ok but only %s/%s VMs Running\n' \
      "$MODULE_ID" "$ready" "$VM_EXPECTED"
  else
    printf '%s\tneeds-run\tCNV=%s flags=%s VMs=%s/%s\n' \
      "$MODULE_ID" "$cnv_ok" "$flags_ok" "$ready" "$VM_EXPECTED"
  fi
}

demo_ready() {
  local ready findings count
  cnv_healthy || return 1
  acs_flags_applied || return 1
  ready="$(count_running_vmis || echo 0)"
  [[ "$ready" -ge "$VM_EXPECTED" ]] || return 1
  count="$(central_vm_count)"
  findings="$(central_findings_count)"
  [[ "${findings}" -ge "${VM_EXPECTED}" && "${count}" -ge "${VM_EXPECTED}" ]]
}

do_dry_run() {
  ensure_oc
  cat <<EOF
${MODULE_ID}: dry-run
  - Patch Central/SecuredCluster ROX_VIRTUAL_MACHINES + scraper ${POLL_INTERVAL}
  - Install/ensure OpenShift Virtualization (${CNV_NS}) with VSOCK + KVM_EMULATION
  - Create ${NS} with VMs: ${VM_NAMES[*]} (image ${CONTAINER_IMAGE})
  - Copy roxagent from Sensor image into each guest and start it (nohup serve, rescan ${RESCAN_INTERVAL})
  - Wait for Central CVE findings on both VMs
EOF
}

do_run() {
  ensure_oc
  ensure_ssh_key
  apply_acs_flags false
  install_cnv false
  deploy_vms false
  wait_vms_running false
  install_agents false
  wait_central_vms false
  echo "${MODULE_ID}: done. Talk track: ${ROOT}/modules/virt-vm-demo.md"
  do_status || true
  if ! demo_ready; then
    echo "${MODULE_ID}: not demo-ready (need ${VM_EXPECTED} Running VMIs with CVE findings)" >&2
    return 1
  fi
}

do_uninstall() {
  ensure_oc
  echo "${MODULE_ID}: deleting project ${NS} (CNV and ACS flags retained)"
  oc delete project "${NS}" --ignore-not-found --wait=false
}

do_uninstall_dry_run() {
  echo "${MODULE_ID}: would delete project ${NS}; CNV and ACS flags kept"
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
    run)
      if [[ "$dry_run" == "true" ]]; then do_dry_run; else do_run; fi
      ;;
    uninstall)
      if [[ "$dry_run" == "true" ]]; then do_uninstall_dry_run; else do_uninstall; fi
      ;;
  esac
}

main "$@"
