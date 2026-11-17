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

Default: implement cmd_status / cmd_run / cmd_uninstall below (simple path).
Selectable option flags: see templates/module-choices.md (ADVANCED).
Do not add those flags here unless you need them.

Uninstall may stay in the shell (skeleton's refuse-or-delete) until Central
cleanup needs Python; when it does, call this helper's uninstall subcommand
from do_uninstall the same way as status/run.
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
    """Mandatory GUI Status folds. See ADDING-A-MODULE.md ('Status folds')."""
    print(
        "ACS_SECTIONS_JSON="
        + json.dumps({"sections": sections}, separators=(",", ":"))
    )


def teaching_sections() -> list:
    """Same four-group teaching shape as templates/module-skeleton.sh."""
    return [
        {
            "group": "Group 1 header. e.g. Overview",
            "title": "Title of first blob. e.g. Installed components",
            "summary": "(optional) right hand side info (1/1 ready)",
            "body": (
                "Body of the first blob. e.g.: Installed network-policy.yaml, "
                "application.yaml"
            ),
            "bodyFormat": "prose",
        },
        {
            "group": "Group 2 header. e.g. Notes",
            "title": "Title of second blob. e.g. Multi-line prose",
            "summary": "(optional) right hand side info",
            "body": (
                "Body of a multi-line prose blob.\n"
                "Each newline becomes a line break in the GUI.\n"
                "\n"
                'Use bodyFormat "prose" for normal readable text '
                "(this is the default if omitted)."
            ),
            "bodyFormat": "prose",
        },
        {
            "group": "Group 3 header. e.g. Config",
            "title": "Title of third blob. e.g. Config object",
            "summary": "(optional) right hand side info (matched)",
            "tag": "ok",
            "tagLabel": "(optional) badge text; tag sets color (ok/ready, error/fail)",
            "body": {
                "note": (
                    "Body of the third blob. bodyFormat json pretty-prints "
                    "this object in a monospace block"
                ),
                "replicas": 1,
                "image": "quay.io/example/app:1.0",
            },
            "bodyFormat": "json",
        },
        {
            "group": "Group 4 header. e.g. Workloads",
            "title": "Title of fourth blob. e.g. Deployment",
            "summary": "(optional) right hand side info (0/1 ready)",
            "tag": "error",
            "tagLabel": "(optional) badge text; tag sets color (ok/ready, error/fail)",
            "body": {"note": "Body of the fourth blob. e.g. status detail"},
            "bodyFormat": "json",
        },
    ]


def cmd_status(_: argparse.Namespace) -> int:
    # TODO: replace teaching_sections() with real checks against the lab.
    # from lib import central  # noqa: F401
    emit_sections(teaching_sections())
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


def cmd_uninstall(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(f"{MODULE_ID}: uninstall dry-run")
        print("  TODO: describe what uninstall would remove (no mutations).")
        emit_status_line("ok", "uninstall dry-run only")
        return 0

    # TODO: remove what run created, or keep this refusal (same contract as the shell).
    print(f"{MODULE_ID}: uninstall is not implemented for this module.", file=sys.stderr)
    emit_status_line("error", "uninstall not implemented")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Helper for module {MODULE_ID}")
    # Simple path: parent parser has no module-specific choice flags.
    # Subcommands only. Most helpers stop here.
    # For selectable option flags, see templates/module-choices.md (ADVANCED).
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser(
        "status", help="Print Status folds + one tab-separated status line"
    )
    p_status.add_argument(
        "--cli",
        action="store_true",
        help="Reserved for shell wrappers (ignored)",
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

    p_un = sub.add_parser("uninstall", help="Remove module artifacts (or --dry-run)")
    p_un.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan only; do not mutate",
    )
    p_un.add_argument(
        "--cli",
        action="store_true",
        help="Reserved for shell wrappers (ignored)",
    )
    p_un.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
