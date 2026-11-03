#!/usr/bin/env python3
"""Ensure Central has an openshift-type auth provider (Users Part 2)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_console_url,
    central_request,
    check_central_auth,
    load_lab_credentials,
)

MODULE_ID = "users-part2-oauth"
PROVIDER_NAME = "OpenShift"
PROVIDER_TYPE = "openshift"


def ui_endpoint_host(creds: dict[str, Any]) -> str:
    url = central_console_url(creds)
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise RuntimeError(f"cannot derive uiEndpoint from Central URL: {url}")
    return host


def list_auth_providers(
    base: str, authorization: str, *, creds: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/authProviders", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/authProviders failed ({code}): {body}")
    return body.get("authProviders") or []


def find_openshift_provider(
    providers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in providers:
        if item.get("type") == PROVIDER_TYPE:
            return item
    return None


DEMO_SCRIPT_SECTION: dict[str, Any] = {
    "group": "Demo",
    "title": "Demo script",
    "summary": "users walkthrough",
    "tag": "ok",
    "tagLabel": "guide",
    "body": (
        "Users Part 2 (OAuth): Central Login with OpenShift for the ACS "
        "console plugin demo.\n\n"
        "Before/after experience tables for adam, boaz, and chris:\n"
        "  modules/users-part1-ocp-demo.md\n"
        "  GUI: /help?doc=users-part1-ocp-demo\n\n"
        "This module is required before OpenShift login works in that walkthrough."
    ),
    "bodyFormat": "prose",
}


def build_sections(
    *,
    central_ok: bool,
    central_body: str,
    provider: dict[str, Any] | None,
    central_error: str = "",
) -> list[dict[str, Any]]:
    if not central_ok:
        return [
            dict(DEMO_SCRIPT_SECTION),
            {
                "group": "Central",
                "title": "API",
                "summary": "error",
                "tag": "error",
                "tagLabel": "error",
                "body": central_error or central_body,
                "bodyFormat": "prose",
            },
            {
                "group": "Auth",
                "title": "OpenShift provider",
                "summary": "unknown",
                "tag": "error",
                "tagLabel": "error",
                "body": "Skipped; Central API not available.",
                "bodyFormat": "prose",
            },
        ]

    central_section = {
        "group": "Central",
        "title": "API",
        "summary": "reachable",
        "tag": "ok",
        "tagLabel": "ok",
        "body": central_body,
        "bodyFormat": "prose",
    }

    if provider:
        name = provider.get("name") or "(unnamed)"
        pid = provider.get("id") or "?"
        enabled = provider.get("enabled")
        auth_section = {
            "group": "Auth",
            "title": "OpenShift provider",
            "summary": "present",
            "tag": "ok",
            "tagLabel": "present",
            "body": f"name: {name}\nid: {pid}\nenabled: {enabled}",
            "bodyFormat": "prose",
        }
    else:
        auth_section = {
            "group": "Auth",
            "title": "OpenShift provider",
            "summary": "missing",
            "tag": "warn",
            "tagLabel": "needs run",
            "body": "No openshift-type auth provider on Central.",
            "bodyFormat": "prose",
        }

    return [dict(DEMO_SCRIPT_SECTION), central_section, auth_section]


def evaluate() -> dict[str, Any]:
    creds = load_lab_credentials()
    base, authorization = central_connection(creds)
    err = check_central_auth(base, authorization, creds=creds)
    if err:
        return {
            "state": "error",
            "message": err,
            "central_ok": False,
            "central_body": base,
            "central_error": err,
            "provider": None,
            "sections": build_sections(
                central_ok=False,
                central_body=base,
                provider=None,
                central_error=err,
            ),
        }

    providers = list_auth_providers(base, authorization, creds=creds)
    provider = find_openshift_provider(providers)
    sections = build_sections(
        central_ok=True,
        central_body=base,
        provider=provider,
    )
    if provider:
        return {
            "state": "ok",
            "message": (
                f"openshift provider present "
                f"(name={provider.get('name')}; id={provider.get('id')})"
            ),
            "central_ok": True,
            "central_body": base,
            "provider": provider,
            "sections": sections,
            "creds": creds,
            "base": base,
            "authorization": authorization,
        }
    return {
        "state": "needs-run",
        "message": "no openshift-type auth provider",
        "central_ok": True,
        "central_body": base,
        "provider": None,
        "sections": sections,
        "creds": creds,
        "base": base,
        "authorization": authorization,
    }


def apply(*, dry_run: bool) -> dict[str, Any]:
    status = evaluate()
    if status["state"] == "error":
        return status

    provider = status.get("provider")
    if provider:
        name = provider.get("name")
        pid = provider.get("id")
        msg = f"openshift provider already present (name={name}; id={pid})"
        return {
            **status,
            "state": "ok",
            "message": msg if not dry_run else f"dry-run: {msg}",
            "log": [msg],
        }

    creds = status["creds"]
    host = ui_endpoint_host(creds)
    if dry_run:
        plan = (
            f"would create openshift auth provider "
            f"name={PROVIDER_NAME} uiEndpoint={host}"
        )
        return {
            **status,
            "state": "ok",
            "message": f"dry-run: {plan}",
            "log": [plan],
        }

    body = {
        "name": PROVIDER_NAME,
        "type": PROVIDER_TYPE,
        "uiEndpoint": host,
        "enabled": True,
        "config": {},
        "validated": False,
        "extraUiEndpoints": [],
        "active": False,
        "requiredAttributes": [],
        "claimMappings": {},
    }
    code, resp = central_request(
        status["base"],
        status["authorization"],
        "POST",
        "/v1/authProviders",
        body,
        creds=creds,
    )
    if code not in (200, 201):
        return {
            "state": "error",
            "message": f"POST /v1/authProviders failed ({code}): {resp}",
            "sections": status.get("sections") or [],
        }

    created_id = (resp or {}).get("id") if isinstance(resp, dict) else None
    final = evaluate()
    final["log"] = [
        f"created openshift auth provider name={PROVIDER_NAME} id={created_id}"
    ]
    if final.get("state") == "ok":
        final["message"] = (
            f"openshift provider ready "
            f"(name={PROVIDER_NAME}; id={created_id})"
        )
    return final


def uninstall(*, dry_run: bool) -> dict[str, Any]:
    status = evaluate()
    if status["state"] == "error":
        return status

    provider = status.get("provider")
    if not provider:
        msg = "no openshift-type auth provider to remove"
        return {
            **status,
            "state": "ok",
            "message": msg if not dry_run else f"dry-run: {msg}",
            "log": [msg],
        }

    pid = provider.get("id")
    name = provider.get("name")
    if dry_run:
        plan = f"would delete openshift auth provider name={name} id={pid}"
        return {
            **status,
            "state": "ok",
            "message": f"dry-run: {plan}",
            "log": [plan],
        }

    code, resp = central_request(
        status["base"],
        status["authorization"],
        "DELETE",
        f"/v1/authProviders/{pid}",
        creds=status["creds"],
    )
    if code not in (200, 204) and code != 404:
        return {
            "state": "error",
            "message": f"DELETE /v1/authProviders/{pid} failed ({code}): {resp}",
            "sections": status.get("sections") or [],
        }

    final = evaluate()
    final["log"] = [f"deleted openshift auth provider name={name} id={pid}"]
    final["state"] = "ok"
    final["message"] = f"removed openshift provider id={pid}"
    # After delete, evaluate is needs-run; keep ok for uninstall success.
    final["sections"] = build_sections(
        central_ok=True,
        central_body=status["central_body"],
        provider=None,
    )
    return final


def print_cli(result: dict[str, Any]) -> None:
    for line in result.get("log") or []:
        print(line)
    sections = result.get("sections")
    if sections is None:
        sections = build_sections(
            central_ok=bool(result.get("central_ok")),
            central_body=str(result.get("central_body") or ""),
            provider=result.get("provider"),
            central_error=str(result.get("central_error") or result.get("message") or ""),
        )
    if sections:
        print(
            "ACS_SECTIONS_JSON="
            + json.dumps({"sections": sections}, separators=(",", ":"))
        )
    state = result.get("state", "error")
    message = result.get("message", "")
    print(f"{MODULE_ID}\t{state}\t{message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "run", "uninstall"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Print human output and TSV for shell wrapper",
    )
    args = parser.parse_args()

    try:
        if args.command == "status":
            result = evaluate()
        elif args.command == "run":
            result = apply(dry_run=args.dry_run)
        else:
            result = uninstall(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - module status contract
        result = {
            "state": "error",
            "message": str(exc),
            "central_ok": False,
            "central_body": "",
            "central_error": str(exc),
            "provider": None,
        }

    if args.cli:
        print_cli(result)
    else:
        # Strip non-serializable connection handles for JSON mode
        safe = {
            k: v
            for k, v in result.items()
            if k not in ("creds", "authorization")
        }
        print(json.dumps(safe, default=str))

    state = result.get("state", "error")
    if args.command == "status":
        return 0 if state in ("ok", "needs-run") else 1
    if args.dry_run:
        return 0 if state != "error" else 1
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
