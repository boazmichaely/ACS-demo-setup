#!/usr/bin/env python3
"""OpenShift Lightspeed on Central OCP + RHACS 5.0 risk AI connectivity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from lib.acs_lightspeed_defaults import (  # noqa: E402
    effective_open_shift_lightspeed,
    load_defaults as load_acs_lightspeed_defaults,
)
from lib.central import (  # noqa: E402
    central_connection,
    central_console_url,
    central_request,
    check_central_auth,
    load_lab_credentials,
)
from lib.openshift import CENTRAL_ONLY_SC_ID, ensure_oc  # noqa: E402

MODULE_ID = "acs-lightspeed"
OLS_NS = "openshift-lightspeed"
SECRET_NAME = "credentials"
OLSCONFIG_NAME = "cluster"
SUB_NAME = "lightspeed-operator"
OG_NAME = "openshift-lightspeed"
NP_NAME = "allow-acs-central"
CRB_NAME = "acs-demo-central-ols-user"
CATALOG_SOURCE = "redhat-operators"
CATALOG_NS = "openshift-marketplace"
CHANNEL = "stable"
FEATURE_FLAG = "ROX_LIGHTSPEED_RISK_SUMMARY"
DEFAULT_OLS_ENDPOINT = "https://lightspeed-app-server.openshift-lightspeed.svc:8443"
DEMO_LABEL_KEY = "acs-demo-setup/module"
DEMO_LABEL_VAL = "acs-lightspeed"


def normalize_plane(raw: str | None) -> str | None:
    s = (raw or "").strip().lower().replace("_", "-")
    if not s or s == "central":
        return None
    if s in ("central-api", "central-ocp"):
        return s
    raise ValueError(f"unsupported plane {raw!r} (want central-api|central-ocp or omit)")


def want_central_ocp(plane: str | None) -> bool:
    return plane is None or plane == "central-ocp"


def want_central_api(plane: str | None) -> bool:
    return plane is None or plane == "central-api"


def run_oc(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["oc", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def run_oc_json(args: list[str]) -> Any:
    proc = run_oc([*args, "-o", "json"], check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"oc {' '.join(args)} failed: {detail}")
    return json.loads(proc.stdout)


def oc_exists(resource: str, name: str, *, namespace: str | None = None) -> bool:
    args = ["get", resource, name]
    if namespace:
        args.extend(["-n", namespace])
    return run_oc(args, check=False).returncode == 0


def ensure_central_oc() -> None:
    ensure_oc(secured_cluster_id=CENTRAL_ONLY_SC_ID)


def llm_settings(creds: dict[str, Any]) -> dict[str, str]:
    defaults = load_acs_lightspeed_defaults(ROOT)
    return effective_open_shift_lightspeed(
        creds.get("openShiftLightspeed"),
        repo_root=ROOT,
        defaults=defaults,
    )


def detect_central_ns_sa() -> tuple[str, str]:
    """Return (namespace, serviceaccount) for Central."""
    for ns in ("stackrox", "rhacs-operator", "acs-central"):
        if oc_exists("sa", "central", namespace=ns):
            return ns, "central"
    # Fallback: find deployment named central
    proc = run_oc(
        ["get", "deploy", "-A", "-o", "json"],
        check=False,
    )
    if proc.returncode == 0:
        items = (json.loads(proc.stdout).get("items") or [])
        for item in items:
            if (item.get("metadata") or {}).get("name") == "central":
                ns = (item.get("metadata") or {}).get("namespace") or "stackrox"
                return ns, "central"
    return "stackrox", "central"


def risk_url(creds: dict[str, Any]) -> str:
    console = (central_console_url(creds) or "").rstrip("/")
    if not console:
        return ""
    if not console.startswith(("http://", "https://")):
        console = f"https://{console}"
    return f"{console}/main/risk"


def emit_sections(sections: list[dict[str, Any]]) -> None:
    print(f"ACS_SECTIONS_JSON={json.dumps({'sections': sections}, separators=(',', ':'))}")


def emit_tsv(state: str, message: str) -> None:
    print(f"{MODULE_ID}\t{state}\t{message}")


def flag_enabled(base: str, auth: str, creds: dict[str, Any]) -> tuple[bool | None, str]:
    code, body = central_request(base, auth, "GET", "/v1/featureflags", creds=creds)
    if code != 200 or not isinstance(body, dict):
        return None, f"GET /v1/featureflags failed ({code})"
    for flag in body.get("featureFlags") or []:
        if (flag.get("envVar") or "") == FEATURE_FLAG:
            return bool(flag.get("enabled")), str(flag.get("name") or FEATURE_FLAG)
    return None, f"{FEATURE_FLAG} not listed"


def lightspeed_status(
    base: str, auth: str, creds: dict[str, Any]
) -> tuple[bool | None, str]:
    code, body = central_request(base, auth, "GET", "/v1/lightspeed/status", creds=creds)
    if code == 404:
        return None, "GET /v1/lightspeed/status not found (need RHACS 5.0+)"
    if code != 200 or not isinstance(body, dict):
        return None, f"GET /v1/lightspeed/status failed ({code}): {body}"
    available = bool(body.get("available"))
    msg = str(body.get("message") or ("available" if available else "unavailable"))
    return available, msg


def probe_ocp() -> dict[str, Any]:
    ensure_central_oc()
    ns_ok = oc_exists("ns", OLS_NS)
    sub_ok = ns_ok and oc_exists("subscription", SUB_NAME, namespace=OLS_NS)
    secret_ok = ns_ok and oc_exists("secret", SECRET_NAME, namespace=OLS_NS)
    ols_ok = ns_ok and oc_exists("olsconfig", OLSCONFIG_NAME)
    np_ok = ns_ok and oc_exists("networkpolicy", NP_NAME, namespace=OLS_NS)
    crb_ok = oc_exists("clusterrolebinding", CRB_NAME)
    ols_user = oc_exists("clusterrole", "ols-user")
    pods_ready = False
    pod_msg = "no pods"
    if ns_ok:
        proc = run_oc(
            [
                "get",
                "pods",
                "-n",
                OLS_NS,
                "-l",
                "app.kubernetes.io/part-of=openshift-lightspeed",
                "-o",
                "json",
            ],
            check=False,
        )
        if proc.returncode == 0:
            items = json.loads(proc.stdout).get("items") or []
            if not items:
                pod_msg = "0 pods"
            else:
                ready = 0
                for pod in items:
                    status = pod.get("status") or {}
                    phase = status.get("phase")
                    conds = status.get("conditions") or []
                    is_ready = any(
                        c.get("type") == "Ready" and c.get("status") == "True" for c in conds
                    )
                    if phase == "Running" and is_ready:
                        ready += 1
                pods_ready = ready == len(items) and ready > 0
                pod_msg = f"{ready}/{len(items)} Ready"
    csv_phase = ""
    if sub_ok:
        try:
            sub = run_oc_json(["get", "subscription", SUB_NAME, "-n", OLS_NS])
            csv = (sub.get("status") or {}).get("currentCSV") or ""
            if csv:
                csv_obj = run_oc_json(["get", "csv", csv, "-n", OLS_NS])
                csv_phase = (csv_obj.get("status") or {}).get("phase") or ""
        except RuntimeError:
            csv_phase = "unknown"
    return {
        "ns": ns_ok,
        "subscription": sub_ok,
        "secret": secret_ok,
        "olsconfig": ols_ok,
        "networkpolicy": np_ok,
        "clusterrolebinding": crb_ok,
        "ols_user_role": ols_user,
        "pods_ready": pods_ready,
        "pod_msg": pod_msg,
        "csv_phase": csv_phase,
    }


def cmd_status(plane: str | None) -> int:
    sections: list[dict[str, Any]] = []
    state = "ok"
    messages: list[str] = []
    creds = load_lab_credentials()
    risk = risk_url(creds)

    ocp: dict[str, Any] | None = None
    if want_central_ocp(plane):
        try:
            ocp = probe_ocp()
        except Exception as exc:
            state = "error"
            messages.append(f"Central OCP probe failed: {exc}")
            ocp = None
        if ocp:
            body_lines = [
                f"Namespace {OLS_NS}: {'present' if ocp['ns'] else 'missing'}",
                f"Subscription {SUB_NAME}: {'present' if ocp['subscription'] else 'missing'}"
                + (f" (CSV {ocp['csv_phase']})" if ocp.get("csv_phase") else ""),
                f"Secret {SECRET_NAME}: {'present' if ocp['secret'] else 'missing'} (token not shown)",
                f"OLSConfig {OLSCONFIG_NAME}: {'present' if ocp['olsconfig'] else 'missing'}",
                f"NetworkPolicy {NP_NAME}: {'present' if ocp['networkpolicy'] else 'missing'}",
                f"ClusterRoleBinding {CRB_NAME}: {'present' if ocp['clusterrolebinding'] else 'missing'}",
                f"ClusterRole ols-user: {'present' if ocp['ols_user_role'] else 'missing'}",
                f"OLS pods: {ocp['pod_msg']}",
            ]
            ocp_ok = all(
                [
                    ocp["ns"],
                    ocp["subscription"],
                    ocp["secret"],
                    ocp["olsconfig"],
                    ocp["networkpolicy"],
                    ocp["clusterrolebinding"],
                    ocp["pods_ready"],
                ]
            )
            if not ocp_ok and state == "ok":
                state = "needs-run"
            sections.append(
                {
                    "group": "central-ocp",
                    "title": "OpenShift Lightspeed on Central",
                    "summary": "ready" if ocp_ok else "incomplete",
                    "tag": "ok" if ocp_ok else "needs-run",
                    "tagLabel": "ready" if ocp_ok else "needs-run",
                    "body": "\n".join(body_lines),
                    "bodyFormat": "prose",
                }
            )

    if want_central_api(plane):
        try:
            base, auth = central_connection(creds)
            auth_err = check_central_auth(base, auth, creds=creds)
            if auth_err:
                state = "error"
                messages.append(auth_err)
                sections.append(
                    {
                        "group": "central-api",
                        "title": "RHACS Lightspeed connectivity",
                        "summary": "auth failed",
                        "tag": "error",
                        "tagLabel": "error",
                        "body": auth_err,
                        "bodyFormat": "prose",
                    }
                )
            else:
                enabled, flag_msg = flag_enabled(base, auth, creds)
                available, status_msg = lightspeed_status(base, auth, creds)
                api_ok = enabled is True and available is True
                if enabled is False and state == "ok":
                    state = "needs-run"
                if available is False and state == "ok":
                    state = "needs-run"
                if enabled is None or available is None:
                    state = "error"
                body = (
                    f"Feature flag {FEATURE_FLAG}: "
                    f"{'enabled' if enabled else 'disabled' if enabled is False else 'unknown'}"
                    f" ({flag_msg})\n"
                    f"GET /v1/lightspeed/status: "
                    f"{'available' if available else 'unavailable' if available is False else 'error'}"
                    f"\n{status_msg}\n"
                    "RHACS 5.0 uses the in-cluster OLS endpoint by default "
                    f"({DEFAULT_OLS_ENDPOINT}); there is no separate AI integration CRUD API."
                )
                sections.append(
                    {
                        "group": "central-api",
                        "title": "RHACS Lightspeed connectivity",
                        "summary": "ready" if api_ok else "not ready",
                        "tag": "ok" if api_ok else ("error" if state == "error" else "needs-run"),
                        "tagLabel": "ready" if api_ok else state,
                        "body": body,
                        "bodyFormat": "prose",
                    }
                )
                if not api_ok and state == "ok":
                    state = "needs-run"
        except Exception as exc:
            state = "error"
            messages.append(str(exc))
            sections.append(
                {
                    "group": "central-api",
                    "title": "RHACS Lightspeed connectivity",
                    "summary": "error",
                    "tag": "error",
                    "tagLabel": "error",
                    "body": str(exc),
                    "bodyFormat": "prose",
                }
            )

    demo_body = (
        "After Lightspeed is available, open Risk in Central, select a deployment, "
        "and use the AI risk explanation control. Output is AI-generated - review before acting."
    )
    if risk:
        demo_body += f"\n{risk}"
    sections.append(
        {
            "group": "demo",
            "title": "Talk track",
            "summary": "Risk AI",
            "body": demo_body,
            "bodyFormat": "prose",
        }
    )

    emit_sections(sections)
    if state == "ok":
        msg = "OpenShift Lightspeed ready for ACS risk AI"
        if risk:
            msg = f"{msg} {risk}"
        emit_tsv("ok", msg)
    elif state == "needs-run":
        emit_tsv(
            "needs-run",
            "; ".join(messages)
            if messages
            else "OpenShift Lightspeed or ACS connectivity incomplete - run this module",
        )
    else:
        emit_tsv("error", "; ".join(messages) or "acs-lightspeed status error")
    return 0 if state != "error" else 1


def apply_yaml(manifest: str, *, dry_run: bool) -> None:
    if dry_run:
        print("---")
        print(manifest.rstrip())
        return
    proc = subprocess.run(
        ["oc", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "oc apply failed").strip())
    if proc.stdout.strip():
        print(proc.stdout.strip())


def wait_for(
    predicate: Any,
    *,
    timeout_s: int,
    sleep_s: float,
    label: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"would wait for {label} (up to {timeout_s}s)")
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(sleep_s)
    raise RuntimeError(f"timed out waiting for {label}")


def install_operator(*, dry_run: bool) -> None:
    ns_yaml = f"""apiVersion: v1
