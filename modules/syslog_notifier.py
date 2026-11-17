#!/usr/bin/env python3
"""Central Syslog notifier helper for syslog-notifier module."""

from __future__ import annotations

import argparse
import json
import sys
import time
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

MODULE_ID = "syslog-notifier"
DEFAULT_NAME = "acs-demo-syslog"
DEFAULT_FACILITY = "LOCAL0"
DEFAULT_PORT = 5140
# Central Test can race a brand-new LoadBalancer; retry briefly.
TEST_ATTEMPTS = 4
TEST_RETRY_SLEEP_SEC = 5


def emit_status_line(state: str, message: str) -> None:
    print(f"{MODULE_ID}\t{state}\t{message}")


def emit_sections(sections: list[dict[str, Any]]) -> None:
    print(
        "ACS_SECTIONS_JSON="
        + json.dumps({"sections": sections}, separators=(",", ":"))
    )


def _tag_for_state(state: str) -> str:
    if state == "ok":
        return "ok"
    if state == "error":
        return "error"
    return "needs-run"


def list_notifiers(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/notifiers", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/notifiers failed ({code}): {body}")
    if not isinstance(body, dict):
        raise RuntimeError(f"GET /v1/notifiers unexpected body: {body!r}")
    raw = body.get("notifiers") or []
    return [n for n in raw if isinstance(n, dict)]


def find_syslog_notifier(
    notifiers: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    want = (name or "").strip()
    for n in notifiers:
        if (n.get("name") or "").strip() != want:
            continue
        if (n.get("type") or "").lower() != "syslog":
            continue
        return n
    return None


def normalize_format(raw: str) -> str:
    s = (raw or "CEF").strip().upper()
    if s in ("LEGACY", "CEF_LEGACY", "CEF-LEGACY", "LEGACY_CEF"):
        return "LEGACY"
    return "CEF"


def notifier_body(
    *,
    name: str,
    hostname: str,
    port: int,
    message_format: str,
    ui_endpoint: str,
    notifier_id: str = "",
    facility: str = DEFAULT_FACILITY,
) -> dict[str, Any]:
    fmt = normalize_format(message_format)
    obj: dict[str, Any] = {
        "name": name,
        "type": "syslog",
        "uiEndpoint": ui_endpoint.rstrip("/"),
        "syslog": {
            "localFacility": facility,
            "messageFormat": fmt,
            "maxMessageSize": 0,
            "tcpConfig": {
                "hostname": hostname,
                "port": int(port),
                "useTls": False,
                "skipTlsVerify": False,
            },
            "extraFields": [{"key": "source", "value": "rhacs"}],
        },
    }
    if notifier_id:
        obj["id"] = notifier_id
    return obj


def syslog_endpoint(notifier: dict[str, Any] | None) -> tuple[str, int, str]:
    if not notifier:
        return "", 0, ""
    sy = notifier.get("syslog") or {}
    if not isinstance(sy, dict):
        return "", 0, ""
    tcp = sy.get("tcpConfig") or {}
    if not isinstance(tcp, dict):
        tcp = {}
    host = str(tcp.get("hostname") or "").strip()
    try:
        port = int(tcp.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    fmt = str(sy.get("messageFormat") or "").strip()
    return host, port, fmt


def build_notifier_sections(
    *,
    name: str,
    want_host: str,
    want_port: int,
    want_format: str,
    notifier: dict[str, Any] | None,
    state: str,
) -> list[dict[str, Any]]:
    nid = str((notifier or {}).get("id") or "")
    got_host, got_port, got_fmt = syslog_endpoint(notifier)
    body = "\n".join(
        [
            f"Notifier name: {name}",
            f"Central id: {nid or '(none)'}",
            f"Want endpoint: {want_host}:{want_port}" if want_host else "Want endpoint: (unknown)",
            f"Central endpoint: {got_host}:{got_port}" if got_host else "Central endpoint: (none)",
            f"Message format (want): {normalize_format(want_format)}",
            f"Message format (Central): {got_fmt or '(none)'}",
            "Extra field: source=rhacs",
            "TLS: disabled (lab v1)",
        ]
    )
    return [
        {
            "group": "Syslog notifier",
            "title": name,
            "summary": state,
            "tag": _tag_for_state(state),
            "body": body,
            "bodyFormat": "prose",
        }
    ]


def assess(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    name: str,
    host: str,
    port: int,
    message_format: str,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    if not name:
        return (
            "error",
            "notifier name is empty",
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=None,
                state="error",
            ),
            None,
        )
    if not host or port <= 0:
        return (
            "needs-run",
            "syslog LoadBalancer endpoint unknown (deploy secured-cluster plane first)",
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=None,
                state="needs-run",
            ),
            None,
        )

    notifiers = list_notifiers(base, authorization, creds=creds)
    hit = find_syslog_notifier(notifiers, name)
    if not hit:
        return (
            "needs-run",
            f"Syslog notifier {name!r} not configured",
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=None,
                state="needs-run",
            ),
            None,
        )

    got_host, got_port, got_fmt = syslog_endpoint(hit)
    want_fmt = normalize_format(message_format)
    if got_host != host or got_port != port:
        return (
            "needs-run",
            f"Syslog notifier endpoint drifted (Central {got_host}:{got_port}, want {host}:{port})",
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=hit,
                state="needs-run",
            ),
            hit,
        )
    if got_fmt and got_fmt.upper() != want_fmt:
        return (
            "needs-run",
            f"Syslog message format drifted (Central {got_fmt}, want {want_fmt})",
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=hit,
                state="needs-run",
            ),
            hit,
        )

    return (
        "ok",
        f"Syslog notifier {name} → {host}:{port} ({want_fmt})",
        build_notifier_sections(
            name=name,
            want_host=host,
            want_port=port,
            want_format=message_format,
            notifier=hit,
            state="ok",
        ),
        hit,
    )


