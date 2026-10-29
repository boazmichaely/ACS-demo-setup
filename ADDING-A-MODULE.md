# How to add a module

A **module** is one step in preparing the demo lab. The GUI and CLI treat every module the same way:

| Flag | What it should do |
|------|-------------------|
| `--help` | Explain the purpose, what it depends on, required env vars, and side effects |
| `--status` | Check whether the lab already has this step done |
| `--run` | Apply the step (safe to run again if nothing changed) |
| `--run --dry-run` | Print what would change, without changing anything |
| `--uninstall` | Remove what this module created (or refuse with a clear error) |
| `--uninstall --dry-run` | Print what uninstall would remove (or refuse the same way) |

## Fast path (copy the skeleton)

```bash
# 1. Pick a short id (kebab-case), e.g. my-feature
ID=my-feature

# 2. Copy the shell skeleton (this is always required)
cp templates/module-skeleton.sh "modules/${ID}.sh"
chmod +x "modules/${ID}.sh"

# 3. Edit the copy: set MODULE_ID, fill in usage() and the do_* functions
#    Search for TODO in modules/${ID}.sh

# 4. REQUIRED: add a row to config/modules.json (see "Catalog entry" below).
#    Without that file entry, the GUI and orchestrator will not list the module.
#    Edit: config/modules.json  →  modules[] array  →  { "id", "label", "dependsOn" }

# 5. Try it
./modules/${ID}.sh --help
./modules/${ID}.sh --status
./scripts/acs-setup.sh --status --module "${ID}"
```

You need **two** things for a module to show up: the script `modules/<id>.sh`, and a catalog row in `config/modules.json`. The orchestrator only executes `modules/<id>.sh`, but it discovers modules only from `config/modules.json`.

## When do you also need a Python file?

**Most modules start as that one shell script.** Put `oc`, simple checks, and straightforward logic in the `do_*` functions inside `modules/<id>.sh`.

**Add a Python helper only when the work is awkward in bash** - typically calling the Central HTTP API or parsing a lot of JSON. Then:

```bash
# id my-feature → helper name uses underscores
cp templates/module-helper.py modules/my_feature.py
```

Open `modules/my-feature.sh` and uncomment the “Optional: call a Python helper” block in the skeleton. Point `HELPER` at `modules/my_feature.py`. Implement commands in the `.py` file; keep `--help` and flag parsing in the `.sh` file.

If you are not sure: stay in bash until it hurts, then add the helper.

## Catalog entry (`config/modules.json`)

Add an object to the `modules` array. **List order** is the GUI order and the default full-run order. If this module must run after another, name that module’s id in `dependsOn`.

```json
{
  "id": "my-feature",
  "label": "Short description for the Description column",
  "dependsOn": []
}
```

- `id` is the module key: script name `modules/<id>.sh`, CLI `--module`, `dependsOn`, and the **Module** column in the GUI. Do not repeat it inside `label`.
- `label` is human text only (Description column). Plain sentence or phrase, capitalized at the start - no `id - …` prefix.
- Do not put a number prefix on the filename (`07-my-feature.sh` is wrong)
- A catalog row with no executable script shows as **not installed** in the GUI (useful for placeholders)

## Status output (required: summary line **and** Status folds)

`--status` must print **two** things (order does not matter; extra log lines are OK):

1. **Summary line** - one tab-separated row. The orchestrator keeps the last row with at least three fields. This drives the Modules table badge and the Status fold header.
2. **Status folds** - exactly one machine line starting with `ACS_SECTIONS_JSON=`. The orchestrator attaches `sections` to `--status --json`; the GUI renders each item as a fold under that module. **This is mandatory.** Without it the Status card shows “No section details.”

### Summary line

```text
my-feature	ok	short human summary
```

| State | Meaning |
|-------|---------|
| `ok` | This step is already in good shape |
| `needs-run` | The lab is reachable, but this step is missing or drifted |
| `error` | You cannot tell (bad credentials, API down, and so on) |

