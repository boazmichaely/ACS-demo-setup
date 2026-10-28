"""lab-credentials.json document helpers (v1 migrate → v2; flatten active lab for modules)."""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse


def _slug(text: str, fallback: str = "lab") -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return raw[:48] or fallback


def _host_hint(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return urlparse(raw).hostname or raw


def empty_openshift() -> dict[str, str]:
    return {"consoleUrl": "", "adminUsername": "", "adminPassword": ""}


def empty_central() -> dict[str, Any]:
    return {
        "consoleUrl": "",
        "apiToken": "",
        "apiTokenName": "",
        "apiTokenExpires": "",
        "adminUsername": "",
        "adminPassword": "",
        "authPreference": "apiToken",
    }


def empty_secured_cluster(
    *,
    sc_id: str | None = None,
    name: str = "production",
    same_as_central: bool = True,
) -> dict[str, Any]:
    return {
        "id": sc_id or str(uuid.uuid4()),
        "name": name,
        "sameAsCentralCluster": same_as_central,
        "openshift": empty_openshift(),
    }


def empty_lab(*, lab_id: str | None = None, name: str = "default") -> dict[str, Any]:
    lid = lab_id or "default"
    sc = empty_secured_cluster(name="production", same_as_central=True)
    return {
        "id": lid,
        "name": name,
        "insecureSkipTlsVerify": False,
        "centralCluster": {
            "openshift": empty_openshift(),
            "central": empty_central(),
        },
        "securedClusters": [sc],
        "activeSecuredClusterId": sc["id"],
    }


def empty_v2_document() -> dict[str, Any]:
    lab = empty_lab(lab_id="default", name="default")
    return {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 2,
        "activeLabId": lab["id"],
        "labs": [lab],
    }


def _lab_name_from_url(url: str) -> str:
    """Prefer apps.<cluster> first DNS label (e.g. bm-50rc4-on-ocp5) over full host slug."""
    host = _host_hint(url)
    if not host:
        return "default"
    m = re.match(
        r"^(?:central-stackrox|console-openshift-console)\.apps\.(.+)$",
        host,
        flags=re.IGNORECASE,
    )
    if m:
        return _slug(m.group(1).split(".")[0], "default")
    return _slug(host, "default")


def migrate_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Map flat v1 {centralCluster, securedCluster} into a single-lab v2 document."""
    central = raw.get("centralCluster") or {}
    secured = raw.get("securedCluster") or {}
    central_url = ((central.get("central") or {}).get("consoleUrl") or "").strip()
    name = _lab_name_from_url(central_url)
    lab_id = name

    sc = empty_secured_cluster(
        name="production",
        same_as_central=bool(secured.get("sameAsCentralCluster", True)),
    )
    sc_ocp = secured.get("openshift") or {}
    sc["openshift"] = {
        "consoleUrl": (sc_ocp.get("consoleUrl") or "").strip(),
        "adminUsername": (sc_ocp.get("adminUsername") or "").strip(),
        "adminPassword": sc_ocp.get("adminPassword") or "",
    }

    c_ocp = central.get("openshift") or {}
    c_central = dict(central.get("central") or empty_central())
    lab = {
        "id": lab_id,
        "name": name if name != "default" else "default",
        "insecureSkipTlsVerify": bool(raw.get("insecureSkipTlsVerify", False)),
        "centralCluster": {
            "openshift": {
                "consoleUrl": (c_ocp.get("consoleUrl") or "").strip(),
                "adminUsername": (c_ocp.get("adminUsername") or "").strip(),
                "adminPassword": c_ocp.get("adminPassword") or "",
            },
            "central": c_central,
        },
        "securedClusters": [sc],
        "activeSecuredClusterId": sc["id"],
    }
    return {
        "$schema": "./config/lab-credentials.schema.json",
        "version": 2,
        "activeLabId": lab_id,
        "labs": [lab],
    }


def normalize_document(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a v2 document; migrate v1 or empty/legacy shapes."""
    if not raw:
        return empty_v2_document()
    if raw.get("version") == 2 and isinstance(raw.get("labs"), list) and raw["labs"]:
        doc = dict(raw)
        doc["version"] = 2
        if not doc.get("activeLabId"):
            doc["activeLabId"] = doc["labs"][0].get("id") or "default"
        # Ensure each lab has securedClusters + activeSecuredClusterId.
        # Empty securedClusters[] is allowed (Central-only labs).
        for lab in doc["labs"]:
            clusters = lab.get("securedClusters")
            if not isinstance(clusters, list):
                sc = empty_secured_cluster()
                lab["securedClusters"] = [sc]
                lab["activeSecuredClusterId"] = sc["id"]
            elif not clusters:
                lab["securedClusters"] = []
                lab["activeSecuredClusterId"] = ""
            elif not lab.get("activeSecuredClusterId"):
                lab["activeSecuredClusterId"] = clusters[0].get("id") or ""
            if "insecureSkipTlsVerify" not in lab and "insecureSkipTlsVerify" in raw:
                lab["insecureSkipTlsVerify"] = bool(raw.get("insecureSkipTlsVerify"))
        return doc
    if "centralCluster" in raw:
        return migrate_v1_to_v2(raw)
    # Legacy {endpoint, token}
    v1 = {
        "version": 1,
        "insecureSkipTlsVerify": False,
        "centralCluster": {
            "openshift": empty_openshift(),
            "central": empty_central(),
        },
        "securedCluster": {
            "sameAsCentralCluster": True,
            "openshift": empty_openshift(),
        },
    }
    endpoint = (raw.get("endpoint") or raw.get("centralEndpoint") or "").strip()
    token = (raw.get("token") or raw.get("apiToken") or "").strip()
    if endpoint:
        v1["centralCluster"]["central"]["consoleUrl"] = endpoint
    if token:
        v1["centralCluster"]["central"]["apiToken"] = token
        v1["centralCluster"]["central"]["authPreference"] = "apiToken"
    return migrate_v1_to_v2(v1)


def active_lab(doc: dict[str, Any]) -> dict[str, Any]:
    doc = normalize_document(doc)
    aid = doc.get("activeLabId")
    for lab in doc.get("labs") or []:
        if lab.get("id") == aid:
            return lab
    labs = doc.get("labs") or []
    if not labs:
        raise RuntimeError("lab-credentials.json has no labs")
    return labs[0]


def preferred_secured_cluster(lab: dict[str, Any]) -> dict[str, Any]:
    """OpenShift creds for module ``oc``: prefer same-as-Central, else first SC.

    Secured-cluster rows are primarily stored for control-plane access; there is
    no UI “active SC” selector. ``activeSecuredClusterId`` is kept for schema
    compatibility and used only when it still matches a row.
    """
    clusters = lab.get("securedClusters") or []
    if not clusters:
        # Central-only lab: modules that need oc fall back to Central OpenShift.
        return empty_secured_cluster(name="", same_as_central=True)
    aid = lab.get("activeSecuredClusterId")
    if aid:
        for sc in clusters:
            if sc.get("id") == aid:
                return sc
    for sc in clusters:
        if sc.get("sameAsCentralCluster", True):
            return sc
    return clusters[0]


def active_secured_cluster(lab: dict[str, Any]) -> dict[str, Any]:
    return preferred_secured_cluster(lab)


def flatten_active_lab(doc: dict[str, Any]) -> dict[str, Any]:
    """v1-shaped view of the active lab for module helpers (centralCluster + securedCluster)."""
    lab = active_lab(doc)
    sc = active_secured_cluster(lab)
    return {
        "version": 1,
        "insecureSkipTlsVerify": bool(lab.get("insecureSkipTlsVerify", False)),
        "centralCluster": lab.get("centralCluster")
        or {"openshift": empty_openshift(), "central": empty_central()},
        "securedCluster": {
            "sameAsCentralCluster": bool(sc.get("sameAsCentralCluster", True)),
            "openshift": sc.get("openshift") or empty_openshift(),
        },
        # Extras for logging (ignored by old readers)
        "_activeLabId": lab.get("id") or "",
        "_activeLabName": lab.get("name") or "",
        "_activeSecuredClusterId": sc.get("id") or "",
        "_activeSecuredClusterName": sc.get("name") or "",
    }


def lab_log_blurb(doc: dict[str, Any] | None = None) -> str:
    """Short lab context for tee'd log dividers."""
    try:
        flat = flatten_active_lab(doc or {})
    except Exception:
        return "lab=? central=? sc=?"
    lab_id = flat.get("_activeLabId") or "?"
    central = _host_hint(
        ((flat.get("centralCluster") or {}).get("central") or {}).get("consoleUrl") or ""
    ) or "?"
    sc_name = flat.get("_activeSecuredClusterName") or "?"
    same = bool((flat.get("securedCluster") or {}).get("sameAsCentralCluster", True))
    if same:
        sc_bit = f"{sc_name}(same-as-central)"
    else:
        sc_bit = sc_name
    return f"lab={lab_id} central={central} sc={sc_bit}"
