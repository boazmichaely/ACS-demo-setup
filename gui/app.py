"""ACS demo setup GUI — local server on 127.0.0.1 only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lab_credentials import credentials_path, for_api_response, merge_and_save

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = Path(__file__).resolve().parent
MODULES_JSON = REPO_ROOT / "config" / "modules.json"
ACS_SETUP = REPO_ROOT / "acs-setup.sh"

HOST = "127.0.0.1"
PORT = 8765

app = FastAPI(title="ACS Demo Setup", version="0.1.0")


class OpenshiftAccessIn(BaseModel):
    consoleUrl: str = ""
    adminUsername: str = ""
    adminPassword: str = Field(default="", description="Blank keeps existing password")


class CentralConsoleIn(BaseModel):
    consoleUrl: str = ""
    apiToken: str = Field(default="", description="Blank keeps existing token")
    adminUsername: str = ""
    adminPassword: str = Field(default="", description="Blank keeps existing password")
    authPreference: str = "apiToken"


class CentralClusterIn(BaseModel):
    openshift: OpenshiftAccessIn = Field(default_factory=OpenshiftAccessIn)
    central: CentralConsoleIn = Field(default_factory=CentralConsoleIn)


class SecuredClusterIn(BaseModel):
    sameAsCentralCluster: bool = True
    openshift: OpenshiftAccessIn = Field(default_factory=OpenshiftAccessIn)


class LabCredentialsIn(BaseModel):
    centralCluster: CentralClusterIn = Field(default_factory=CentralClusterIn)
    securedCluster: SecuredClusterIn = Field(default_factory=SecuredClusterIn)


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
def get_credentials() -> dict[str, Any]:
    return for_api_response(REPO_ROOT)


@app.post("/api/credentials")
def save_credentials(body: LabCredentialsIn) -> dict[str, bool]:
    merge_and_save(REPO_ROOT, body.model_dump())
    return {"ok": True}


@app.get("/api/credentials/path")
def get_credentials_path() -> dict[str, str]:
    return {"path": str(credentials_path(REPO_ROOT))}


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
