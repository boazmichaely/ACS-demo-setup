#!/usr/bin/env python3
"""Configure ACS compliance scan schedules via Central API (RHACS UI equivalent).

One Central schedule (``ocp4-cis-scan-schedule``). Selection comes from
``--secured-cluster-id`` (repeatable) and/or ``--secured-cluster NAME``.
With neither, only the lab soft-default SC is used. Install merges
selected Central cluster ids into the schedule; uninstall drops them (deletes
the schedule when empty).
"""

from __future__ import annotations

import argparse
import json
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
    load_lab_document,
)
from lib.lab_doc import active_lab, preferred_secured_cluster  # noqa: E402
from lib.openshift import (  # noqa: E402
    ensure_oc,
    list_secured_cluster_targets,
)

SCAN_NAME = "ocp4-cis-scan-schedule"
PROFILES = ["ocp4-cis", "ocp4-cis-node"]
PROFILE_POLL_SECONDS = 3
PROFILE_SYNC_TIMEOUT_SECONDS = 600
SCHEDULE = {
    "intervalType": "DAILY",
    "hour": 2,
    "minute": 0,
}
DESCRIPTION = "ACS demo lab compliance scan schedule"

# Set from CLI before status/run/uninstall.
SECURED_CLUSTER_OVERRIDE = ""
SECURED_CLUSTER_IDS: list[str] = []


def secured_cluster_name_from_oc() -> str | None:
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
    return None


def list_central_clusters(base: str, token: str) -> list[dict[str, Any]]:
    code, body = central_request(base, token, "GET", "/v1/clusters")
    if code != 200:
        raise RuntimeError(f"GET /v1/clusters failed ({code}): {body}")
    return body.get("clusters") or []


