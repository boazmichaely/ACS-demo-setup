"""Central API credentials and requests for orchestrated modules.

Contract (orchestrator / GUI runs):
  - lab-credentials.json is the source of truth
  - ROX_API_TOKEN, TOKEN, ACS_CENTRAL_ENDPOINT are fallbacks only when the file field is empty
  - Auth: if only apiToken or only adminPassword is set, use that one.
    If both are set, honor authPreference (apiToken | password).
  - TLS: insecureSkipTlsVerify in the credentials file, or ACS_INSECURE_SKIP_TLS_VERIFY=1

Import this module from Python module helpers; do not reimplement credential precedence.
"""

from __future__ import annotations

import base64
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


def insecure_skip_tls_verify(creds: dict[str, Any] | None = None) -> bool:
    """Env ACS_INSECURE_SKIP_TLS_VERIFY overrides the credentials file when set."""
    env = os.environ.get("ACS_INSECURE_SKIP_TLS_VERIFY", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    doc = creds if creds is not None else None
    if doc is None:
        try:
            doc = load_lab_credentials()
        except RuntimeError:
            return False
    return bool(doc.get("insecureSkipTlsVerify"))


def ssl_context_for_central(creds: dict[str, Any] | None = None) -> ssl.SSLContext:
    if insecure_skip_tls_verify(creds):
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _central_block(creds: dict[str, Any]) -> dict[str, Any]:
    return creds.get("centralCluster", {}).get("central") or {}


def _resolved_token(central: dict[str, Any]) -> str:
    token = (central.get("apiToken") or "").strip()
    if not token:
        token = os.environ.get("ROX_API_TOKEN", "").strip() or os.environ.get(
            "TOKEN", ""
        ).strip()
    return token


def central_authorization(creds: dict[str, Any]) -> str:
    """Return a full HTTP Authorization header value (Bearer … or Basic …)."""
    central = _central_block(creds)
    token = _resolved_token(central)
    password = (central.get("adminPassword") or "").strip()
    username = (central.get("adminUsername") or "").strip() or "admin"
    pref = (central.get("authPreference") or "apiToken").strip()
    if pref not in ("apiToken", "password"):
        pref = "apiToken"

    has_token = bool(token)
    has_password = bool(password)

    if has_token and has_password:
        use_token = pref != "password"
    elif has_token:
        use_token = True
    elif has_password:
        use_token = False
    else:
        raise RuntimeError(
            "neither Central API token nor admin password set in lab-credentials.json"
        )

    if use_token:
        return f"Bearer {token}"

    blob = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {blob}"


def central_api_token(creds: dict[str, Any]) -> str:
    """Return the bearer token when token auth is selected; else raise.

    Prefer central_authorization() / central_connection() for API calls.
    """
    header = central_authorization(creds)
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    raise RuntimeError(
        "Central auth resolved to admin password; no API token in use "
        "(set apiToken or switch authPreference)"
    )


def central_console_url(creds: dict[str, Any]) -> str:
    url = (_central_block(creds).get("consoleUrl") or "").strip()
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


def _normalize_authorization(authorization: str) -> str:
    auth = (authorization or "").strip()
    if not auth:
        raise RuntimeError("empty Central Authorization header")
    lower = auth.lower()
    if lower.startswith("bearer ") or lower.startswith("basic "):
        return auth
    return f"Bearer {auth}"


def central_request(
    base: str,
    authorization: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    creds: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Call Central REST. authorization may be a full header value or a bare API token."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": _normalize_authorization(authorization),
            "Content-Type": "application/json",
        },
    )
    context = ssl_context_for_central(creds)
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
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        hint = ""
        if "CERTIFICATE" in str(reason).upper() or "SSL" in str(reason).upper():
            hint = (
                " — enable Skip TLS verify for Central in Lab credentials "
                "(or set ACS_INSECURE_SKIP_TLS_VERIFY=1)"
            )
        # Encode as a synthetic non-HTTP failure for callers
        return 0, f"cannot reach Central at {base}: {reason}{hint}"


def check_central_auth(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any] | None = None,
) -> str | None:
    """Return an error message when Central auth fails; None when OK."""
    code, body = central_request(
        base, authorization, "GET", "/v1/metadata", creds=creds
    )
    if code == 200:
        return None
    if code == 0:
        return str(body)
    if code in (401, 403):
        return (
            f"Central API not authorized at {base} ({code}); "
            "check API token or admin password in lab-credentials.json"
        )
    return f"Central API request failed at {base} ({code}): {body}"


def central_connection(creds: dict[str, Any] | None = None) -> tuple[str, str]:
    """Load credentials and return (api_base, authorization_header)."""
    doc = creds if creds is not None else load_lab_credentials()
    return central_api_base(doc), central_authorization(doc)
