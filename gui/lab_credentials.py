"""Load and save lab-credentials.json (see config/lab-credentials.schema.json)."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RELATIVE_PATH = "lab-credentials.json"
LEGACY_RELATIVE_PATH = "central-credentials.json"
SCHEMA_RELATIVE = "config/lab-credentials.schema.json"


def credentials_path(repo_root: Path) -> Path:
    override = os.environ.get("ACS_LAB_CREDENTIALS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return repo_root / DEFAULT_RELATIVE_PATH


def empty_document(repo_root: Path) -> dict[str, Any]:
    return {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 1,
        "insecureSkipTlsVerify": False,
        "centralCluster": {
            "openshift": {
                "consoleUrl": "",
                "adminUsername": "",
                "adminPassword": "",
            },
            "central": {
                "consoleUrl": "",
                "apiToken": "",
                "apiTokenName": "",
                "apiTokenExpires": "",
                "adminUsername": "",
                "adminPassword": "",
                "authPreference": "apiToken",
            },
        },
        "securedCluster": {
            "sameAsCentralCluster": True,
            "openshift": {
                "consoleUrl": "",
                "adminUsername": "",
                "adminPassword": "",
            },
        },
    }


def _jwt_token_meta(token: str) -> tuple[str, str]:
    """Read RHACS API token display name and expiry from JWT payload."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        return "", ""
    try:
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (json.JSONDecodeError, ValueError, TypeError):
        return "", ""

    name = str(payload.get("name") or "").strip()
    exp = payload.get("exp")
    exp_date = ""
    if isinstance(exp, (int, float)) and exp > 0:
        exp_date = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d")
    return name, exp_date