def central_cluster_by_name(
    clusters: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    matches = [c for c in clusters if (c.get("name") or "") == name]
    if len(matches) == 1:
        return matches[0]
    return None


def _default_target_name_filter() -> str:
    """Lab soft-default SC name when no selection flags were passed."""
    lab = active_lab(load_lab_document())
    sc = preferred_secured_cluster(lab)
    return (sc.get("name") or "").strip()


def resolve_lab_clusters(
    base: str,
    token: str,
    *,
    name_filter: str = "",
    id_filter: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve Central cluster ids for lab secured clusters.

    Returns (resolved[{id,name,labId,labName,note}], warnings).
    """
    central = list_central_clusters(base, token)
    id_want = {s.strip() for s in (id_filter or []) if (s or "").strip()}
    if id_want:
        all_targets = list_secured_cluster_targets(name_filter=None)
        targets = [t for t in all_targets if (t.get("id") or "").strip() in id_want]
        missing = id_want - {(t.get("id") or "").strip() for t in targets}
        if missing:
            raise RuntimeError(
                f"secured cluster id(s) not in lab: {', '.join(sorted(missing))}"
            )
    else:
        targets = list_secured_cluster_targets(name_filter=name_filter or None)
    if name_filter and not id_want and not targets:
        raise RuntimeError(
            f"no lab secured cluster matching {name_filter!r}; "
            "check Lab credentials securedClusters names"
        )

    resolved: list[dict[str, Any]] = []
    warnings: list[str] = []

    for target in targets:
        lab_id = target.get("id") or ""
        lab_name = target.get("name") or lab_id
        if target.get("credsError"):
            warnings.append(f"{lab_name}: OpenShift creds missing ({target['credsError']})")
            # Still try lab name → Central without oc
            hit = central_cluster_by_name(central, lab_name)
            if hit:
                resolved.append(
                    {
                        "id": hit["id"],
                        "name": hit.get("name") or lab_name,
                        "labId": lab_id,
                        "labName": lab_name,
                        "note": "resolved by lab name (no oc)",
                    }
                )
            else:
                warnings.append(
                    f"{lab_name}: not registered in Central (and no oc to discover)"
                )
            continue

        try:
            ensure_oc(secured_cluster_id=lab_id)
        except RuntimeError as exc:
            warnings.append(f"{lab_name}: oc login failed ({exc})")
            hit = central_cluster_by_name(central, lab_name)
            if hit:
                resolved.append(
                    {
                        "id": hit["id"],
                        "name": hit.get("name") or lab_name,
                        "labId": lab_id,
                        "labName": lab_name,
                        "note": "resolved by lab name after oc failure",
                    }
                )
            continue

        acs_name = secured_cluster_name_from_oc() or lab_name
        hit = central_cluster_by_name(central, acs_name)
        if not hit and acs_name != lab_name:
            hit = central_cluster_by_name(central, lab_name)
        if not hit:
            known = ", ".join(sorted(c.get("name") or "?" for c in central)) or "(none)"
            warnings.append(
                f"{lab_name}: ACS name {acs_name!r} not in Central; known: {known}"
            )
            continue
        resolved.append(
            {
                "id": hit["id"],
                "name": hit.get("name") or acs_name,
                "labId": lab_id,
                "labName": lab_name,
                "note": "",
            }
        )

    # Dedupe by Central id
    by_id: dict[str, dict[str, Any]] = {}
    for row in resolved:
        by_id[str(row["id"])] = row
    return list(by_id.values()), warnings


def list_profile_summaries(base: str, token: str, cluster_id: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"clusterIds": cluster_id})
    code, body = central_request(base, token, "GET", f"/v2/compliance/profiles/summary?{query}")
    if code != 200:
        raise RuntimeError(f"GET /v2/compliance/profiles/summary failed ({code}): {body}")
    return body.get("profiles") or []


def wait_for_profiles(
    base: str, token: str, cluster_id: str, cluster_name: str, *, dry_run: bool
) -> list[str]:
    log: list[str] = []
    start = time.monotonic()
    while True:
        summaries = list_profile_summaries(base, token, cluster_id)
        available = {p.get("name") or "" for p in summaries}
        missing = [name for name in PROFILES if name not in available]
        elapsed = int(time.monotonic() - start)
        if not missing:
            log.append(
                f"{cluster_name}: profiles available ({', '.join(PROFILES)}; "
                f"{len(summaries)} total)"
            )
            return log

        line = (
            f"{cluster_name}: waiting for profiles "
            f"({', '.join(missing)} missing; {elapsed}s)…"
        )
        print(line, flush=True)
        log.append(line)

        if dry_run:
            log.append(f"{cluster_name}: dry-run would keep polling until profiles appear")
            return log

        if elapsed >= PROFILE_SYNC_TIMEOUT_SECONDS:
            raise RuntimeError(
                f"{cluster_name}: profiles not synced within "
                f"{PROFILE_SYNC_TIMEOUT_SECONDS}s: missing {', '.join(missing)}"
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


def desired_scan_body(cluster_ids: list[str]) -> dict[str, Any]:
    return {
        "scanName": SCAN_NAME,
        "clusters": list(cluster_ids),
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
        and config_cluster_ids(existing) == sorted(str(c) for c in (desired.get("clusters") or []))
        and sorted(existing_cfg.get("profiles") or []) == sorted(desired_cfg.get("profiles") or [])
        and bool(existing_cfg.get("oneTimeScan")) == bool(desired_cfg.get("oneTimeScan"))
        and _schedule_key(existing_cfg.get("scanSchedule")) == _schedule_key(desired_cfg.get("scanSchedule"))
    )


def schedule_summary() -> str:
    return "daily 02:00 UTC"


def scan_status_message(
    *, matched: bool, exists: bool, cluster_names: list[str] | None = None
) -> str:
    profile_text = " + ".join(PROFILES)
    names = ", ".join(cluster_names or []) or "(no clusters)"
    if matched:
        return (
            f"scan schedule {SCAN_NAME} ({schedule_summary()}, {profile_text}; "
            f"clusters: {names})"
        )
    if exists:
        return f"scan schedule {SCAN_NAME} out of date (want clusters: {names})"
    return f"scan schedule {SCAN_NAME} not configured (want clusters: {names})"


def profiles_ready(base: str, token: str, cluster_id: str) -> tuple[bool, str]:
    summaries = list_profile_summaries(base, token, cluster_id)
    available = {p.get("name") or "" for p in summaries}
    missing = [name for name in PROFILES if name not in available]
    if missing:
        return False, f"missing profiles {', '.join(missing)} ({len(summaries)} synced)"
    return True, f"{len(summaries)} profiles synced"


def _selection_filters() -> tuple[str, list[str]]:
    """Return (name_filter, id_filter) for this invoke."""
    ids = [s.strip() for s in SECURED_CLUSTER_IDS if (s or "").strip()]
    name = SECURED_CLUSTER_OVERRIDE.strip()
    if ids or name:
        return name, ids
    # Default: soft-default SC only.
    return _default_target_name_filter(), []


def evaluate_scan() -> dict[str, Any]:
    creds = load_lab_credentials()
    base, token = central_connection(creds)
    auth_err = check_central_auth(base, token, creds=creds)
    if auth_err:
        return {"state": "error", "message": auth_err}

    name_filter, id_filter = _selection_filters()
    resolved, warnings = resolve_lab_clusters(
        base, token, name_filter=name_filter, id_filter=id_filter or None
    )
    check_set = resolved

    if not check_set:
        msg = "no secured clusters resolvable for compliance schedule"
        if warnings:
            msg = f"{msg}; " + "; ".join(warnings[:3])
        return {"state": "error", "message": msg, "warnings": warnings}

    desired_ids = sorted({str(r["id"]) for r in resolved})
    desired_names = [r["name"] for r in resolved]
    existing = find_scan_configuration(list_scan_configurations(base, token))
    desired = desired_scan_body(desired_ids)

    profile_notes: list[str] = []
    profiles_ok = True
    for row in check_set:
        ok, note = profiles_ready(base, token, str(row["id"]))
        profile_notes.append(f"{row['name']}: {note}")
        if not ok:
            profiles_ok = False

    if not profiles_ok:
        return {
            "state": "needs-run",
            "message": scan_status_message(
                matched=False, exists=bool(existing), cluster_names=desired_names
            ),
            "detail": "; ".join(profile_notes),
            "clusterIds": desired_ids,
            "clusterNames": desired_names,
            "configId": (existing or {}).get("id"),
            "warnings": warnings,
            "resolved": resolved,
        }

    if existing and config_matches(existing, desired):
        return {
            "state": "ok",
            "message": scan_status_message(
                matched=True, exists=True, cluster_names=desired_names
            ),
            "clusterIds": desired_ids,
            "clusterNames": desired_names,
            "configId": existing.get("id"),
            "warnings": warnings,
            "resolved": resolved,
        }

    return {
        "state": "needs-run",
        "message": scan_status_message(
            matched=False, exists=bool(existing), cluster_names=desired_names
        ),
        "clusterIds": desired_ids,
        "clusterNames": desired_names,
        "configId": (existing or {}).get("id"),
        "warnings": warnings,
        "resolved": resolved,
    }


def uninstall_scan(*, dry_run: bool) -> dict[str, Any]:
    """Delete the shared schedule, or remove one cluster when --secured-cluster is set."""
    log: list[str] = []
    try:
        creds = load_lab_credentials()
        base, token = central_connection(creds)
        auth_err = check_central_auth(base, token, creds=creds)
        if auth_err:
            return {"state": "error", "message": auth_err, "log": log}
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "message": str(exc), "log": log}

    existing = find_scan_configuration(list_scan_configurations(base, token))
    name_filter, id_filter = _selection_filters()
    scoped = bool(id_filter) or bool(name_filter)

    if not existing or not existing.get("id"):
        log.append(f"No Central scan configuration named {SCAN_NAME} to delete")
        return {
            "state": "ok",
            "message": f"scan schedule {SCAN_NAME} already absent",
            "log": log,
        }

    config_id = existing["id"]
    path = f"/v2/compliance/scan/configurations/{config_id}"

    if scoped:
        resolved, warnings = resolve_lab_clusters(
            base, token, name_filter=name_filter, id_filter=id_filter or None
        )
        for w in warnings:
            log.append(f"note: {w}")
        if not resolved:
            return {
                "state": "error",
                "message": (
                    f"cannot resolve selection to remove "
                    f"(name={name_filter!r} ids={id_filter})"
                ),
                "log": log,
            }
        remove_ids = {str(r["id"]) for r in resolved}
        current = set(config_cluster_ids(existing))
        remaining = sorted(current - remove_ids)
        if not remaining:
            if dry_run:
                log.append(f"Would DELETE {path} ({SCAN_NAME}; last cluster removed)")
                return {
                    "state": "ok",
                    "message": f"dry-run: would delete scan schedule {SCAN_NAME}",
                    "log": log,
                    "configId": config_id,
                }
            code, body = central_request(base, token, "DELETE", path)
            if code not in (200, 204, 404):
                return {
                    "state": "error",
                    "message": f"delete scan configuration failed ({code}): {body}",
                    "log": log,
                }
            log.append(f"Deleted Central scan configuration {SCAN_NAME} ({config_id})")
            return {
                "state": "ok",
                "message": f"scan schedule {SCAN_NAME} deleted",
                "log": log,
            }

        # PUT remaining clusters
        desired = desired_scan_body(remaining)
        payload = {**desired, "id": config_id}
        if dry_run:
            log.append(f"Would PUT {path} removing cluster(s) {sorted(remove_ids)}")
            log.append(json.dumps(desired, indent=2))
            return {
                "state": "ok",
                "message": f"dry-run: would drop {name_filter} from {SCAN_NAME}",
                "log": log,
                "configId": config_id,
            }
        code, body = central_request(base, token, "PUT", path, payload)
        if code != 200:
            return {
                "state": "error",
                "message": f"update scan configuration failed ({code}): {body}",
                "log": log,
            }
        dropped = name_filter or ",".join(sorted(remove_ids))
        log.append(
            f"Updated {SCAN_NAME}: removed {dropped}; remaining {len(remaining)} cluster(s)"
        )
        return {
            "state": "ok",
            "message": f"scan schedule {SCAN_NAME} updated (dropped selection)",
            "log": log,
            "configId": config_id,
        }

    if dry_run:
        log.append("Planned changes (Central scan configuration):")
        log.append(f"  - DELETE {path} ({SCAN_NAME})")
        return {
            "state": "ok",
            "message": f"dry-run: would delete scan schedule {SCAN_NAME}",
            "log": log,
            "configId": config_id,
        }

    code, body = central_request(base, token, "DELETE", path)
    if code not in (200, 204, 404):
        return {
            "state": "error",
            "message": f"delete scan configuration failed ({code}): {body}",
            "log": log,
            "configId": config_id,
        }
    log.append(f"Deleted Central scan configuration {SCAN_NAME} ({config_id})")
    return {
        "state": "ok",
        "message": f"scan schedule {SCAN_NAME} deleted",
        "log": log,
    }


def apply_scan(*, dry_run: bool) -> dict[str, Any]:
    log: list[str] = []
    creds = load_lab_credentials()
    base, token = central_connection(creds)
    auth_err = check_central_auth(base, token, creds=creds)
    if auth_err:
        return {"state": "error", "message": auth_err, "log": log}

    name_filter, id_filter = _selection_filters()
    scoped_rows, warnings = resolve_lab_clusters(
        base, token, name_filter=name_filter, id_filter=id_filter or None
    )
    for w in warnings:
        log.append(f"note: {w}")
    if not scoped_rows:
        return {
            "state": "error",
            "message": (
                f"cannot resolve selection for schedule "
                f"(name={name_filter!r} ids={id_filter})"
            ),
            "log": log,
        }

    # Union: keep existing schedule members + selected ids (idempotent add).
    existing = find_scan_configuration(list_scan_configurations(base, token))
    union_ids = set(config_cluster_ids(existing) if existing else [])
    for row in scoped_rows:
        union_ids.add(str(row["id"]))
    name_by_id = {str(r["id"]): r["name"] for r in scoped_rows}
    # Best-effort names for clusters already on the schedule.
    try:
        all_rows, _ = resolve_lab_clusters(base, token, name_filter="")
        for r in all_rows:
            name_by_id.setdefault(str(r["id"]), r["name"])
    except RuntimeError:
        pass
    target_rows = [
        {"id": cid, "name": name_by_id.get(cid, cid)} for cid in sorted(union_ids)
    ]
    wait_rows = scoped_rows

    desired_ids = [str(r["id"]) for r in target_rows]
    desired_names = [r["name"] for r in target_rows]
    desired = desired_scan_body(desired_ids)
    existing = find_scan_configuration(list_scan_configurations(base, token))

    for row in wait_rows:
        try:
            log.extend(
                wait_for_profiles(
                    base, token, str(row["id"]), row["name"], dry_run=dry_run
                )
            )
        except RuntimeError as exc:
            log.append(str(exc))
            target_rows = [r for r in target_rows if str(r["id"]) != str(row["id"])]
            desired_ids = [str(r["id"]) for r in target_rows]
            desired_names = [r["name"] for r in target_rows]
            desired = desired_scan_body(desired_ids)
            log.append(f"omitting {row['name']} from schedule (profiles not ready)")

    if not desired_ids:
        return {
            "state": "error",
            "message": "no clusters left with compliance profiles for schedule",
            "log": log,
        }

    log.append(
        f"Target secured cluster(s): {', '.join(desired_names)} ({len(desired_ids)})"
    )

    if dry_run:
        action = "PUT" if existing else "POST"
        path = (
            f"/v2/compliance/scan/configurations/{existing['id']}"
            if existing
            else "/v2/compliance/scan/configurations"
        )
        log.append("Planned changes (phase 2 - Central scan configuration):")
        log.append(f"  - {action} {path}")
        log.append("  - POST /v2/compliance/scan/configurations/{id}/run (on-demand)")
        log.append(json.dumps(desired, indent=2))
        return {
            "state": "ok",
            "message": scan_status_message(
                matched=bool(existing and config_matches(existing, desired)),
                exists=bool(existing),
                cluster_names=desired_names,
            ),
            "log": log,
            "clusterIds": desired_ids,
            "clusterNames": desired_names,
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
    log.append(f"Triggered on-demand compliance scan for {SCAN_NAME}")

    final = evaluate_scan()
    if final.get("detail"):
        log.append(final["detail"])
    final["log"] = log
    final.pop("detail", None)
    return final


def main() -> int:
    global SECURED_CLUSTER_OVERRIDE, SECURED_CLUSTER_IDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "run", "uninstall"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cli", action="store_true", help="Emit human-readable log lines")
    parser.add_argument(
        "--secured-cluster",
        default="",
        help="Narrow to one lab/ACS secured cluster name (legacy)",
    )
    parser.add_argument(
        "--secured-cluster-id",
        action="append",
        default=[],
        dest="secured_cluster_ids",
        help="Repeatable lab secured-cluster id (orchestrator selection)",
    )
    args = parser.parse_args()
    SECURED_CLUSTER_OVERRIDE = (args.secured_cluster or "").strip()
    SECURED_CLUSTER_IDS = [
        s.strip() for s in (args.secured_cluster_ids or []) if (s or "").strip()
    ]

    try:
        if args.command == "status":
            result = evaluate_scan()
        elif args.command == "uninstall":
            result = uninstall_scan(dry_run=args.dry_run)
        else:
            result = apply_scan(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - module boundary
        result = {"state": "error", "message": str(exc), "log": []}

    if args.cli:
        for line in result.get("log") or []:
            if line:
                print(line)
        for w in result.get("warnings") or []:
            print(f"warning: {w}")
        print(f"scan-status\t{result.get('state', 'error')}\t{result.get('message', '')}")
    else:
        print(json.dumps(result, default=str))

    state = result.get("state", "error")
    if args.command == "status":
        return 0 if state in ("ok", "needs-run") else 1
    if args.dry_run:
        return 0 if state != "error" else 1
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
