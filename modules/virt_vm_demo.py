#!/usr/bin/env python3
"""Central helpers for virt-vm-demo via /v2/virtualmachines APIs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
)


def probe_vms(namespace: str | None = None) -> dict[str, Any]:
    """Return Virtual Machines known to Central (v2 API used by the UI)."""
    creds = load_lab_credentials()
    base, auth = central_connection(creds)
    err = check_central_auth(base, auth, creds=creds)
    if err:
        return {"ok": False, "error": err, "vms": [], "count": 0}

    code, body = central_request(
        base,
        auth,
        "GET",
        "/v2/virtualmachines/vms?pagination.limit=100",
        creds=creds,
    )
    if code != 200 or not isinstance(body, dict):
        return {
            "ok": False,
            "error": f"GET /v2/virtualmachines/vms -> {code}: {body}",
            "vms": [],
            "count": 0,
        }

    vms: list[dict[str, Any]] = list(body.get("vms") or [])
    if namespace:
        vms = [vm for vm in vms if (vm.get("namespace") or "") == namespace]

    scanned = 0
    with_cves = 0
    samples: list[str] = []
    for vm in vms:
        name = vm.get("name") or "?"
        scan_time = vm.get("scanTime")
        comp = vm.get("componentScanCount") or {}
        sev = vm.get("cveSeverityCounts") or {}
        # 5.0 API: severity values are ints or {total, fixable} objects
        sev_n = 0
        for k in ("critical", "important", "moderate", "low", "unknown"):
            v = sev.get(k)
            if isinstance(v, dict):
                sev_n += int(v.get("total") or 0)
            elif v is not None:
                sev_n += int(v or 0)
        comp_scanned = int((comp.get("scanned") if isinstance(comp, dict) else 0) or 0)
        if scan_time:
            scanned += 1
        if sev_n or comp_scanned:
            with_cves += 1
        samples.append(
            f"{name}: guest={vm.get('guestOs') or '?'} "
            f"scanTime={'yes' if scan_time else 'no'} "
            f"components={comp.get('scanned', 0)}/{comp.get('total', 0)} "
            f"cves~={sev_n}"
        )

    return {
        "ok": True,
        "error": "",
        "api": "/v2/virtualmachines/vms",
        "count": len(vms),
        "scanned": scanned,
        "withFindings": with_cves,
        "samples": samples,
        "vms": [
            {
                "id": vm.get("id"),
                "name": vm.get("name"),
                "namespace": vm.get("namespace"),
                "guestOs": vm.get("guestOs"),
                "scanTime": vm.get("scanTime"),
                "componentScanCount": vm.get("componentScanCount"),
                "cveSeverityCounts": vm.get("cveSeverityCounts"),
            }
            for vm in vms
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["probe-vms", "json"])
    p.add_argument("--namespace", default="")
    args = p.parse_args()
    out = probe_vms(args.namespace or None)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