kind: Namespace
metadata:
  name: {OLS_NS}
  labels:
    {DEMO_LABEL_KEY}: {DEMO_LABEL_VAL}
"""
    og_yaml = f"""apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: {OG_NAME}
  namespace: {OLS_NS}
  labels:
    {DEMO_LABEL_KEY}: {DEMO_LABEL_VAL}
spec:
  targetNamespaces:
  - {OLS_NS}
"""
    sub_yaml = f"""apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {SUB_NAME}
  namespace: {OLS_NS}
  labels:
    {DEMO_LABEL_KEY}: {DEMO_LABEL_VAL}
spec:
  channel: {CHANNEL}
  name: lightspeed-operator
  source: {CATALOG_SOURCE}
  sourceNamespace: {CATALOG_NS}
  installPlanApproval: Automatic
"""
    apply_yaml(ns_yaml, dry_run=dry_run)
    apply_yaml(og_yaml, dry_run=dry_run)
    apply_yaml(sub_yaml, dry_run=dry_run)

    def csv_succeeded() -> bool:
        if not oc_exists("subscription", SUB_NAME, namespace=OLS_NS):
            return False
        try:
            sub = run_oc_json(["get", "subscription", SUB_NAME, "-n", OLS_NS])
            csv = (sub.get("status") or {}).get("currentCSV") or ""
            if not csv:
                return False
            csv_obj = run_oc_json(["get", "csv", csv, "-n", OLS_NS])
            return (csv_obj.get("status") or {}).get("phase") == "Succeeded"
        except RuntimeError:
            return False

    wait_for(
        csv_succeeded,
        timeout_s=600,
        sleep_s=5,
        label="lightspeed-operator CSV Succeeded",
        dry_run=dry_run,
    )
    wait_for(
        lambda: oc_exists("clusterrole", "ols-user"),
        timeout_s=180,
        sleep_s=3,
        label="ClusterRole ols-user",
        dry_run=dry_run,
    )


def apply_llm_secret(settings: dict[str, str], *, dry_run: bool) -> None:
    token = (settings.get("apiToken") or "").strip()
    if not token and not dry_run:
        raise RuntimeError(
            "OpenShift Lightspeed API token is empty - set it under Lab credentials → "
            "Integration Secrets → OpenShift Lightspeed LLM"
        )
    # Use stringData so oc apply handles encoding.
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": OLS_NS,
            "labels": {DEMO_LABEL_KEY: DEMO_LABEL_VAL},
        },
        "type": "Opaque",
        "stringData": {"apitoken": token or "DRY_RUN_PLACEHOLDER"},
    }
    apply_yaml(json.dumps(secret), dry_run=dry_run)


def apply_olsconfig(settings: dict[str, str], *, dry_run: bool) -> None:
    model = settings.get("model") or "gpt-4o"
    url = settings.get("url") or "https://api.openai.com/v1"
    provider_name = "myOpenai"
    ols = {
        "apiVersion": "ols.openshift.io/v1alpha1",
        "kind": "OLSConfig",
        "metadata": {
            "name": OLSCONFIG_NAME,
            "labels": {DEMO_LABEL_KEY: DEMO_LABEL_VAL},
        },
        "spec": {
            "llm": {
                "providers": [
                    {
                        "name": provider_name,
                        "type": "openai",
                        "credentialsSecretRef": {"name": SECRET_NAME},
                        "url": url,
                        "models": [{"name": model}],
                    }
                ]
            },
            "ols": {
                "defaultModel": model,
                "defaultProvider": provider_name,
                "logLevel": "INFO",
            },
        },
    }
    apply_yaml(json.dumps(ols), dry_run=dry_run)


def apply_rbac_and_network(*, dry_run: bool) -> tuple[str, str]:
    ns, sa = detect_central_ns_sa()
    crb = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {CRB_NAME}
  labels:
    {DEMO_LABEL_KEY}: {DEMO_LABEL_VAL}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ols-user
subjects:
- kind: ServiceAccount
  name: {sa}
  namespace: {ns}
"""
    np = f"""apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {NP_NAME}
  namespace: {OLS_NS}
  labels:
    {DEMO_LABEL_KEY}: {DEMO_LABEL_VAL}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/part-of: openshift-lightspeed
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: {ns}
      podSelector:
        matchLabels:
          app: central
    ports:
    - protocol: TCP
      port: 8443
  policyTypes:
  - Ingress
"""
    apply_yaml(crb, dry_run=dry_run)
    apply_yaml(np, dry_run=dry_run)
    return ns, sa


