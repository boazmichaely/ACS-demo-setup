"""Managed demo policies: DEMO category + Slack notifier attach/detach.

Policy modules create/update/delete via ensure_managed_policy.
slack-notifier discovers by category DEMO and attaches/detaches its notifier.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from lib.central import central_request

DEMO_CATEGORY = "DEMO"


def merge_demo_categories(*category_lists: list[Any] | None) -> list[str]:
    """Union category lists and ensure DEMO is present (stable order)."""
    out: list[str] = []
    for cats in category_lists:
        for raw in cats or []:
            name = str(raw or "").strip()
            if name and name not in out:
                out.append(name)
    if DEMO_CATEGORY not in out:
        out.append(DEMO_CATEGORY)
    return out


def find_policy_by_name(
    base: str,
    authorization: str,
    name: str,
    *,
    creds: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    code, body = central_request(
        base, authorization, "GET", "/v1/policies", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/policies failed ({code}): {body}")
    if not isinstance(body, dict):
        raise RuntimeError(f"GET /v1/policies unexpected body: {body!r}")
    want = (name or "").strip()
    for policy in body.get("policies") or []:
        if isinstance(policy, dict) and (policy.get("name") or "").strip() == want:
            return policy
    return None


def get_policy(
    base: str,
    authorization: str,
    policy_id: str,
    *,
    creds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code, body = central_request(
        base,
        authorization,
        "GET",
        f"/v1/policies/{policy_id}",
        creds=creds,
    )
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"GET /v1/policies/{policy_id} failed ({code}): {body}")
    return body


def list_demo_policies(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return full policy objects whose categories include DEMO.

    List summaries omit categories, so we query Category:DEMO then GET each
    full policy (needed for accurate notifiers[]).
    """
    path = "/v1/policies?" + urllib.parse.urlencode(
        {"query": f"Category:{DEMO_CATEGORY}"}
    )
    code, body = central_request(base, authorization, "GET", path, creds=creds)
    if code != 200:
        raise RuntimeError(f"GET /v1/policies?query=Category:{DEMO_CATEGORY} failed ({code}): {body}")
    if not isinstance(body, dict):
        raise RuntimeError(f"GET /v1/policies unexpected body: {body!r}")

    hits: list[dict[str, Any]] = []
    for summary in body.get("policies") or []:
        if not isinstance(summary, dict):
            continue
        pid = str(summary.get("id") or "").strip()
        if not pid:
            continue
        full = get_policy(base, authorization, pid, creds=creds)
        if DEMO_CATEGORY not in (full.get("categories") or []):
            continue
        hits.append(full)
    return hits


def ensure_managed_policy(
    base: str,
    authorization: str,
    policy: dict[str, Any],
    *,
    creds: dict[str, Any] | None = None,
    dry_run: bool = False,
    preserve_notifiers: bool = True,
) -> dict[str, Any]:
    """Upsert a policy by name; merge DEMO into categories; optionally keep notifiers."""
    if not isinstance(policy, dict):
        raise RuntimeError("policy payload must be an object")
    name = (policy.get("name") or "").strip()
    if not name:
        raise RuntimeError("policy payload has no name")

    payload = dict(policy)
    existing = find_policy_by_name(base, authorization, name, creds=creds)
    full_existing: dict[str, Any] | None = None
    if existing:
        pid = str(existing.get("id") or "").strip()
        if pid:
            try:
                full_existing = get_policy(base, authorization, pid, creds=creds)
            except RuntimeError:
                full_existing = existing
        else:
            full_existing = existing

    existing_cats = (full_existing or {}).get("categories") if full_existing else None
    payload["categories"] = merge_demo_categories(
        list(existing_cats) if isinstance(existing_cats, list) else None,
        list(payload.get("categories") or []),
    )

    if preserve_notifiers and full_existing is not None:
        # Keep Slack (and any other) notifiers across policy-module re-runs.
        if "notifiers" not in policy:
            payload["notifiers"] = list(full_existing.get("notifiers") or [])

    if full_existing is not None:
        existing_id = str(full_existing.get("id") or "").strip()
        if existing_id:
            payload["id"] = existing_id

        # Already stamped DEMO and caller did not change notifiers intentionally:
        # still PUT when other fields may differ; callers often send full desired body.
        if dry_run:
            print(f"dry-run: would update policy '{name}' (id={existing_id})")
            return full_existing

        code, body = central_request(
            base,
            authorization,
            "PUT",
            f"/v1/policies/{existing_id}",
            payload,
            creds=creds,
        )
        if code not in (200, 201):
            raise RuntimeError(
                f"update policy '{name}' failed ({code}): {body}"
            )
        return get_policy(base, authorization, existing_id, creds=creds)

    payload.pop("id", None)
    if dry_run:
        print(f"dry-run: would create policy '{name}'")
        return {"name": name, "id": "(new)", "categories": payload["categories"]}

    code, body = central_request(
        base, authorization, "POST", "/v1/policies", payload, creds=creds
    )
    if code not in (200, 201):
        raise RuntimeError(f"create policy '{name}' failed ({code}): {body}")
    pid = ""
    if isinstance(body, dict):
        pid = str(body.get("id") or "").strip()
    if pid:
        return get_policy(base, authorization, pid, creds=creds)
    return body if isinstance(body, dict) else {"name": name}


