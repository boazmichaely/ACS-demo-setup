"""OpenShift / oc access for the **active** lab.

**Source of truth:** ``lab-credentials.json`` (this tool). Module ``oc`` never
treats the operator’s interactive ``~/.kube/config`` as authoritative.

**Derived cache:** kubeconfigs under ``<repo>/.cache/kubeconfigs/``:

- Default (soft-default SC): ``<lab-id>.kubeconfig``
- Per secured cluster (e.g. compliance-operator fan-out):
  ``<lab-id>__<sc-id>.kubeconfig``

Safe to delete; ``ensure`` regenerates them.

Troubleshoot via the orchestrator (same CLI as ``--status`` / ``--run``)::

  ./scripts/acs-setup.sh --oc-status
  ./scripts/acs-setup.sh --oc-login [--force]

Bash modules call ``python -m lib.openshift login --print-kubeconfig`` internally and
``export KUBECONFIG`` so later ``oc`` in that shell uses the lab file.

Compliance Operator (and similar fan-out) uses
``login --secured-cluster-id ID --print-kubeconfig``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from lib.central import load_lab_credentials, load_lab_document, repo_root

KUBECONFIG_DIRNAME = ".cache/kubeconfigs"
# Synthetic id when the lab has no securedClusters (Central OpenShift only).
CENTRAL_ONLY_SC_ID = "_central"
# Mandatory workload stamp for OpenShift-plane module applies (lab SC name).
DEMO_SC_LABEL = "acs-demo-setup/secured-cluster"


def kubeconfig_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / KUBECONFIG_DIRNAME


def _safe_id(text: str, fallback: str = "default") -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "").strip()) or fallback
    return safe[:64]


def lab_id_from_creds(creds: dict[str, Any]) -> str:
    lid = (creds.get("_activeLabId") or "").strip()
    if lid:
        return lid
    # Fallback slug from Central URL host
    central = ((creds.get("centralCluster") or {}).get("central") or {}).get(
        "consoleUrl"
    ) or ""
    host = urlparse(
        central if "://" in central else f"https://{central}"
    ).hostname or "default"
    return _safe_id(host)


def kubeconfig_path_for_lab(lab_id: str, root: Path | None = None) -> Path:
    return kubeconfig_dir(root) / f"{_safe_id(lab_id)}.kubeconfig"


def kubeconfig_path_for_secured_cluster(
    lab_id: str, sc_id: str, root: Path | None = None
) -> Path:
    """Per-lab + per-secured-cluster kubeconfig path."""
    return (
        kubeconfig_dir(root)
        / f"{_safe_id(lab_id)}__{_safe_id(sc_id or CENTRAL_ONLY_SC_ID)}.kubeconfig"
    )


def _openshift_block(creds: dict[str, Any]) -> dict[str, Any]:
    secured = creds.get("securedCluster") or {}
    if secured.get("sameAsCentralCluster", True):
        return (creds.get("centralCluster") or {}).get("openshift") or {}
    return secured.get("openshift") or {}


def _flat_creds_for_sc(lab: dict[str, Any], sc: dict[str, Any]) -> dict[str, Any]:
    """v1-shaped creds so _openshift_block / expected_api_url work for one SC."""
    return {
        "version": 1,
        "insecureSkipTlsVerify": bool(lab.get("insecureSkipTlsVerify", False)),
        "centralCluster": lab.get("centralCluster")
        or {"openshift": {}, "central": {}},
        "securedCluster": {
            "sameAsCentralCluster": bool(sc.get("sameAsCentralCluster", True)),
            "openshift": sc.get("openshift") or {},
        },
        "_activeLabId": lab.get("id") or "",
        "_activeLabName": lab.get("name") or "",
        "_activeSecuredClusterId": sc.get("id") or "",
        "_activeSecuredClusterName": sc.get("name") or "",
    }


def list_secured_cluster_targets(
    *,
    name_filter: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Secured clusters on the active lab for multi-SC modules (e.g. CO).

    Empty ``securedClusters`` → one synthetic Central-OpenShift target.
    Optional ``name_filter`` matches lab SC ``name`` (case-sensitive).
    """
    from lib.lab_doc import active_lab, empty_secured_cluster

    doc = load_lab_document(root)
    lab = active_lab(doc)
    clusters = list(lab.get("securedClusters") or [])
    if not clusters:
        clusters = [
            empty_secured_cluster(
                sc_id=CENTRAL_ONLY_SC_ID, name="central", same_as_central=True
            )
        ]

    want = (name_filter or "").strip()
    out: list[dict[str, Any]] = []
    for sc in clusters:
        name = (sc.get("name") or "").strip() or (sc.get("id") or "")
        if want and name != want and (sc.get("id") or "") != want:
            continue
        sid = (sc.get("id") or "").strip() or CENTRAL_ONLY_SC_ID
        flat = _flat_creds_for_sc(lab, sc)
        try:
            api = expected_api_url(flat)
            cred_err = None
        except RuntimeError as exc:
            api = None
            cred_err = str(exc)
        out.append(
            {
                "id": sid,
                "name": name or sid,
                "sameAsCentralCluster": bool(sc.get("sameAsCentralCluster", True)),
                "apiUrl": api,
                "credsError": cred_err,
            }
        )
    return out


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

    m = re.match(
        r"^console-openshift-console\.apps\.(.+)$",
        host,
        flags=re.IGNORECASE,
    )
    if m:
        return f"https://api.{m.group(1)}:6443"

    if host.startswith("api."):
        return f"https://{host}:6443" if ":6443" not in raw else f"https://{host}"

    raise RuntimeError(
        f"cannot derive OpenShift API URL from console host {host}; "
        "use a standard console-openshift-console.apps… URL"
    )