def wait_ols_pods(*, dry_run: bool) -> None:
    def ready() -> bool:
        proc = run_oc(
            [
                "get",
                "pods",
                "-n",
                OLS_NS,
                "-l",
                "app.kubernetes.io/part-of=openshift-lightspeed",
                "-o",
                "json",
            ],
            check=False,
        )
        if proc.returncode != 0:
            return False
        items = json.loads(proc.stdout).get("items") or []
        if not items:
            return False
        for pod in items:
            status = pod.get("status") or {}
            if status.get("phase") != "Running":
                return False
            conds = status.get("conditions") or []
            if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds):
                return False
        return True

    wait_for(ready, timeout_s=600, sleep_s=5, label="OLS pods Ready", dry_run=dry_run)


def run_central_ocp(*, dry_run: bool, settings: dict[str, str]) -> None:
    ensure_central_oc()
    print(f"=== central-ocp: OpenShift Lightspeed in {OLS_NS} ===")
    install_operator(dry_run=dry_run)
    apply_llm_secret(settings, dry_run=dry_run)
    apply_olsconfig(settings, dry_run=dry_run)
    ns, sa = apply_rbac_and_network(dry_run=dry_run)
    print(f"Granted ols-user to system:serviceaccount:{ns}:{sa}")
    wait_ols_pods(dry_run=dry_run)


