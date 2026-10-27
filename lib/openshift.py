"""OpenShift / oc access for the **active** lab.

**Source of truth:** ``lab-credentials.json`` (this tool). Module ``oc`` never
treats the operator’s interactive ``~/.kube/config`` as authoritative.

**Derived cache:** per-lab kubeconfigs under
``<repo>/.cache/kubeconfigs/<lab-id>.kubeconfig``, created/refreshed from the
active lab’s OpenShift fields. Safe to delete; ``ensure`` regenerates them.

Troubleshoot via the orchestrator (same CLI as ``--status`` / ``--run``)::

  ./scripts/acs-setup.sh --oc-status
  ./scripts/acs-setup.sh --oc-login [--force]

Bash modules call ``python -m lib.openshift login --print-kubeconfig`` internally and
``export KUBECONFIG`` so later ``oc`` in that shell uses the lab file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lib.central import load_lab_credentials, repo_root

KUBECONFIG_DIRNAME = ".cache/kubeconfigs"


def kubeconfig_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / KUBECONFIG_DIRNAME


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
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", host).strip("-") or "default"
    return safe[:64]


def kubeconfig_path_for_lab(lab_id: str, root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", (lab_id or "default").strip()) or "default"
    return kubeconfig_dir(root) / f"{safe}.kubeconfig"


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
    user = (ocp.get("adminUsername") or "").strip()
    password = (ocp.get("adminPassword") or "").strip()
    missing: list[str] = []
    if not user:
        missing.append("adminUsername")
    if not password:
        missing.append("adminPassword")
    if missing:
        raise RuntimeError(
            "OpenShift credentials incomplete in lab-credentials.json for active lab "
            f"(missing: {', '.join(missing)}). Target API would be {api}."
        )

    kubeconfig.parent.mkdir(parents=True, exist_ok=True)
    login = _run_oc(
        [
            "login",
            api,
            f"--username={user}",
            f"--password={password}",
            "--insecure-skip-tls-verify=true",
        ],
        kubeconfig=kubeconfig,
        timeout=90,
    )
    if login.returncode != 0:
        detail = (login.stderr or login.stdout or "").strip() or f"exit {login.returncode}"
        raise RuntimeError(f"oc login to {api} (kubeconfig={kubeconfig}) failed: {detail}")


def ensure_oc(
    creds: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> Path:
    """Ensure oc talks to the **active lab** via a per-lab kubeconfig.

    Returns the kubeconfig path and sets ``os.environ["KUBECONFIG"]`` for this process.
    """
    if not shutil.which("oc"):
        raise RuntimeError("oc not on PATH")

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
                f"after login, oc server is {current!r} but active lab expects {api!r} "
                f"(kubeconfig={kc})"
            )

    os.environ["KUBECONFIG"] = str(kc)
    return kc


def ensure_oc_message(
    creds: dict[str, Any] | None = None, *, force: bool = False
) -> str | None:
    """Return None on success, or an error message string."""
    try:
        ensure_oc(creds, force=force)
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
            "Fill OpenShift console URL (and user/password) for the active lab in "
            "lab-credentials.json, then: ./scripts/acs-setup.sh --oc-login"
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

    if args.cmd == "login":
        force = bool(getattr(args, "force", False))
        try:
            kc = ensure_oc(force=force)
        except RuntimeError as exc:
            try:
                info = show_active()
                info["ok"] = False
                if str(exc) not in (info.get("problems") or []):
                    info.setdefault("problems", []).insert(0, str(exc))
                if not getattr(args, "print_kubeconfig", False):
                    print(format_status_report(info), file=sys.stderr)
                else:
                    print(exc, file=sys.stderr)
            except RuntimeError:
                print(exc, file=sys.stderr)
            return 1
        if getattr(args, "print_kubeconfig", False):
            print(kc)
            return 0
        print(f"OK - refreshed kubeconfig\n  kubeconfig : {kc}")
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
