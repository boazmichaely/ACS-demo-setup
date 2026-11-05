"""Plan multi-SC module invocations for the CLI/GUI orchestrator.

When no secured-cluster ids are passed, callers must invoke the module once
with no new flags (identical to pre-fan-out behavior).

When ids are passed, build OpenShift-N then Central-1 argv extras and env.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.central import load_lab_document, repo_root
from lib.lab_doc import active_lab
from lib.openshift import CENTRAL_ONLY_SC_ID

@dataclass(frozen=True)
class ModuleInvocation:
    plane: str | None
    sc_ids: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    argv_extra: tuple[str, ...] = ()


def load_modules_catalog(root: Path | None = None) -> list[dict[str, Any]]:
    path = (root or repo_root()) / "config" / "modules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("modules") or [])


def module_row(module_id: str, root: Path | None = None) -> dict[str, Any]:
    for row in load_modules_catalog(root):
        if (row.get("id") or "").strip() == module_id:
            return row
    raise KeyError(f"unknown module id: {module_id}")


def impact_planes(row: dict[str, Any]) -> list[str]:
    planes = row.get("impactPlanes")
    if not isinstance(planes, list) or not planes:
        return []
    out: list[str] = []
    for p in planes:
        s = str(p).strip().lower()
        if s in ("central", "openshift") and s not in out:
            out.append(s)
    return out


def _sc_name_by_id(sc_id: str, root: Path | None = None) -> str:
    doc = load_lab_document(root)
    lab = active_lab(doc)
    clusters = list(lab.get("securedClusters") or [])
    if sc_id == CENTRAL_ONLY_SC_ID and not clusters:
        return "central"
    for item in clusters:
        if (item.get("id") or "").strip() == sc_id:
            name = (item.get("name") or "").strip()
            if not name:
                raise RuntimeError(f"secured cluster {sc_id!r} has an empty name")
            return name
    known = ", ".join(
        f"{c.get('name') or '?'}({c.get('id') or '?'})" for c in clusters
    ) or "(none)"
    raise RuntimeError(
        f"secured cluster id {sc_id!r} not in active lab securedClusters ({known})"
    )


def _openshift_invocation(sc_id: str, root: Path | None = None) -> ModuleInvocation:
    name = _sc_name_by_id(sc_id, root)
    return ModuleInvocation(
        plane="openshift",
        sc_ids=(sc_id,),
        env={
            "ACS_DEMO_PLANE": "openshift",
            "ACS_DEMO_SC_ID": sc_id,
            "ACS_DEMO_SC_NAME": name,
        },
        argv_extra=("--plane", "openshift", "--secured-cluster-id", sc_id),
    )


def _central_invocation(sc_ids: list[str], root: Path | None = None) -> ModuleInvocation:
    argv: list[str] = ["--plane", "central"]
    env: dict[str, str] = {"ACS_DEMO_PLANE": "central"}
    ids = tuple(sc_ids)
    if ids:
        # Primary env points at the first id; modules that need the full set
        # should read repeated --secured-cluster-id flags.
        env["ACS_DEMO_SC_ID"] = ids[0]
        env["ACS_DEMO_SC_NAME"] = _sc_name_by_id(ids[0], root)
        for sid in ids:
            argv.extend(["--secured-cluster-id", sid])
    return ModuleInvocation(
        plane="central",
        sc_ids=ids,
        env=env,
        argv_extra=tuple(argv),
    )


def plan_module_invocations(
    module_row_or_id: dict[str, Any] | str,
    action: str,
    sc_ids: list[str] | None = None,
    *,
    root: Path | None = None,
) -> list[ModuleInvocation]:
    """Return ordered invocations for run/uninstall/status.

    Empty ``sc_ids`` → one bare invocation (no plane flags) so callers can
    preserve legacy single-process behavior.

    Non-empty ``sc_ids`` → OpenShift once per id, then Central once with all
    ids when the catalog lists both planes.
    """
    if isinstance(module_row_or_id, str):
        row = module_row(module_row_or_id, root)
    else:
        row = module_row_or_id

    ids = [s.strip() for s in (sc_ids or []) if (s or "").strip()]
    # Dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            uniq.append(sid)

    if not uniq:
        return [ModuleInvocation(plane=None, sc_ids=(), env={}, argv_extra=())]

    planes = impact_planes(row)
    if not planes:
        # Catalog missing planes: pass ids through on a single invoke without --plane
        argv: list[str] = []
        for sid in uniq:
            argv.extend(["--secured-cluster-id", sid])
        env = {
            "ACS_DEMO_SC_ID": uniq[0],
            "ACS_DEMO_SC_NAME": _sc_name_by_id(uniq[0], root),
        }
        return [
            ModuleInvocation(
                plane=None,
                sc_ids=tuple(uniq),
                env=env,
                argv_extra=tuple(argv),
            )
        ]

    out: list[ModuleInvocation] = []
    # Install and uninstall: OpenShift N then Central 1.
    # Status uses the same order so OpenShift facts are collected first.
    _ = action  # reserved for future plane-order overrides
    if "openshift" in planes:
        for sid in uniq:
            out.append(_openshift_invocation(sid, root))
    if "central" in planes:
        out.append(_central_invocation(uniq, root))
    return out


def invocations_to_json(invocations: list[ModuleInvocation]) -> str:
    payload = [
        {
            "plane": inv.plane,
            "sc_ids": list(inv.sc_ids),
            "env": inv.env,
            "argv_extra": list(inv.argv_extra),
        }
        for inv in invocations
    ]
    return json.dumps(payload)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m lib.module_orchestrate",
        description="Plan multi-SC module invocations (JSON)",
    )
    parser.add_argument("--module", required=True, help="Module id from modules.json")
    parser.add_argument(
        "--action",
        default="run",
        choices=("run", "uninstall", "status"),
        help="Action being planned (default: run)",
    )
    parser.add_argument(
        "--secured-cluster-id",
        action="append",
        default=[],
        dest="sc_ids",
        help="Repeatable lab secured-cluster id",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        plan = plan_module_invocations(args.module, args.action, list(args.sc_ids))
    except (KeyError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(invocations_to_json(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
