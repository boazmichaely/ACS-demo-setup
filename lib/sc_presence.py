"""Detect whether a module's secured-cluster footprint exists on a given SC.

Used by the orchestrator (``single`` / ``multi-warn`` policy) and the GUI picker.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from lib.module_orchestrate import impact_planes, load_modules_catalog, module_row
from lib.openshift import ensure_oc

# Namespace / project footprint for most SC modules.
# users-part1-ocp uses an OAuth IdP marker instead (see probe_users_part1).
PRESENCE_NAMESPACE: dict[str, str] = {
    "ms-demo": "ms-demo",
    "init-demo": "acs-init-container-test",
    "syslog-notifier": "acs-syslog-demo",
    "splunk-TA": "splunk-demo",
    "virt-vm-demo": "acs-virt-demo",
    "openshift-mcp": "openshift-mcp",
    "openshift-mcp-gateway": "mcp-gateway",
    "acs-lightspeed": "openshift-lightspeed",
    "acs-mcp": "acs-mcp",
    "prometheus": "openshift-user-workload-monitoring",
    "secrets-manager": "vault",
}

USERS_PART1_IDP = "lab_htpasswd"
USERS_PART1_SECRET_NS = "openshift-config"
USERS_PART1_SECRET = "htpasswd-secret"

POLICY_SINGLE = "single"
POLICY_MULTI_WARN = "multi-warn"
POLICY_MULTI = "multi"
VALID_POLICIES = frozenset({POLICY_SINGLE, POLICY_MULTI_WARN, POLICY_MULTI})


def secured_cluster_policy(row: dict[str, Any]) -> str | None:
    """Return policy for modules with secured-cluster impact; else None."""
    planes = impact_planes(row)
    if "secured-cluster" not in planes and "openshift" not in planes:
        return None
    raw = str(row.get("securedClusterPolicy") or "").strip().lower()
    if raw in VALID_POLICIES:
        return raw
    # Safe default for SC modules missing the field.
    return POLICY_SINGLE


def _oc_get_ns(kubeconfig: str, namespace: str) -> bool:
    try:
        r = subprocess.run(
            [
                "oc",
                "--kubeconfig",
                kubeconfig,
                "get",
                "ns",
                namespace,
                "-o",
                "name",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _probe_users_part1(kubeconfig: str) -> bool:
    try:
        r = subprocess.run(
            [
                "oc",
                "--kubeconfig",
                kubeconfig,
                "-n",
                USERS_PART1_SECRET_NS,
                "get",
                "secret",
                USERS_PART1_SECRET,
                "-o",
                "name",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if r.returncode == 0:
            return True
        r2 = subprocess.run(
            [
                "oc",
                "--kubeconfig",
                kubeconfig,
                "get",
                "oauth",
                "cluster",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if r2.returncode != 0:
            return False
        data = json.loads(r2.stdout or "{}")
        for idp in data.get("spec", {}).get("identityProviders") or []:
            if (idp.get("name") or "") == USERS_PART1_IDP:
                return True
        return False
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def module_present_on_sc(
    module_id: str,
    sc_id: str,
    *,
    root: Path | None = None,
) -> bool:
    """True if this module's footprint is detectable on the secured cluster."""
    mid = (module_id or "").strip()
    sid = (sc_id or "").strip()
    if not mid or not sid:
        return False
    try:
        kc_path = ensure_oc(secured_cluster_id=sid)
        kc = str(kc_path)
    except Exception:
        return False
    if mid == "users-part1-ocp":
        return _probe_users_part1(kc)
    ns = PRESENCE_NAMESPACE.get(mid)
    if not ns:
        return False
    return _oc_get_ns(kc, ns)


def presence_by_sc(
    module_id: str,
    sc_ids: list[str],
    *,
    root: Path | None = None,
) -> dict[str, bool]:
    """Map sc_id → present for the given ids."""
    out: dict[str, bool] = {}
    for sid in sc_ids:
        sid = (sid or "").strip()
        if not sid:
            continue
        out[sid] = module_present_on_sc(module_id, sid, root=root)
    return out


def other_scs_with_presence(
    module_id: str,
    target_sc_ids: list[str],
    all_lab_sc_ids: list[str],
    *,
    root: Path | None = None,
) -> list[str]:
    """Return lab SC ids (excluding targets) where the module footprint exists."""
    targets = {(s or "").strip() for s in target_sc_ids if (s or "").strip()}
    found: list[str] = []
    for sid in all_lab_sc_ids:
        sid = (sid or "").strip()
        if not sid or sid in targets:
            continue
        if module_present_on_sc(module_id, sid, root=root):
            found.append(sid)
    return found


def enforce_secured_cluster_policy(
    module_id: str,
    action: str,
    sc_ids: list[str],
    *,
    force: bool = False,
    root: Path | None = None,
) -> list[str]:
    """Validate SC selection against catalog policy.

    Returns warning strings (non-fatal). Raises RuntimeError on hard violations.
    Only applies to ``run`` / ``uninstall``; ``status`` returns [].
    """
    act = (action or "").strip().lower()
    if act not in ("run", "uninstall"):
        return []

    try:
        row = module_row(module_id, root)
    except KeyError:
        return []

    policy = secured_cluster_policy(row)
    if policy is None:
        return []

    ids = [s.strip() for s in sc_ids if (s or "").strip()]
    # Dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            uniq.append(sid)

    warnings: list[str] = []
    if not uniq:
        return warnings

    if policy == POLICY_SINGLE and len(uniq) > 1:
        raise RuntimeError(
            f"{module_id}: securedClusterPolicy=single allows at most one "
            f"secured cluster; got {len(uniq)}: {', '.join(uniq)}"
        )

    # Presence across the lab (all SCs in credentials).
    from lib.central import load_lab_document
    from lib.lab_doc import active_lab

    try:
        lab = active_lab(load_lab_document(root))
        lab_ids = [
            str(c.get("id") or "").strip()
            for c in (lab.get("securedClusters") or [])
            if (c.get("id") or "").strip()
        ]
        name_by_id = {
            str(c.get("id") or "").strip(): str(c.get("name") or c.get("id") or "")
            for c in (lab.get("securedClusters") or [])
        }
    except Exception:
        lab_ids = list(uniq)
        name_by_id = {s: s for s in uniq}

    others = other_scs_with_presence(module_id, uniq, lab_ids, root=root)
    if not others:
        return warnings

    labels = ", ".join(name_by_id.get(s, s) for s in others)

    if policy == POLICY_SINGLE and act == "run":
        raise RuntimeError(
            f"{module_id}: already installed on secured cluster(s) {labels}. "
            f"Uninstall there first, or select that cluster only "
            f"(securedClusterPolicy=single)."
        )

    if policy == POLICY_MULTI_WARN and act == "run":
        msg = (
            f"{module_id}: already present on secured cluster(s) {labels}; "
            f"installing on additional cluster(s) {', '.join(uniq)}"
        )
        if force:
            warnings.append(msg + " (--force)")
        else:
            warnings.append(msg + " (continuing; GUI should have confirmed)")
        return warnings

    return warnings


def catalog_policies(root: Path | None = None) -> dict[str, str | None]:
    """module_id → policy (or None if no SC plane)."""
    out: dict[str, str | None] = {}
    for row in load_modules_catalog(root):
        mid = str(row.get("id") or "").strip()
        if mid:
            out[mid] = secured_cluster_policy(row)
    return out
