#!/usr/bin/env python3
"""Central policy helper for the init-demo module.

Fetches upstream ACS-init-container-test policy JSON (or a local file) and
upserts/deletes/lists policies via lib.central. Also lists active namespace
violations for Status folds.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_console_url,
    central_request,
    load_lab_credentials,
)
from lib.demo_policies import (  # noqa: E402
    DEMO_CATEGORY,
    ensure_managed_policy,
    find_policy_by_name,
)

MODULE_ID = "init-demo"
NS_DEFAULT = "acs-init-container-test"

DEMO_POLICY_NAMES = [
    "DEMO-Init-Test: Privileged Container (Blue/Red)",
    "DEMO-Init-Test: Fixable Important+ CVE (Dirty/Red)",
    "DEMO-Init-Test: Missing Liveness Probe (main only)",
]

UPSTREAM_POLICY_FILES = [
    "privileged-init-container.json",
    "fixable-important-cve.json",
    "missing-liveness-probe.json",
]

UPSTREAM_BASE = (
    "https://raw.githubusercontent.com/boazmichaely/"
    "ACS-init-container-test/main/policies"
)


def _load_policy(path_or_url: str) -> dict[str, Any]:
    if path_or_url.startswith(("http://", "https://")):
        req = urllib.request.Request(path_or_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            sys.exit(f"ERROR fetching policy JSON from {path_or_url}: {exc}")
        policy = json.loads(raw)
    else:
        with open(path_or_url, encoding="utf-8") as handle:
            policy = json.load(handle)
    if not isinstance(policy, dict):
        sys.exit(f"ERROR: policy JSON must be an object: {path_or_url}")
    return policy


def cmd_upsert_policy(args: argparse.Namespace) -> int:
    creds = load_lab_credentials()
    base, authorization = central_connection(creds)
    policy = _load_policy(args.file)
    name = policy.get("name") or ""
    if not name:
        print("ERROR: policy JSON has no name", file=sys.stderr)
        return 1

    try:
        existing = find_policy_by_name(base, authorization, name, creds=creds)
        result = ensure_managed_policy(
            base, authorization, policy, creds=creds, preserve_notifiers=True
        )
    except RuntimeError as exc:
        print(f"ERROR upserting policy '{name}': {exc}", file=sys.stderr)
        return 1
    action = "updated" if existing else "created"
    pid = result.get("id") if isinstance(result, dict) else None
    cats = result.get("categories") if isinstance(result, dict) else []
    demo = DEMO_CATEGORY in (cats or [])
    print(
        f"{action} policy '{name}' (id={pid}"
        f"{', category=DEMO' if demo else ''})"
    )
    return 0


def cmd_delete_policy(args: argparse.Namespace) -> int:
    creds = load_lab_credentials()
    base, authorization = central_connection(creds)
    try:
        existing = find_policy_by_name(
            base, authorization, args.name, creds=creds
        )
    except RuntimeError as exc:
        print(f"ERROR listing policies: {exc}", file=sys.stderr)
        return 1
    if not existing:
        print(f"policy '{args.name}' not found, nothing to delete")
        return 0
    code, body = central_request(
        base,
        authorization,
        "DELETE",
        f"/v1/policies/{existing['id']}",
        creds=creds,
    )
    if code not in (200, 204):
        print(f"ERROR deleting policy '{args.name}': {code} {body}", file=sys.stderr)
        return 1
    print(f"deleted policy '{args.name}' (id={existing['id']})")
    return 0


def cmd_policy_status(_: argparse.Namespace) -> int:
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 0

    code, body = central_request(
        base, authorization, "GET", "/v1/policies", creds=creds
    )
    if code != 200:
        print(json.dumps({"ok": False, "error": f"list policies failed: {code} {body}"}))
        return 0

    names = {
        p.get("name")
        for p in (body.get("policies") or [] if isinstance(body, dict) else [])
    }
    policies = [
        {"name": name, "present": name in names} for name in DEMO_POLICY_NAMES
    ]
    all_present = all(p["present"] for p in policies)
    print(json.dumps({"ok": True, "allPresent": all_present, "policies": policies}))
    return 0


def _violation_console_url(console: str, alert_id: str) -> str:
    """Deep link into Central UI for one alert (Applications view)."""
    root = (console or "").strip().rstrip("/")
    if not root:
        return ""
    if not root.startswith(("http://", "https://")):
        root = f"https://{root}"
    aid = (alert_id or "").strip()
    if not aid:
        return ""
    return (
        f"{root}/main/violations/{urllib.parse.quote(aid, safe='')}"
        f"?filteredWorkflowView=Applications%20view"
    )


def cmd_violations(args: argparse.Namespace) -> int:
    ns = args.namespace or NS_DEFAULT
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        console = central_console_url(creds)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "alerts": []}))
        return 0

    query = f"Namespace:{ns}+Violation State:ACTIVE"
    path = "/v1/alerts?" + urllib.parse.urlencode(
        {"query": query, "pagination.limit": "200"}
    )
    code, body = central_request(base, authorization, "GET", path, creds=creds)
    if code != 200:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"list alerts failed: {code} {body}",
                    "alerts": [],
                }
            )
        )
        return 0

    alerts_out = []
    for alert in (body.get("alerts") or [] if isinstance(body, dict) else []):
        aid = alert.get("id") or ""
        alerts_out.append(
            {
                "deployment": (alert.get("deployment") or {}).get("name"),
                "policy": (alert.get("policy") or {}).get("name"),
                "state": alert.get("state"),
                "id": aid,
                "url": _violation_console_url(console, aid),
            }
        )
    print(json.dumps({"ok": True, "alerts": alerts_out, "consoleUrl": console}))
    return 0


def cmd_list_demo_names(_: argparse.Namespace) -> int:
    for name in DEMO_POLICY_NAMES:
        print(name)
    return 0


def cmd_list_upstream_urls(_: argparse.Namespace) -> int:
    for fname in UPSTREAM_POLICY_FILES:
        print(f"{UPSTREAM_BASE}/{fname}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("upsert-policy", help="Load upstream/local policy JSON and upsert")
    p.add_argument("file", help="Local path or https URL to policy JSON")
    p.set_defaults(func=cmd_upsert_policy)

    p = sub.add_parser("delete-policy", help="Delete a DEMO-Init-Test policy by name")
    p.add_argument("name")
    p.set_defaults(func=cmd_delete_policy)

    p = sub.add_parser("policy-status", help="JSON presence of the three DEMO policies")
    p.set_defaults(func=cmd_policy_status)

    p = sub.add_parser("violations", help="JSON active alerts for a namespace")
    p.add_argument("--namespace", default=NS_DEFAULT)
    p.set_defaults(func=cmd_violations)

    p = sub.add_parser("list-demo-names", help="Print DEMO policy names (one per line)")
    p.set_defaults(func=cmd_list_demo_names)

    p = sub.add_parser(
        "list-upstream-urls", help="Print upstream policy JSON URLs (one per line)"
    )
    p.set_defaults(func=cmd_list_upstream_urls)

    args = parser.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
