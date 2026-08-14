# Requirements

What we are building, for whom, and how we know it works. Read this before touching code.

---

## 1. Problem

A RHACS demo lab is more than “Central is installed.” Before a presentation you routinely need to:

- Confirm Central is reachable and you have a working API token
- Point `roxctl` at the right Central
- Confirm the secured cluster and sensors are healthy
- Deploy or refresh sample apps that generate violations and network traffic
- Wire image registries, demo users, OAuth login, ACS RBAC, Slack, compliance scans, and Splunk export

Today those steps are scattered across ad hoc scripts, manual `oc` commands, and UI clicks. They are hard to repeat after a cluster rebuild, hard to see at a glance (“what’s still broken?”), and hard to hand to someone who did not build the lab.

**This project** is a small toolkit and **web GUI** that run those steps as named, ordered, idempotent **modules**, each with explicit **status** and **run** behavior. The GUI is the primary interface from the first module onward; the CLI exists for automation and for the GUI backend to call.

---

## 2. Users

| User | Need |
|------|------|
| **Lab owner** (primary) | Prepare or refresh the demo cluster from the GUI; see module status at a glance and run steps without memorizing CLI flags |
| **Future you** | After weeks away, open the GUI (or run `--status`) and know what to fix |
| **Automation** | Same behavior via `acs-setup.sh` for scripting and for the GUI server to invoke |

Not in scope: unattended multi-tenant provisioning, production installs, or teaching someone OpenShift from zero.

---

## 3. Target environment

### 3.1 Already true before any module runs

| # | Condition |
|---|-----------|
| E-1 | A single OpenShift cluster is the demo target |
| E-2 | `oc` (or `kubectl`) on the **user's** machine is logged in with permissions to create projects, routes, OAuth, cluster Operators, etc. as each module requires |
| E-3 | The RHACS Operator is installed |
| E-4 | **Central is installed and running** (Custom Resource already applied; not greenfield install) |
| E-5 | **A secured cluster is installed and registered** with that Central (sensor stack present) |
| E-6 | `bash`, `jq`, and `python3` are available on the **user's** machine |
| E-7 | Network path exists from the laptop to Central’s HTTPS endpoint (route or override URL) |

### 3.2 What this project does *not* assume

- A specific OpenShift version (modules may document minimums in their `--help`)
- That every optional integration (Slack token, Splunk, external registries) is preconfigured; modules that need secrets document required env vars

### 3.3 User-provided inputs (secrets and overrides)

Documented in an example env file (no real values in git). Primary store: gitignored **`lab-credentials.json`** at repo root (schema: `config/lab-credentials.schema.json`, example: `config/lab-credentials.example.json`). Override path: `ACS_LAB_CREDENTIALS_FILE`.

| Area | Fields | Notes |
|------|--------|--------|
| **Central cluster → OpenShift** | console URL, admin username, admin password | OCP admin fields optional when the user relies on `oc login` |
| **Central cluster → RHACS Central** | console URL, API token, admin username, admin password, `authPreference` | `authPreference`: `apiToken` or `password` when both are set |
| **Secured cluster** | `sameAsCentralCluster` (boolean) | Default `true` when Central and sensor share one cluster |
| **Secured cluster → OpenShift** (when not same) | console URL, admin username, admin password | Same optional OCP admin semantics |

Legacy `central-credentials.json` (`endpoint` + `token`) is read once and migrated to the v1 shape on load.

| Variable | Used by | Meaning |
|----------|---------|---------|
| `ACS_LAB_CREDENTIALS_FILE` | GUI, modules | Override path to credentials JSON |
| `ACS_CENTRAL_ENDPOINT` | modules using Central API | Fallback Central URL when `lab-credentials.json` field is empty |
| `ROX_API_TOKEN` / `TOKEN` | modules using Central API | Fallback API token when `lab-credentials.json` field is empty |
| Module-specific vars | e.g. `slack-notifier`, `splunk` | Defined in each module’s `--help` |

---

## 4. Glossary