def ensure_notifier(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    name: str,
    host: str,
    port: int,
    message_format: str,
    dry_run: bool,
) -> dict[str, Any]:
    notifiers = list_notifiers(base, authorization, creds=creds)
    existing = find_syslog_notifier(notifiers, name)
    body = notifier_body(
        name=name,
        hostname=host,
        port=port,
        message_format=message_format,
        ui_endpoint=base,
        notifier_id=str((existing or {}).get("id") or ""),
    )
    if dry_run:
        action = "PUT" if existing else "POST"
        print(f"{MODULE_ID}: dry-run would {action} /v1/notifiers for {name!r} → {host}:{port}")
        return existing or body

    if existing:
        nid = str(existing.get("id") or "")
        code, resp = central_request(
            base, authorization, "PUT", f"/v1/notifiers/{nid}", body, creds=creds
        )
        if code != 200:
            raise RuntimeError(f"PUT /v1/notifiers/{nid} failed ({code}): {resp}")
        notifiers = list_notifiers(base, authorization, creds=creds)
        hit = find_syslog_notifier(notifiers, name)
        if not hit:
            raise RuntimeError(f"notifier {name!r} missing after PUT")
        return hit

    code, resp = central_request(
        base, authorization, "POST", "/v1/notifiers", body, creds=creds
    )
    if code not in (200, 201) or not isinstance(resp, dict):
        raise RuntimeError(f"POST /v1/notifiers failed ({code}): {resp}")
    # Re-fetch: TestNotifier needs the stored syslog object (incl. maxMessageSize).
    notifiers = list_notifiers(base, authorization, creds=creds)
    hit = find_syslog_notifier(notifiers, name)
    if not hit:
        raise RuntimeError(f"notifier {name!r} missing after POST")
    return hit


def test_notifier(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    notifier: dict[str, Any],
    dry_run: bool,
) -> None:
    # Prefer the full stored notifier; incomplete create responses make Test return 400.
    body = {
        "id": notifier.get("id"),
        "name": notifier.get("name"),
        "type": "syslog",
        "uiEndpoint": (notifier.get("uiEndpoint") or base).rstrip("/"),
        "labelKey": notifier.get("labelKey") or "",
        "labelDefault": notifier.get("labelDefault") or "",
        "syslog": notifier.get("syslog") or {},
    }
    if dry_run:
        print(f"{MODULE_ID}: dry-run would POST /v1/notifiers/test for {body.get('name')!r}")
        return

    last_err: Exception | None = None
    for attempt in range(1, TEST_ATTEMPTS + 1):
        # Re-fetch each attempt in case Central finishes persisting fields late.
        nid = str(notifier.get("id") or "").strip()
        name = str(notifier.get("name") or "").strip()
        if nid or name:
            notifiers = list_notifiers(base, authorization, creds=creds)
            fresh = None
            if nid:
                for n in notifiers:
                    if str(n.get("id") or "") == nid:
                        fresh = n
                        break
            if fresh is None and name:
                fresh = find_syslog_notifier(notifiers, name)
            if fresh:
                notifier = fresh
                body["id"] = notifier.get("id")
                body["name"] = notifier.get("name")
                body["uiEndpoint"] = (notifier.get("uiEndpoint") or base).rstrip("/")
                body["syslog"] = notifier.get("syslog") or {}

        code, resp = central_request(
            base, authorization, "POST", "/v1/notifiers/test", body, creds=creds
        )
        if code == 200:
            if attempt > 1:
                print(f"{MODULE_ID}: Central Test succeeded on attempt {attempt}")
            return
        last_err = RuntimeError(f"POST /v1/notifiers/test failed ({code}): {resp}")
        if attempt < TEST_ATTEMPTS:
            print(
                f"{MODULE_ID}: Central Test attempt {attempt}/{TEST_ATTEMPTS} failed; "
                f"retry in {TEST_RETRY_SLEEP_SEC}s…"
            )
            time.sleep(TEST_RETRY_SLEEP_SEC)
    assert last_err is not None
    raise last_err


