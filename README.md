# ACS demo setup

This tool helps you finish preparing an RHACS (Red Hat Advanced Cluster Security) demo lab **after** Central and a secured cluster are already installed and running. It handles the repeatable follow-on work: storing lab credentials, checking what is already configured, and running setup steps (modules) such as registry integrations or the Compliance Operator.

You mostly use the **web GUI**. The CLI is available for scripting and is what the GUI calls under the hood.

Private repo: https://github.com/boazmichaely/ACS-demo-setup

## Run the GUI

```bash
cd ~/code/acs-demo-setup
./serve.sh
```

By default the UI is at http://127.0.0.1:8765. If that port is already in use, the script picks the next free port. Use the URL printed in the terminal.

## Lab credentials

Put secrets in `lab-credentials.json` at the repo root. That file is gitignored. You can edit it in the GUI (**Lab credentials** panel) or by hand. For the JSON shape, see [config/lab-credentials.example.json](config/lab-credentials.example.json).

You can point at a different file with `ACS_LAB_CREDENTIALS_FILE` if you want.

When a module needs OpenShift (`oc`), it does **not** use your normal `~/.kube/config`. It uses a per-lab kubeconfig derived from `lab-credentials.json`, stored under `.cache/kubeconfigs/`.

```bash
./scripts/acs-setup.sh --oc-status    # Is oc ready for the active lab?
./scripts/acs-setup.sh --oc-login     # Create or refresh that kubeconfig (add --force to redo login)
```

## CLI

Useful when you are not in the browser:

```bash
./scripts/acs-setup.sh --help
./scripts/acs-setup.sh --status --json
./scripts/acs-setup.sh --run --module registries
```

## Repo layout

| Path | Role |
|------|------|
| `./serve.sh` | Starts the GUI |
| `gui/` | Web UI (FastAPI + static pages) |
| `scripts/acs-setup.sh` | Orchestrator: status, run, and oc helpers |
| `config/modules.json` | List of modules (display order, labels, dependencies) |
| `modules/<id>.sh` | One shell entrypoint per module |
| `templates/module-skeleton.sh` | Copy-paste starting point for a new module |
| `templates/module-helper.py` | Optional Python helper template (Central / heavy JSON) |
| `lib/` | Shared helpers for Central API and OpenShift login |

Today, `registries` and `compliance-operator` have real scripts. Other modules can appear in `modules.json` before their script exists; in the GUI those rows show as **not installed**.

## Adding a module

See [ADDING-A-MODULE.md](ADDING-A-MODULE.md) for the full walkthrough: catalog entry, `--status` contract, and the Status folds presentation language (tab-separated values summary line plus `ACS_SECTIONS_JSON`).

In the running GUI, the masthead **?** menu opens this README, the module guide, and an interactive Status folds field map.

Each module should also explain itself when you run `./modules/<id>.sh --help` (what it does, what it needs, what it changes).