def run_central_api(*, dry_run: bool, creds: dict[str, Any]) -> None:
    print("=== central-api: verify RHACS Lightspeed connectivity ===")
    base, auth = central_connection(creds)
    auth_err = check_central_auth(base, auth, creds=creds)
    if auth_err:
        raise RuntimeError(auth_err)
    enabled, flag_msg = flag_enabled(base, auth, creds)
    if enabled is None:
        raise RuntimeError(flag_msg)
    if not enabled:
        raise RuntimeError(
            f"{FEATURE_FLAG} is disabled on Central - enable it (feature flag / Central env) "
            "before using risk AI summaries"
        )
    print(f"{FEATURE_FLAG} enabled ({flag_msg})")
    if dry_run:
        print(f"would poll GET /v1/lightspeed/status until available (endpoint {DEFAULT_OLS_ENDPOINT})")
        return

    deadline = time.time() + 300
    last = ""
    while time.time() < deadline:
        available, msg = lightspeed_status(base, auth, creds)
        last = msg
        if available:
            print(f"Lightspeed status available: {msg}")
            return
        if available is None:
            raise RuntimeError(msg)
        time.sleep(5)
    raise RuntimeError(f"Lightspeed still unavailable after wait: {last}")


def cmd_run(plane: str | None, *, dry_run: bool) -> int:
    creds = load_lab_credentials()
    settings = llm_settings(creds)
    try:
        if want_central_ocp(plane):
            if not (settings.get("apiToken") or "").strip() and not dry_run:
                emit_tsv(
                    "needs-run",
                    "LLM API token missing in lab credentials (Integration Secrets → OpenShift Lightspeed LLM)",
                )
                return 1
            run_central_ocp(dry_run=dry_run, settings=settings)
        if want_central_api(plane):
            run_central_api(dry_run=dry_run, creds=creds)
    except Exception as exc:
        emit_tsv("error", str(exc))
        return 1

    risk = risk_url(creds)
    if dry_run:
        emit_tsv("ok", "dry-run plan printed for acs-lightspeed")
    else:
        msg = "OpenShift Lightspeed configured for ACS risk AI"
        if risk:
            msg = f"{msg} {risk}"
        emit_tsv("ok", msg)
    return 0


