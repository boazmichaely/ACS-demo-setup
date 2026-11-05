#!/usr/bin/env python3
"""Map adam/boaz/chris to ACS roles and a ms-demo access scope (Users Part 3)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
)

MODULE_ID = "users-part3-acs"
SCOPE_NAME = "ms-demo"
SCOPE_DESCRIPTION = "Access to ms-demo namespace (demo)"
MS_NS = "ms-demo"
ROLE_BOAZ = "boaz-in-acs"
ROLE_CHRIS = "chris-in-acs"
ANALYST_NAME = "Analyst"
ADMIN_ROLE = "Admin"
PROVIDER_TYPE = "openshift"


def _ok_fold(summary: str, body: str) -> dict[str, str]:
    return {
        "tag": "ok",
        "tagLabel": "ready",
        "summary": summary,
        "body": body,
        "bodyFormat": "prose",
    }


def _warn_fold(summary: str, body: str) -> dict[str, str]:
    return {
        "tag": "warn",
        "tagLabel": "needs run",
        "summary": summary,
        "body": body,
        "bodyFormat": "prose",
    }


def _error_fold(summary: str, body: str) -> dict[str, str]:
    return {
        "tag": "error",
        "tagLabel": "error",
        "summary": summary,
        "body": body,
        "bodyFormat": "prose",
    }


def find_openshift_provider(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> dict[str, Any] | None:
    code, body = central_request(
        base, authorization, "GET", "/v1/authProviders", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/authProviders failed ({code}): {body}")
    for item in body.get("authProviders") or []:
        if item.get("type") == PROVIDER_TYPE:
            return item
    return None


def resolve_cluster_name(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> str:
    override = os.environ.get("ACS_SECURED_CLUSTER_NAME", "").strip()
    if override:
        return override
    code, body = central_request(
        base, authorization, "GET", "/v1/clusters", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/clusters failed ({code}): {body}")
    clusters = body.get("clusters") or []
    if len(clusters) == 1:
        name = (clusters[0].get("name") or "").strip()
        if name:
            return name
    raise RuntimeError(
        "Could not resolve the ACS secured cluster name. Set "
        "ACS_SECURED_CLUSTER_NAME to the name shown under ACS → "
        "Platform Configuration → Clusters."
    )


def resolve_analyst_permission_set_id(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> str:
    code, body = central_request(
        base, authorization, "GET", "/v1/permissionsets", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/permissionsets failed ({code}): {body}")
    for item in body.get("permissionSets") or []:
        if item.get("name") == ANALYST_NAME:
            pid = item.get("id")
            if pid:
                return str(pid)
    raise RuntimeError(
        f'Built-in permission set named "{ANALYST_NAME}" was not found in Central'
    )


def list_scopes(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/simpleaccessscopes", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/simpleaccessscopes failed ({code}): {body}")
    return body.get("accessScopes") or []


def find_scope_by_name(
    scopes: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    for item in scopes:
        if item.get("name") == name:
            return item
    return None


def desired_scope_rules(cluster_name: str) -> dict[str, Any]:
    return {
        "includedClusters": [],
        "includedNamespaces": [
            {"clusterName": cluster_name, "namespaceName": MS_NS},
        ],
        "clusterLabelSelectors": [],
        "namespaceLabelSelectors": [],
    }


def _namespace_pairs(rules: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Normalize includedNamespaces for compare (ignore clusterId padding)."""
    pairs: list[tuple[str, str]] = []
    for item in (rules or {}).get("includedNamespaces") or []:
        pairs.append(
            (
                str(item.get("clusterName") or "").strip(),
                str(item.get("namespaceName") or "").strip(),
            )
        )
    return pairs


def scope_matches(scope: dict[str, Any], cluster_name: str) -> bool:
    if scope.get("name") != SCOPE_NAME:
        return False
    rules = scope.get("rules") or {}
    want = _namespace_pairs(desired_scope_rules(cluster_name))
    have = _namespace_pairs(rules)
    # Empty includedClusters is expected for a namespace-only demo scope.
    clusters = rules.get("includedClusters") or []
    return have == want and clusters == []


