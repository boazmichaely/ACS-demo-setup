#!/usr/bin/env python3
"""Central Slack notifier (#acs-demo-notifier by default)."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
)
from lib.demo_policies import (  # noqa: E402
    DEMO_CATEGORY,
    attach_notifier,
    detach_notifier,
    list_demo_policies,
    policy_has_notifier,
)
from lib.slack_notifier_defaults import (  # noqa: E402
    effective_slack_notifier,
    load_defaults,
)

MODULE_ID = "slack-notifier"


def emit_status_line(state: str, message: str) -> None:
    print(f"{MODULE_ID}\t{state}\t{message}")


def emit_sections(sections: list[dict[str, Any]]) -> None:
    print(
        "ACS_SECTIONS_JSON="
        + json.dumps({"sections": sections}, separators=(",", ":"))
    )


def _auth_header(authorization: str) -> str:
    auth = (authorization or "").strip()
    if not auth:
        raise RuntimeError("empty Central Authorization header")
    lower = auth.lower()
    if lower.startswith("bearer ") or lower.startswith("basic "):
        return auth
    return f"Bearer {auth}"


def _raw_lab_slack_override() -> dict[str, Any]:
    """Active lab slackNotifier as stored (empty fields = inherit defaults).

    Reads the on-disk object without normalize_slack_notifier filling defaults,
    so an absent/blank override is distinguishable from a real lab override.
    """
    from lib.central import credentials_path

    path = credentials_path(ROOT)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    labs = raw.get("labs") or []
    if not isinstance(labs, list) or not labs:
        return {}
    aid = (raw.get("activeLabId") or "").strip()
    lab = None
    if aid:
        for row in labs:
            if isinstance(row, dict) and (row.get("id") or "") == aid:
                lab = row
                break
    if lab is None and isinstance(labs[0], dict):
        lab = labs[0]
    if not isinstance(lab, dict):
        return {}
    sn = lab.get("slackNotifier") or {}
    return sn if isinstance(sn, dict) else {}


def resolve_config(args: argparse.Namespace) -> tuple[dict[str, str], str]:
    """Return (effective config, source: default|lab|flag)."""
    defaults = load_defaults(ROOT)
    stored = _raw_lab_slack_override()
    lab_eff = effective_slack_notifier(stored, defaults=defaults)

    flag_wh = (getattr(args, "webhook", None) or "").strip()
    flag_name = (getattr(args, "name", None) or "").strip()
    flag_ch = (getattr(args, "channel_url", None) or "").strip()

    if flag_wh or flag_name or flag_ch:
        cfg = {
            "webhookUrl": flag_wh or lab_eff["webhookUrl"],
            "notifierName": flag_name or lab_eff["notifierName"],
            "channelUrl": flag_ch or lab_eff["channelUrl"],
        }
        return cfg, "flag"

    has_lab = any(
        (stored.get(k) or "").strip()
        for k in ("webhookUrl", "notifierName", "channelUrl")
    )
    return lab_eff, "lab" if has_lab else "default"


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


def find_slack_notifier(
    notifiers: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    want = (name or "").strip()
    for n in notifiers:
        if (n.get("name") or "").strip() != want:
            continue
        if (n.get("type") or "").lower() != "slack":
            continue
        return n
    return None


def notifier_body(
    *,
    name: str,
    webhook: str,
    ui_endpoint: str,
    notifier_id: str = "",
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "name": name,
        "type": "slack",
        "uiEndpoint": ui_endpoint.rstrip("/"),
        "labelDefault": webhook,
    }
    if notifier_id:
        obj["id"] = notifier_id
    return obj


def _tag_for_state(state: str) -> str:
    if state == "ok":
        return "ok"
    if state == "error":
        return "error"
    return "needs-run"


def demo_policy_sections(
    policies: list[dict[str, Any]],
    *,
    notifier_id: str,
) -> list[dict[str, Any]]:
    """One fold per DEMO policy: wired vs missing this Slack notifier."""
    sections: list[dict[str, Any]] = []
    nid = (notifier_id or "").strip()
    if not policies:
        sections.append(
            {
                "group": "DEMO policies",
                "title": f"No {DEMO_CATEGORY} policies",
                "summary": "none",
                "tag": "ok",
                "body": (
                    f"No Central policies with category {DEMO_CATEGORY}. "
                    "Re-run init-demo / signature-integration (or another "
                    "policy module) so policies are stamped DEMO, then "
                    "re-run slack-notifier."
                ),
                "bodyFormat": "prose",
            }
        )
        return sections

    for policy in policies:
        name = (policy.get("name") or "(unnamed)").strip()
        pid = str(policy.get("id") or "").strip()
        wired = bool(nid) and policy_has_notifier(policy, nid)
        state = "ok" if wired else "needs-run"
        body_lines = [
            f"Policy id: {pid or '(none)'}",
            f"Category: {DEMO_CATEGORY}",
            f"Slack notifier: {'attached' if wired else 'missing'}",
        ]
        sections.append(
            {
                "group": "DEMO policies",
                "title": name,
                "summary": "wired" if wired else "missing notifier",
                "tag": _tag_for_state(state),
                "body": "\n".join(body_lines),
                "bodyFormat": "prose",
            }
        )
    return sections


def build_sections(
    cfg: dict[str, str],
    source: str,
    *,
    notifier: dict[str, Any] | None,
    state: str,
    demo_policies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    nid = (notifier or {}).get("id") or ""
    central_wh = ((notifier or {}).get("labelDefault") or "").strip()
    channel = (cfg.get("channelUrl") or "").strip()
    channel_line = channel if channel else "(no channel URL configured)"
    body_lines = [
        f"Notifier name: {cfg.get('notifierName') or ''}",
        f"Central id: {nid or '(none)'}",
        f"Webhook source: {source}",
        f"Webhook URL: {cfg.get('webhookUrl') or ''}",
        f"Channel: {channel_line}",
    ]
    if central_wh and central_wh != (cfg.get("webhookUrl") or "").strip():
        body_lines.append(f"Central labelDefault (drift): {central_wh}")
    sections: list[dict[str, Any]] = [
        {
            "group": "Slack notifier",
            "title": cfg.get("notifierName") or "Slack",
            "summary": state,
            "tag": _tag_for_state(state),
            "body": "\n".join(body_lines),
            "bodyFormat": "prose",
        }
    ]
    if demo_policies is not None:
        sections.extend(
            demo_policy_sections(demo_policies, notifier_id=str(nid))
        )
    return sections


def assess(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    cfg: dict[str, str],
    source: str,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    name = (cfg.get("notifierName") or "").strip()
    want_wh = (cfg.get("webhookUrl") or "").strip()
    if not name:
        return (
            "error",
            "notifier name is empty",
            build_sections(
                cfg, source, notifier=None, state="error", demo_policies=[]
            ),
            None,
        )
    if not want_wh:
        return (
            "error",
            "webhook URL is empty (set defaults, lab credentials, or --webhook)",
            build_sections(
                cfg, source, notifier=None, state="error", demo_policies=[]
            ),
            None,
        )

    notifiers = list_notifiers(base, authorization, creds=creds)
    hit = find_slack_notifier(notifiers, name)
    demo_policies = list_demo_policies(base, authorization, creds=creds)

    if not hit:
        sections = build_sections(
            cfg,
            source,
            notifier=None,
            state="needs-run",
            demo_policies=demo_policies,
        )
        return "needs-run", f"Slack notifier {name!r} not configured", sections, None

    central_wh = (hit.get("labelDefault") or "").strip()
    if central_wh != want_wh:
        sections = build_sections(
            cfg,
            source,
            notifier=hit,
            state="needs-run",
            demo_policies=demo_policies,
        )
        return (
            "needs-run",
            f"Slack notifier {name!r} webhook drifted",
            sections,
            hit,
        )

    nid = str(hit.get("id") or "").strip()
    unwired = [
        p
        for p in demo_policies
        if not policy_has_notifier(p, nid)
    ]
    if unwired:
        sections = build_sections(
            cfg,
            source,
            notifier=hit,
            state="needs-run",
            demo_policies=demo_policies,
        )
        return (
            "needs-run",
            f"Slack notifier ready; {len(unwired)} DEMO polic"
            f"{'y' if len(unwired) == 1 else 'ies'} missing notifier",
            sections,
            hit,
        )

    sections = build_sections(
        cfg, source, notifier=hit, state="ok", demo_policies=demo_policies
    )
    n = len(demo_policies)
    if n:
        msg = f"Slack notifier {name} ready; {n} DEMO polic{'y' if n == 1 else 'ies'} wired"
    else:
        msg = f"Slack notifier {name} ready (no DEMO policies yet)"
    return "ok", msg, sections, hit


def wire_demo_policies(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    notifier_id: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Attach notifier to every DEMO policy. Returns (attached_or_would, total)."""
    nid = (notifier_id or "").strip()
    if not nid:
        raise RuntimeError("notifier missing id; cannot wire DEMO policies")
    policies = list_demo_policies(base, authorization, creds=creds)
    changed = 0
    for policy in policies:
        pid = str(policy.get("id") or "").strip()
        if not pid:
            continue
        if policy_has_notifier(policy, nid):
            continue
        attach_notifier(
            base,
            authorization,
            policy_id=pid,
            notifier_id=nid,
            creds=creds,
            dry_run=dry_run,
        )
        changed += 1
    return changed, len(policies)