| Term | Meaning here |
|------|----------------|
| **Module** | One demo-prep concern (e.g. Slack integration), implemented as one script |
| **Orchestrator** | `acs-setup.sh` — dispatches to modules, aggregates status |
| **Run** | Apply or refresh configuration toward the desired demo state |
| **Status** | Read-only check: is this module’s desired state present and healthy? |
| **ok** | Status state: nothing to do |
| **needs-run** | Status state: desired state missing or drifted; `--run` should fix it |
| **error** | Status state: check failed (permissions, API down, misconfiguration) |
| **User** | The person preparing the demo lab (GUI or CLI). Do not call them an "operator" — that word is reserved for Kubernetes/OpenShift **Operators** (RHACS Operator, Compliance Operator, etc.). |

### Terminology

- **User** — human running this toolkit on their laptop.
- **Operator** (capital **O**, or "RHACS Operator", "Splunk Operator", …) — a cluster component installed via OLM/Helm, not a person.

---

## 5. System requirements

### 5.1 Repository layout

| ID | Requirement |
|----|-------------|
| R-LAY-1 | `config/modules.json` is the single registry of module id, display label, numeric order, and `dependsOn` |
| R-LAY-2 | Each module has a documented entrypoint: `modules/NN-<id>.sh` (may delegate to helpers in the same directory) |
| R-LAY-3 | `acs-setup.sh` lives at repo root and is the only supported top-level CLI entrypoint |
| R-LAY-4 | `gui/` is part of the repo from the first shipped module; not a later add-on |
| R-LAY-5 | `STATUS.md` is updated when module behavior ships (human changelog, not generated) |
| R-LAY-6 | Secrets and local credential files are gitignored; example env documents variable names only |
| R-LAY-7 | `lib/` holds thin shared helpers required by modules; modules must not duplicate that logic |

### 5.2 Orchestrator (`acs-setup.sh`)

| ID | Requirement |
|----|-------------|
| R-ORCH-1 | Supports `--help`, `--status`, `--run` |
| R-ORCH-2 | `--status` without `--module` runs every module’s `--status` and prints aggregated output |
| R-ORCH-3 | `--status --module <id>` runs one module’s `--status` |
| R-ORCH-4 | `--run` without `--module` runs all modules in dependency order (topological sort of `dependsOn`; tie-break by `number`) |
| R-ORCH-5 | `--run --module <id>` runs one module; does not auto-run dependencies unless documented in that module’s `--help` |
| R-ORCH-6 | `--dry-run` passed through to every module (see R-MOD-8) |
| R-ORCH-7 | Optional `--json` on `--status` emits machine-readable aggregate for the GUI |
| R-ORCH-8 | Exit code: `0` only if every invoked module succeeds; otherwise non-zero |
| R-ORCH-9 | Orchestrator **dispatches** to module scripts; it does not embed module logic and does not delegate to one giant script |

### 5.3 Module script contract (every `modules/NN-*.sh`)

| ID | Requirement |
|----|-------------|
| R-MOD-1 | Implements `--help`, `--status`, `--run`, and `--dry-run` |
| R-MOD-2 | `--help` explains purpose, dependencies, required env vars, and side effects |
| R-MOD-3 | `--status` prints exactly one TSV row: `id`, `state`, `message` where `state` ∈ `ok` \| `needs-run` \| `error` |
| R-MOD-4 | `--run` is idempotent: second run with no drift leaves cluster in the same desired state |
| R-MOD-5 | `--run` exit `0` on success; non-zero on failure with stderr message |
| R-MOD-6 | **Entrypoint** implements the contract above. **Implementation:** prefer bash + jq for thin glue (`oc`, `curl`, file I/O). Use **Python 3** when it clearly reduces risk or complexity (structured Central API calls, non-trivial JSON transforms, validation). Avoid unmaintainable shell; avoid Python where a few lines of bash suffice |
| R-MOD-7 | Module entrypoints are callable standalone without the orchestrator |
| R-MOD-8 | **`--dry-run` on `--run`:** every module supports it. **Verify/read-only modules:** print what would be checked and with which inputs — no mutations. **Mutating modules:** print what would be applied/changed without applying. Exit `0`; use stderr/stdout for the plan |
| R-MOD-9 | Modules that call Central or read lab credentials must use **`lib/central.py`** (file-first precedence). Do not reimplement credential loading or env override rules in module code |

### 5.4 Aggregated status format

**TSV (default):** header row then one row per module:

```text
id	state	message
registries	ok	quay.io and registry.redhat.io integrations configured
slack-notifier	needs-run	Slack integration not configured
```