def expected_api_url(creds: dict[str, Any]) -> str:
    ocp = _openshift_block(creds)
    console = (ocp.get("consoleUrl") or "").strip()
    if not console:
        raise RuntimeError(
            "active lab has no OpenShift consoleUrl "
            "(Central OpenShift if same-as-Central, else secured-cluster OpenShift). "
            "Refusing to use a leftover oc session from another lab."
        )
    return api_url_from_console(console)


def _normalize_server(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    # Treat default https:443 as equivalent to bare host:6443 only when both are API ports
    return f"{host}:{port}"


def _servers_match(expected_api: str, actual_server: str) -> bool:
    exp = _normalize_server(expected_api)
    act = _normalize_server(actual_server)
    if not exp or not act:
        return False
    if exp == act:
        return True
    # api.foo:6443 vs api.foo:443 rarely; also compare host only if ports are API-ish
    exp_host = exp.rsplit(":", 1)[0]
    act_host = act.rsplit(":", 1)[0]
    return exp_host == act_host and exp_host.startswith("api.")


def _run_oc(
    args: list[str],
    *,
    kubeconfig: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["oc", *args]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    if kubeconfig is not None:
        run_env["KUBECONFIG"] = str(kubeconfig)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=run_env,
        input=input_text,
    )


def oc_whoami_ok(kubeconfig: Path | None = None) -> bool:
    if not shutil.which("oc"):
        return False
    try:
        result = _run_oc(["whoami"], kubeconfig=kubeconfig, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def oc_show_server(kubeconfig: Path | None = None) -> str:
    if not shutil.which("oc"):
        return ""
    try:
        result = _run_oc(
            ["whoami", "--show-server"], kubeconfig=kubeconfig, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _login_to_lab(creds: dict[str, Any], kubeconfig: Path, api: str) -> None:
    ocp = _openshift_block(creds)
    token = (ocp.get("apiToken") or "").strip()
    user = (ocp.get("adminUsername") or "").strip()
    password = (ocp.get("adminPassword") or "").strip()

    kubeconfig.parent.mkdir(parents=True, exist_ok=True)
    if token:
        login_args = [
            "login",
            api,
            f"--token={token}",
            "--insecure-skip-tls-verify=true",
        ]
    else:
        missing: list[str] = []
        if not user:
            missing.append("adminUsername")
        if not password:
            missing.append("adminPassword")
        if missing:
            raise RuntimeError(
                "OpenShift credentials incomplete in lab-credentials.json for active lab "
                f"(missing: {', '.join(missing)}; or set apiToken for SSO labs). "
                f"Target API would be {api}."
            )
        login_args = [
            "login",
            api,
            f"--username={user}",
            f"--password={password}",
            "--insecure-skip-tls-verify=true",
        ]

    login = _run_oc(login_args, kubeconfig=kubeconfig, timeout=90)
    if login.returncode != 0:
        detail = (login.stderr or login.stdout or "").strip() or f"exit {login.returncode}"
        raise RuntimeError(f"oc login to {api} (kubeconfig={kubeconfig}) failed: {detail}")


def ensure_oc(
    creds: dict[str, Any] | None = None,
    *,
    force: bool = False,
    secured_cluster_id: str | None = None,
) -> Path:
    """Ensure oc talks to the active lab (or a specific secured cluster).

    Default (no ``secured_cluster_id``): soft-default SC → per-lab kubeconfig.
    With ``secured_cluster_id``: that SC’s OpenShift → per-lab+SC kubeconfig.

    Returns the kubeconfig path and sets ``os.environ["KUBECONFIG"]`` for this process.
    """
    if not shutil.which("oc"):
        raise RuntimeError("oc not on PATH")

    sc_id = (secured_cluster_id or "").strip()
    if sc_id:
        from lib.lab_doc import active_lab, empty_secured_cluster

        v2 = load_lab_document()
        lab = active_lab(v2)
        lab_id = (lab.get("id") or "").strip() or lab_id_from_creds(
            load_lab_credentials()
        )
        clusters = list(lab.get("securedClusters") or [])
        sc: dict[str, Any] | None = None
        if sc_id == CENTRAL_ONLY_SC_ID and not clusters:
            sc = empty_secured_cluster(
                sc_id=CENTRAL_ONLY_SC_ID, name="central", same_as_central=True
            )
        else:
            for item in clusters:
                if (item.get("id") or "").strip() == sc_id:
                    sc = item
                    break
        if sc is None:
            known = ", ".join(
                f"{c.get('name') or '?'}({c.get('id') or '?'})" for c in clusters
            ) or "(none)"
            raise RuntimeError(
                f"secured cluster id {sc_id!r} not in active lab securedClusters ({known})"
            )
        doc = _flat_creds_for_sc(lab, sc)
        kc = kubeconfig_path_for_secured_cluster(lab_id, sc_id)
    else:
        doc = creds if creds is not None else load_lab_credentials()
        lab_id = lab_id_from_creds(doc)
        kc = kubeconfig_path_for_lab(lab_id)

    api = expected_api_url(doc)

    need_login = force or not kc.is_file() or not oc_whoami_ok(kc)
    if not need_login:
        current = oc_show_server(kc)
        if not _servers_match(api, current):
            need_login = True

    if need_login:
        _login_to_lab(doc, kc, api)
        if not oc_whoami_ok(kc):
            raise RuntimeError(
                f"oc login to {api} appeared to succeed but whoami still fails "
                f"(kubeconfig={kc})"
            )
        current = oc_show_server(kc)
        if current and not _servers_match(api, current):
            raise RuntimeError(
                f"after login, oc server is {current!r} but expected {api!r} "
                f"(kubeconfig={kc})"
            )

    os.environ["KUBECONFIG"] = str(kc)
    return kc


def ensure_oc_message(
    creds: dict[str, Any] | None = None,
    *,
    force: bool = False,
    secured_cluster_id: str | None = None,
) -> str | None:
    """Return None on success, or an error message string."""
    try:
        ensure_oc(
            creds, force=force, secured_cluster_id=secured_cluster_id
        )
        return None
    except RuntimeError as exc:
        return str(exc)


def show_active(root: Path | None = None) -> dict[str, Any]:
    creds = load_lab_credentials(root)
    lab_id = lab_id_from_creds(creds)
    kc = kubeconfig_path_for_lab(lab_id, root)
    info: dict[str, Any] = {
        "activeLabId": lab_id,
        "activeLabName": creds.get("_activeLabName") or lab_id,
        "kubeconfig": str(kc),
        "kubeconfigExists": kc.is_file(),
        "ocOnPath": bool(shutil.which("oc")),
    }
    try:
        info["expectedApi"] = expected_api_url(creds)
        info["expectedApiError"] = None
    except RuntimeError as exc:
        info["expectedApi"] = None
        info["expectedApiError"] = str(exc)

    info["ocServer"] = None
    info["ocWhoamiOk"] = False
    info["ocUser"] = None
    info["serverMatches"] = False

    if info["kubeconfigExists"] and info["ocOnPath"]:
        info["ocServer"] = oc_show_server(kc) or None
        info["ocWhoamiOk"] = oc_whoami_ok(kc)
        if info["ocWhoamiOk"]:
            w = _run_oc(["whoami"], kubeconfig=kc, timeout=20)
            info["ocUser"] = (w.stdout or "").strip() or None
        if info.get("expectedApi") and info.get("ocServer"):
            info["serverMatches"] = _servers_match(
                info["expectedApi"], info["ocServer"]
            )

    problems: list[str] = []
    hints: list[str] = []
    if not info["ocOnPath"]:
        problems.append("oc is not on PATH")
    if info.get("expectedApiError"):
        problems.append(info["expectedApiError"])
        hints.append(
            "Fill OpenShift console URL and apiToken (SSO) or user/password for the "
            "active lab in lab-credentials.json, then: ./scripts/acs-setup.sh --oc-login"
        )
    elif not info["kubeconfigExists"]:
        problems.append("no kubeconfig file for this lab yet")
        hints.append("Run: ./scripts/acs-setup.sh --oc-login")
    elif not info["ocWhoamiOk"]:
        problems.append("kubeconfig exists but oc whoami failed (expired or invalid login)")
        hints.append("Run: ./scripts/acs-setup.sh --oc-login --force")
    elif not info.get("ocServer"):
        problems.append("could not read oc server from kubeconfig")
        hints.append("Run: ./scripts/acs-setup.sh --oc-login --force")
    elif not info["serverMatches"]:
        problems.append(
            f"kubeconfig server {info['ocServer']!r} does not match active lab "
            f"API {info['expectedApi']!r}"
        )
        hints.append("Run: ./scripts/acs-setup.sh --oc-login --force")

    info["ok"] = len(problems) == 0
    info["problems"] = problems
    info["hints"] = hints
    return info


@dataclass(frozen=True)
class ModuleTarget:
    """Resolved secured-cluster target for an OpenShift-plane module invoke."""

    id: str
    name: str
    same_as_central: bool

    @property
    def labels(self) -> dict[str, str]:
        return demo_sc_labels(self.name)


def _env_sc_id() -> str:
    return (os.environ.get("ACS_DEMO_SC_ID") or "").strip()


def _env_sc_name() -> str:
    return (os.environ.get("ACS_DEMO_SC_NAME") or "").strip()


def demo_sc_labels(sc_name: str) -> dict[str, str]:
    name = (sc_name or "").strip()
    if not name:
        raise RuntimeError(
            f"cannot build {DEMO_SC_LABEL}: secured cluster name is empty"
        )
    return {DEMO_SC_LABEL: name}


def resolve_module_target(
    secured_cluster_id: str | None = None,
    *,
    root: Path | None = None,
) -> ModuleTarget:
    """Resolve a lab secured cluster for OpenShift-plane work and labels.

    ``secured_cluster_id`` wins; else ``ACS_DEMO_SC_ID``; else Target cluster
    for Setup / synthetic Central-only id when the lab has no SCs.
    """
    from lib.lab_doc import (
        active_lab,
        empty_secured_cluster,
        preferred_secured_cluster,
    )

    doc = load_lab_document(root)
    lab = active_lab(doc)
    clusters = list(lab.get("securedClusters") or [])
    sc_id = (secured_cluster_id or "").strip() or _env_sc_id()

    sc: dict[str, Any] | None = None
    if sc_id:
        if sc_id == CENTRAL_ONLY_SC_ID and not clusters:
            sc = empty_secured_cluster(
                sc_id=CENTRAL_ONLY_SC_ID, name="central", same_as_central=True
            )
        else:
            for item in clusters:
                if (item.get("id") or "").strip() == sc_id:
                    sc = item
                    break
        if sc is None:
            known = ", ".join(
                f"{c.get('name') or '?'}({c.get('id') or '?'})" for c in clusters
            ) or "(none)"
            raise RuntimeError(
                f"secured cluster id {sc_id!r} not in active lab securedClusters ({known})"
            )
    elif not clusters:
        sc = empty_secured_cluster(
            sc_id=CENTRAL_ONLY_SC_ID, name="central", same_as_central=True
        )
    else:
        sc = preferred_secured_cluster(lab)

    tid = (sc.get("id") or "").strip()
    tname = (sc.get("name") or "").strip() or _env_sc_name()
    if not tname:
        raise RuntimeError(
            f"secured cluster {tid!r} has an empty name; set name in lab credentials"
        )
    return ModuleTarget(
        id=tid or CENTRAL_ONLY_SC_ID,
        name=tname,
        same_as_central=bool(sc.get("sameAsCentralCluster", True)),
    )


def merge_demo_labels(obj: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    """Merge ``labels`` into ``metadata.labels`` on one Kubernetes object dict."""
    if not isinstance(obj, dict):
        return obj
    meta = obj.setdefault("metadata", {})
    if not isinstance(meta, dict):
        meta = {}
        obj["metadata"] = meta
    existing = meta.get("labels")
    if not isinstance(existing, dict):
        existing = {}
    merged = dict(existing)
    merged.update(labels)
    meta["labels"] = merged
    return obj


def label_manifest_documents(raw: str | bytes, labels: dict[str, str]) -> str:
    """Split multi-doc YAML, stamp labels on each object with metadata, re-serialize."""
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    docs = list(yaml.safe_load_all(text))
    out: list[Any] = []
    for doc in docs:
        if doc is None:
            continue
        if isinstance(doc, dict) and (
            "metadata" in doc or "kind" in doc or "apiVersion" in doc
        ):
            out.append(merge_demo_labels(doc, labels))
        else:
            out.append(doc)
    if not out:
        raise RuntimeError("no Kubernetes documents found to label")
    buf = io.StringIO()
    yaml.safe_dump_all(
        out,
        buf,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return buf.getvalue()


def apply_labeled(
    path_or_stdin: str | Path | None = None,
    *,
    secured_cluster_id: str | None = None,
    dry_run: bool = False,
    raw: str | bytes | None = None,
) -> None:
    """``oc apply`` manifests after stamping ``DEMO_SC_LABEL``.

    Pass ``path_or_stdin`` as a file path, ``"-"`` for stdin, or supply ``raw``.
    """
    target = resolve_module_target(secured_cluster_id)
    ensure_oc(secured_cluster_id=target.id)
    labels = target.labels

    if raw is not None:
        body = raw
    elif path_or_stdin is None or str(path_or_stdin) == "-":
        body = sys.stdin.read()
    else:
        body = Path(path_or_stdin).read_text(encoding="utf-8")

    labeled = label_manifest_documents(body, labels)
    apply_args = ["apply", "-f", "-"]
    if dry_run:
        apply_args.extend(["--dry-run=client"])
    result = _run_oc(
        apply_args,
        kubeconfig=Path(os.environ["KUBECONFIG"]),
        timeout=180,
        input_text=labeled,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or (
            f"exit {result.returncode}"
        )
        raise RuntimeError(f"oc apply-labeled failed: {detail}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")


def delete_by_demo_labels(
    *,
    secured_cluster_id: str | None = None,
    namespace: str | None = None,
    resource: str = "all",
    dry_run: bool = False,
) -> None:
    """Delete resources selected by ``DEMO_SC_LABEL=<lab SC name>``."""
    target = resolve_module_target(secured_cluster_id)
    ensure_oc(secured_cluster_id=target.id)
    selector = f"{DEMO_SC_LABEL}={target.name}"
    args = ["delete", resource, "-l", selector]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    if dry_run:
        args.append("--dry-run=client")
    result = _run_oc(
        args, kubeconfig=Path(os.environ["KUBECONFIG"]), timeout=180
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or (
            f"exit {result.returncode}"
        )
        raise RuntimeError(f"oc delete-by-demo-labels failed: {detail}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")


def format_status_report(info: dict[str, Any]) -> str:
    """Human-readable verdict for --oc-status."""
    lines: list[str] = []
    if info.get("ok"):
        lines.append("OK - active lab OpenShift access looks good")
    else:
        lines.append("PROBLEM - active lab OpenShift access is not ready for modules")

    lines.append(f"  active lab : {info.get('activeLabName') or info.get('activeLabId')}")
    if info.get("expectedApi"):
        lines.append(f"  expected   : {info['expectedApi']}")
    elif info.get("expectedApiError"):
        lines.append(f"  expected   : (unavailable)")
    lines.append(f"  kubeconfig : {info.get('kubeconfig')}")
    lines.append(
        f"  file       : {'present' if info.get('kubeconfigExists') else 'missing'}"
    )
    if info.get("ocUser") or info.get("ocWhoamiOk") is not None:
        user = info.get("ocUser") or ("(whoami failed)" if info.get("kubeconfigExists") else "-")
        lines.append(f"  oc user    : {user}")
    if info.get("ocServer"):
        match = "yes" if info.get("serverMatches") else "NO - wrong cluster"
        lines.append(f"  oc server  : {info['ocServer']} (matches expected: {match})")
    elif info.get("kubeconfigExists"):
        lines.append("  oc server  : (unknown)")

    for problem in info.get("problems") or []:
        lines.append(f"  problem    : {problem}")
    for hint in info.get("hints") or []:
        lines.append(f"  next       : {hint}")

    if info.get("ok"):
        lines.append("  next       : modules that call ensure_oc will use this kubeconfig")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lib.openshift",
        description="Per-lab oc kubeconfig helper (active lab from lab-credentials.json)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser(
        "status", help="OK/PROBLEM report for the active lab (read-only)"
    )
    p_status.add_argument("--json", action="store_true", help="Machine-readable JSON")

    p_login = sub.add_parser(
        "login", help="Create/refresh kubeconfig for the active lab from lab-credentials"
    )
    p_login.add_argument(
        "--force", action="store_true", help="Force oc login even if session looks valid"
    )
    p_login.add_argument(
        "--print-kubeconfig",
        action="store_true",
        help="Print kubeconfig path on stdout (for: export KUBECONFIG=$(…))",
    )
    p_login.add_argument(
        "--secured-cluster-id",
        default="",
        help="Login to this secured cluster (not the lab soft-default SC)",
    )

    p_list = sub.add_parser(
        "list-secured-clusters",
        help="JSON list of active-lab secured clusters (for multi-SC modules)",
    )
    p_list.add_argument(
        "--name",
        default="",
        help="Filter to one secured cluster name or id",
    )

    p_apply = sub.add_parser(
        "apply-labeled",
        help=f"oc apply after stamping {DEMO_SC_LABEL}=<lab SC name>",
    )
    p_apply.add_argument(
        "-f",
        "--filename",
        default="-",
        help="Manifest file path, or - for stdin (default)",
    )
    p_apply.add_argument(
        "--secured-cluster-id",
        default="",
        help="Lab secured cluster id (else ACS_DEMO_SC_ID / Target)",
    )
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Client-side dry-run only",
    )

    p_del = sub.add_parser(
        "delete-by-demo-labels",
        help=f"oc delete -l {DEMO_SC_LABEL}=<lab SC name>",
    )
    p_del.add_argument(
        "--secured-cluster-id",
        default="",
        help="Lab secured cluster id (else ACS_DEMO_SC_ID / Target)",
    )
    p_del.add_argument(
        "--namespace",
        "-n",
        default="",
        help="Namespace (default: all namespaces)",
    )
    p_del.add_argument(
        "--resource",
        default="all",
        help="Resource type for oc delete (default: all)",
    )
    p_del.add_argument(
        "--dry-run",
        action="store_true",
        help="Client-side dry-run only",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd == "status":
        try:
            info = show_active()
        except RuntimeError as exc:
            print(f"PROBLEM - {exc}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(info, indent=2))
        else:
            print(format_status_report(info))
        return 0 if info.get("ok") else 1

    if args.cmd == "list-secured-clusters":
        try:
            rows = list_secured_cluster_targets(
                name_filter=(getattr(args, "name", "") or "").strip() or None
            )
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(json.dumps(rows))
        return 0

    if args.cmd == "login":
        force = bool(getattr(args, "force", False))
        sc_id = (getattr(args, "secured_cluster_id", "") or "").strip() or None
        try:
            kc = ensure_oc(force=force, secured_cluster_id=sc_id)
        except RuntimeError as exc:
            if sc_id or getattr(args, "print_kubeconfig", False):
                print(exc, file=sys.stderr)
            else:
                try:
                    info = show_active()
                    info["ok"] = False
                    if str(exc) not in (info.get("problems") or []):
                        info.setdefault("problems", []).insert(0, str(exc))
                    print(format_status_report(info), file=sys.stderr)
                except RuntimeError:
                    print(exc, file=sys.stderr)
            return 1
        if getattr(args, "print_kubeconfig", False):
            print(kc)
            return 0
        extra = f" sc={sc_id}" if sc_id else ""
        print(f"OK - refreshed kubeconfig{extra}\n  kubeconfig : {kc}")
        return 0

    if args.cmd == "apply-labeled":
        sc_id = (getattr(args, "secured_cluster_id", "") or "").strip() or None
        try:
            apply_labeled(
                getattr(args, "filename", "-"),
                secured_cluster_id=sc_id,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    if args.cmd == "delete-by-demo-labels":
        sc_id = (getattr(args, "secured_cluster_id", "") or "").strip() or None
        ns = (getattr(args, "namespace", "") or "").strip() or None
        try:
            delete_by_demo_labels(
                secured_cluster_id=sc_id,
                namespace=ns,
                resource=(getattr(args, "resource", "") or "all").strip() or "all",
                dry_run=bool(getattr(args, "dry_run", False)),
            )
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