def unwire_demo_policies(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    notifier_id: str,
    dry_run: bool,
) -> int:
    """Detach notifier from every DEMO policy. Returns count detached/would."""
    nid = (notifier_id or "").strip()
    if not nid:
        return 0
    policies = list_demo_policies(base, authorization, creds=creds)
    changed = 0
    for policy in policies:
        pid = str(policy.get("id") or "").strip()
        if not pid or not policy_has_notifier(policy, nid):
            continue
        detach_notifier(
            base,
            authorization,
            policy_id=pid,
            notifier_id=nid,
            creds=creds,
            dry_run=dry_run,
        )
        changed += 1
    return changed


def ensure_notifier(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    cfg: dict[str, str],
    dry_run: bool,
) -> dict[str, Any]:
    name = (cfg.get("notifierName") or "").strip()
    webhook = (cfg.get("webhookUrl") or "").strip()
    notifiers = list_notifiers(base, authorization, creds=creds)
    existing = find_slack_notifier(notifiers, name)
    body = notifier_body(
        name=name,
        webhook=webhook,
        ui_endpoint=base,
        notifier_id=str((existing or {}).get("id") or ""),
    )

    if dry_run:
        action = "PUT" if existing else "POST"
        print(f"{MODULE_ID}: dry-run would {action} /v1/notifiers for {name!r}")
        return existing or body

    if existing:
        nid = str(existing.get("id") or "")
        code, resp = central_request(
            base, authorization, "PUT", f"/v1/notifiers/{nid}", body, creds=creds
        )
        if code != 200:
            raise RuntimeError(f"PUT /v1/notifiers/{nid} failed ({code}): {resp}")
        # PUT returns Empty; re-fetch
        notifiers = list_notifiers(base, authorization, creds=creds)
        hit = find_slack_notifier(notifiers, name)
        if not hit:
            raise RuntimeError(f"notifier {name!r} missing after PUT")
        return hit

    code, resp = central_request(
        base, authorization, "POST", "/v1/notifiers", body, creds=creds
    )
    if code not in (200, 201) or not isinstance(resp, dict):
        raise RuntimeError(f"POST /v1/notifiers failed ({code}): {resp}")
    return resp