**JSON (`--json`):** array of objects `{ "id", "number", "label", "state", "message", "dependsOn" }`.

### 5.5 Implementation constraints

| ID | Requirement |
|----|-------------|
| R-NFR-1 | Prefer self-contained module entrypoints; shared logic lives in `lib/` when two or more modules need the same behavior (credentials, Central API client, etc.) |
| R-NFR-2 | No credentials committed to git |
| R-NFR-3 | Modules log clearly which cluster/namespace/API they touch |
| R-NFR-4 | Safe to run `--status` anytime; `--run` may change cluster state as documented per module |

### 5.6 ACS interaction model

| ID | Requirement |
|----|-------------|
| R-ACS-1 | **Mimic the RHACS UI.** When a capability exists in Central (integrations, compliance scan schedules, notifier config, RBAC, etc.), modules configure it through **Central API** the same way an operator would in the console — not by applying lower-level cluster CRs that bypass Central |
| R-ACS-2 | **Compliance scans:** do **not** apply Compliance Operator `ScanSetting` / `ScanSettingBinding` (or related scan CRs) directly. Operator install is on-cluster (`oc`); scan schedules are Central API only (see M9) |

---

## 6. Module requirements

For each module: **purpose**, **depends on**, **status must verify**, **run must do**, **acceptance**.

---

### M1 — `registries` (ACS image integrations)

**Purpose:** Configure RHACS image integrations needed for vulnerability scanning on the secured cluster. Reads registry credentials from the OpenShift cluster pull secret and applies them to Central.

**Depends on:** none (uses Central API token from `lab-credentials.json` and `oc` on the secured cluster)

**Status must verify:**

1. Central API token is available and authenticates
2. `pull-secret` in `openshift-config` is readable via `oc`
3. `Public Quay.io` integration has robot credentials matching pull-secret `quay.io`
4. `registry.redhat.io` docker registry integration exists and matches pull-secret

**Run must do:**

1. Read `quay.io` and `registry.redhat.io` credentials from the secured-cluster pull secret
2. Update `Public Quay.io` with `registryRobotCredentials` (replaces OAuth-only auth)
3. Create or update `registry.redhat.io` integration idempotently
4. Test integrations when applying (not on dry-run)

**Acceptance:**

- `--status` is `ok` when both integrations match the pull secret
- `--run` is idempotent on a configured lab
- Image scans for `quay.io/openshift-release-dev` images succeed after run

---

### M2 — `roxctl-env` (`~/.roxctl` for demos)

**Purpose:** Configure the local `roxctl` CLI so demo commands work without manual config editing.

**Depends on:** none (reads endpoint and token from `lab-credentials.json`)

**Status must verify:**

1. `~/.roxctl` (or documented config path) points at the Central endpoint in lab credentials
2. Configured token works (`roxctl` can authenticate)

**Run must do:**

1. Read endpoint and token from lab credentials / env
2. Write `roxctl` config for Central URL and admin API token
3. Not rotate or create Central users unless documented

**Acceptance:**

- After `--run`, a documented `roxctl` command against Central succeeds
- `--status` is `ok` when config matches current Central endpoint and token

---

### M3 — `ms-demo` (Mostmark microservices)

**Purpose:** Deploy the Mostmark microservices demo app in OpenShift project `ms-demo` for network/policy/violation demos.

**Depends on:** none

**Status must verify:** Project exists; workloads ready per module definition

**Run must do:** Create/update manifests in `ms-demo`; idempotent apply

**Acceptance:** App reachable or pods ready; `--status` reflects drift if someone deleted the project

---

### M4 — `init-demo` (Init Containers sample)

**Purpose:** Deploy the Init Containers demo app in project `init-demo`.

**Depends on:** none

**Status / run / acceptance:** Same pattern as M3 for project `init-demo`

---

### M5 — `ocp-users` (OpenShift demo users)

**Purpose:** Regenerate HTPasswd-backed users, Identity Provider, and RBAC needed for OpenShift login demos.

**Depends on:** none

**Status must verify:** IdP, users, and bindings match demo spec

**Run must do:** Apply/regenerate HTPasswd secret, OAuth IdP, roles/bindings per demo spec

**Acceptance:** Documented demo users can log in to OpenShift

---

### M6 — `ocp-OAuth` (Central OpenShift login)

**Purpose:** Configure Central to use OpenShift as an identity provider for UI login demos.

