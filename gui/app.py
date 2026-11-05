"""ACS demo setup GUI — local server on 127.0.0.1 only."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lab_credentials import (
    credentials_path,
    for_api_response,
    merge_and_save,
    set_active_lab,
)
from run_log import append_today_log, begin_run, mark_lab_switch, mark_page_load, read_today_log

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = Path(__file__).resolve().parent
MODULES_JSON = REPO_ROOT / "config" / "modules.json"
ACS_SETUP = REPO_ROOT / "scripts" / "acs-setup.sh"
VERSION_FILE = REPO_ROOT / "VERSION"
GITHUB_REPO = "boazmichaely/ACS-demo-setup"

HOST = "127.0.0.1"
PORT = 8765


def read_app_version() -> str:
    if not VERSION_FILE.is_file():
        raise RuntimeError(f"missing VERSION file: {VERSION_FILE}")
    ver = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not ver:
        raise RuntimeError(f"VERSION file is empty: {VERSION_FILE}")
    return ver


try:
    _APP_VERSION = read_app_version()
except RuntimeError:
    _APP_VERSION = "0.0.0"

app = FastAPI(title="ACS Demo Setup", version=_APP_VERSION)


class OpenshiftAccessIn(BaseModel):
    consoleUrl: str = ""
    adminUsername: str = ""
    adminPassword: str = Field(default="", description="Blank keeps existing password")
    apiToken: str = Field(
        default="",
        description="Blank keeps existing OpenShift API token; preferred over password when set",
    )


class CentralConsoleIn(BaseModel):
    consoleUrl: str = ""
    apiToken: str = Field(default="", description="Blank keeps existing token")
    apiTokenName: str = ""
    apiTokenExpires: str = Field(default="", description="YYYY-MM-DD")
    adminUsername: str = ""
    adminPassword: str = Field(default="", description="Blank keeps existing password")
    authPreference: str = "apiToken"


class CentralClusterIn(BaseModel):
    openshift: OpenshiftAccessIn = Field(default_factory=OpenshiftAccessIn)
    central: CentralConsoleIn = Field(default_factory=CentralConsoleIn)


class SecuredClusterIn(BaseModel):
    id: str = ""
    name: str = ""
    sameAsCentralCluster: bool = True
    openshift: OpenshiftAccessIn = Field(default_factory=OpenshiftAccessIn)


class LabIn(BaseModel):
    id: str = ""
    name: str = ""
    insecureSkipTlsVerify: bool = False
    centralCluster: CentralClusterIn = Field(default_factory=CentralClusterIn)
    securedClusters: list[SecuredClusterIn] = Field(default_factory=list)
    activeSecuredClusterId: str = ""


class LabCredentialsIn(BaseModel):
    activeLabId: str = ""
    labs: list[LabIn] = Field(default_factory=list)


class ActiveLabIn(BaseModel):
    labId: str


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    extra = [
        str(GUI_DIR / ".venv" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    env["PATH"] = ":".join([p for p in extra if p] + [env.get("PATH", "")])
    return env


def run_acs_setup(*args: str) -> subprocess.CompletedProcess[str]:
    if not ACS_SETUP.is_file():
        raise HTTPException(status_code=500, detail=f"missing orchestrator: {ACS_SETUP}")
    return subprocess.run(
        [str(ACS_SETUP), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=subprocess_env(),
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _parse_semver(raw: str) -> tuple[int, int, int] | None:
    s = (raw or "").strip()
    if s.lower().startswith("v"):
        s = s[1:]
    parts = s.split(".")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2].split("-", 1)[0])
    except ValueError:
        return None


def _semver_greater(left: str, right: str) -> bool:
    a = _parse_semver(left)
    b = _parse_semver(right)
    if not a or not b:
        return False
    return a > b


def _fetch_latest_github_release() -> dict[str, str] | None:
    """Return {tagName, htmlUrl} or None when unavailable."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "acs-demo-setup",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(data, dict):
        return None
    tag_name = str(data.get("tag_name") or "").strip()
    if not tag_name:
        return None
    html_url = str(data.get("html_url") or "").strip() or (
        f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}"
    )
    return {"tagName": tag_name, "htmlUrl": html_url}


@app.get("/api/version")
def api_version() -> dict[str, Any]:
    """Installed version + whether a newer GitHub Release exists (server-side check)."""
    try:
        version = read_app_version()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    tag = version if version.startswith("v") else f"v{version}"
    out: dict[str, Any] = {
        "version": version,
        "repo": GITHUB_REPO,
        "releaseUrl": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
        "updateAvailable": False,
        "latestTag": "",
        "latestReleaseUrl": "",
    }
    latest = _fetch_latest_github_release()
    if not latest:
        return out
    out["latestTag"] = latest["tagName"]
    out["latestReleaseUrl"] = latest["htmlUrl"]
    if _semver_greater(latest["tagName"], version):
        out["updateAvailable"] = True
    return out


@app.get("/api/version/latest")
def api_version_latest() -> dict[str, str]:
    """Latest GitHub Release (server-side fetch)."""
    latest = _fetch_latest_github_release()
    if not latest:
        raise HTTPException(status_code=404, detail="no releases available")
    return {**latest, "repo": GITHUB_REPO}


def _catalog_module_ids() -> set[str]:
    if not MODULES_JSON.is_file():
        return set()
    data = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    return {(m.get("id") or "").strip() for m in data.get("modules", []) if m.get("id")}


