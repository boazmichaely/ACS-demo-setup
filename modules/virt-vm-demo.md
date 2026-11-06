# ACS for Virtual Machines - demo talk track

Audience: security / platform teams evaluating RHACS on OpenShift Virtualization
(for example EBC or discovery). Runtime for the click path: about 5-7 minutes
once the lab module has finished (`./modules/virt-vm-demo.sh --run`).

Lab module creates project `acs-virt-demo` with two RHEL 9 guests (`rhel9-1`,
`rhel9-2`) from the eng **dnf-primed** image
(`quay.io/rhacs-eng/vm-images:rhel9-dnf-primed-latest`), enables ACS
virtual-machine scraping, and installs `roxagent` in each guest so Scanner V4
can match CVEs without a live DNF transaction in the guest. Infra clusters use
**KVM emulation** (no bare metal required); first boot and first agent scan are
slower than on BM.

## One-line setup

Same ACS Central that protects containers also sees OpenShift Virtualization
guests - one control plane for mixed container and VM estates on OCP Virt.

## Act 1 - Inventory

1. Open Central (URL from lab credentials).
2. Go to **Vulnerability Management → Results → Virtual Machines**
   (5.0 / Dev Preview badge may still show on some builds).
3. Show the two VMs from namespace `acs-virt-demo`.
4. Optional: OpenShift console → **Virtualization** → same two VMs Running.

## Act 2 - Guest packages (and CVEs)

1. Open `rhel9-1` (or `rhel9-2`).
2. Show **guest OS** (RHEL 9.x) and the **component inventory** from the
   in-guest agent (hundreds of RPM packages over VSOCK - not just the guest
   containerDisk image).
3. Walk CVE severity once populated.
4. Contrast with a container deployment in the same Central: image layers vs
   live guest packages - different workload shape, same ACS workflow.

**Lab tip:** Under **KVM_EMULATION**, the first agent package index can take
10-20+ minutes. Sensor logs show `VMScraper: scrape ... ok outcome=forwarded`
when Central has the report. The module waits until **both** VMs show CVE
findings before `--status` is `ok`.

## Act 3 - Architecture honesty (about 30 seconds)

Say this clearly so the customer does not confuse ACS with guest EDR:

- **Requires** OpenShift Virtualization, VSOCK on the VM
  (`autoattachVSOCK: true`), and the in-guest `roxagent`.
- **Today:** RHEL guest OS vulnerability reporting (GA targeted with ACS 5.0).
- **Not yet:** Windows guests (CrowdStrike integration on the roadmap, planning
  around ACS 5.2), process/network runtime *inside* the guest (separate pillar
  from vulnerability scanning), VMs that do not run on OCP Virt.
- ACS is **not** a Carbon Black / antivirus replacement; keep guest AV/EDR if
  the customer already runs it.

## Close

One ACS Central for containers and VMs on the virt platform - strong story for
migration and mixed estates. Platform hardening (Compliance Operator / OCP Virt
profiles) is the companion conversation; this module only proves guest CVE
visibility.

## Operator reminders

| Item | Detail |
|------|--------|
| Module | `./modules/virt-vm-demo.sh --run` |
| Namespace | `acs-virt-demo` |
| Guests | `rhel9-1`, `rhel9-2` (dnf-primed eng image + pull secret) |
| Scraper | SecuredCluster `virtualMachines.scraper.pollInterval` = `1m` (SC); `ROX_VIRTUAL_MACHINES` also on Central CR (Central OCP) |
| Agent | `roxagent serve --rescan-interval 30m` (infrequent; initial scan matters) |
| Central API | `/v2/virtualmachines/vms` (UI Virtual Machines page) |
| Demo-ready | `--status ok` only when both VMIs are Running and both have CVE findings |

## Internal references

- Demo recipe (Piotr): `#proj-acs-openshift-virtualization`
  https://redhat-internal.slack.com/archives/C07ARHMGLKA/p1768290533467369
- Feature scope (Saledort): `#ACS on virtualization`
  https://redhat-internal.slack.com/archives/C0BGRBPRQ3S/p1784014883681779
- Coverage limits: `#forum-acs`
  https://redhat-internal.slack.com/archives/C01R0E7CVMX/p1793617154736829
- KB (VM scanning support draft): https://access.redhat.com/articles/7045053
