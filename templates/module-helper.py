#!/usr/bin/env python3
"""Optional Python helper for a module.

Copy next to your shell entrypoint only when bash is a poor fit - usually
Central HTTP/JSON work. Example:

  cp templates/module-skeleton.sh modules/my-feature.sh
  cp templates/module-helper.py modules/my_feature.py
  chmod +x modules/my-feature.sh

Wire the helper from the shell script using the commented block in
templates/module-skeleton.sh (set HELPER to modules/my_feature.py).

The shell script remains the module entrypoint the orchestrator runs.
This file is a library/CLI the shell calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# TODO: set to the same id as modules/<id>.sh and config/modules.json
MODULE_ID = "my-feature"


def emit_status_line(state: str, message: str) -> None:
    """One line: id, state, message separated by tabs (what --status must print)."""
    print(f"{MODULE_ID}\t{state}\t{message}")


def emit_sections(sections: list) -> None:
    """Optional GUI Status folds. See ADDING-A-MODULE.md ('Detailed Status folds')."""
    print(
        "ACS_SECTIONS_JSON="
        + json.dumps({"sections": sections}, separators=(",", ":"))
    )


def cmd_status(_: argparse.Namespace) -> int:
    # TODO: real check. Use lib.central / lib.openshift as needed.
    # from lib import central  # noqa: F401
    # Optional folds:
    # emit_sections([{
    #     "group": "Overview",
    #     "title": "Check",
    #     "summary": "ok",
    #     "body": "Detail for the expanded fold.",
    #     "bodyFormat": "prose",
    # }])
    emit_status_line(
        "needs-run", f"TODO: implement status in modules/{Path(__file__).name}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(f"{MODULE_ID}: dry-run")
        print("  TODO: describe planned Central/cluster changes (no mutations).")
        emit_status_line("ok", "dry-run only")
        return 0

    # TODO: apply changes, then emit ok / needs-run / error
    emit_status_line("error", f"TODO: implement run in modules/{Path(__file__).name}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Helper for module {MODULE_ID}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser(
        "status", help="Print one tab-separated status line (id, state, message)"
    )
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="Apply module (or --dry-run)")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan only; do not mutate",
    )
    p_run.add_argument(
        "--cli",
        action="store_true",
        help="Reserved for shell wrappers (ignored)",
    )
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
