# Requirements

What we are building, for whom, and how we know it works. Read this before touching code.

---

## 1. Problem

A RHACS demo lab is more than “Central is installed.” Before a presentation you routinely need to:

- Confirm Central is reachable and you have a working API token
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
| **Automation** | Same behavior via `scripts/acs-setup.sh` for scripting and for the GUI server to invoke |

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

Schema **version 2**: `activeLabId` + `labs[]`. Each lab has Central cluster credentials, zero or more `securedClusters`, and `activeSecuredClusterId`. The GUI and modules use the **active lab** (and a secured cluster when present; otherwise Central OpenShift). Helpers in `lib/lab_doc.py` migrate older shapes and flatten the active lab for modules (`centralCluster` + `securedCluster`).

| Area | Fields | Notes |
|------|--------|--------|
| **Document** | `activeLabId`, `labs[]` | Switch active lab in the GUI strip; disk log records `lab-switch` / `page-load` with a short lab blurb |
| **Per lab** | `id`, `name`, `insecureSkipTlsVerify` | TLS skip is per lab; env `ACS_INSECURE_SKIP_TLS_VERIFY` overrides |
| **Central cluster → OpenShift** | console URL, admin username, admin password, optional `apiToken` | If `apiToken` is set, modules use `oc login --token=` (SSO labs). Else username/password. |
| **Central cluster → RHACS Central** | console URL, API token, admin username, admin password, `authPreference` | `authPreference`: `apiToken` or `password` when both are set |
| **Secured clusters** | `id`, `name`, `sameAsCentralCluster`, OpenShift block | Default `sameAsCentralCluster: true`; **`activeSecuredClusterId` is user-selected** (GUI: OpenShift for modules) and is the OpenShift target for module `oc` work. Empty `securedClusters` → Central OpenShift |

Legacy v1 (`centralCluster` + `securedCluster`) and `central-credentials.json` (`endpoint` + `token`) are migrated to v2 on load.

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
| **Orchestrator** | `scripts/acs-setup.sh` — dispatches to modules, aggregates status |
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
| R-LAY-1 | `config/modules.json` is the single registry: `id` (script / CLI / Module column), `label` (Description only), list order, `dependsOn`, and `statusComplexity` (1-10 hint for GUI status refresh order; lower refreshes first) |
| R-LAY-2 | Each module has a documented entrypoint: `modules/<id>.sh` (may delegate to helpers in the same directory) |
| R-LAY-3 | `./serve.sh` is the top-level GUI entrypoint; `scripts/acs-setup.sh` is the CLI orchestrator |
| R-LAY-4 | `gui/` is part of the repo from the first shipped module; not a later add-on |
| R-LAY-5 | `STATUS.md` is updated when module behavior ships (human changelog, not generated) |
| R-LAY-6 | Secrets and local credential files are gitignored; example env documents variable names only |
| R-LAY-7 | `lib/` holds thin shared helpers required by modules; modules must not duplicate that logic |

### 5.2 Orchestrator (`scripts/acs-setup.sh`)

| ID | Requirement |
|----|-------------|
| R-ORCH-1 | Supports `--help`, `--status`, `--run` |
| R-ORCH-2 | `--status` without `--module` runs every module’s `--status` and prints aggregated output |
| R-ORCH-3 | `--status --module <id>` runs one module’s `--status` |
| R-ORCH-4 | `--run` without `--module` runs all modules in `modules.json` list order (GUI multi-select run still topological-sorts `dependsOn`) |
| R-ORCH-5 | `--run --module <id>` runs one module; does not auto-run dependencies unless documented in that module’s `--help` |
| R-ORCH-6 | `--dry-run` passed through to every module (see R-MOD-8) |
| R-ORCH-7 | Optional `--json` on `--status` emits machine-readable aggregate for the GUI |
| R-ORCH-8 | Exit code: `0` only if every invoked module succeeds; otherwise non-zero |
| R-ORCH-9 | Orchestrator **dispatches** to module scripts; it does not embed module logic and does not delegate to one giant script |

