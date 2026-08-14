# ACS demo setup

Repeatable automation to **prepare a RHACS demo lab** after Central and a secured cluster are already running: credentials, `roxctl`, sample apps, users, OAuth, integrations, compliance, Splunk — driven primarily through a **web GUI** from the first module on.

**Start here:** [REQUIREMENTS.md](REQUIREMENTS.md) — problem statement, environment assumptions, system behavior, and per-module acceptance criteria.

This repo is greenfield. Implementation follows approved requirements, not the other way around.

## Quick orientation

| Piece | Role |
|-------|------|
| `gui/` | Primary interface: status, credentials, run per module (ships with M1) |
| `acs-setup.sh` | CLI entrypoint for automation and GUI backend: `--status`, `--run`, `--help` |
| `config/modules.json` | Module registry (ids, order, dependencies) |
| `modules/NN-<id>.sh` | Module entrypoint (bash/jq; Python where it helps) |

**Lab prerequisites:** OpenShift with `oc` access, RHACS operator installed, Central and secured cluster already up. See REQUIREMENTS §3.

## Status

GUI v0 shipped (orchestrator stub; module scripts not yet implemented). **M1 not implemented yet.**

**Secrets:** `central-credentials.json` and `*.local.env` are gitignored. Copy `acs-demo-setup.local.env.example` for optional env overrides.

## Run the GUI

```bash
cd ~/code/ACS-demo-setup
./gui/serve.sh
```

Open http://127.0.0.1:8765