def get_role(
    base: str, authorization: str, name: str, *, creds: dict[str, Any]
) -> dict[str, Any] | None:
    code, body = central_request(
        base, authorization, "GET", f"/v1/roles/{name}", creds=creds
    )
    if code == 404:
        return None
    if code != 200:
        raise RuntimeError(f"GET /v1/roles/{name} failed ({code}): {body}")
    if not (body or {}).get("name"):
        return None
    return body


def role_matches(
    role: dict[str, Any], *, permission_set_id: str, access_scope_id: str
) -> bool:
    return (
        role.get("permissionSetId") == permission_set_id
        and role.get("accessScopeId") == access_scope_id
        and role.get("globalAccess") == "NO_ACCESS"
    )


def list_groups(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/groups", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/groups failed ({code}): {body}")
    return body.get("groups") or []


def find_group(
    groups: list[dict[str, Any]],
    *,
    provider_id: str,
    key: str,
    value: str,
    role_name: str | None = None,
) -> dict[str, Any] | None:
    for group in groups:
        props = group.get("props") or {}
        if props.get("authProviderId") != provider_id:
            continue
        if props.get("key", "") != key:
            continue
        if props.get("value", "") != value:
            continue
        if role_name is not None and group.get("roleName") != role_name:
            continue
        return group
    return None


