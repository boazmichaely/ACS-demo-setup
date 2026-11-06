# Impact planes rename (fleet)

**Goal:** Rename catalog / orchestrator planes so ACSCS eligibility is explicit.

| Old | New | Meaning | Works with ACSCS Central |
|-----|-----|---------|--------------------------|
| `openshift` | `secured-cluster` | `oc` / CRS / sensor on a secured cluster | yes |
| `central` (API) | `central-api` | Central HTTP API only | yes |
| *(new)* | `central-ocp` | `oc` against Central’s OpenShift (`_central`) | **no** |

ACSCS-safe module = `impactPlanes` does **not** include `central-ocp`.

**Interrupt recovery:** this file is the source of truth. Per-module cells
below are `TODO` / `WIP` / `DONE`. Resume at the first non-DONE cell.
Timestamps use `YYYY-MM-DD HH:MM` (local).

Last updated: 2026-11-06 17:23

---

## Epic checklist

| # | Task | Status | Updated | Notes |
|---|------|--------|---------|-------|
| 0 | Tracker MD; delete `MODULE-USAGE-MULTI-SC-PROGRESS.md` | DONE | 2026-11-06 14:03 | This file |
| 1 | Catalog (`config/modules.json`) | DONE | 2026-11-06 14:03 | All rows remapped |
| 2 | Shared code (orchestrator + flag helpers) | DONE | 2026-11-06 15:13 | See Shared row |
| 3 | Module help / Usage | DONE | 2026-11-06 15:13 | Flags verified via `--help` |
| 4 | Module status output | DONE | 2026-11-06 15:13 | registries phases; virt/init plane strings |
| 5 | GUI Type column + impact picker | DONE | 2026-11-06 15:12 | `gui/static/app.js` |
| 6 | README architecture / concepts | DONE | 2026-11-06 15:12 | |
| 7 | ADDING-A-MODULE + REQUIREMENTS | DONE | 2026-11-06 15:12 | |

---

## Shared infrastructure (task 2)

| Piece | Code | Notes | Updated |
|-------|------|-------|---------|
| `lib/module_orchestrate.py` | DONE | New plane ids; SC fan-out; central-ocp then central-api | 2026-11-06 14:03 |
| `modules/_central_only_orch_flags.sh` | DONE | Accepts `central-api`; ignores SC / central-ocp | 2026-11-06 14:03 |
| `modules/_central_side_orch_flags.sh` | DONE | registries (api + ocp) | 2026-11-06 14:04 |
| `templates/module-skeleton.sh` | DONE | New plane ids in Usage/Flags/case | 2026-11-06 15:13 |
| `scripts/acs-setup.sh` help blurb | DONE | Fan-out wording | 2026-11-06 15:12 |

---

## Per-module matrix (tasks 2–4)

Columns: **Code** = `--plane` parsing + `want_*` / run paths; **Help** = Usage /
`--help`; **Status** = human status lines / JSON phases that name planes.

| Module | Planes | Code | Help | Status | Updated | Notes |
|--------|--------|------|------|--------|---------|-------|
| registries | api + ocp | DONE | DONE | DONE | 2026-11-06 17:23 | ocp=`oc`+cache; api=Central API from cache only (no oc) |
| signature-integration | api | DONE | DONE | DONE | 2026-11-06 15:13 | `_central_only_` |
| slack-notifier | api | DONE | DONE | DONE | 2026-11-06 15:13 | |
| users-part2-oauth | api | DONE | DONE | DONE | 2026-11-06 15:13 | |
| users-part3-acs | api | DONE | DONE | DONE | 2026-11-06 15:13 | |
| compliance-operator | api + sc | DONE | DONE | DONE | 2026-11-06 15:13 | lib plane cases updated |
| init-demo | api + sc | DONE | DONE | DONE | 2026-11-06 15:13 | |
| virt-vm-demo | api + ocp + sc | DONE | DONE | DONE | 2026-11-06 15:13 | ocp=CR; api=CVE wait |
| ms-demo | sc | DONE | DONE | DONE | 2026-11-06 15:13 | legacy `openshift` alias |
| users-part1-ocp | sc | DONE | DONE | DONE | 2026-11-06 15:13 | |
| splunk-TA | sc | DONE | DONE | DONE | 2026-11-06 15:11 | |
| *(stubs)* | catalog only | N/A | N/A | N/A | 2026-11-06 14:03 | Catalog DONE; no scripts |

Legend: `TODO` not started · `WIP` started / incomplete · `DONE` verified · `N/A` no script

---

## Docs / UI (tasks 5–7)

| Piece | Status | Updated |
|-------|--------|---------|
| `gui/static/app.js` Type labels | DONE | 2026-11-06 17:20 | Three plane columns with `+` marks |
| `gui/static/app.js` impact picker (central vs SC) | DONE | 2026-11-06 15:12 |
| `README.md` architecture intro | DONE | 2026-11-06 15:12 |
| `ADDING-A-MODULE.md` planes section | DONE | 2026-11-06 15:12 |
| `REQUIREMENTS.md` plane mentions | DONE | 2026-11-06 15:12 |

---

## Progress log

| Time | Note |
|------|------|
| 2026-11-06 14:03 | Tracker created; old Usage progress MD removed; catalog written; orchestrator + helpers rewritten |
| 2026-11-06 14:04 | Mechanical rename pass across all shipped `.sh` modules (incomplete) |
| 2026-11-06 14:05 | Per-module matrix added so interrupt resume is obvious |
| 2026-11-06 15:10 | Status check: ~1/3 done; resume requested |
| 2026-11-06 15:11 | Fixed API-only / SC-only Flags + case arms; dual-plane help + lib; virt ocp/api split; registries status phases |
| 2026-11-06 15:12 | GUI Type + picker; README architecture; ADDING-A-MODULE; REQUIREMENTS; acs-setup help |
| 2026-11-06 15:13 | Orchestrator smoke with live SC ids; `--help` Flags verified; skeleton Flags; epic marked DONE |
| 2026-11-06 17:02 | Per-module review: all shipped PASS (catalog/help/orch/case). Residual: registries accepts both Central planes but does not split work per plane (full pull-secret+API every invoke) |
| 2026-11-06 17:16 | registries first split (flawed: api still used oc) |
| 2026-11-06 17:23 | registries fixed: central-ocp writes `.cache/registries-pull-secret.json`; central-api never calls oc |
| 2026-11-06 17:20 | GUI modules table: Type is three columns (Central API / Central OCP / Secured Cluster) with `+` marks; cache bust shell85 | |
