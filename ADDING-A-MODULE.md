# What is a module

A **module** is used to perform one setup step for the demo lab. It is a shell/Python program that can do anything you like. The GUI acts as an orchestrator and renderer that talks to modules using the hooks listed below.

- **Triggers:** The module is triggered to **run** (install) or **uninstall**, both with a **dry-run** option.
- **Output:** The module provides structured **status** info for the GUI to render.

Template files are provided to start you off, and a common Python library provides a unified way to use admin credentials for the associated Central and OpenShift clusters in your lab.

| Flag | What the module must do (Module Contract) |
|------|-------------------------------------------|
| `--help` | Explain the purpose of the module, what it depends on, which environment variables it needs, and what `--run` and `--uninstall` change. |
| `--status` | Report whether this step is already done. Print both a short summary line and detailed Status folds (described later). Both outputs are required. |
| `--run` | Apply the step. Running it again when nothing has drifted must still succeed. |
| `--run --dry-run` | Describe what `--run` would change, without changing the cluster or Central. |
| `--uninstall` | Remove what this module created, or refuse with a clear error. |
| `--uninstall --dry-run` | Describe what `--uninstall` would remove, or refuse the same way. |

The rest of this page is the recipe: catalog row, skeleton, status shape, credentials, then smoke test.

## What you must create

A module shows up in the GUI and the CLI orchestrator only when both exist:

1. An executable script at `modules/<id>.sh`.
2. A matching row in `config/modules.json`.

The orchestrator reads the catalog, then runs `modules/<id>.sh`. A catalog row without a script still appears as **not installed** (handy as a placeholder). A script with no catalog row is invisible.

## Fast path

```bash
# 1. Choose a short kebab-case id, for example my-feature
ID=my-feature

# 2. Copy the shell skeleton (always required)
cp templates/module-skeleton.sh "modules/${ID}.sh"
chmod +x "modules/${ID}.sh"

# 3. Edit the copy: set MODULE_ID, fill in usage() and the do_* functions.
#    Search for TODO. The skeleton’s emit_status_sections() is the teaching
#    example for Status folds; replace it with real lab checks when ready.

# 4. Add a row to config/modules.json (see “Catalog entry” below).
#    Without that row, the module will not appear in the GUI.

# 5. Smoke-test from the terminal
./modules/${ID}.sh --help
./modules/${ID}.sh --status
./scripts/acs-setup.sh --status --module "${ID}"
```

