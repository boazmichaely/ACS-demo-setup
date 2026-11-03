# virt-vm-demo redesign handoff

**Date:** 2026-11-03  
**Lab:** `bm-50rc4-on-ocp5` (ACS 5.0.0-rc.4)  
**Goal of next chat:** Redesign the module for a reliable, demo-ready ACS-for-VM story. Do not treat the current module as a finished design.

**Live demo that works today (do not break without a plan):**

| VM | Image | Components | CVEs (approx) | Notes |
|----|-------|------------|---------------|-------|
| `rhel9-1` | stock `rhel-guest-image` + entitlement + httpd DNF path | 506/506 | ~1462 | Keep as the known-good “stock guest” proof |
| `rhel9-3` | `quay.io/rhacs-eng/vm-images:rhel9-dnf-primed-latest` | 511/511 | ~1533 | Eng/Piotr primed path |
| `rhel9-2` | deleted | - | - | Removed under KVM_EMULATION load; module still defaults to 3 VMs |

Namespace: `acs-virt-demo`. Module status currently reports `needs-run` because `ACS_VIRT_VM_COUNT` still expects 3.

---

## Presentation / story (what we settled on)

**One-liner:** Same ACS Central that protects containers also shows OpenShift Virtualization guest CVEs - one control plane for mixed estates.

**Click path (~5–7 min once lab is ready):**

1. **Inventory** - Vulnerability Management → Results → Virtual Machines; show Running RHEL guests in `acs-virt-demo` (also visible in OCP Virt UI).
2. **Packages + CVEs** - Open a VM; show guest OS, hundreds of RPM components from in-guest `roxagent` over VSOCK, then severity counts.
3. **Honesty (~30s)** - Requires OCP Virt + VSOCK + in-guest agent; today = RHEL guest vuln reporting (GA targeted with ACS 5.0). Not Windows, not guest EDR/runtime, not non-Virt VMs. Not a Carbon Black replacement.

**Talk-track file:** `modules/virt-vm-demo.md` (still mentions three VMs; update during redesign).

---

## What the product actually needs (for redesign)

Official RHACS VM scanning needs (among other things):

- OCP Virtualization, VSOCK on HyperConverged + `autoattachVSOCK: true` on VMs
- In-guest `roxagent` (pull mode over VSOCK to Sensor scraper)
- RHEL guest with subscription/entitlement path to Red Hat content
- **At least one DNF transaction** (or equivalent primed DNF metadata) so repo/DNF metadata exists for Scanner V4 matching

**Two gates people confuse:**

1. **Inventory** - agent builds an index report of packages.
2. **CVE match** - Central/Scanner V4 needs DNF/repo → CPE context; without it packages stay effectively unscanned (`OS_UNKNOWN` / `dnfMetadataStatus: unavailable` / `NOT_SCANNED`).

**Agent content token (upstream `roxagent`):** XXH64 of IndexReport + facts (includes `dnf_metadata_status`). Sensor `GetReport` with matching `last_known_token` → `outcome=unchanged` (no new forward to Central). New content → `outcome=forwarded` → rematch.

**Intervals:**

- Sensor scraper `pollInterval` (module default `1m`) = how often Sensor dials the agent.
- Agent `--rescan-interval` (module default now `30m`; product floor `5m`, stock `4h`) = how often the guest rebuilds inventory. Under `KVM_EMULATION`, `5m` often becomes a permanent CPU loop because one rescan takes longer than 5m.

---

## What we learned on this lab (forward-looking only)

