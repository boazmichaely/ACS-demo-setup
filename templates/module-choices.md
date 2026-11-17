# ADVANCED — use this when your module has multiple choices

Most modules do **not** need this. Start from [`module-skeleton.sh`](module-skeleton.sh) and [`module-helper.py`](module-helper.py) and stay on the simple path.

## What this is (and is not)

**Is:** extra selectable flags *your module invents* (variants / options), for example `--format CEF|LEGACY`, `--name`, or `--webhook`.

**Is not:** multi-plane (`--plane`) or multi secured-cluster (`--secured-cluster-id` / `SC_IDS`). Those already live in the simple skeleton. Do not add this recipe only because the module has more than one plane or SC.

Real modules that use this pattern: [`modules/slack-notifier.sh`](../modules/slack-notifier.sh), [`modules/users-part3-acs.sh`](../modules/users-part3-acs.sh), [`modules/syslog-notifier.sh`](../modules/syslog-notifier.sh) (`--format`).

Prefer CLI flags over module-specific environment variables for choices. Add only the flags you need (do not copy every example below).

## Shell (`modules/<id>.sh`)

Copy these pieces into the live script from the skeleton. Replace the simple `run_helper` if you already wired one - do not stack both.

### 1) Near the top (with `MODULE_ID` / `SC_IDS`)

```bash
EXTRA_ARGS=()
```

### 2) Document the flags in `usage()` under `## Flags`

### 3) In `main()`'s `case`, append to `EXTRA_ARGS`

Minimal example (one choice flag). Add more flags the same way only if needed:

```bash
--format)
  shift
  [[ $# -gt 0 ]] || { echo "$(basename "$0"): --format needs a value" >&2; exit 1; }
  EXTRA_ARGS+=(--format "$1")
  ;;
```

### 4) Wire the Python helper (bash 3.2-safe empty-array expand)

macOS `/bin/bash` + `set -u`: empty `"${EXTRA_ARGS[@]}"` is unbound. Use a length guard:

```bash
HELPER="${ROOT}/modules/my_feature.py"
PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi
run_helper() {
  if ((${#EXTRA_ARGS[@]})); then
    "$PYTHON" "$HELPER" "${EXTRA_ARGS[@]}" "$@"
  else
    "$PYTHON" "$HELPER" "$@"
  fi
}
```

Then call from `do_status` / `do_run` / `do_uninstall`, for example:

```bash
run_helper status --cli
run_helper run --cli
run_helper uninstall --cli
```

(Uninstall may stay in the shell until Central cleanup needs the helper; see the skeleton comment block.)

## Python helper (`modules/<id_with_underscores>.py`)

When the shell passes choice flags **before** the subcommand:

```text
python modules/my_feature.py --format CEF status --cli
```

declare those flags on the **parent** parser (not only on subcommands). Minimal example:

```python
parser.add_argument(
    "--format",
    choices=("CEF", "LEGACY"),
    default="CEF",
    help="Message format variant",
)
```

Read `args.format` inside `cmd_status` / `cmd_run`. Prefer `choices=` when the set is closed. Keep defaults so a bare `status` / `run` still works. Add further parent flags (`--name`, `--webhook`, …) only when the module needs them.