**Depends on:** none (may assume M5 users exist for end-to-end login)

**Status must verify:** Central auth provider configured for OpenShift OAuth

**Run must do:** Apply Central/OpenShift OAuth integration per demo spec

**Acceptance:** Login to Central via OpenShift works for a demo user

---

### M7 — `acs-users` (Central RBAC for demo users)

**Purpose:** Create ACS access scopes, roles, and permission sets for demo personas.

**Depends on:** `ocp-OAuth`

**Status must verify:** Expected roles/scopes exist and map to demo users

**Run must do:** Idempotent Central API configuration

**Acceptance:** Demo user sees expected ACS access after OpenShift login

---

### M8 — `slack-notifier` (Central → Slack)

**Purpose:** Configure Central’s Slack notification integration for demo alerting.

**Depends on:** `roxctl-env` (or equivalent working Central API access)

**Status must verify:** Slack notifier configured in Central

**Run must do:** Create/update notifier; requires Slack webhook/token via env

**Acceptance:** Test notification or config presence per module spec

---

### M9 — `compliance-operator` (Compliance Operator + scan schedule)

**Purpose:** Ensure the OpenShift Compliance Operator is installed on the secured cluster and ACS compliance scan schedules are configured the same way a user would in the RHACS UI.

**ACS principle (required):** This toolkit targets **RHACS (ACS)** demos. Do **not** configure compliance scans by applying Compliance Operator `ScanSetting` / `ScanSettingBinding` (or related scan CRs) directly on the cluster. That bypasses Central and duplicates what the UI does via Central API. The operator install is on-cluster (`oc`); scan schedules must be created through **Central API** (equivalent to Compliance → scan configurations → Save in the UI), not raw CO YAML.

**Phased delivery:**

| Phase | Scope | Mechanism |
|-------|--------|-----------|
| **1 (shipped first)** | Install Compliance Operator via OLM on the secured cluster | `oc` — namespace, OperatorGroup, Subscription; wait for CSV/deployment |
| **2 (follow-up)** | Scan schedule for the demo cluster | Central API (e.g. `POST /v2/compliance/scan/configurations`) — mimic UI wizard |

**Depends on:** none (secured cluster is a manual prerequisite per §3.1)

**Status must verify (full module):** Compliance Operator healthy; scan schedule present in Central.

**Status (phase 1 only):** Compliance Operator Subscription + CSV `Succeeded` + operator deployment ready. Message notes scan schedule not configured until phase 2.

**Run must do (full module):** Install Compliance Operator if missing; create/update scan schedule via Central API.

**Run (phase 1 only):** OLM install only; idempotent `oc apply`; no Central API calls; no `ScanSetting` / `ScanSettingBinding`.

**Acceptance (full module):** Compliance scans visible in Central for demo cluster.

**Acceptance (phase 1):** `--status` is `ok` when the operator is installed and healthy on the secured cluster.

---

### M10 — `splunk` (Splunk Operator + TA)

**Purpose:** Deploy Splunk Operator and RHACS Splunk TA so audit/violation events can flow to Splunk for SIEM demos.

**Depends on:** none

**Status must verify:** Splunk stack and TA integration healthy per module spec

**Run must do:** Delegate to `splunk-lab.sh` `install` (or equivalent); idempotent per wrapped script behavior

**Wrap:** Entrypoint finds `splunk-lab.sh` via `ACS_SPLUNK_LAB_SCRIPT` or documented default under `rhacs-splunk-ta-demo-skill`. Vendoring into this repo is optional follow-up, not required for M10 v1.

**Acceptance:** Events searchable in Splunk after demo traffic; `--status` reflects wrapped script health; clear message if script path or TA bundle missing

---

## 7. GUI requirements

The GUI is **required from the first deliverable** (module M1 `registries`). No module ships without corresponding GUI support for that module’s status, configuration, and run action.

**Look, feel, layout, and interaction:** [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) (PatternFly v5, wide column, module table, collapsibles, log pane).