def _enrich_central_token_fields(central: dict[str, Any]) -> dict[str, Any]:
    """Ensure apiTokenName / apiTokenExpires; derive from JWT when missing."""
    out = dict(central)
    token = (out.get("apiToken") or "").strip()
    jwt_name, jwt_exp = _jwt_token_meta(token) if token else ("", "")

    name = (out.get("apiTokenName") or "").strip() or jwt_name
    exp = (out.get("apiTokenExpires") or "").strip() or jwt_exp
    out["apiTokenName"] = name
    out["apiTokenExpires"] = exp
    return out


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Map old {endpoint, token} file to v1 lab-credentials shape."""
    doc = empty_document(Path("."))
    endpoint = (raw.get("endpoint") or raw.get("centralEndpoint") or "").strip()
    token = (raw.get("token") or raw.get("apiToken") or "").strip()
    if endpoint:
        doc["centralCluster"]["central"]["consoleUrl"] = endpoint
    if token:
        doc["centralCluster"]["central"]["apiToken"] = token
        doc["centralCluster"]["central"]["authPreference"] = "apiToken"
    return doc


def load_raw(repo_root: Path) -> dict[str, Any]:
    path = credentials_path(repo_root)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if "centralCluster" not in data:
            return _migrate_legacy(data)

        central = data["centralCluster"].get("central") or {}
        enriched = _enrich_central_token_fields(central)
        if enriched != central:
            data["centralCluster"]["central"] = enriched
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            path.chmod(0o600)
        return data

    legacy = repo_root / LEGACY_RELATIVE_PATH
    if legacy.is_file():
        data = json.loads(legacy.read_text(encoding="utf-8"))
        return _migrate_legacy(data)

    return empty_document(repo_root)


def _merge_secret(incoming: str, existing: str) -> str:
    return incoming.strip() if incoming.strip() else existing


def _merge_openshift(
    incoming: dict[str, Any], existing: dict[str, Any]
) -> dict[str, str]:
    return {
        "consoleUrl": (incoming.get("consoleUrl") or existing.get("consoleUrl") or "").strip(),
        "adminUsername": (
            incoming.get("adminUsername") or existing.get("adminUsername") or ""
        ).strip(),
        "adminPassword": _merge_secret(
            incoming.get("adminPassword") or "",
            existing.get("adminPassword") or "",
        ),
    }


def merge_and_save(repo_root: Path, incoming: dict[str, Any]) -> Path:
    existing = load_raw(repo_root)
    central_in = incoming.get("centralCluster") or {}
    secured_in = incoming.get("securedCluster") or {}

    central_ocp = _merge_openshift(
        central_in.get("openshift") or {},
        existing["centralCluster"]["openshift"],
    )
    central_existing = existing["centralCluster"]["central"]
    central_in_c = central_in.get("central") or {}
    central = {
        "consoleUrl": (
            central_in_c.get("consoleUrl") or central_existing.get("consoleUrl") or ""
        ).strip(),
        "apiToken": _merge_secret(
            central_in_c.get("apiToken") or "",
            central_existing.get("apiToken") or "",
        ),
        "apiTokenName": (central_in_c.get("apiTokenName") or "").strip(),
        "apiTokenExpires": (central_in_c.get("apiTokenExpires") or "").strip(),
        "adminUsername": (
            central_in_c.get("adminUsername") or central_existing.get("adminUsername") or ""
        ).strip(),
        "adminPassword": _merge_secret(
            central_in_c.get("adminPassword") or "",
            central_existing.get("adminPassword") or "",
        ),
        "authPreference": central_in_c.get("authPreference")
        or central_existing.get("authPreference")
        or "apiToken",
    }
    if central["authPreference"] not in ("apiToken", "password"):
        central["authPreference"] = "apiToken"
    central = _enrich_central_token_fields(central)

    same = bool(secured_in.get("sameAsCentralCluster", True))
    secured_ocp = _merge_openshift(
        secured_in.get("openshift") or {},
        existing["securedCluster"]["openshift"],
    )

    if "insecureSkipTlsVerify" in incoming:
        skip_tls = bool(incoming.get("insecureSkipTlsVerify"))
    else:
        skip_tls = bool(existing.get("insecureSkipTlsVerify", False))

    doc = {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 1,
        "insecureSkipTlsVerify": skip_tls,
        "centralCluster": {"openshift": central_ocp, "central": central},
        "securedCluster": {"sameAsCentralCluster": same, "openshift": secured_ocp},
    }

    path = credentials_path(repo_root)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def for_api_response(repo_root: Path) -> dict[str, Any]:
    raw = load_raw(repo_root)
    central = raw["centralCluster"]
    secured = raw["securedCluster"]
    c_central = _enrich_central_token_fields(central["central"])
    api_token = c_central.get("apiToken") or ""

    return {
        "filePath": str(credentials_path(repo_root)),
        "saved": credentials_path(repo_root).is_file()
        or (repo_root / LEGACY_RELATIVE_PATH).is_file(),
        "insecureSkipTlsVerify": bool(raw.get("insecureSkipTlsVerify", False)),
        "centralCluster": {
            "openshift": {
                "consoleUrl": central["openshift"].get("consoleUrl") or "",
                "adminUsername": central["openshift"].get("adminUsername") or "",
                "adminPassword": central["openshift"].get("adminPassword") or "",
            },
            "central": {
                "consoleUrl": c_central.get("consoleUrl") or "",
                "adminUsername": c_central.get("adminUsername") or "",
                "authPreference": c_central.get("authPreference") or "apiToken",
                "apiToken": api_token,
                "apiTokenName": c_central.get("apiTokenName") or "",
                "apiTokenExpires": c_central.get("apiTokenExpires") or "",
                "adminPassword": c_central.get("adminPassword") or "",
            },
        },
        "securedCluster": {
            "sameAsCentralCluster": bool(secured.get("sameAsCentralCluster", True)),
            "openshift": {
                "consoleUrl": secured["openshift"].get("consoleUrl") or "",
                "adminUsername": secured["openshift"].get("adminUsername") or "",
                "adminPassword": secured["openshift"].get("adminPassword") or "",
            },
        },
    }


def central_api_token(repo_root: Path) -> str:
    """Bearer token when that is the resolved auth; empty if password-only."""
    raw = load_raw(repo_root)
    central = raw["centralCluster"]["central"]
    token = (central.get("apiToken") or "").strip()
    password = (central.get("adminPassword") or "").strip()
    pref = (central.get("authPreference") or "apiToken").strip()
    if token and password:
        return token if pref != "password" else ""
    return token


def central_console_url(repo_root: Path) -> str:
    raw = load_raw(repo_root)
    return (raw["centralCluster"]["central"].get("consoleUrl") or "").strip()