### 5.3 Module script contract (every `modules/<id>.sh`)

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
| R-MOD-9 | Modules that call **Central** must use **`lib/central.py`** (auth, TLS, file-first precedence). Modules that need **`oc`** must use **`lib/openshift.py`**: **`lab-credentials.json` is the source of truth**; `ensure_oc` maintains a **per-lab kubeconfig** under `.cache/kubeconfigs/` and must not rely on the user’s interactive `~/.kube/config`. Do not reimplement credential loading or env override rules in module code |

### 5.4 Aggregated status format

**TSV (default):** header row then one row per module:

```text
id	state	message
registries	ok	quay.io, registry.redhat.io, and us-central1-docker.pkg.dev integrations configured
slack-notifier	needs-run	Slack integration not configured
```

**JSON (`--json`):** array of objects `{ "id", "number", "label", "state", "message", "dependsOn" }` (`number` is the 1-based catalog position, not stored in `modules.json`).

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

**Purpose:** Configure RHACS image integrations needed for vulnerability scanning on the secured cluster. Reads Quay and `registry.redhat.io` credentials from the OpenShift cluster pull secret, and adds an anonymous public integration for Google Artifact Registry (`us-central1-docker.pkg.dev`) so `ms-demo` Online Boutique images can be scanned.

**Depends on:** none (Central credentials via `lib/central`; OpenShift via `lib/openshift` / `oc`)

**Status must verify:**

1. Central credentials authenticate (API token and/or admin password per `lib/central`)
2. `pull-secret` in `openshift-config` is readable via `oc`
3. `Public Quay.io` integration has robot credentials matching pull-secret `quay.io`
4. `registry.redhat.io` docker registry integration exists and matches pull-secret
5. Public docker integration for `us-central1-docker.pkg.dev` exists (anonymous; no pull-secret)

**Run must do:**

1. Read `quay.io` and `registry.redhat.io` credentials from the secured-cluster pull secret
2. Update `Public Quay.io` with `registryRobotCredentials` (replaces OAuth-only auth)
3. Create or update `registry.redhat.io` integration idempotently
4. Create or update `Public Google Artifact Registry (us-central1)` for `us-central1-docker.pkg.dev`
5. After creating/updating that Artifact Registry integration, best-effort rescan of unscanned images from that host
6. Test integrations when applying (not on dry-run)

**Acceptance:**

- `--status` is `ok` when Quay, `registry.redhat.io`, and Artifact Registry integrations are configured
- `--run` is idempotent on a configured lab
- Image scans for `quay.io/openshift-release-dev` and `us-central1-docker.pkg.dev/google-samples/...` images succeed after run

---

### M11 — `signature-integration` (ACS Cosign / Red Hat Public)

**Purpose:** Ensure Signature Integration **Red Hat Public** (Red Hat release key 3 Cosign public key), Inform Build+Deploy policy **Images must be signed by Red Hat Public**, and prime three signed images plus one unsigned contrast via `roxctl image scan` (no deploy).

**Depends on:** none in catalog. Central API auth; Central must be able to pull the primed registries (Quay / `registry.access.redhat.com`).

**Status / Run / Acceptance:**

- `--status` is `ok` when Red Hat Public matches the bundled PEM fingerprint, the Inform policy is present and linked, and all three signed primes report `VERIFIED` under that verifier
- `--run` is idempotent; creates/updates integration + policy; primes via `POST /v1/images/scan`; fails if a signed prime does not verify
- `--uninstall` removes the Inform policy only (leaves Red Hat Public)
- `--hard-delete` (module shell only): print inventory, require interactive `DELETE`, then remove policy + Red Hat Public. Does not modify Signature Integration named exactly `Red Hat`

Demo notes: [`modules/signature-integration-demo.md`](modules/signature-integration-demo.md).

---

### M2 — `compliance-operator` (Compliance Operator + scan schedule)

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

### M2b — `virt-vm-demo` (ACS guest vulnerabilities on OCP Virt)