Keep `templates/module-skeleton.sh` open while you write `emit_status_sections()`. You can also use the [ms-demo](https://github.com/boazmichaely/ACS-demo-setup/blob/main/modules/ms-demo.sh) module as a lightweight example. In the GUI, kebab **Help** shows the same text as `--help`.

## Catalog entry

Add one object to the `modules` array in `config/modules.json`. Array order is GUI order and the default full-install order. If this module must run after another, put that module’s `id` in `dependsOn`.

```json
{
  "id": "my-feature",
  "label": "Short description for the Description column",
  "dependsOn": []
}
```

- `id` is the module key. It must match `modules/<id>.sh`, CLI `--module`, other modules’ `dependsOn`, and the **Module** column. Do not repeat the id inside `label`.
- `label` is Description-column text only. Plain sentence or phrase, capitalized. Not `id - description`.
- Prefer `my-feature.sh` over `07-my-feature.sh`.

## Optional Python helper

Most modules stay one shell script. Put simple `oc` checks in the `do_*` functions.

Add Python when bash is a poor fit - usually Central HTTP or heavy JSON:

```bash
cp templates/module-helper.py modules/my_feature.py
```

In `modules/my-feature.sh`, wire the helper block from the skeleton and set `HELPER` to that path. Keep `--help` and flag parsing in the shell script. Put the heavy work in the `.py` file.

If you are unsure, stay in bash until it hurts.

## Status output

`--status` must print two machine-readable results. Order does not matter. Extra log lines on stdout or stderr are fine.

1. A **summary line** (TSV): badge + one sentence.
2. Exactly one **Status folds** line: `ACS_SECTIONS_JSON=...` for the detailed Status card.

Missing folds → Status shows “No section details.” Missing or bad TSV → no sensible badge or header message.

### Summary line (TSV)

**TSV** means fields separated by a single tab, not commas or spaces. Three fields: module `id`, `state`, short human `message`.

```text
my-feature	ok	short human summary
```

```bash
printf '%s\t%s\t%s\n' "$MODULE_ID" "ok" "short human summary"
```

The orchestrator keeps the last line with at least three tab-separated fields.

| State | Meaning |
|-------|---------|
| `ok` | This step is already in good shape. |
| `needs-run` | The lab is reachable, but this step is missing or has drifted. |
| `error` | The module cannot decide (bad credentials, API down, and so on). |

That line fills the Modules table badge/message and the Status module header. It does not fill the grouped folds underneath - those come from Status folds.

### Status folds (`ACS_SECTIONS_JSON`)

Your module does not draw PatternFly widgets. It emits structured facts; the GUI turns them into grouped, expandable rows.

One `--status` run feeds the CLI (`acs-setup.sh --status --json`), the Modules table (TSV), and the Status card (`ACS_SECTIONS_JSON`).

**Why folds exist:** a TSV line is enough for one badge and one sentence. It is not enough when a step has many independent checks. Folds are a tiny report format (`prose` or `json` bodies only) that bash can emit with `jq` (or Python with `json.dumps`). Presentation stays in the GUI.

#### How it looks

The screenshot below is the skeleton’s teaching folds after a Status refresh. Groups on the left with expand-all; folds indented under each group; optional badge and right-hand summary.

![Status folds from the module skeleton: four groups with indented folds, optional badges, and right-hand summaries](docs/images/status-sections-example.png)

Interactive field map (same CSS as live Status; each piece labeled with the JSON field name):

- GUI **?** menu → **Status folds field map**
- Or [gui/static/status-sections-map.html](gui/static/status-sections-map.html) at [http://127.0.0.1:8765/static/status-sections-map.html](http://127.0.0.1:8765/static/status-sections-map.html) (use the port `./serve.sh` printed if different)

#### Wire format

One line: `ACS_SECTIONS_JSON=` plus compact JSON. Build with `jq` or `json.dumps` - do not hand-escape a giant string in `printf`.

```bash
printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
```

Root object:

```json
{ "sections": [ ]
}
```

Each element of `sections` is one fold:

| Field | Required? | Role in the UI |
|-------|-----------|----------------|
| `group` | Recommended | Heading above a batch of folds. Same string = same heading. Group row gets expand-all for that batch. |
| `title` | Yes | Main label; click to expand. |
| `summary` | No | Muted hint on the right. |
| `tag` / `tagLabel` | No | Badge left of `title`. `tag` sets color (`ok`/`ready` green, `error`/`fail` red, else warn). `tagLabel` is visible text (falls back to `tag`). |
| `body` | Yes | Expanded content. |
| `bodyFormat` | No | `prose` (default) or `json`. |

#### Skeleton example

Copy `emit_status_sections()` from `templates/module-skeleton.sh`, then replace the sample data. Short version:

```bash
emit_status_sections() {
  local sections_json prose_multiline
  prose_multiline="$(cat <<'EOF'
Body of a multi-line prose blob.
Each newline becomes a line break in the GUI.
EOF
  )"
  sections_json="$(
    jq -nc --arg prose_multi "$prose_multiline" '{
      sections: [
        {
          group: "Group 1 header. e.g. Overview",
          title: "Title of first blob. e.g. Installed components",
          summary: "(optional) right hand side info (1/1 ready)",
          body: "Body of the first blob...",
          bodyFormat: "prose"
        },
        {
          group: "Group 2 header. e.g. Notes",
          title: "Title of second blob. e.g. Multi-line prose",
          summary: "(optional) right hand side info",
          body: $prose_multi,
          bodyFormat: "prose"
        }
      ]
    }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  emit_status_sections
  printf '%s\tok\tshort human summary\n' "$MODULE_ID"
}
```

Prefer `jq --arg` / `--argjson` over interpolating shell into the `jq` program. Large real example: `scripts/compliance_co_overview.py`.

## Run, dry-run, and uninstall

- `--run` should leave the lab in the desired state. Safe to run twice when nothing drifted.
- `--run --dry-run` describes the plan, exits 0, changes nothing.
- `--uninstall` removes what this module owns. Prefer cleanup that is safe when already gone.
- If uninstall is not safe or not defined, refuse: clear message, TSV `error`, non-zero exit. Do not pretend success.
- Orchestrator uninstall always needs `--module <id>` (no uninstall-everything CLI).
- Hard failure: non-zero exit and a clear message on stderr.

## Credentials and auth

Do not invent your own login path. The lab stores credentials in gitignored `lab-credentials.json` (edit them in the GUI). Modules should read that file through the shared libraries so every module sees the **active lab** the same way.

There are two different “doors”:

| Door | Library | What it is for |
|------|---------|----------------|
| **Central** (RHACS API) | `lib/central.py` | HTTP calls to Central (integrations, policies, scan schedules, …) |
| **OpenShift** (`oc`) | `lib/openshift.py` | Cluster objects on the OpenShift the lab marked **OpenShift for modules** |

OpenShift modules do **not** use your interactive `~/.kube/config`.  Instead, `lib/openshift.py` logs in with the lab’s OpenShift admin fields and writes a per-lab kubeconfig under `.cache/`. In the GUI, pick which secured cluster is **OpenShift for modules** when a lab has more than one. If the lab has no secured clusters, OpenShift helpers fall back to Central’s OpenShift block (Central-on-OCP labs).

Env fallbacks (`ROX_API_TOKEN`, `ACS_CENTRAL_ENDPOINT`, and friends) only fill empty file fields. Prefer the credentials file.

### Minimal OpenShift example (shell)

Same pattern as `ms-demo`: ask Python for a kubeconfig path, export it, then run `oc`.

```bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT}/gui/.venv/bin/python"
# or: PYTHON="$(command -v python3)"

ensure_oc() {
  local kc
  kc="$(cd "$ROOT" && "$PYTHON" -m lib.openshift login --print-kubeconfig)" || return 1
  export KUBECONFIG="$kc"
}

do_run() {
  ensure_oc || return 1
  oc get project ms-demo >/dev/null 2>&1 || oc new-project ms-demo
  # … oc apply …
}
```

Call `ensure_oc` in the current shell (not inside `$(...)`), or `KUBECONFIG` will not stick for later `oc` commands.

### Minimal Central example (Python helper)

```python
from lib.central import central_connection, central_request, load_lab_credentials

creds = load_lab_credentials()
base, authorization = central_connection(creds)
code, body = central_request(
    base, authorization, "GET", "/v1/imageintegrations", creds=creds
)
```

`central_connection` resolves console URL + `Authorization` (API token or admin password per the lab’s `authPreference`). Use that instead of reading tokens by hand.

### Style tip

If the RHACS UI configures something in Central, prefer the Central API. Avoid applying lower-level cluster objects that bypass Central when Central already owns that feature (compliance scan schedules are the usual example).

## Verify end-to-end

```bash
./scripts/acs-setup.sh --status --module my-feature
./scripts/acs-setup.sh --run --module my-feature --dry-run
./scripts/acs-setup.sh --run --module my-feature
./scripts/acs-setup.sh --uninstall --module my-feature --dry-run
./serve.sh
```

In the GUI you should see an enabled Modules row, sensible Status after refresh, Run / Uninstall / Help on the row menu, and Dry run applying to Run and Uninstall.

## Contributing

Open a pull request with the `config/modules.json` entry and `modules/<id>.sh`. Include a helper `.py` only if you added one. There is no plugin store and no auto-discovery outside the catalog. Private experiments can use the same layout locally; share them with a PR when they help beyond your lab.
