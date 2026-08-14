"""ACS demo setup GUI — local server on 127.0.0.1 only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = Path(__file__).resolve().parent
MODULES_JSON = REPO_ROOT / "config" / "modules.json"
CREDENTIALS_PATH = REPO_ROOT / "central-credentials.json"
ACS_SETUP = REPO_ROOT / "acs-setup.sh"

HOST = "127.0.0.1"
PORT = 8765

app = FastAPI(title="ACS Demo Setup", version="0.1.0")


class CredentialsIn(BaseModel):
    endpoint: str = ""
    token: str = Field(default="", description="Leave blank to keep existing token")


class RunResult(BaseModel):
    ok: bool
    exit_code: int
    stdout: str
    stderr: str


def run_acs_setup(*args: str) -> subprocess.CompletedProcess[str]:
    if not ACS_SETUP.is_file():
        raise HTTPException(status_code=500, detail=f"missing orchestrator: {ACS_SETUP}")
    return subprocess.run(
        [str(ACS_SETUP), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/modules")
def list_modules() -> list[dict]:
    if not MODULES_JSON.is_file():
        raise HTTPException(status_code=500, detail=f"missing {MODULES_JSON}")
    data = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    return sorted(data.get("modules", []), key=lambda m: m.get("number", 0))


@app.get("/api/status")
def get_status() -> list[dict]:
    result = run_acs_setup("--status", "--json")
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=result.stderr.strip() or result.stdout.strip() or "status failed",
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid status JSON: {exc}") from exc


@app.get("/api/credentials")
def get_credentials() -> dict:
    if not CREDENTIALS_PATH.is_file():
        return {
            "endpoint": "",
            "has_token": False,
            "token_masked": "",
            "saved": False,
        }
    data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    token = data.get("token") or ""
    masked = ""
    if token:
        masked = f"{token[:4]}…{token[-4:]}" if len(token) > 8 else "********"
    return {
        "endpoint": data.get("endpoint") or "",
        "has_token": bool(token),
        "token_masked": masked,
        "saved": True,
    }


@app.post("/api/credentials")
def save_credentials(body: CredentialsIn) -> dict[str, bool]:
    existing: dict[str, str] = {}
    if CREDENTIALS_PATH.is_file():
        existing = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))

    endpoint = body.endpoint.strip()
    token = body.token.strip() if body.token.strip() else (existing.get("token") or "")

    payload = {"endpoint": endpoint, "token": token}
    CREDENTIALS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    CREDENTIALS_PATH.chmod(0o600)
    return {"ok": True}


@app.post("/api/run/{module_id}", response_model=RunResult)
def run_module(module_id: str, dry_run: bool = False) -> RunResult:
    args = ["--run", "--module", module_id]
    if dry_run:
        args.append("--dry-run")
    result = run_acs_setup(*args)
    return RunResult(
        ok=result.returncode == 0,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


app.mount("/static", StaticFiles(directory=GUI_DIR / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(GUI_DIR / "static" / "index.html")
