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

# 4. Register it in config/modules.json (see below)

# 5. Try it
./modules/${ID}.sh --help
./modules/${ID}.sh --status
./scripts/acs-setup.sh --status --module "${ID}"
```

The orchestrator only runs `modules/<id>.sh`. That file is the module.

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
  "label": "my-feature - short description for the table",
  "dependsOn": []
}
```

- `id` must match the script name: `modules/<id>.sh`
- Do not put a number prefix on the filename (`07-my-feature.sh` is wrong)
- A catalog row with no executable script shows as **not installed** in the GUI (useful for placeholders)

## Status output

`--status` must print **one** tab-separated line like this (extra log lines are OK; the orchestrator keeps the last matching row):

```text
my-feature	ok	short human summary
```

| State | Meaning |
|-------|---------|
| `ok` | This step is already in good shape |
| `needs-run` | The lab is reachable, but this step is missing or drifted |
| `error` | You cannot tell (bad credentials, API down, and so on) |

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
