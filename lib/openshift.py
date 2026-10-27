"""OpenShift / oc access from lab-credentials.json (independent of ACS Central).

Modules that need oc should call ensure_oc() so saved OCP username/password
are enough when the current kube context is missing or dead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lib.central import load_lab_credentials, repo_root


def _openshift_block(creds: dict[str, Any]) -> dict[str, Any]:
    secured = creds.get("securedCluster") or {}
    if secured.get("sameAsCentralCluster", True):
        return (creds.get("centralCluster") or {}).get("openshift") or {}
    return secured.get("openshift") or {}


def api_url_from_console(console_url: str) -> str:
    """Derive https://api.<cluster>:6443 from an OpenShift console URL."""
    raw = (console_url or "").strip()
    if not raw:
        raise RuntimeError("OpenShift console URL is empty in lab-credentials.json")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    host = urlparse(raw).hostname or ""
    if not host:
        raise RuntimeError(f"invalid OpenShift console URL: {console_url}")

    # console-openshift-console.apps.<cluster> → api.<cluster>
    m = re.match(
        r"^console-openshift-console\.apps\.(.+)$",
        host,
        flags=re.IGNORECASE,
    )
    if m:
        return f"https://api.{m.group(1)}:6443"

    # Already an api host
    if host.startswith("api."):
        return f"https://{host}:6443" if ":6443" not in raw else f"https://{host}"

    raise RuntimeError(
        f"cannot derive OpenShift API URL from console host {host}; "
        "use a standard console-openshift-console.apps… URL"
    )


def _run_oc(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def oc_whoami_ok() -> bool:
    if not shutil.which("oc"):
        return False
    try:
        result = _run_oc(["whoami"], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ensure_oc(creds: dict[str, Any] | None = None) -> None:
    """Ensure oc can talk to the lab cluster; login from lab-credentials if needed.

    Raises RuntimeError with a clear message when OpenShift access cannot be established.
    """
    if not shutil.which("oc"):
        raise RuntimeError("oc not on PATH")

    if oc_whoami_ok():
        return

    doc = creds if creds is not None else load_lab_credentials()
    ocp = _openshift_block(doc)
    user = (ocp.get("adminUsername") or "").strip()
    password = (ocp.get("adminPassword") or "").strip()
    console = (ocp.get("consoleUrl") or "").strip()

    missing: list[str] = []
    if not console:
        missing.append("consoleUrl")
    if not user:
        missing.append("adminUsername")
    if not password:
        missing.append("adminPassword")
    if missing:
        raise RuntimeError(
            "oc not logged in and OpenShift credentials incomplete in "
            f"lab-credentials.json (missing: {', '.join(missing)})"
        )

    api = api_url_from_console(console)
    # Non-interactive login; lab clusters often need insecure TLS skip on the API
    login = _run_oc(
        [
            "login",
            api,
            f"--username={user}",
            f"--password={password}",
            "--insecure-skip-tls-verify=true",
        ],
        timeout=90,
    )
    if login.returncode != 0:
        detail = (login.stderr or login.stdout or "").strip() or f"exit {login.returncode}"
        raise RuntimeError(f"oc login to {api} failed: {detail}")

    if not oc_whoami_ok():
        raise RuntimeError(f"oc login to {api} appeared to succeed but oc whoami still fails")


def ensure_oc_message(creds: dict[str, Any] | None = None) -> str | None:
    """Return None on success, or an error message string."""
    try:
        ensure_oc(creds)
        return None
    except RuntimeError as exc:
        return str(exc)


def main(argv: list[str] | None = None) -> int:
    """CLI for bash modules: python -m lib.openshift ensure|check"""
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "ensure"
    if cmd in ("-h", "--help", "help"):
        print("Usage: python -m lib.openshift ensure|check", file=sys.stderr)
        return 0
    err = ensure_oc_message()
    if err:
        print(err, file=sys.stderr)
        return 1
    if cmd == "check":
        who = _run_oc(["whoami"], timeout=20)
        print((who.stdout or "").strip() or "ok")
    return 0


if __name__ == "__main__":
    # Allow `python lib/openshift.py` from repo root without -m
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