@app.get("/api/modules")
def list_modules() -> list[dict]:
    if not MODULES_JSON.is_file():
        raise HTTPException(status_code=500, detail=f"missing {MODULES_JSON}")
    data = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    # Preserve catalog order; expose 1-based "number" for GUI display only.
    modules: list[dict] = []
    for index, mod in enumerate(data.get("modules", []), start=1):
        entry = dict(mod)
        mid = (entry.get("id") or "").strip()
        entry["number"] = index
        script = REPO_ROOT / "modules" / f"{mid}.sh"
        entry["scriptInstalled"] = script.is_file() and os.access(script, os.X_OK)
        modules.append(entry)
    return modules


@app.get("/api/modules/{module_id}/help")
def module_help(module_id: str) -> dict[str, str]:
    """Return ``modules/<id>.sh --help`` text for the kebab Help action."""
    mid = (module_id or "").strip()
    if mid not in _catalog_module_ids():
        raise HTTPException(status_code=404, detail=f"unknown module: {mid}")
    script = REPO_ROOT / "modules" / f"{mid}.sh"
    if not script.is_file() or not os.access(script, os.X_OK):
        raise HTTPException(status_code=404, detail=f"module script not installed: {mid}")
    result = subprocess.run(
        [str(script), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=subprocess_env(),
    )
    text = (result.stdout or "").strip() or (result.stderr or "").strip()
    if not text:
        raise HTTPException(
            status_code=500,
            detail=f"{mid} --help produced no output (exit {result.returncode})",
        )
    return {"id": mid, "text": text}


@app.get("/api/status")
def get_status(modules: str | None = Query(default=None)) -> list[dict]:
    if modules:
        ids = [m.strip() for m in modules.split(",") if m.strip()]
        merged: list[dict] = []
        for module_id in ids:
            result = run_acs_setup("--status", "--json", "--module", module_id)
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=result.stderr.strip()
                    or result.stdout.strip()
                    or f"status failed for {module_id}",
                )
            try:
                merged.extend(json.loads(result.stdout))
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=500, detail=f"invalid status JSON for {module_id}: {exc}"
                ) from exc
        return merged

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
def save_credentials(body: LabCredentialsIn) -> dict[str, Any]:
    try:
        merge_and_save(REPO_ROOT, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **for_api_response(REPO_ROOT)}


@app.post("/api/credentials/active-lab")
def post_active_lab(body: ActiveLabIn) -> dict[str, Any]:
    try:
        set_active_lab(REPO_ROOT, body.labId.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mark_lab_switch(REPO_ROOT)
    return {"ok": True, **for_api_response(REPO_ROOT)}


@app.get("/api/credentials/path")
def get_credentials_path() -> dict[str, str]:
    return {"path": str(credentials_path(REPO_ROOT))}


@app.get("/api/log")
def get_run_log() -> dict[str, str]:
    return {"text": read_today_log(REPO_ROOT)}


@app.post("/api/log/page-load")
def post_log_page_load() -> dict[str, bool]:
    mark_page_load(REPO_ROOT)
    return {"ok": True}


@app.post("/api/run/{module_id}")
def run_module(
    module_id: str,
    dry_run: bool = False,
    uninstall: bool = False,
) -> StreamingResponse:
    if uninstall:
        args = ["--uninstall", "--module", module_id]
    else:
        args = ["--run", "--module", module_id]
    if dry_run:
        args.append("--dry-run")

    def stream_output():
        begin_run(REPO_ROOT, module_id, dry_run=dry_run, uninstall=uninstall)
        proc = subprocess.Popen(
            [str(ACS_SETUP), *args],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=subprocess_env(),
        )
        assert proc.stdout is not None
        try:
            for chunk in proc.stdout:
                append_today_log(REPO_ROOT, chunk)
                yield chunk
        finally:
            proc.wait()
        trailer = f"\n__EXIT__:{proc.returncode}\n"
        append_today_log(REPO_ROOT, trailer)
        yield trailer

    return StreamingResponse(stream_output(), media_type="text/plain; charset=utf-8")


HELP_DOCS: dict[str, tuple[str, Path]] = {
    "readme": ("README", REPO_ROOT / "README.md"),
    "adding-a-module": ("How to add a module", REPO_ROOT / "ADDING-A-MODULE.md"),
    "users-part1-ocp-demo": (
        "Users series demo script",
        REPO_ROOT / "modules" / "users-part1-ocp-demo.md",
    ),
}


@app.get("/api/help/{doc_id}")
def help_doc(doc_id: str) -> dict[str, str]:
    """Return a repo Markdown help page for the GUI help viewer."""
    entry = HELP_DOCS.get(doc_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Unknown help doc: {doc_id}")
    title, path = entry
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Missing help file: {path.name}")
    text = path.read_text(encoding="utf-8")
    # Help viewer loads images from /help-assets/… (docs/ mounted below).
    text = text.replace("](docs/", "](/help-assets/")
    return {"id": doc_id, "title": title, "markdown": text}


@app.get("/help")
def help_viewer() -> FileResponse:
    return FileResponse(
        GUI_DIR / "static" / "help.html",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


app.mount("/help-assets", StaticFiles(directory=REPO_ROOT / "docs"), name="help_assets")
app.mount("/static", StaticFiles(directory=GUI_DIR / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    # HTML must not stick in the browser; asset URLs inside it carry ?v= cache busts.
    return FileResponse(
        GUI_DIR / "static" / "index.html",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