def test_notifier(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    notifier: dict[str, Any],
    dry_run: bool,
) -> None:
    body = {
        "name": notifier.get("name"),
        "type": "slack",
        "uiEndpoint": (notifier.get("uiEndpoint") or base).rstrip("/"),
        "labelDefault": notifier.get("labelDefault"),
    }
    if notifier.get("id"):
        body["id"] = notifier["id"]
    if dry_run:
        print(f"{MODULE_ID}: dry-run would POST /v1/notifiers/test for {body.get('name')!r}")
        return
    code, resp = central_request(
        base, authorization, "POST", "/v1/notifiers/test", body, creds=creds
    )
    if code != 200:
        raise RuntimeError(f"POST /v1/notifiers/test failed ({code}): {resp}")


def _host_hint(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return urlparse(raw).hostname or raw


def lab_context_lines(creds: dict[str, Any], cfg: dict[str, str]) -> list[str]:
    lab_name = (creds.get("_activeLabName") or creds.get("_activeLabId") or "?").strip()
    lab_id = (creds.get("_activeLabId") or "").strip()
    central = _host_hint(
        ((creds.get("centralCluster") or {}).get("central") or {}).get("consoleUrl") or ""
    ) or "?"
    sc_name = (creds.get("_activeSecuredClusterName") or "?").strip()
    same = bool((creds.get("securedCluster") or {}).get("sameAsCentralCluster", True))
    sc_bit = f"{sc_name} (same as Central)" if same else sc_name
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "ACS demo setup: slack-notifier lab ping",
        f"Lab: {lab_name}" + (f" ({lab_id})" if lab_id and lab_id != lab_name else ""),
        f"Central: {central}",
        f"Secured cluster: {sc_bit}",
        f"Notifier: {cfg.get('notifierName') or ''}",
        f"When: {when}",
    ]
    return lines


