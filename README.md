# ACS demo setup

Repeatable automation to **prepare a RHACS demo lab** after Central and a secured cluster are already running: credentials, `roxctl`, sample apps, users, OAuth, integrations, compliance, Splunk — driven primarily through a **web GUI**.

| Doc | Contents |
|-----|----------|
| [REQUIREMENTS.md](REQUIREMENTS.md) | Problem, lab assumptions, modules, CLI contract, functional GUI behavior |
| [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) | **Look and feel** — PatternFly v5, layout, credentials panel, module table, status, log |

**Repo:** https://github.com/boazmichaely/ACS-demo-setup (private)

## Layout

| Piece | Role |
|-------|------|
| `./serve.sh` | **Primary entrypoint** — starts the GUI |
| `gui/` | Web UI (FastAPI + static front end) |
| `scripts/acs-setup.sh` | CLI orchestrator + GUI backend (`--status`, `--run`, `--help`) |
| `config/modules.json` | Module registry |
| `config/lab-credentials.schema.json` | Credentials file shape (see `lab-credentials.example.json`) |
| `modules/NN-<id>.sh` | Module entrypoints (bash/jq; Python where it helps) |

**Lab prerequisites:** OpenShift with `oc`, RHACS Operator installed, Central and secured cluster already up. See [REQUIREMENTS.md §3](REQUIREMENTS.md).

**Secrets:** gitignored `lab-credentials.json` at the repo root. Shape: [config/lab-credentials.example.json](config/lab-credentials.example.json). Override path with `ACS_LAB_CREDENTIALS_FILE`. Edit via the GUI **Lab credentials** panel or by hand.

## Run the GUI

```bash
cd ~/code/acs-demo-setup
./serve.sh
./serve.sh --help
```

Opens on http://127.0.0.1:8765 by default. If that port is busy, the next free port is used - use the URL printed at startup.

## CLI

```bash
./scripts/acs-setup.sh --help
./scripts/acs-setup.sh --status --json
./scripts/acs-setup.sh --run --module registries
```

## Status

| Area | State |
|------|--------|
| Requirements | Approved ([§9](REQUIREMENTS.md)) |
| GUI | PatternFly v5 per [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) |
| Modules | `registries`, `compliance-operator` implemented; others listed in `config/modules.json` |