**Purpose:** Install OpenShift Virtualization (VSOCK + KVM_EMULATION for infra labs), deploy two RHEL 9 VMs (`rhel9-1`, `rhel9-2`) in `acs-virt-demo` from the eng dnf-primed guest image with in-guest `roxagent`, and enable ACS `ROX_VIRTUAL_MACHINES` / short scraper poll so Central **Vulnerability Management → Virtual Machines** shows guest CVEs. Talk track: `modules/virt-vm-demo.md`.

**Depends on:** none (ACS already installed on the lab)

**Status must verify:** HyperConverged healthy; ACS flags on Central + SecuredCluster; both demo VMIs Running; Central reports CVE findings on both VMs in `acs-virt-demo`.

**Run must do:** Patch ACS CRs; install/ensure CNV; create pull secret + two VMs; install agent from Sensor image `/stackrox/bin/roxagent`; wait until both VMs have CVE findings (fail if timeout).

**Uninstall must do:** Delete project `acs-virt-demo` (CNV and ACS flags retained).

**Acceptance:** `--status` is `ok` when CNV is healthy, flags are set, both demo VMIs are Running, and both have CVE findings in Central.

---

### M3 — `ms-demo` (Mostmark microservices)

**Purpose:** Deploy the Mostmark microservices demo app in OpenShift project `ms-demo` for network/policy/violation demos.

**Depends on:** none

**Status must verify:** Project exists; workloads ready per module definition

**Run must do:** Create/update manifests in `ms-demo`; idempotent apply

**Acceptance:** App reachable or pods ready; `--status` reflects drift if someone deleted the project

---

### M4 — `init-demo` (Init-container Clean/Dirty/Blue/Red)

