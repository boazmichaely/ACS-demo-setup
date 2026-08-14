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
| `gui/` | Primary interface — [REQUIREMENTS-GUI.md](REQUIREMENTS-GUI.md) |
| `acs-setup.sh` | CLI + GUI backend (`--status`, `--run`, `--help`) |
| `config/modules.json` | Module registry |
| `modules/NN-<id>.sh` | Module entrypoints (bash/jq; Python where it helps) |

**Lab prerequisites:** OpenShift with `oc`, RHACS operator installed, Central and secured cluster already up. See [REQUIREMENTS.md §3](REQUIREMENTS.md).

**Secrets:** `central-credentials.json` and `*.local.env` are gitignored. Copy [acs-demo-setup.local.env.example](acs-demo-setup.local.env.example) for optional env overrides.

## Run the GUI

```bash
cd ~/code/ACS-demo-setup
./gui/serve.sh
```

Open http://127.0.0.1:8765

## Status

| Area | State |
|------|--------|
| Requirements | Approved ([§9](REQUIREMENTS.md)) |
| GUI backend | FastAPI stub — shells out to `acs-setup.sh` |
| GUI look/feel | **Not yet** PatternFly — see [REQUIREMENTS-GUI.md §10](REQUIREMENTS-GUI.md) |
| Module scripts | Not implemented (M1 next) |