def find_login_groups(
    groups: list[dict[str, Any]], *, provider_id: str, login: str
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for group in groups:
        props = group.get("props") or {}
        if props.get("authProviderId") != provider_id:
            continue
        if props.get("key") == "name" and props.get("value") == login:
            found.append(group)
    return found


DEMO_SCRIPT_BODY = (
    "Users Part 3 (ACS): map adam, boaz, and chris to ACS roles and scopes.\n\n"
    "Act 2 compares console (OCP RBAC) vs ACS Central (boaz aligned, chris misaligned):\n"
    "  modules/users-part1-ocp-demo.md\n"
    "  https://github.com/boazmichaely/ACS-demo-setup/blob/main/modules/users-part1-ocp-demo.md"
)


def build_sections(facts: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = [
        {
            "group": "Demo",
            "title": "Demo script",
            **_ok_fold("users walkthrough", DEMO_SCRIPT_BODY),
            "tagLabel": "guide",
        }
    ]

    if not facts.get("central_ok"):
        err = str(facts.get("central_error") or facts.get("message") or "Central error")
        sections.append(
            {
                "group": "Central",
                "title": "API",
                **_error_fold("error", err),
            }
        )
        for title in (
            "OpenShift provider",
            "Access scope",
            "Roles",
            "Group rules",
        ):
            sections.append(
                {
                    "group": "Auth",
                    "title": title,
                    **_error_fold("unknown", "Skipped; Central API is not available."),
                }
            )
        return sections

    sections.append(
        {
            "group": "Central",
            "title": "API",
            **_ok_fold("reachable", str(facts.get("central_body") or "")),
        }
    )

    provider = facts.get("provider")
    if provider:
        sections.append(
            {
                "group": "Auth",
                "title": "OpenShift provider",
                **_ok_fold(
                    "present",
                    f"name: {provider.get('name')}\nid: {provider.get('id')}",
                ),
            }
        )
    else:
        sections.append(
            {
                "group": "Auth",
                "title": "OpenShift provider",
                **_warn_fold(
                    "missing",
                    "No openshift-type auth provider. Run users-part2-oauth first.",
                ),
            }
        )

    if facts.get("scope_ok"):
        scope = facts.get("scope") or {}
        sections.append(
            {
                "group": "Auth",
                "title": "Access scope",
                **_ok_fold(
                    "ready",
                    f"name: {SCOPE_NAME}\nid: {scope.get('id')}\n"
                    f"namespace: {MS_NS}\ncluster: {facts.get('cluster_name')}",
                ),
            }
        )
    else:
        sections.append(
            {
                "group": "Auth",
                "title": "Access scope",
                **_warn_fold(
                    "needs run",
                    facts.get("scope_detail")
                    or f"Access scope {SCOPE_NAME} is missing or drifted.",
                ),
            }
        )

    if facts.get("roles_ok"):
        sections.append(
            {
                "group": "Auth",
                "title": "Roles",
                **_ok_fold(
                    "ready",
                    f"{ROLE_BOAZ} and {ROLE_CHRIS} use Analyst with scope {SCOPE_NAME}.",
                ),
            }
        )
    else:
        sections.append(
            {
                "group": "Auth",
                "title": "Roles",
                **_warn_fold(
                    "needs run",
                    facts.get("roles_detail")
                    or f"{ROLE_BOAZ} and/or {ROLE_CHRIS} are missing or drifted.",
                ),
            }
        )

    if facts.get("rules_ok"):
        sections.append(
            {
                "group": "Auth",
                "title": "Group rules",
                **_ok_fold(
                    "ready",
                    "adam maps to Admin; boaz maps to "
                    f"{ROLE_BOAZ}; chris maps to {ROLE_CHRIS}.",
                ),
            }
        )
    else:
        sections.append(
            {
                "group": "Auth",
                "title": "Group rules",
                **_warn_fold(
                    "needs run",
                    facts.get("rules_detail")
                    or "One or more OpenShift auth group rules are missing.",
                ),
            }
        )

    return sections


def evaluate() -> dict[str, Any]:
    creds = load_lab_credentials()
    base, authorization = central_connection(creds)
    err = check_central_auth(base, authorization, creds=creds)
    if err:
        facts = {
            "state": "error",
            "message": err,
            "central_ok": False,
            "central_body": base,
            "central_error": err,
        }
        facts["sections"] = build_sections(facts)
        return facts

    facts: dict[str, Any] = {
        "central_ok": True,
        "central_body": base,
        "creds": creds,
        "base": base,
        "authorization": authorization,
        "provider": None,
        "scope": None,
        "scope_ok": False,
        "roles_ok": False,
        "rules_ok": False,
        "cluster_name": None,
        "analyst_permission_set_id": None,
    }

    try:
        provider = find_openshift_provider(base, authorization, creds=creds)
    except RuntimeError as exc:
        facts["state"] = "error"
        facts["message"] = str(exc)
        facts["central_error"] = str(exc)
        facts["sections"] = build_sections(facts)
        return facts

    facts["provider"] = provider
    if not provider:
        facts["state"] = "needs-run"
        facts["message"] = "run users-part2-oauth first (no openshift auth provider)"
        facts["scope_detail"] = "Skipped until an openshift auth provider exists."
        facts["roles_detail"] = "Skipped until an openshift auth provider exists."
        facts["rules_detail"] = "Skipped until an openshift auth provider exists."
        facts["sections"] = build_sections(facts)
        return facts

    try:
        cluster_name = resolve_cluster_name(base, authorization, creds=creds)
        analyst_id = resolve_analyst_permission_set_id(
            base, authorization, creds=creds
        )
    except RuntimeError as exc:
        facts["state"] = "error"
        facts["message"] = str(exc)
        facts["sections"] = build_sections(facts)
        return facts

    facts["cluster_name"] = cluster_name
    facts["analyst_permission_set_id"] = analyst_id

    scopes = list_scopes(base, authorization, creds=creds)
    scope = find_scope_by_name(scopes, SCOPE_NAME)
    facts["scope"] = scope
    if scope and scope_matches(scope, cluster_name):
        facts["scope_ok"] = True
    elif scope:
        facts["scope_detail"] = (
            f"Scope {SCOPE_NAME} exists but does not include "
            f"{cluster_name}/{MS_NS}."
        )
    else:
        facts["scope_detail"] = f"Scope {SCOPE_NAME} is missing."

    role_boaz = get_role(base, authorization, ROLE_BOAZ, creds=creds)
    role_chris = get_role(base, authorization, ROLE_CHRIS, creds=creds)
    facts["role_boaz"] = role_boaz
    facts["role_chris"] = role_chris
    scope_id = (scope or {}).get("id") if facts["scope_ok"] else None
    if (
        role_boaz
        and role_chris
        and scope_id
        and role_matches(
            role_boaz, permission_set_id=analyst_id, access_scope_id=scope_id
        )
        and role_matches(
            role_chris, permission_set_id=analyst_id, access_scope_id=scope_id
        )
    ):
        facts["roles_ok"] = True
    else:
        missing = []
        if not role_boaz:
            missing.append(f"{ROLE_BOAZ} missing")
        elif not scope_id or not role_matches(
            role_boaz, permission_set_id=analyst_id, access_scope_id=str(scope_id)
        ):
            missing.append(f"{ROLE_BOAZ} drifted")
        if not role_chris:
            missing.append(f"{ROLE_CHRIS} missing")
        elif not scope_id or not role_matches(
            role_chris, permission_set_id=analyst_id, access_scope_id=str(scope_id)
        ):
            missing.append(f"{ROLE_CHRIS} drifted")
        facts["roles_detail"] = "; ".join(missing) or "roles need reconcile"

    groups = list_groups(base, authorization, creds=creds)
    facts["groups"] = groups
    provider_id = str(provider.get("id"))
    adam_ok = bool(
        find_group(
            groups,
            provider_id=provider_id,
            key="name",
            value="adam",
            role_name=ADMIN_ROLE,
        )
    )
    boaz_ok = bool(
        find_group(
            groups,
            provider_id=provider_id,
            key="name",
            value="boaz",
            role_name=ROLE_BOAZ,
        )
    )
    chris_ok = bool(
        find_group(
            groups,
            provider_id=provider_id,
            key="name",
            value="chris",
            role_name=ROLE_CHRIS,
        )
    )
    facts["rules_ok"] = adam_ok and boaz_ok and chris_ok
    if not facts["rules_ok"]:
        bits = []
        if not adam_ok:
            bits.append("adam to Admin missing")
        if not boaz_ok:
            bits.append(f"boaz to {ROLE_BOAZ} missing")
        if not chris_ok:
            bits.append(f"chris to {ROLE_CHRIS} missing")
        facts["rules_detail"] = "; ".join(bits)

    if facts["scope_ok"] and facts["roles_ok"] and facts["rules_ok"]:
        facts["state"] = "ok"
        facts["message"] = (
            f"users-part3-acs ready (scope {SCOPE_NAME}; "
            f"{ROLE_BOAZ}/{ROLE_CHRIS}; adam Admin)"
        )
    else:
        facts["state"] = "needs-run"
        facts["message"] = (
            f"scope={'ok' if facts['scope_ok'] else 'needs-run'}; "
            f"roles={'ok' if facts['roles_ok'] else 'needs-run'}; "
            f"rules={'ok' if facts['rules_ok'] else 'needs-run'}"
        )

    facts["sections"] = build_sections(facts)
    return facts


def _upsert_scope(
    status: dict[str, Any], *, dry_run: bool, log: list[str]
) -> str | None:
    """Return scope id, or None on failure (sets status message)."""
    base = status["base"]
    authorization = status["authorization"]
    creds = status["creds"]
    cluster_name = status["cluster_name"]
    scope = status.get("scope")
    want_rules = desired_scope_rules(cluster_name)

    if scope and scope_matches(scope, cluster_name):
        log.append(f"scope {SCOPE_NAME} already matches")
        return str(scope.get("id"))

    body = {
        "name": SCOPE_NAME,
        "description": SCOPE_DESCRIPTION,
        "rules": want_rules,
    }
    if dry_run:
        if scope:
            log.append(f"would update scope {SCOPE_NAME}")
            return str(scope.get("id"))
        log.append(f"would create scope {SCOPE_NAME}")
        return "dry-run-scope-id"

    if not scope:
        code, resp = central_request(
            base,
            authorization,
            "POST",
            "/v1/simpleaccessscopes",
            body,
            creds=creds,
        )
        if code not in (200, 201):
            status["state"] = "error"
            status["message"] = (
                f"POST /v1/simpleaccessscopes failed ({code}): {resp}"
            )
            return None
        sid = (resp or {}).get("id")
        log.append(f"created scope {SCOPE_NAME} id={sid}")
        return str(sid)

    put_body = dict(scope)
    put_body["name"] = SCOPE_NAME
    put_body["description"] = SCOPE_DESCRIPTION
    put_body["rules"] = want_rules
    sid = scope.get("id")
    code, resp = central_request(
        base,
        authorization,
        "PUT",
        f"/v1/simpleaccessscopes/{sid}",
        put_body,
        creds=creds,
    )
    if code != 200:
        status["state"] = "error"
        status["message"] = (
            f"PUT /v1/simpleaccessscopes/{sid} failed ({code}): {resp}"
        )
        return None
    log.append(f"updated scope {SCOPE_NAME} id={sid}")
    return str(sid)


def _upsert_role(
    status: dict[str, Any],
    *,
    role_name: str,
    existing: dict[str, Any] | None,
    permission_set_id: str,
    access_scope_id: str,
    dry_run: bool,
    log: list[str],
) -> bool:
    base = status["base"]
    authorization = status["authorization"]
    creds = status["creds"]
    want = {
        "name": role_name,
        "description": f"Analyst for {MS_NS} (demo)",
        "permissionSetId": permission_set_id,
        "accessScopeId": access_scope_id,
        "globalAccess": "NO_ACCESS",
        "resourceToAccess": {},
    }
    if existing and role_matches(
        existing,
        permission_set_id=permission_set_id,
        access_scope_id=access_scope_id,
    ):
        log.append(f"role {role_name} already matches")
        return True

    if dry_run:
        log.append(
            f"would {'update' if existing else 'create'} role {role_name}"
        )
        return True

    if not existing:
        code, resp = central_request(
            base,
            authorization,
            "POST",
            f"/v1/roles/{role_name}",
            want,
            creds=creds,
        )
        if code not in (200, 201):
            status["state"] = "error"
            status["message"] = (
                f"POST /v1/roles/{role_name} failed ({code}): {resp}"
            )
            return False
        log.append(f"created role {role_name}")
        return True

    put_body = dict(existing)
    put_body.update(want)
    code, resp = central_request(
        base,
        authorization,
        "PUT",
        f"/v1/roles/{role_name}",
        put_body,
        creds=creds,
    )
    if code != 200:
        status["state"] = "error"
        status["message"] = (
            f"PUT /v1/roles/{role_name} failed ({code}): {resp}"
        )
        return False
    log.append(f"updated role {role_name}")
    return True


def _ensure_group_rule(
    status: dict[str, Any],
    *,
    provider_id: str,
    key: str,
    value: str,
    role_name: str,
    dry_run: bool,
    log: list[str],
) -> bool:
    groups = status.get("groups") or []
    exact = find_group(
        groups,
        provider_id=provider_id,
        key=key,
        value=value,
        role_name=role_name,
    )
    if exact:
        label = value or "(empty)"
        log.append(f"group rule {key}={label} -> {role_name} already present")
        return True

    if key == "name" and value:
        conflicts = [
            g
            for g in find_login_groups(
                groups, provider_id=provider_id, login=value
            )
            if g.get("roleName") != role_name
        ]
        for conflict in conflicts:
            print(
                f"WARNING: {value} is mapped to role "
                f"{conflict.get('roleName')!r}; expected {role_name!r}. "
                "Remove the extra rule in the ACS UI if login picks the wrong role.",
                file=sys.stderr,
            )
            # Do not auto-delete; do not create a duplicate.
            log.append(
                f"skipped creating {value} -> {role_name} "
                f"(conflicting rule role={conflict.get('roleName')})"
            )
            return True

    if dry_run:
        label = value or "(empty)"
        log.append(f"would create group rule {key}={label} -> {role_name}")
        return True

    body = {
        "props": {
            "authProviderId": provider_id,
            "key": key,
            "value": value,
        },
        "roleName": role_name,
    }
    code, resp = central_request(
        status["base"],
        status["authorization"],
        "POST",
        "/v1/groups",
        body,
        creds=status["creds"],
    )
    if code not in (200, 201):
        status["state"] = "error"
        status["message"] = f"POST /v1/groups failed ({code}): {resp}"
        return False
    label = value or "(empty)"
    log.append(f"created group rule {key}={label} -> {role_name}")
    return True


def apply(*, dry_run: bool) -> dict[str, Any]:
    status = evaluate()
    if status["state"] == "error":
        return status
    if not status.get("provider"):
        status["state"] = "error"
        status["message"] = (
            "run users-part2-oauth first (no openshift auth provider)"
        )
        return status

    log: list[str] = []
    scope_id = _upsert_scope(status, dry_run=dry_run, log=log)
    if not scope_id:
        status["log"] = log
        status["sections"] = build_sections(status)
        return status

    analyst_id = status["analyst_permission_set_id"]
    if not _upsert_role(
        status,
        role_name=ROLE_BOAZ,
        existing=status.get("role_boaz"),
        permission_set_id=analyst_id,
        access_scope_id=scope_id,
        dry_run=dry_run,
        log=log,
    ):
        status["log"] = log
        status["sections"] = build_sections(status)
        return status
    if not _upsert_role(
        status,
        role_name=ROLE_CHRIS,
        existing=status.get("role_chris"),
        permission_set_id=analyst_id,
        access_scope_id=scope_id,
        dry_run=dry_run,
        log=log,
    ):
        status["log"] = log
        status["sections"] = build_sections(status)
        return status

    provider_id = str(status["provider"]["id"])
    # Refresh groups before rule ensure when not dry-run after prior creates.
    if not dry_run:
        status["groups"] = list_groups(
            status["base"], status["authorization"], creds=status["creds"]
        )

    for key, value, role_name in (
        ("name", "adam", ADMIN_ROLE),
        ("name", "boaz", ROLE_BOAZ),
        ("name", "chris", ROLE_CHRIS),
        ("", "", "None"),
    ):
        if not _ensure_group_rule(
            status,
            provider_id=provider_id,
            key=key,
            value=value,
            role_name=role_name,
            dry_run=dry_run,
            log=log,
        ):
            status["log"] = log
            status["sections"] = build_sections(status)
            return status
        if not dry_run:
            status["groups"] = list_groups(
                status["base"], status["authorization"], creds=status["creds"]
            )

    if dry_run:
        status["state"] = "ok"
        status["message"] = "dry-run: " + "; ".join(log)
        status["log"] = log
        status["sections"] = build_sections(status)
        return status

    final = evaluate()
    final["log"] = log
    if final.get("state") == "ok":
        final["message"] = (
            f"users-part3-acs ready (scope {SCOPE_NAME}; "
            f"{ROLE_BOAZ}/{ROLE_CHRIS}; adam Admin)"
        )
    return final


def _delete_group(
    status: dict[str, Any], group: dict[str, Any], *, dry_run: bool, log: list[str]
) -> bool:
    props = group.get("props") or {}
    label = f"{props.get('key')}={props.get('value')} -> {group.get('roleName')}"
    if dry_run:
        log.append(f"would delete group rule {label}")
        return True
    group_id = str(props.get("id") or "").strip()
    provider_id = str(props.get("authProviderId") or "").strip()
    if not group_id or not provider_id:
        status["state"] = "error"
        status["message"] = (
            f"cannot delete group rule {label}: missing props.id or "
            "props.authProviderId"
        )
        return False
    # Central 5.x expects query params (DELETE body is ignored / empty).
    path = (
        f"/v1/groups?id={quote(group_id, safe='')}"
        f"&authProviderId={quote(provider_id, safe='')}"
    )
    code, resp = central_request(
        status["base"],
        status["authorization"],
        "DELETE",
        path,
        creds=status["creds"],
    )
    if code not in (200, 204) and code != 404:
        status["state"] = "error"
        status["message"] = f"DELETE {path} failed ({code}): {resp}"
        return False
    log.append(f"deleted group rule {label}")
    return True


def uninstall(*, dry_run: bool) -> dict[str, Any]:
    status = evaluate()
    if status["state"] == "error":
        return status

    log: list[str] = []
    provider = status.get("provider")
    groups = status.get("groups") or []
    if provider:
        provider_id = str(provider.get("id"))
        owned = [
            ("name", "adam", ADMIN_ROLE),
            ("name", "boaz", ROLE_BOAZ),
            ("name", "chris", ROLE_CHRIS),
        ]
        for key, value, role_name in owned:
            group = find_group(
                groups,
                provider_id=provider_id,
                key=key,
                value=value,
                role_name=role_name,
            )
            if group:
                if not _delete_group(status, group, dry_run=dry_run, log=log):
                    status["log"] = log
                    status["sections"] = build_sections(status)
                    return status
            else:
                log.append(
                    f"group rule {key}={value} -> {role_name} already absent"
                )
    else:
        log.append("no openshift provider; skipping group-rule deletes")

    for role_name in (ROLE_BOAZ, ROLE_CHRIS):
        role = get_role(
            status["base"],
            status["authorization"],
            role_name,
            creds=status["creds"],
        ) if status.get("central_ok") else None
        if not role:
            log.append(f"role {role_name} already absent")
            continue
        if dry_run:
            log.append(f"would delete role {role_name}")
            continue
        code, resp = central_request(
            status["base"],
            status["authorization"],
            "DELETE",
            f"/v1/roles/{role_name}",
            creds=status["creds"],
        )
        if code not in (200, 204) and code != 404:
            status["state"] = "error"
            status["message"] = (
                f"DELETE /v1/roles/{role_name} failed ({code}): {resp}"
            )
            status["log"] = log
            return status
        log.append(f"deleted role {role_name}")

    scope = status.get("scope")
    if not scope:
        # Re-fetch in case evaluate marked scope drifted/missing name only
        scopes = list_scopes(
            status["base"], status["authorization"], creds=status["creds"]
        )
        scope = find_scope_by_name(scopes, SCOPE_NAME)

    if not scope:
        log.append(f"scope {SCOPE_NAME} already absent")
    elif dry_run:
        log.append(f"would delete scope {SCOPE_NAME} id={scope.get('id')}")
    else:
        sid = scope.get("id")
        code, resp = central_request(
            status["base"],
            status["authorization"],
            "DELETE",
            f"/v1/simpleaccessscopes/{sid}",
            creds=status["creds"],
        )
        if code not in (200, 204) and code != 404:
            status["state"] = "error"
            status["message"] = (
                f"DELETE /v1/simpleaccessscopes/{sid} failed ({code}): {resp}"
            )
            status["log"] = log
            return status
        log.append(f"deleted scope {SCOPE_NAME} id={sid}")

    status["state"] = "ok"
    status["message"] = (
        "dry-run: " + "; ".join(log) if dry_run else "removed users-part3-acs objects"
    )
    status["log"] = log
    if not dry_run:
        final = evaluate()
        final["state"] = "ok"
        final["message"] = "removed users-part3-acs objects"
        final["log"] = log
        final["sections"] = build_sections(final)
        return final
    status["sections"] = build_sections(status)
    return status


def print_cli(result: dict[str, Any]) -> None:
    for line in result.get("log") or []:
        print(line)
    sections = result.get("sections") or build_sections(result)
    if sections:
        print(
            "ACS_SECTIONS_JSON="
            + json.dumps({"sections": sections}, separators=(",", ":"))
        )
    print(f"{MODULE_ID}\t{result.get('state', 'error')}\t{result.get('message', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "run", "uninstall"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "status":
            result = evaluate()
        elif args.command == "run":
            result = apply(dry_run=args.dry_run)
        else:
            result = uninstall(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        result = {
            "state": "error",
            "message": str(exc),
            "central_ok": False,
            "central_body": "",
            "central_error": str(exc),
        }
        result["sections"] = build_sections(result)

    if args.cli:
        print_cli(result)
    else:
        safe = {
            k: v
            for k, v in result.items()
            if k not in ("creds", "authorization", "groups")
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