**Purpose:** Install the [ACS-init-container-test](https://github.com/boazmichaely/ACS-init-container-test) demo: four Deployments (`clean-app`, `dirty-app`, `blue-app`, `red-app`) in OpenShift project `acs-init-container-test`, plus three namespace-scoped Central `DEMO-Init-Test` policies from upstream. Shows Central scanning and policy evaluation on init containers.

**Depends on:** none

**Status must verify:** Project exists; all four Deployments present; `clean-app`/`dirty-app` ready (`blue-app`/`red-app` may stay `0/1` without privileged SCC - expected); three `DEMO-Init-Test: …` policies present; Status folds list active namespace violations (informational).

**Run must do:** Create project if needed; apply four upstream manifests from GitHub; wait for clean/dirty; upsert the three DEMO-named policies via Central API.

**Uninstall must do:** Delete the three DEMO policies; delete project `acs-init-container-test` and wait until gone.

**Acceptance:** `--status` is `ok` when workloads (with clean/dirty ready) and DEMO policies are present; drift if project or policies are removed.

---

### M5 — `users-part1-ocp` — Users Part 1 (OCP)

**Purpose:** Lead-in for the ACS console plugin visibility demo: HTPasswd users (adam/boaz/chris), IdP, and OpenShift project RBAC. Full walkthrough lives in `modules/users-part1-ocp-demo.md`. `users-part2-oauth` and `users-part3-acs` complete Central login and ACS mappings; the ACS console plugin must already be installed.

**Depends on:** none (demo walkthrough uses `ms-demo` / `init-demo` projects when those modules are installed; Part 1 itself does not require them)

**Status must verify:** IdP, users, and bindings match demo spec; Demo fold shows the walkthrough; Credentials fold lists fixed lab passwords

**Run must do:** Apply/regenerate HTPasswd secret, OAuth IdP `lab_htpasswd`, roles/bindings (adam cluster-admin; boaz admin on `ms-demo`; chris admin on `ms-demo` + `acs-init-container-test`)

**Acceptance:** Documented demo users can log in to OpenShift; personas match the demo script

---

### M6 — `users-part2-oauth` — Users Part 2 (OAuth)

**Purpose:** Configure Central to use OpenShift as an identity provider for UI login demos.

**Depends on:** `users-part1-ocp` (catalog; end-to-end login needs M5 users)

**Status must verify:** Central auth provider configured for OpenShift OAuth

**Run must do:** Apply Central/OpenShift OAuth integration per demo spec

**Acceptance:** Login to Central via OpenShift works for a demo user

---

### M7 — `users-part3-acs` — Users Part 3 (ACS)

**Purpose:** Map OpenShift logins adam, boaz, and chris to ACS roles and access scopes for Central. Adam becomes built-in Admin. Boaz and chris become Analysts (`boaz-in-acs`, `chris-in-acs`) with access scope limited to `ms-demo`. The OpenShift console Security plugin still follows OpenShift RBAC (Part 1); this module does not change that. Act 2 of the demo compares console vs ACS Central: boaz is aligned (both sides `ms-demo` only); chris is misaligned (OCP admin on `ms-demo` and `acs-init-container-test`, ACS only `ms-demo`). Full walkthrough lives in `modules/users-part1-ocp-demo.md`.

**Depends on:** `users-part2-oauth`

**Status must verify:** Access scope `ms-demo` exists with the expected namespace rule; roles `boaz-in-acs` and `chris-in-acs` use Analyst with that scope; OpenShift auth group rules map adam to Admin, boaz to `boaz-in-acs`, and chris to `chris-in-acs`

**Run must do:** Idempotent Central API reconcile for that scope, those roles, and those group rules (including the empty-key default `None` rule when missing)

**Acceptance:** After OpenShift login to Central, adam has Admin access; boaz and chris have Analyst access on `ms-demo`; chris has no useful ACS access on `acs-init-container-test` despite OpenShift admin there; console Security for those users still matches Part 1 OpenShift RBAC

---

### M8 — `slack-notifier` (Central → Slack)

**Purpose:** Configure Central’s Slack notifier so demo alerts land in Slack, and attach that notifier to policies stamped with category `DEMO`. Default target is shared RH-internal `#acs-demo-notifier`; labs may override notifier name, webhook, and channel link.

**Depends on:** none in catalog. Working Central API access via lab credentials. DEMO policies come from other modules (`init-demo`, `signature-integration`, …); re-run those first if policies lack category `DEMO`.

**Webhook resolution:** module flags (`--webhook` / `--name` / `--channel-url`) → lab-credentials override → [`config/slack-notifier.defaults.json`](config/slack-notifier.defaults.json)

**Status / Run / Acceptance:**

- `--status` is `ok` when the named Slack notifier exists in Central, `labelDefault` matches the resolved webhook, and every policy with category `DEMO` has this notifier attached; folds show webhook + channel URL plus each DEMO policy as wired or missing
- `--run` creates/updates via `POST`/`PUT /v1/notifiers`, **must** `POST /v1/notifiers/test` (fails if the test fails), posts a lab-context webhook ping, then attaches the notifier to all `DEMO` policies
- `--uninstall` detaches this notifier from `DEMO` policies (policies and category stay), then deletes only the resolved notifier name
- Demo notes: [`modules/slack-notifier-demo.md`](modules/slack-notifier-demo.md)
- Shared policy helper: [`lib/demo_policies.py`](lib/demo_policies.py)

---

### M9 — `splunk` (Splunk Operator + TA)

**Purpose:** Deploy Splunk Operator and RHACS Splunk TA so audit/violation events can flow to Splunk for SIEM demos.

**Depends on:** none

**Status must verify:** Splunk stack and TA integration healthy per module spec

**Run must do:** Delegate to `splunk-lab.sh` `install` (or equivalent); idempotent per wrapped script behavior

**Wrap:** Entrypoint finds `splunk-lab.sh` via `ACS_SPLUNK_LAB_SCRIPT` or documented default under `rhacs-splunk-ta-demo-skill`. Vendoring into this repo is optional follow-up, not required for M9 v1.

**Acceptance:** Events searchable in Splunk after demo traffic; `--status` reflects wrapped script health; clear message if script path or TA bundle missing

---

## 7. GUI requirements

The GUI is **required from the first deliverable** (module M1 `registries`). No module ships without corresponding GUI support for that module’s status, configuration, and run action.

**Look, feel, layout, and interaction:** [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) (PatternFly v5, wide column, module table, collapsibles, log pane).

| ID | Requirement |
|----|-------------|
| R-GUI-1 | `gui/` exists before M1 is considered done |
| R-GUI-2 | Reads `config/modules.json` for module list, order, labels, dependencies, and `statusComplexity` |
| R-GUI-2b | Status refresh probes installed modules one at a time in ascending `statusComplexity` (1-10), updating the UI after each; missing complexity defaults to 5 |
| R-GUI-3 | Shows per-module status (invokes orchestrator `--status --json` or equivalent API) |
| R-GUI-4 | Lab credentials form per [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) §3; persisted to `lab-credentials.json` |
| R-GUI-5 | For each shipped module: control to run that module (with confirmation when `--run` is destructive) |
| R-GUI-6 | Refresh status on demand and after a run completes; full refresh is progressive (per module, ordered by `statusComplexity`) |
| R-GUI-7 | Does not commit secrets; server-side gitignored storage preferred over browser localStorage for tokens |
| R-GUI-8 | GUI backend invokes `scripts/acs-setup.sh` (or module entrypoints directly with the same contract); GUI does not reimplement module logic |
| R-GUI-9 | New modules add GUI affordances in the **same PR/change** as the module script |
| R-GUI-10 | GUI server binds **`127.0.0.1` only**; no network exposure beyond the **user's** laptop |
| R-GUI-11 | Visual and UX requirements in **REQUIREMENTS-GUI.md** are part of GUI acceptance |

### 7.1 First deliverable (M1 + GUI)

Shipping M1 is not complete until all of the following work:

1. `config/modules.json` includes module `registries` as M1
2. `modules/registries.sh` meets R-MOD-* and M1 acceptance
3. `scripts/acs-setup.sh` can `--status` and `--run --module registries`
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
| D-1 | Local credentials file: path and JSON shape? | **Decided:** gitignored **`lab-credentials.json`** at repo root, schema **`config/lab-credentials.schema.json` v2** (`activeLabId` + `labs[]` with multi secured clusters). ACS Central and OpenShift are independent blocks per lab. Modules flatten the active lab. Env: `ACS_LAB_CREDENTIALS_FILE`, `ACS_CENTRAL_ENDPOINT`, `ROX_API_TOKEN`/`TOKEN`, `ACS_INSECURE_SKIP_TLS_VERIFY`. |
| D-2 | M3 `--run`: verify-only or also register/fix secured cluster? | **N/A:** `secured-cluster` removed from module list; registration is a manual prerequisite (§3.1 E-5). |
| D-3 | GUI stack and how the local server is started | **Decided:** Python backend (FastAPI) + HTML/JS frontend; **`./serve.sh`** at repo root (wraps `gui/serve.sh`); REST API shells out to `scripts/acs-setup.sh`. Bind **`127.0.0.1` only**; port **8765**. No auth (solo laptop use). |
| D-4 | M10: reimplement Splunk deploy or call existing `splunk-lab.sh`? | **Decided:** **Wrap first** — `modules/10-splunk.sh` delegates to `splunk-lab.sh` (default path documented; override via env e.g. `ACS_SPLUNK_LAB_SCRIPT`). Map module `--status` / `--run` to script `--status` / `install`. **Optional later:** vendor script into this repo if path coupling or sync becomes annoying. TA `.tgz` remains **user-supplied**; status reports if missing. |
| D-5 | Per-module `--dry-run` mandatory for all modules or only destructive ones? | **Decided:** **All modules** implement `--dry-run` for consistency. Verify/read-only modules describe checks and examination context only; mutating modules describe planned changes without applying. GUI may expose dry-run where useful. |

---

## 10. Review checklist

Before implementation starts, confirm:

- [ ] Section 3 (environment) matches your real lab
- [ ] M1 `registries` acceptance matches lab workflow (pull secret → Central integrations)
- [ ] Module catalog in `config/modules.json` matches what we intend to ship
- [x] Open decisions in section 9 are answered
- [ ] First deliverable accepted: M1 + GUI per §7.1
