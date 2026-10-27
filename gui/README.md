# GUI

Local web UI for ACS demo setup. Binds **127.0.0.1:8765** only.

**Design:** [REQUIREMENTS-GUI.md](../REQUIREMENTS-GUI.md) (PatternFly v5).

## Start

From the repo root (preferred):

```bash
./serve.sh
./serve.sh --help
```

Equivalent: `./gui/serve.sh`. Default http://127.0.0.1:8765; if busy, the next free port is chosen and printed.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Server up |
| GET | `/api/modules` | Module registry |
| GET | `/api/status` | Orchestrator `--status --json` |
| GET/POST | `/api/credentials` | Read/save `lab-credentials.json` (v2: `activeLabId` + `labs[]`) |
| POST | `/api/credentials/active-lab` | Set `activeLabId` (`{ "labId": "…" }`); writes a `lab-switch` disk-log marker |

Lab switch updates which Central/OpenShift credentials modules read. OpenShift access for modules uses **per-lab kubeconfigs** derived from `lab-credentials.json`. Troubleshoot with `./scripts/acs-setup.sh --oc-status` / `--oc-login` (see repo [README](../README.md)). The interactive `~/.kube/config` is not the source of truth.
| GET | `/api/log` | Today's tee'd run log text (`logs/gui-YYYY-MM-DD.log`) |
| POST | `/api/log/page-load` | Append a `page-load` timestamp divider (hard refresh / load) |
| POST | `/api/run/{id}?dry_run=true` | Orchestrator `--run` (streamed to the browser and tee'd to today's log) |

The backend shells out to `scripts/acs-setup.sh`; it does not embed module logic. Run output is tee'd under gitignored `logs/` (3 calendar-day rotation). The Log pane is a session console (cleared on hard refresh); use the tee'd files for history.
