# Module Usage ↔ multi-SC flags (temporary)

**Do not delete until Boaz has reviewed all results.**

Goal: every shipped module’s `--help` / Usage documents how it treats
orchestrator flags (`--plane`, `--secured-cluster-id`). Behavior must match
the text. Central-only modules **graciously ignore** OpenShift-only noise.

Reference: `ADDING-A-MODULE.md` § Planes and multi-SC; shared helpers in
`modules/_central_only_orch_flags.sh`.

Last updated: 2026-11-06 (all shipped modules reviewed)

---

## Legend

| Mark | Meaning |
|------|---------|
| TODO | Not reviewed |
| DONE | Usage + behavior aligned |
| FIXED | Behavior bug found and fixed while aligning Usage |
| N/A | Catalog stub (no script) |

---

## Checklist

| Module | Planes | Status | Usage documents flags? | Behavior notes |
|--------|--------|--------|------------------------|----------------|
| compliance-operator | both | DONE | Yes - plane + SC id + per-plane Side effects | Reference; Flags text expanded |
| registries | central | FIXED | Yes - central / ignore OpenShift | **Was:** crash on `--plane` / `--secured-cluster-id`. **Now:** ignore with warn; pull-secret always Central OCP |
| signature-integration | central | FIXED | Yes | Same graceful-ignore bugfix |
| slack-notifier | central | FIXED | Yes | Same graceful-ignore bugfix |
| users-part2-oauth | central | FIXED | Yes | Same graceful-ignore bugfix |
| users-part3-acs | central | FIXED | Yes - distinguishes lab id vs ACS name | Ignores `--secured-cluster-id`; keeps `--secured-cluster NAME` for ACS scope |
| ms-demo | openshift | DONE | Yes - plane + SC id in Usage lines | Rejects `--plane central`; ≤1 SC id |
| users-part1-ocp | openshift | DONE | Yes | Same pattern; documents console lives on that SC |
| splunk-TA | openshift | DONE | Yes | Same pattern |
| init-demo | both | DONE | Yes - what each plane does | OpenShift: workloads; Central: policies; SC ids ignored on central plane |
| virt-vm-demo | both | DONE | Yes - what each plane does | OpenShift: CNV/VMs/SC CR; Central: Central CR on `_central` + CVE wait |
| openshift-mcp | openshift | N/A | | No script |
| openshift-mcp-gateway | openshift | N/A | | No script |
| acs-mcp | openshift | N/A | | No script |
| secrets-manager | openshift | N/A | | No script |
| acs-lightspeed | both | N/A | | No script |
| prometheus | both | N/A | | No script |

---

## Acceptance per module

- [x] Usage lists `--plane` / `--secured-cluster-id` (or Central-only ignore policy)
- [x] Usage says what each flag does for this module
- [x] Script accepts what Usage claims
- [x] Central-only: OpenShift flags ignored gracefully (warn; no crash)
- [x] OpenShift-only: rejects `--plane central`; ≤1 SC id
- [x] Both: plane split matches help; SC id rules match help

---

## Bugs fixed this pass

1. **Central-only modules crashed** on orchestrator `--plane` / `--secured-cluster-id`
   (`unknown option`). Fixed via `modules/_central_only_orch_flags.sh` + Usage
   documenting ignore policy for: `registries`, `signature-integration`,
   `slack-notifier`, `users-part2-oauth`, `users-part3-acs`.

2. **Usage templates omitted flags** the scripts already accepted (OpenShift-only
   modules listed SC id but often not `--plane` in the Usage command lines).
   Updated `ms-demo`, `users-part1-ocp`, `splunk-TA`.

3. **Dual-plane help** clarified per-plane work for `init-demo`, `virt-vm-demo`,
   `compliance-operator` (Flags section).

---

## How to review

```bash
for m in registries signature-integration slack-notifier users-part2-oauth \
  users-part3-acs ms-demo users-part1-ocp splunk-TA init-demo virt-vm-demo \
  compliance-operator; do
  echo "======== $m ========"
  ./modules/${m}.sh --help 2>/dev/null | sed -n '/^## Usage/,/^## Status/p'
done
```

Smoke: Central-only ignore

```bash
./modules/registries.sh --status --plane openshift --secured-cluster-id x
# expect: warn lines, then normal status (not "unknown option")
```

---

## Progress log

### 2026-11-06 - started

- Tracker created; inventory of Usage vs parsers.

### 2026-11-06 - completed shipped modules

- Added `_central_only_orch_flags.sh`; wired five Central-only modules.
- Expanded Usage/Flags on OpenShift-only and both-plane modules.
- **Awaiting Boaz review before deleting this file.**
