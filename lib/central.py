"""Central API credentials and requests for orchestrated modules.

Contract (orchestrator / GUI runs):
  - lab-credentials.json is the source of truth
  - ROX_API_TOKEN, TOKEN, ACS_CENTRAL_ENDPOINT are fallbacks only when the file field is empty

Import this module from Python module helpers; do not reimplement credential precedence.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CREDENTIALS_FILE = "lab-credentials.json"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def credentials_path(root: Path | None = None) -> Path:
    override = os.environ.get("ACS_LAB_CREDENTIALS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return (root or repo_root()) / DEFAULT_CREDENTIALS_FILE


def load_lab_credentials(root: Path | None = None) -> dict[str, Any]:
    path = credentials_path(root)
    if not path.is_file():
        raise RuntimeError(f"lab credentials file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def central_api_token(creds: dict[str, Any]) -> str:
    token = (creds.get("centralCluster", {}).get("central", {}).get("apiToken") or "").strip()
    if not token:
        token = os.environ.get("ROX_API_TOKEN", "").strip() or os.environ.get("TOKEN", "").strip()
    if not token:
        raise RuntimeError("Central API token not set in lab-credentials.json")
    return token


def central_console_url(creds: dict[str, Any]) -> str:
    url = (creds.get("centralCluster", {}).get("central", {}).get("consoleUrl") or "").strip()
    if not url:
        url = os.environ.get("ACS_CENTRAL_ENDPOINT", "").strip()
    if not url:
        raise RuntimeError("Central console URL not set in lab-credentials.json")
    return url


def central_api_base(creds: dict[str, Any]) -> str:
    endpoint = central_console_url(creds)
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.hostname:
        raise RuntimeError(f"invalid Central endpoint: {endpoint}")
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port and parsed.port != default_port:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"


def central_request(
    base: str,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, context=context, timeout=60) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return response.status, {}
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def check_central_auth(base: str, token: str) -> str | None:
    """Return an error message when Central auth fails; None when OK."""
    code, body = central_request(base, token, "GET", "/v1/metadata")
    if code == 200:
        return None
    if code in (401, 403):
        return (
            f"Central API not authorized at {base} ({code}); "
            "check API token in lab-credentials.json"
        )
    return f"Central API request failed at {base} ({code}): {body}"


def central_connection(creds: dict[str, Any] | None = None) -> tuple[str, str]:
    """Load credentials and return (api_base, api_token)."""
    doc = creds if creds is not None else load_lab_credentials()
    return central_api_base(doc), central_api_token(doc)