### Status folds (`ACS_SECTIONS_JSON`)

Print **one** line: `ACS_SECTIONS_JSON=` plus compact JSON. Build that JSON with `jq` so the structure stays readable (do not hand-escape a giant string inside `printf`).

Pattern from the skeleton (`emit_status_sections` + summary line):

```bash
emit_status_sections() {
  local sections_json body
  body="Longer detail for the expanded fold."
  sections_json="$(
    jq -nc --arg body "$body" '{
      sections: [
        {
          group: "Overview",
          title: "Example check",
          summary: "looks fine",
          body: $body,
          bodyFormat: "prose"
        },
        {
          group: "Overview",
          title: "Config snippet",
          tag: "ok",
          tagLabel: "ready",
          summary: "matched",
          body: { key: "value" },
          bodyFormat: "json"
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

`jq` is already required by the orchestrator. Keep this pattern when you replace the TODOs.

**Visual map (open in the GUI server):** [`gui/static/status-sections-map.html`](gui/static/status-sections-map.html)  
→ http://127.0.0.1:8765/static/status-sections-map.html

```text
Status card
└─ Module fold header  ← from TSV summary line (not from sections[])
   │    [id]   [state badge]   [message]
   │
   └─ Body
      ├─ group                  ← uppercase heading; new heading only when group changes
      │    └─ fold (closed row)
      │         [tagLabel]  title ................ summary
      │         └─ (expanded) body
      │              bodyFormat "prose" → normal text
      │              bodyFormat "json"  → monospace pretty-print
      └─ group (next batch) …
```

| Field | Required? | What it is in the UI |
|-------|-----------|----------------------|
| `group` | recommended | Heading above a batch of folds. Same string keeps items under one heading; a new value starts a new heading. |
| `title` | yes | Main label on the fold row (what you click). |
| `summary` | no | Muted hint on the right of that row. |
| `tag` / `tagLabel` | no | Badge left of `title`. `tag` sets color (`ok`/`ready`, `error`/`fail`, else warn); `tagLabel` is the visible text. |
| `body` | yes | Content inside the expanded fold. |
| `bodyFormat` | no | `prose` (default): normal text. `json`: pretty-printed code block (object/array or JSON string). |

Richer multi-fold example: Compliance Operator (`scripts/compliance_co_overview.py`).

## Run, dry-run, and uninstall

- `--run` should leave the lab in the desired state. Running it again when nothing drifted should still succeed.
- `--dry-run` (with `--run`) should describe the plan and exit 0 without changing the cluster or Central.
- `--uninstall` should remove what this module owns. Prefer idempotent cleanup when already absent.
- If uninstall is not safe or not defined, **refuse**: print a clear message, emit a status line with state `error`, and exit non-zero. Do not pretend success.
- Orchestrator uninstall always requires `--module <id>` (no bulk uninstall of every module from the CLI).
- On hard failure, exit non-zero and print a clear message on stderr.

## Credentials and ACS style

Do not invent a second credential path:

- Central → `lib/central.py`
- OpenShift → `lib/openshift.py` (uses `lab-credentials.json`, not `~/.kube/config`)

If the RHACS UI configures something in Central, prefer the Central API. Avoid applying lower-level cluster objects that bypass Central when Central already owns that feature (compliance scan schedules are the usual example).

## Verify end-to-end

```bash
./scripts/acs-setup.sh --status --module my-feature
./scripts/acs-setup.sh --run --module my-feature --dry-run
./scripts/acs-setup.sh --run --module my-feature
./scripts/acs-setup.sh --uninstall --module my-feature --dry-run
./serve.sh
```

In the GUI you should see an enabled row, a sensible status after refresh, and Run / Uninstall from the row menu (the Dry run toggle applies to both).

## Contributing

Open a PR with the `modules.json` entry and `modules/<id>.sh` (plus a helper `.py` only if you added one). There is no plugin store and no auto-discovery of scripts outside the catalog. Private experiments can use the same layout on your machine; share them with a PR when they are useful beyond your lab.