| Topic | Guidance for redesign |
|-------|------------------------|
| Emulation | Infra workers lack `/dev/kvm`; CNV uses `KVM_EMULATION`. Expect slow boot, slow DNF, slow first agent scan (often 10–20+ min). |
| VM count | Prefer **2 VMs** under emulation (or 1). Three guests, especially two on one worker, starve agent scans. |
| Guest image | Eng path uses **dnf-primed** `quay.io/rhacs-eng/vm-images:rhel9-dnf-primed-latest` + pull secret from cluster `openshift-config/pull-secret` (`quay.io/rhacs-eng`). Stock `rhel-guest-image` needs entitlement + live DNF. |
| Pull secret | Module creates `acs-vm-pull-secret` in demo NS; VM template lists `imagePullSecrets`. |
| Agent install | Guest systemd is flaky under emulation; module runs `nohup … roxagent serve --port 818 --host-path /`. Eng native install uses bind-mounts under `/tmp/roxroot` - consider aligning later. |
| DNF seed | Stock path: copy `openshift-config-managed/etc-pki-entitlement` + `trivial` (`dnf reinstall setup`) or `httpd`. Primed path: `ACS_VIRT_DNF_MODE=skip`. Mask `dnf-makecache.timer` on guests if it fights the agent for CPU. |
| Status semantics | Do not report module `ok` until CVE findings exist on the intended VM set. Nested API severity is `{total, fixable}` - already handled in `virt_vm_demo.py`. |
| Piotr Slack (staging/demo) | [Thread](https://redhat-internal.slack.com/archives/C07ARHMGLKA/p1793656550.909819): staging has no VM demo; use infra `n2-standard-8` + [add-vms GH action](https://github.com/stackrox/stackrox/actions/workflows/add-vms-to-cluster.yml); DNF txn required for dnf DB / scan data. |

---

## Current module surface (files)

| Path | Role |
|------|------|
| `modules/virt-vm-demo.sh` | Install/status/uninstall orchestrator |
| `modules/virt_vm_demo.py` | Central `/v2/virtualmachines/vms` probe |
| `modules/virt-vm-demo.md` | Talk track |
| `modules/virt-vm-demo/vm.yaml.tmpl` | VM CR (VSOCK, cloud-init, pull secret, containerDisk) |
| `modules/virt-vm-demo/vm-agent.service` | Optional systemd unit (not used under emulation nohup path) |
| `config/modules.json` | Module registration |

**Env knobs already present:** `ACS_VIRT_NAMESPACE`, `ACS_VIRT_VM_COUNT`, `ACS_VIRT_POLL_INTERVAL`, `ACS_VIRT_RESCAN_INTERVAL`, `ACS_VIRT_GUEST_IMAGE`, `ACS_VIRT_DNF_MODE` (`trivial`\|`httpd`\|`skip`), `ACS_VIRT_UNINSTALL_CNV`.

**Git note:** These module files were largely untracked/dirty on 2026-11-03; commit when redesign ships or as an explicit checkpoint.

---

## Suggested redesign outcomes

1. **Default to 2 VMs** when `KVM_EMULATION` is detected (or always on infra labs); document BM/`n2-standard-8` for 3+.
2. **Single guest strategy** (pick one primary): primed image + `DNF_MODE=skip`, *or* stock image + entitlement + one small DNF txn - not a hybrid mess of both stories unless intentional (e.g. one of each for contrast).
3. **Status = demo-ready** only when `withFindings >= expected` and Running count matches.
4. **Agent lifecycle:** one process per guest; persist start across reboot if possible; never default `5m` rescan on emulation.
5. **Talk track** synced to actual VM names/count and primed vs stock.
6. Optional later: align `--host-path` / bind-mount layout with eng `install-agent-native.sh`.

---

## Quick verify commands (next agent)

```bash
export KUBECONFIG=…/bm-50rc4-on-ocp5.kubeconfig
./modules/virt-vm-demo.sh --status
oc -n acs-virt-demo get vm,vmi
# Sensor: look for VMScraper outcome=forwarded vs unchanged
oc -n stackrox logs deploy/sensor -c sensor --since=30m | rg 'VMScraper|rhel9'
```

Central UI: **Vulnerability Management → Results → Virtual Machines**.

---

## Out of scope for redesign (unless asked)

- Replacing ACS feature flags / CNV install logic wholesale
- Windows guests / guest runtime / Compliance Virt profiles
- Restoring rhel9-2 on this overloaded emulation lab without node capacity changes
