# GUI

Local web UI for ACS demo setup. Binds **127.0.0.1:8765** only.

## Start

```bash
./gui/serve.sh
```

Open http://127.0.0.1:8765

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Server up |
| GET | `/api/modules` | Module registry |
| GET | `/api/status` | Orchestrator `--status --json` |
| GET/POST | `/api/credentials` | Read/save `central-credentials.json` |
| POST | `/api/run/{id}?dry_run=true` | Orchestrator `--run` |

The backend shells out to `acs-setup.sh` at repo root; it does not embed module logic.