def post_lab_context_to_webhook(
    webhook_url: str,
    *,
    creds: dict[str, Any],
    cfg: dict[str, str],
    dry_run: bool,
) -> None:
    """Second message (ours): Central's TestNotifier text is fixed upstream."""
    text = "\n".join(lab_context_lines(creds, cfg))
    if dry_run:
        print(f"{MODULE_ID}: dry-run would POST lab context to Incoming Webhook")
        print(text)
        return
    payload = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status != 200 or body != "ok":
                raise RuntimeError(
                    f"Slack webhook lab ping failed (HTTP {resp.status}): {body or '(empty)'}"
                )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Slack webhook lab ping failed (HTTP {exc.code}): {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack webhook lab ping unreachable: {exc.reason}") from exc


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
        base,
        authorization,
        "DELETE",
        f"/v1/notifiers/{notifier_id}",
        creds=creds,
    )
    if code not in (200, 204):
        raise RuntimeError(f"DELETE /v1/notifiers/{notifier_id} failed ({code}): {resp}")


def cmd_status(args: argparse.Namespace) -> int:
    try:
        cfg, source = resolve_config(args)
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_sections(
                build_sections(cfg, source, notifier=None, state="error")
            )
            emit_status_line("error", auth_err)
            return 0
        state, message, sections, _hit = assess(
            base, authorization, creds=creds, cfg=cfg, source=source
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
    dry_run = bool(args.dry_run)
    try:
        cfg, source = resolve_config(args)
        if not (cfg.get("webhookUrl") or "").strip():
            emit_status_line("error", "webhook URL is empty")
            return 1
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_status_line("error", auth_err)
            return 1

        notifier = ensure_notifier(
            base, authorization, creds=creds, cfg=cfg, dry_run=dry_run
        )
        # Ensure test body has webhook even on dry-run create path
        if dry_run and not notifier.get("labelDefault"):
            notifier = notifier_body(
                name=cfg["notifierName"],
                webhook=cfg["webhookUrl"],
                ui_endpoint=base,
            )
        test_notifier(
            base, authorization, creds=creds, notifier=notifier, dry_run=dry_run
        )
        post_lab_context_to_webhook(
            cfg["webhookUrl"], creds=creds, cfg=cfg, dry_run=dry_run
        )

        nid = str(notifier.get("id") or "").strip()
        if dry_run and not nid:
            # Cannot list/attach without a real id on a create dry-run.
            demo_count = len(list_demo_policies(base, authorization, creds=creds))
            emit_status_line(
                "ok",
                f"dry-run: would ensure + test + lab ping for {cfg['notifierName']}; "
                f"would attach to {demo_count} DEMO polic"
                f"{'y' if demo_count == 1 else 'ies'}",
            )
            return 0

        wired, total = wire_demo_policies(
            base,
            authorization,
            creds=creds,
            notifier_id=nid,
            dry_run=dry_run,
        )

        if dry_run:
            emit_status_line(
                "ok",
                f"dry-run: would ensure + Central test + lab ping for {cfg['notifierName']}; "
                f"would attach notifier on {wired}/{total} DEMO policies",
            )
            return 0

        state, message, sections, _hit = assess(
            base, authorization, creds=creds, cfg=cfg, source=source
        )
        emit_sections(sections)
        emit_status_line(
            state,
            message + f"; Central test + lab ping sent; attached {wired}/{total}",
        )
        return 0 if state == "ok" else 1
    except Exception as exc:
        emit_status_line("error", str(exc))
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    dry_run = bool(args.dry_run)
    try:
        cfg, source = resolve_config(args)
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_status_line("error", auth_err)
            return 1

        notifiers = list_notifiers(base, authorization, creds=creds)
        hit = find_slack_notifier(notifiers, cfg["notifierName"])
        if not hit:
            sections = build_sections(
                cfg, source, notifier=None, state="ok", demo_policies=[]
            )
            emit_sections(sections)
            emit_status_line("ok", f"Slack notifier {cfg['notifierName']!r} already absent")
            return 0

        nid = str(hit.get("id") or "")
        if not nid:
            emit_status_line("error", "notifier missing id")
            return 1

        detached = unwire_demo_policies(
            base,
            authorization,
            creds=creds,
            notifier_id=nid,
            dry_run=dry_run,
        )
        delete_notifier(
            base, authorization, creds=creds, notifier_id=nid, dry_run=dry_run
        )
        if dry_run:
            emit_status_line(
                "ok",
                f"dry-run: would detach from {detached} DEMO polic"
                f"{'y' if detached == 1 else 'ies'} and delete {cfg['notifierName']!r}",
            )
            return 0
        sections = build_sections(
            cfg, source, notifier=None, state="needs-run", demo_policies=[]
        )
        emit_sections(sections)
        emit_status_line(
            "ok",
            f"detached from {detached} DEMO polic"
            f"{'y' if detached == 1 else 'ies'}; deleted Slack notifier "
            f"{cfg['notifierName']}",
        )
        return 0
    except Exception as exc:
        emit_status_line("error", str(exc))
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--webhook", default="", help="Override Incoming Webhook URL")
    p.add_argument("--name", default="", help="Override Central notifier display name")
    p.add_argument(
        "--channel-url",
        default="",
        dest="channel_url",
        help="Override Slack channel deep link for status folds",
    )
    sub = p.add_subparsers(dest="command", required=True)

    st = sub.add_parser("status", help="Check Slack notifier in Central")
    st.set_defaults(func=cmd_status)

    run = sub.add_parser(
        "run",
        help="Ensure Slack notifier, test it, and attach to DEMO-category policies",
    )
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    un = sub.add_parser(
        "uninstall",
        help="Detach Slack notifier from DEMO policies, then delete the notifier",
    )
    un.add_argument("--dry-run", action="store_true")
    un.set_defaults(func=cmd_uninstall)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