def _notifier_ids(policy: dict[str, Any]) -> list[str]:
    raw = policy.get("notifiers") or []
    out: list[str] = []
    for item in raw:
        nid = str(item or "").strip()
        if nid and nid not in out:
            out.append(nid)
    return out


def attach_notifier(
    base: str,
    authorization: str,
    *,
    policy_id: str,
    notifier_id: str,
    creds: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ensure notifier_id is on the policy; no-op if already attached."""
    pid = (policy_id or "").strip()
    nid = (notifier_id or "").strip()
    if not pid or not nid:
        raise RuntimeError("policy_id and notifier_id are required")

    full = get_policy(base, authorization, pid, creds=creds)
    current = _notifier_ids(full)
    if nid in current:
        return full

    payload = dict(full)
    payload["categories"] = merge_demo_categories(list(full.get("categories") or []))
    payload["notifiers"] = current + [nid]
    name = (full.get("name") or pid).strip()

    if dry_run:
        print(f"dry-run: would attach notifier {nid} to policy '{name}'")
        return full

    code, body = central_request(
        base,
        authorization,
        "PUT",
        f"/v1/policies/{pid}",
        payload,
        creds=creds,
    )
    if code not in (200, 201):
        raise RuntimeError(
            f"attach notifier to policy '{name}' failed ({code}): {body}"
        )
    return get_policy(base, authorization, pid, creds=creds)


def detach_notifier(
    base: str,
    authorization: str,
    *,
    policy_id: str,
    notifier_id: str,
    creds: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove notifier_id from the policy; leave DEMO category and other notifiers."""
    pid = (policy_id or "").strip()
    nid = (notifier_id or "").strip()
    if not pid or not nid:
        raise RuntimeError("policy_id and notifier_id are required")

    full = get_policy(base, authorization, pid, creds=creds)
    current = _notifier_ids(full)
    if nid not in current:
        return full

    payload = dict(full)
    payload["notifiers"] = [x for x in current if x != nid]
    name = (full.get("name") or pid).strip()

    if dry_run:
        print(f"dry-run: would detach notifier {nid} from policy '{name}'")
        return full

    code, body = central_request(
        base,
        authorization,
        "PUT",
        f"/v1/policies/{pid}",
        payload,
        creds=creds,
    )
    if code not in (200, 201):
        raise RuntimeError(
            f"detach notifier from policy '{name}' failed ({code}): {body}"
        )
    return get_policy(base, authorization, pid, creds=creds)


def policy_has_notifier(policy: dict[str, Any], notifier_id: str) -> bool:
    nid = (notifier_id or "").strip()
    return bool(nid) and nid in _notifier_ids(policy)