def delete_notifier(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    notifier_id: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"{MODULE_ID}: dry-run would DELETE /v1/notifiers/{notifier_id}")
        return
    code, resp = central_request(
        base, authorization, "DELETE", f"/v1/notifiers/{notifier_id}", creds=creds
    )
    if code not in (200, 204):
        raise RuntimeError(f"DELETE /v1/notifiers/{notifier_id} failed ({code}): {resp}")


def cmd_status(args: argparse.Namespace) -> int:
    name = (args.name or DEFAULT_NAME).strip()
    host = (args.host or "").strip()
    port = int(args.port or DEFAULT_PORT)
    message_format = normalize_format(args.format or "CEF")
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_sections(
                build_notifier_sections(
                    name=name,
                    want_host=host,
                    want_port=port,
                    want_format=message_format,
                    notifier=None,
                    state="error",
                )
            )
            emit_status_line("error", auth_err)
            return 0
        state, message, sections, _hit = assess(
            base,
            authorization,
            creds=creds,
            name=name,
            host=host,
            port=port,
            message_format=message_format,
        )
    except Exception as exc:
        emit_sections(
            [
                {
                    "group": "Error",
                    "title": "Status failed",
                    "tag": "error",
                    "body": str(exc),
                    "bodyFormat": "prose",
                }
            ]
        )
        emit_status_line("error", str(exc))
        return 0
    emit_sections(sections)
    emit_status_line(state, message)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    dry = bool(args.dry_run)
    name = (args.name or DEFAULT_NAME).strip()
    host = (args.host or "").strip()
    port = int(args.port or DEFAULT_PORT)
    message_format = normalize_format(args.format or "CEF")
    if (not host or port <= 0) and not dry:
        emit_status_line(
            "error",
            "missing syslog endpoint (--host/--port from secured-cluster LoadBalancer)",
        )
        return 1
    if (not host or port <= 0) and dry:
        host = host or "(lb-pending)"
        port = port if port > 0 else DEFAULT_PORT
    if dry:
        print(
            f"{MODULE_ID}: dry-run would upsert Syslog notifier {name!r} → "
            f"{host}:{port} format={message_format}, then Central Test"
        )
        emit_sections(
            build_notifier_sections(
                name=name,
                want_host=host,
                want_port=port,
                want_format=message_format,
                notifier=None,
                state="ok",
            )
        )
        emit_status_line(
            "ok", f"dry-run planned Syslog notifier {name} → {host}:{port}"
        )
        return 0
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_status_line("error", auth_err)
            return 1
        notifier = ensure_notifier(
            base,
            authorization,
            creds=creds,
            name=name,
            host=host,
            port=port,
            message_format=message_format,
            dry_run=dry,
        )
        test_notifier(
            base, authorization, creds=creds, notifier=notifier, dry_run=dry
        )
        print(f"{MODULE_ID}: Central Test notifier succeeded for {name!r}")
        state, message, sections, _ = assess(
            base,
            authorization,
            creds=creds,
            name=name,
            host=host,
            port=port,
            message_format=message_format,
        )
        emit_sections(sections)
        emit_status_line(state, message)
        return 0 if state == "ok" else 1
    except Exception as exc:
        emit_status_line("error", str(exc))
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    dry = bool(args.dry_run)
    name = (args.name or DEFAULT_NAME).strip()
    if dry:
        print(f"{MODULE_ID}: dry-run would DELETE Syslog notifier {name!r}")
        emit_status_line("ok", f"dry-run would delete Syslog notifier {name}")
        return 0
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_status_line("error", auth_err)
            return 1
        notifiers = list_notifiers(base, authorization, creds=creds)
        hit = find_syslog_notifier(notifiers, name)
        if not hit:
            emit_status_line("ok", f"Syslog notifier {name!r} already absent")
            return 0
        nid = str(hit.get("id") or "").strip()
        delete_notifier(
            base, authorization, creds=creds, notifier_id=nid, dry_run=False
        )
        emit_status_line("ok", f"deleted Syslog notifier {name}")
        return 0
    except Exception as exc:
        emit_status_line("error", str(exc))
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ACS Syslog notifier helper")
    p.add_argument("--name", default=DEFAULT_NAME, help="Central notifier display name")
    p.add_argument("--host", default="", help="Syslog receiver hostname or IP (LoadBalancer)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Syslog TCP port")
    p.add_argument(
        "--format",
        default="CEF",
        help="Message format: CEF (default) or LEGACY (CEF legacy field order)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("status")
    sp.set_defaults(func=cmd_status)
    rp = sub.add_parser("run")
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=cmd_run)
    up = sub.add_parser("uninstall")
    up.add_argument("--dry-run", action="store_true")
    up.set_defaults(func=cmd_uninstall)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
