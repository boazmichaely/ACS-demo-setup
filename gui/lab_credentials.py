"""Load and save lab-credentials.json (see config/lab-credentials.schema.json)."""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT_FOR_LIB = Path(__file__).resolve().parent.parent
if str(REPO_ROOT_FOR_LIB) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FOR_LIB))

from lib.lab_doc import (  # noqa: E402
    active_lab,
    active_secured_cluster,
    empty_lab,
    empty_openshift,
    empty_secured_cluster,
    empty_v2_document,
    flatten_active_lab,
    lab_log_blurb,
    normalize_document,
)

DEFAULT_RELATIVE_PATH = "lab-credentials.json"
LEGACY_RELATIVE_PATH = "central-credentials.json"


def credentials_path(repo_root: Path) -> Path:
    override = os.environ.get("ACS_LAB_CREDENTIALS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return repo_root / DEFAULT_RELATIVE_PATH


def empty_document(repo_root: Path) -> dict[str, Any]:
    return empty_v2_document()


def _jwt_token_meta(token: str) -> tuple[str, str]:
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
    out = dict(central)
    token = (out.get("apiToken") or "").strip()
    jwt_name, jwt_exp = _jwt_token_meta(token) if token else ("", "")
    name = (out.get("apiTokenName") or "").strip() or jwt_name
    exp = (out.get("apiTokenExpires") or "").strip() or jwt_exp
    out["apiTokenName"] = name
    out["apiTokenExpires"] = exp
    return out


def _enrich_doc_tokens(doc: dict[str, Any]) -> dict[str, Any]:
    for lab in doc.get("labs") or []:
        central = (lab.get("centralCluster") or {}).get("central") or {}
        enriched = _enrich_central_token_fields(central)
        lab.setdefault("centralCluster", {})["central"] = enriched
    return doc


def load_raw(repo_root: Path) -> dict[str, Any]:
    """Load credentials file as normalized v2 document."""
    path = credentials_path(repo_root)
    raw: dict[str, Any] | None = None
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        legacy = repo_root / LEGACY_RELATIVE_PATH
        if legacy.is_file():
            raw = json.loads(legacy.read_text(encoding="utf-8"))

    doc = _enrich_doc_tokens(normalize_document(raw))

    # Persist migration to v2 when the on-disk file was still v1 / legacy
    if path.is_file() and raw is not None and raw.get("version") != 2:
        _write_doc(path, doc)
    elif not path.is_file() and raw is not None:
        # Migrated from legacy path — write modern file
        _write_doc(path, doc)

    return doc


def load_flat(repo_root: Path) -> dict[str, Any]:
    """Active-lab view in v1 shape for modules / lib.central."""
    return flatten_active_lab(load_raw(repo_root))


def _write_doc(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _merge_secret(incoming: str, existing: str) -> str:
    return incoming.strip() if incoming.strip() else existing


def _merge_openshift(incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, str]:
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


def _merge_central(incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    central = {
        "consoleUrl": (incoming.get("consoleUrl") or existing.get("consoleUrl") or "").strip(),
        "apiToken": _merge_secret(incoming.get("apiToken") or "", existing.get("apiToken") or ""),
        "apiTokenName": (incoming.get("apiTokenName") or "").strip(),
        "apiTokenExpires": (incoming.get("apiTokenExpires") or "").strip(),
        "adminUsername": (
            incoming.get("adminUsername") or existing.get("adminUsername") or ""
        ).strip(),
        "adminPassword": _merge_secret(
            incoming.get("adminPassword") or "",
            existing.get("adminPassword") or "",
        ),
        "authPreference": incoming.get("authPreference")
        or existing.get("authPreference")
        or "apiToken",
    }
    if central["authPreference"] not in ("apiToken", "password"):
        central["authPreference"] = "apiToken"
    return _enrich_central_token_fields(central)


def merge_and_save(repo_root: Path, incoming: dict[str, Any]) -> Path:
    """Save full v2 document from GUI payload (activeLabId + labs[])."""
    existing = load_raw(repo_root)
    existing_by_id = {lab.get("id"): lab for lab in existing.get("labs") or []}

    incoming_labs = incoming.get("labs")
    if not isinstance(incoming_labs, list) or not incoming_labs:
        raise ValueError("labs must be a non-empty array")

    merged_labs: list[dict[str, Any]] = []
    for lab_in in incoming_labs:
        lab_id = (lab_in.get("id") or "").strip() or str(uuid.uuid4())
        prev = existing_by_id.get(lab_id) or empty_lab(lab_id=lab_id, name=lab_id)
        name = (lab_in.get("name") or prev.get("name") or lab_id).strip()

        if "insecureSkipTlsVerify" in lab_in:
            skip = bool(lab_in.get("insecureSkipTlsVerify"))
        else:
            skip = bool(prev.get("insecureSkipTlsVerify", False))

        cc_in = lab_in.get("centralCluster") or {}
        cc_prev = prev.get("centralCluster") or {}
        central_ocp = _merge_openshift(cc_in.get("openshift") or {}, cc_prev.get("openshift") or {})
        central = _merge_central(cc_in.get("central") or {}, cc_prev.get("central") or {})

        prev_sc_by_id = {
            sc.get("id"): sc for sc in (prev.get("securedClusters") or []) if sc.get("id")
        }
        sc_list_in = lab_in.get("securedClusters")
        if not isinstance(sc_list_in, list):
            sc_list_in = prev.get("securedClusters") or []

        merged_scs: list[dict[str, Any]] = []
        for sc_in in sc_list_in:
            sc_id = (sc_in.get("id") or "").strip() or str(uuid.uuid4())
            sc_prev = prev_sc_by_id.get(sc_id) or empty_secured_cluster(sc_id=sc_id)
            merged_scs.append(
                {
                    "id": sc_id,
                    "name": (sc_in.get("name") or sc_prev.get("name") or "secured").strip(),
                    "sameAsCentralCluster": bool(
                        sc_in.get(
                            "sameAsCentralCluster",
                            sc_prev.get("sameAsCentralCluster", True),
                        )
                    ),
                    "openshift": _merge_openshift(
                        sc_in.get("openshift") or {},
                        sc_prev.get("openshift") or empty_openshift(),
                    ),
                }
            )

        active_sc = (lab_in.get("activeSecuredClusterId") or "").strip()
        if merged_scs and not any(sc["id"] == active_sc for sc in merged_scs):
            active_sc = merged_scs[0]["id"]
        if not merged_scs:
            active_sc = ""

        merged_labs.append(
            {
                "id": lab_id,
                "name": name,
                "insecureSkipTlsVerify": skip,
                "centralCluster": {"openshift": central_ocp, "central": central},
                "securedClusters": merged_scs,
                "activeSecuredClusterId": active_sc,
            }
        )

    active_lab_id = (incoming.get("activeLabId") or "").strip()
    if not any(lab["id"] == active_lab_id for lab in merged_labs):
        active_lab_id = merged_labs[0]["id"]

    doc = {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 2,
        "activeLabId": active_lab_id,
        "labs": merged_labs,
    }
    path = credentials_path(repo_root)
    _write_doc(path, doc)
    return path


def set_active_lab(repo_root: Path, lab_id: str) -> dict[str, Any]:
    doc = load_raw(repo_root)
    if not any(lab.get("id") == lab_id for lab in doc.get("labs") or []):
        raise ValueError(f"unknown lab id: {lab_id}")
    doc["activeLabId"] = lab_id
    _write_doc(credentials_path(repo_root), doc)
    return doc


def for_api_response(repo_root: Path) -> dict[str, Any]:
    raw = load_raw(repo_root)
    labs_out: list[dict[str, Any]] = []
    for lab in raw.get("labs") or []:
        cc = lab.get("centralCluster") or {}
        c_central = _enrich_central_token_fields(cc.get("central") or {})
        scs = []
        for sc in lab.get("securedClusters") or []:
            ocp = sc.get("openshift") or {}
            scs.append(
                {
                    "id": sc.get("id") or "",
                    "name": sc.get("name") or "",
                    "sameAsCentralCluster": bool(sc.get("sameAsCentralCluster", True)),
                    "openshift": {
                        "consoleUrl": ocp.get("consoleUrl") or "",
                        "adminUsername": ocp.get("adminUsername") or "",
                        "adminPassword": ocp.get("adminPassword") or "",
                    },
                }
            )
        c_ocp = cc.get("openshift") or {}
        labs_out.append(
            {
                "id": lab.get("id") or "",
                "name": lab.get("name") or "",
                "insecureSkipTlsVerify": bool(lab.get("insecureSkipTlsVerify", False)),
                "centralCluster": {
                    "openshift": {
                        "consoleUrl": c_ocp.get("consoleUrl") or "",
                        "adminUsername": c_ocp.get("adminUsername") or "",
                        "adminPassword": c_ocp.get("adminPassword") or "",
                    },
                    "central": {
                        "consoleUrl": c_central.get("consoleUrl") or "",
                        "adminUsername": c_central.get("adminUsername") or "",
                        "authPreference": c_central.get("authPreference") or "apiToken",
                        "apiToken": c_central.get("apiToken") or "",
                        "apiTokenName": c_central.get("apiTokenName") or "",
                        "apiTokenExpires": c_central.get("apiTokenExpires") or "",
                        "adminPassword": c_central.get("adminPassword") or "",
                    },
                },
                "securedClusters": scs,
                "activeSecuredClusterId": lab.get("activeSecuredClusterId") or (
                    scs[0]["id"] if scs else ""
                ),
            }
        )

    active = active_lab(raw)
    sc = active_secured_cluster(active)
    central_host = ""
    try:
        cu = ((active.get("centralCluster") or {}).get("central") or {}).get("consoleUrl") or ""
        if cu:
            if not cu.startswith(("http://", "https://")):
                cu = f"https://{cu}"
            central_host = urlparse(cu).hostname or cu
    except Exception:
        central_host = ""

    return {
        "filePath": str(credentials_path(repo_root)),
        "saved": credentials_path(repo_root).is_file()
        or (repo_root / LEGACY_RELATIVE_PATH).is_file(),
        "version": 2,
        "activeLabId": raw.get("activeLabId") or (labs_out[0]["id"] if labs_out else ""),
        "labs": labs_out,
        "activeLabSummary": {
            "id": active.get("id") or "",
            "name": active.get("name") or "",
            "centralHost": central_host,
            "activeSecuredClusterName": sc.get("name") or "",
            "activeSecuredSameAsCentral": bool(sc.get("sameAsCentralCluster", True)),
        },
        "logBlurb": lab_log_blurb(raw),
    }


def central_api_token(repo_root: Path) -> str:
    flat = load_flat(repo_root)
    central = flat["centralCluster"]["central"]
    token = (central.get("apiToken") or "").strip()
    password = (central.get("adminPassword") or "").strip()
    pref = (central.get("authPreference") or "apiToken").strip()
    if token and password:
        return token if pref != "password" else ""
    return token


def central_console_url(repo_root: Path) -> str:
    flat = load_flat(repo_root)
    return (flat["centralCluster"]["central"].get("consoleUrl") or "").strip()