| ID | Requirement |
|----|-------------|
| R-GUI-1 | `gui/` exists before M1 is considered done |
| R-GUI-2 | Reads `config/modules.json` for module list, order, labels, and dependencies |
| R-GUI-3 | Shows per-module status (invokes orchestrator `--status --json` or equivalent API) |
| R-GUI-4 | Lab credentials form per [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) §3; persisted to `lab-credentials.json` |
| R-GUI-5 | For each shipped module: control to run that module (with confirmation when `--run` is destructive) |
| R-GUI-6 | Refresh status on demand and after a run completes |
| R-GUI-7 | Does not commit secrets; server-side gitignored storage preferred over browser localStorage for tokens |
| R-GUI-8 | GUI backend invokes `acs-setup.sh` (or module entrypoints directly with the same contract); GUI does not reimplement module logic |
| R-GUI-9 | New modules add GUI affordances in the **same PR/change** as the module script |
| R-GUI-10 | GUI server binds **`127.0.0.1` only**; no network exposure beyond the **user's** laptop |
| R-GUI-11 | Visual and UX requirements in **REQUIREMENTS-GUI.md** are part of GUI acceptance |

### 7.1 First deliverable (M1 + GUI)

Shipping M1 is not complete until all of the following work:

1. `config/modules.json` includes module `registries` as M1
2. `modules/01-registries.sh` meets R-MOD-* and M1 acceptance
3. `acs-setup.sh` can `--status` and `--run --module registries`
4. GUI lists module `registries`, shows its status, and triggers run
5. Lab credentials form saves Central endpoint and API token (manual prerequisite)

Later modules extend the same GUI (new row/card, config fields if needed, run button); the shell is never the only way to drive setup.

---

## 8. Explicitly out of scope

| Item | Reason |
|------|--------|
| Installing RHACS Operator | Lab prerequisite (E-3) |
| Installing Central from scratch | Lab prerequisite (E-4) |
| Net-new OpenShift cluster creation | Outside demo-prep |
| Committing API tokens or webhooks | Security |
| Replacing RHACS product documentation | This is lab automation only |

---

## 9. Open decisions (block implementation until resolved)

| # | Question | Decision |
|---|----------|----------|
| D-1 | Local credentials file: path and JSON shape? | **Decided:** gitignored **`lab-credentials.json`** at repo root, schema **`config/lab-credentials.schema.json`**. Two clusters: **centralCluster** (OpenShift + RHACS Central) and **securedCluster** (optional separate OpenShift when `sameAsCentralCluster` is false). OCP admin username/password optional per cluster. Central: console URL, API token, admin username/password, `authPreference` (`apiToken` \| `password`). GUI Save merges secrets (blank password/token keeps existing). Env: `ACS_LAB_CREDENTIALS_FILE`, `ACS_CENTRAL_ENDPOINT`, `ROX_API_TOKEN`/`TOKEN` may override per module `--help`. Legacy `central-credentials.json` migrated on read. |
| D-2 | M3 `--run`: verify-only or also register/fix secured cluster? | **N/A:** `secured-cluster` removed from module list; registration is a manual prerequisite (§3.1 E-5). |
| D-3 | GUI stack and how the local server is started | **Decided:** Python backend (Flask or FastAPI) + simple HTML/JS frontend; `./gui/serve.sh` or equivalent; REST API shells out to `acs-setup.sh`. Bind **`127.0.0.1` only** (localhost); fixed port documented in `gui/README` or `--help`. No auth (solo laptop use). |
| D-4 | M10: reimplement Splunk deploy or call existing `splunk-lab.sh`? | **Decided:** **Wrap first** — `modules/10-splunk.sh` delegates to `splunk-lab.sh` (default path documented; override via env e.g. `ACS_SPLUNK_LAB_SCRIPT`). Map module `--status` / `--run` to script `--status` / `install`. **Optional later:** vendor script into this repo if path coupling or sync becomes annoying. TA `.tgz` remains **user-supplied**; status reports if missing. |
| D-5 | Per-module `--dry-run` mandatory for all modules or only destructive ones? | **Decided:** **All modules** implement `--dry-run` for consistency. Verify/read-only modules describe checks and examination context only; mutating modules describe planned changes without applying. GUI may expose dry-run where useful. |

---

## 10. Review checklist

Before implementation starts, confirm:

- [ ] Section 3 (environment) matches your real lab
- [ ] M1 `registries` acceptance matches lab workflow (pull secret → Central integrations)
- [ ] Module list M1–M10 is complete; nothing missing, nothing to drop
- [x] Open decisions in section 9 are answered
- [ ] First deliverable accepted: M1 + GUI per §7.1
