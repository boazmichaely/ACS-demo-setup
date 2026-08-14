"""Load, save, and mask lab-credentials.json (see config/lab-credentials.schema.json)."""

from __future__ import annotations

import json
import os
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
        "centralCluster": {
            "openshift": {
                "consoleUrl": "",
                "adminUsername": "",
                "adminPassword": "",
            },
            "central": {
                "consoleUrl": "",
                "apiToken": "",
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


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) > 8:
        return f"{value[:4]}…{value[-4:]}"
    return "********"


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
        if "centralCluster" in data:
            return data
        return _migrate_legacy(data)

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

    same = bool(secured_in.get("sameAsCentralCluster", True))
    secured_ocp = _merge_openshift(
        secured_in.get("openshift") or {},
        existing["securedCluster"]["openshift"],
    )

    doc = {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 1,
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
    c_central = central["central"]
    api_token = c_central.get("apiToken") or ""

    return {
        "filePath": str(credentials_path(repo_root)),
        "saved": credentials_path(repo_root).is_file()
        or (repo_root / LEGACY_RELATIVE_PATH).is_file(),
        "centralCluster": {
            "openshift": {
                "consoleUrl": central["openshift"].get("consoleUrl") or "",
                "adminUsername": central["openshift"].get("adminUsername") or "",
                "hasAdminPassword": bool(central["openshift"].get("adminPassword")),
                "adminPasswordMasked": _mask_secret(
                    central["openshift"].get("adminPassword") or ""
                ),
            },
            "central": {
                "consoleUrl": c_central.get("consoleUrl") or "",
                "adminUsername": c_central.get("adminUsername") or "",
                "authPreference": c_central.get("authPreference") or "apiToken",
                "hasApiToken": bool(api_token),
                "apiTokenMasked": _mask_secret(api_token),
                "hasAdminPassword": bool(c_central.get("adminPassword")),
                "adminPasswordMasked": _mask_secret(c_central.get("adminPassword") or ""),
            },
        },
        "securedCluster": {
            "sameAsCentralCluster": bool(secured.get("sameAsCentralCluster", True)),
            "openshift": {
                "consoleUrl": secured["openshift"].get("consoleUrl") or "",
                "adminUsername": secured["openshift"].get("adminUsername") or "",
                "hasAdminPassword": bool(secured["openshift"].get("adminPassword")),
                "adminPasswordMasked": _mask_secret(
                    secured["openshift"].get("adminPassword") or ""
                ),
            },
        },
    }


def central_api_token(repo_root: Path) -> str:
    """Convenience for modules: preferred Central API credential."""
    raw = load_raw(repo_root)
    central = raw["centralCluster"]["central"]
    pref = central.get("authPreference") or "apiToken"
    if pref == "apiToken" and central.get("apiToken"):
        return central["apiToken"]
    return central.get("apiToken") or ""


def central_console_url(repo_root: Path) -> str:
    raw = load_raw(repo_root)
    return (raw["centralCluster"]["central"].get("consoleUrl") or "").strip()
