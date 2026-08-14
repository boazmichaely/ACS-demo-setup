#!/usr/bin/env python3
"""Configure ACS compliance scan schedules via Central API (RHACS UI equivalent)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
)

SCAN_NAME = os.environ.get("ACS_COMPLIANCE_SCAN_NAME", "acs-demo-setup").strip() or "acs-demo-setup"
PROFILES = ["ocp4-cis", "ocp4-cis-node"]
PROFILE_POLL_SECONDS = 3
PROFILE_SYNC_TIMEOUT_SECONDS = int(
    os.environ.get("ACS_COMPLIANCE_PROFILE_SYNC_TIMEOUT_SECONDS", "600")
)
SCHEDULE = {
    "intervalType": "DAILY",
    "hour": 2,
    "minute": 0,
}
DESCRIPTION = "ACS demo lab compliance scan schedule"


def secured_cluster_name_from_oc() -> str:
    override = os.environ.get("ACS_COMPLIANCE_CLUSTER_NAME", "").strip()
    if override:
        return override

    for ns in ("stackrox", "rhacs-operator"):
        try:
            raw = subprocess.check_output(
                ["oc", "get", "securedcluster", "-n", ns, "-o", "json"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except subprocess.CalledProcessError:
            continue
        items = json.loads(raw).get("items") or []
        for item in items:
            name = (item.get("spec") or {}).get("clusterName") or ""
            if name.strip():
                return name.strip()

    raise RuntimeError(
        "could not determine secured cluster name from oc; "
        "log in to the secured cluster or set ACS_COMPLIANCE_CLUSTER_NAME"
    )


def list_central_clusters(base: str, token: str) -> list[dict[str, Any]]:
    code, body = central_request(base, token, "GET", "/v1/clusters")
    if code != 200:
        raise RuntimeError(f"GET /v1/clusters failed ({code}): {body}")
    return body.get("clusters") or []


def resolve_secured_cluster(base: str, token: str) -> dict[str, Any]:
    target_name = secured_cluster_name_from_oc()
    matches = [c for c in list_central_clusters(base, token) if c.get("name") == target_name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        known = ", ".join(sorted(c.get("name") or "?" for c in list_central_clusters(base, token)))
        raise RuntimeError(
            f"secured cluster {target_name!r} not registered in Central; known clusters: {known or '(none)'}"
        )
    raise RuntimeError(f"multiple Central clusters named {target_name!r}")


def list_profile_summaries(base: str, token: str, cluster_id: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"clusterIds": cluster_id})
    code, body = central_request(base, token, "GET", f"/v2/compliance/profiles/summary?{query}")
    if code != 200:
        raise RuntimeError(f"GET /v2/compliance/profiles/summary failed ({code}): {body}")
    return body.get("profiles") or []


def wait_for_profiles(base: str, token: str, cluster_id: str, *, dry_run: bool) -> list[str]:
    log: list[str] = []
    start = time.monotonic()
    while True:
        summaries = list_profile_summaries(base, token, cluster_id)
        available = {p.get("name") or "" for p in summaries}
        missing = [name for name in PROFILES if name not in available]
        elapsed = int(time.monotonic() - start)
        if not missing:
            log.append(
                f"Compliance profiles available in Central: {', '.join(PROFILES)} ({len(summaries)} total)"
            )
            return log

        line = (
            f"Waiting for compliance profiles in Central "
            f"({', '.join(missing)} missing; {elapsed}s elapsed)…"
        )
        print(line, flush=True)
        log.append(line)

        if dry_run:
            log.append("Dry run: would keep polling every 3s until profiles appear.")
            return log

        if elapsed >= PROFILE_SYNC_TIMEOUT_SECONDS:
            raise RuntimeError(
                f"profiles not synced to Central within {PROFILE_SYNC_TIMEOUT_SECONDS}s: "
                f"missing {', '.join(missing)}"
            )
        time.sleep(PROFILE_POLL_SECONDS)


def list_scan_configurations(base: str, token: str) -> list[dict[str, Any]]:
    code, body = central_request(base, token, "GET", "/v2/compliance/scan/configurations")
    if code != 200:
        raise RuntimeError(f"GET /v2/compliance/scan/configurations failed ({code}): {body}")
    return body.get("configurations") or []


def find_scan_configuration(configs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in configs:
        if item.get("scanName") == SCAN_NAME:
            return item
    return None


def desired_scan_body(cluster_id: str) -> dict[str, Any]:
    return {
        "scanName": SCAN_NAME,
        "clusters": [cluster_id],
        "scanConfig": {
            "oneTimeScan": False,
            "profiles": list(PROFILES),
            "description": DESCRIPTION,
            "scanSchedule": dict(SCHEDULE),
            "notifiers": [],
        },
    }


def _schedule_key(schedule: dict[str, Any] | None) -> tuple[Any, ...]:
    if not schedule:
        return ("", 0, 0)
    return (
        schedule.get("intervalType") or "",
        schedule.get("hour", 0),
        schedule.get("minute", 0),
    )


def config_cluster_ids(config: dict[str, Any]) -> list[str]:
    clusters = config.get("clusters") or []
    if clusters:
        return sorted(str(c) for c in clusters)
    status = config.get("clusterStatus") or []
    return sorted(str(item.get("clusterId") or "") for item in status if item.get("clusterId"))


def config_matches(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    existing_cfg = existing.get("scanConfig") or {}
    desired_cfg = desired.get("scanConfig") or {}
    return (
        existing.get("scanName") == desired.get("scanName")
        and config_cluster_ids(existing) == sorted(desired.get("clusters") or [])
        and sorted(existing_cfg.get("profiles") or []) == sorted(desired_cfg.get("profiles") or [])
        and bool(existing_cfg.get("oneTimeScan")) == bool(desired_cfg.get("oneTimeScan"))
        and _schedule_key(existing_cfg.get("scanSchedule")) == _schedule_key(desired_cfg.get("scanSchedule"))
    )


def schedule_summary() -> str:
    return "daily 02:00 UTC"


def scan_status_message(*, matched: bool, exists: bool) -> str:
    profile_text = " + ".join(PROFILES)
    if matched:
        return f"scan schedule {SCAN_NAME} ({schedule_summary()}, {profile_text})"
    if exists:
        return f"scan schedule {SCAN_NAME} out of date"
    return f"scan schedule {SCAN_NAME} not configured"


def evaluate_scan() -> dict[str, Any]:
    creds = load_lab_credentials()
    base, token = central_connection(creds)
    auth_err = check_central_auth(base, token)
    if auth_err:
        return {"state": "error", "message": auth_err}

    cluster = resolve_secured_cluster(base, token)
    cluster_id = cluster["id"]
    cluster_name = cluster.get("name") or cluster_id

    summaries = list_profile_summaries(base, token, cluster_id)
    available = {p.get("name") or "" for p in summaries}
    missing = [name for name in PROFILES if name not in available]
    if missing:
        return {
            "state": "needs-run",
            "message": scan_status_message(matched=False, exists=False),
            "detail": (
                f"profiles not in Central yet for {cluster_name}: {', '.join(missing)} "
                f"({len(summaries)} profiles synced)"
            ),
            "clusterName": cluster_name,
            "clusterId": cluster_id,
        }

    desired = desired_scan_body(cluster_id)
    existing = find_scan_configuration(list_scan_configurations(base, token))
    if existing and config_matches(existing, desired):
        return {
            "state": "ok",
            "message": scan_status_message(matched=True, exists=True),
            "clusterName": cluster_name,
            "clusterId": cluster_id,
            "configId": existing.get("id"),
        }

    return {
        "state": "needs-run",
        "message": scan_status_message(matched=False, exists=bool(existing)),
        "clusterName": cluster_name,
        "clusterId": cluster_id,
        "configId": (existing or {}).get("id"),
    }


def apply_scan(*, dry_run: bool) -> dict[str, Any]:
    log: list[str] = []
    status = evaluate_scan()
    if status.get("state") == "error":
        return {**status, "log": log}

    creds = load_lab_credentials()
    base, token = central_connection(creds)
    cluster_id = status["clusterId"]
    cluster_name = status["clusterName"]
    desired = desired_scan_body(cluster_id)
    existing = None
    if status.get("configId"):
        existing = {"id": status["configId"], **next(
            (c for c in list_scan_configurations(base, token) if c.get("id") == status["configId"]),
            {},
        )}

    log.append(f"Target secured cluster: {cluster_name} ({cluster_id})")
    log.extend(wait_for_profiles(base, token, cluster_id, dry_run=dry_run))

    if dry_run:
        action = "PUT" if existing else "POST"
        path = (
            f"/v2/compliance/scan/configurations/{existing['id']}"
            if existing
            else "/v2/compliance/scan/configurations"
        )
        log.append("Planned changes (phase 2 — Central scan configuration):")
        log.append(f"  - {action} {path}")
        log.append(f"  - POST /v2/compliance/scan/configurations/{{id}}/run (on-demand scan results)")
        log.append(json.dumps(desired, indent=2))
        return {
            "state": "ok" if status.get("state") != "error" else status["state"],
            "message": scan_status_message(
                matched=bool(existing and config_matches(existing, desired)),
                exists=bool(existing),
            ),
            "log": log,
            "clusterName": cluster_name,
            "clusterId": cluster_id,
        }

    if existing and config_matches(existing, desired):
        config_id = existing.get("id")
        log.append(f"Scan configuration {SCAN_NAME} already up to date")
    elif existing and existing.get("id"):
        config_id = existing["id"]
        payload = {**desired, "id": config_id}
        code, body = central_request(
            base,
            token,
            "PUT",
            f"/v2/compliance/scan/configurations/{config_id}",
            payload,
        )
        if code != 200:
            return {
                "state": "error",
                "message": f"update scan configuration failed ({code}): {body}",
                "log": log,
            }
        log.append(f"Updated scan configuration {SCAN_NAME}")
    else:
        code, body = central_request(
            base,
            token,
            "POST",
            "/v2/compliance/scan/configurations",
            desired,
        )
        if code != 200:
            return {
                "state": "error",
                "message": f"create scan configuration failed ({code}): {body}",
                "log": log,
            }
        config_id = body.get("id")
        if not config_id:
            return {
                "state": "error",
                "message": "create scan configuration returned no id",
                "log": log,
            }
        log.append(f"Created scan configuration {SCAN_NAME}")

    code, body = central_request(
        base,
        token,
        "POST",
        f"/v2/compliance/scan/configurations/{config_id}/run",
    )
    if code != 200:
        return {
            "state": "error",
            "message": f"trigger scan run failed ({code}): {body}",
            "log": log,
            "configId": config_id,
        }
    log.append(f"Triggered on-demand compliance scan for {SCAN_NAME} (scan results)")

    final = evaluate_scan()
    if final.get("detail"):
        log.append(final["detail"])
    final["log"] = log
    final.pop("detail", None)
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "run"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cli", action="store_true", help="Emit human-readable log lines")
    args = parser.parse_args()

    try:
        if args.command == "status":
            result = evaluate_scan()
        else:
            result = apply_scan(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - module boundary
        result = {"state": "error", "message": str(exc), "log": []}

    if args.cli:
        for line in result.get("log") or []:
            if line:
                print(line)
        if args.command == "status":
            print(f"scan-status\t{result.get('state', 'error')}\t{result.get('message', '')}")
        else:
            print(f"scan-status\t{result.get('state', 'error')}\t{result.get('message', '')}")
    else:
        print(json.dumps(result))

    state = result.get("state", "error")
    if args.command == "status":
        return 0 if state in ("ok", "needs-run") else 1
    if args.dry_run:
        return 0 if state != "error" else 1
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