def delete_resource(kind: str, name: str, *, namespace: str | None = None, dry_run: bool) -> None:
    args = ["delete", kind, name, "--ignore-not-found"]
    if namespace:
        args.extend(["-n", namespace])
    if dry_run:
        print(f"would oc {' '.join(args)}")
        return
    proc = run_oc(args, check=False)
    if proc.stdout.strip():
        print(proc.stdout.strip())


def cmd_uninstall(plane: str | None, *, dry_run: bool) -> int:
    try:
        if want_central_api(plane):
            print(
                "central-api: RHACS 5.0 has no AI integration object to delete; "
                "connectivity clears when OLS is removed on central-ocp."
            )
        if want_central_ocp(plane):
            ensure_central_oc()
            print(f"=== central-ocp uninstall ({OLS_NS}) ===")
            delete_resource("networkpolicy", NP_NAME, namespace=OLS_NS, dry_run=dry_run)
            delete_resource("clusterrolebinding", CRB_NAME, dry_run=dry_run)
            delete_resource("olsconfig", OLSCONFIG_NAME, dry_run=dry_run)
            delete_resource("secret", SECRET_NAME, namespace=OLS_NS, dry_run=dry_run)
            # Delete CSVs owned by subscription before subscription
            if oc_exists("subscription", SUB_NAME, namespace=OLS_NS) and not dry_run:
                try:
                    sub = run_oc_json(["get", "subscription", SUB_NAME, "-n", OLS_NS])
                    csv = (sub.get("status") or {}).get("currentCSV") or ""
                    if csv:
                        delete_resource("csv", csv, namespace=OLS_NS, dry_run=dry_run)
                except RuntimeError:
                    pass
            delete_resource("subscription", SUB_NAME, namespace=OLS_NS, dry_run=dry_run)
            delete_resource("operatorgroup", OG_NAME, namespace=OLS_NS, dry_run=dry_run)
            if dry_run:
                print(f"would delete namespace {OLS_NS}")
            else:
                run_oc(["delete", "ns", OLS_NS, "--ignore-not-found"], check=False)
    except Exception as exc:
        emit_tsv("error", str(exc))
        return 1
    emit_tsv("ok", "acs-lightspeed uninstall complete (or dry-run plan printed)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="acs_lightspeed.py")
    p.add_argument("--plane", default="", help="central-api|central-ocp or omit for both")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "run", "uninstall"):
        sp = sub.add_parser(name)
        sp.add_argument("--cli", action="store_true")
        if name in ("run", "uninstall"):
            sp.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plane = normalize_plane(args.plane)
    except ValueError as exc:
        print(f"{MODULE_ID}\terror\t{exc}", file=sys.stderr)
        return 1
    if args.cmd == "status":
        return cmd_status(plane)
    if args.cmd == "run":
        return cmd_run(plane, dry_run=bool(args.dry_run))
    if args.cmd == "uninstall":
        return cmd_uninstall(plane, dry_run=bool(args.dry_run))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
