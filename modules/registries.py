#!/usr/bin/env python3
"""Configure ACS image registry integrations from Central's OpenShift pull secret."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
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
)
from lib.openshift import CENTRAL_ONLY_SC_ID, ensure_oc  # noqa: E402

MODULE_ID = "registries"
QUAY_INTEGRATION_NAME = "Public Quay.io"
RHEL_INTEGRATION_NAME = "registry.redhat.io"
# Public Google Artifact Registry host used by Mostmark / Online Boutique (ms-demo).
GAR_INTEGRATION_NAME = "Public Google Artifact Registry (us-central1)"
GAR_ENDPOINT = "us-central1-docker.pkg.dev"
REQUIRED_PULL_SECRET_HOSTS = ("quay.io", "registry.redhat.io")
# Written by central-ocp; read by central-api. Gitignored under .cache/.
PULL_SECRET_CACHE = ROOT / ".cache" / "registries-pull-secret.json"


def normalize_plane(raw: str | None) -> str | None:
    """Return canonical plane or None (both planes in one process)."""
    s = (raw or "").strip().lower().replace("_", "-")
    if not s:
        return None
    if s == "central":
        return None  # legacy: both
    if s in ("central-api", "central-ocp"):
        return s
    raise ValueError(f"unsupported plane {raw!r} (want central-api|central-ocp or omit)")


def want_central_ocp(plane: str | None) -> bool:
    return plane is None or plane == "central-ocp"


def want_central_api(plane: str | None) -> bool:
    return plane is None or plane == "central-api"


def run_oc_json(args: list[str]) -> Any:
    cmd = ["oc", *args, "-o", "json"]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"oc {' '.join(args)} failed: {detail}") from exc
    return json.loads(raw)


def load_pull_secret_auths() -> dict[str, dict[str, str]]:
    secret = run_oc_json(["get", "secret", "pull-secret", "-n", "openshift-config"])
    encoded = secret.get("data", {}).get(".dockerconfigjson")
    if not encoded:
        raise RuntimeError("pull-secret in openshift-config has no .dockerconfigjson")
    payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    auths = payload.get("auths") or {}
    if not auths:
        raise RuntimeError("pull-secret has no registry auths")
    return auths


def auth_entry(auths: dict[str, dict[str, str]], host: str) -> tuple[str, str]:
    entry = auths.get(host)
    if not entry or not entry.get("auth"):
        raise RuntimeError(f"pull-secret missing auth for {host}")
    user, password = base64.b64decode(entry["auth"]).decode("utf-8").split(":", 1)
    if not user or not password:
        raise RuntimeError(f"pull-secret auth for {host} is empty")
    return user, password


def list_integrations(
    base: str, authorization: str, *, creds: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/imageintegrations", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/imageintegrations failed ({code}): {body}")
    return body.get("integrations") or []


def find_quay_integration(integrations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in integrations:
        if item.get("name") == QUAY_INTEGRATION_NAME:
            return item
        endpoint = (item.get("quay") or {}).get("endpoint")
        if item.get("type") == "quay" and endpoint == "quay.io":
            return item
    return None


def find_rhel_integration(integrations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in integrations:
        endpoint = (item.get("docker") or {}).get("endpoint")
        if endpoint == "registry.redhat.io":
            return item
    return None


def find_gar_integration(integrations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in integrations:
        if item.get("name") == GAR_INTEGRATION_NAME:
            return item
        endpoint = (item.get("docker") or {}).get("endpoint")
        if item.get("type") == "docker" and endpoint == GAR_ENDPOINT:
            return item
    return None


def quay_is_configured(integration: dict[str, Any] | None, expected_user: str) -> bool:
    if not integration:
        return False
    creds = (integration.get("quay") or {}).get("registryRobotCredentials") or {}
    return creds.get("username") == expected_user and bool(creds.get("password"))


def rhel_is_configured(integration: dict[str, Any] | None, expected_user: str) -> bool:
    if not integration:
        return False
    docker = integration.get("docker") or {}
    return docker.get("endpoint") == "registry.redhat.io" and docker.get("username") == expected_user


def gar_is_configured(integration: dict[str, Any] | None) -> bool:
    if not integration:
        return False
    docker = integration.get("docker") or {}
    return (
        integration.get("type") == "docker"
        and docker.get("endpoint") == GAR_ENDPOINT
        and "REGISTRY" in (integration.get("categories") or [])
    )


def build_quay_payload(
    integration_id: str,
    username: str,
    password: str,
    *,
    skip_test: bool,
) -> dict[str, Any]:
    return {
        "id": integration_id,
        "name": QUAY_INTEGRATION_NAME,
        "type": "quay",
        "categories": ["REGISTRY"],
        "quay": {
            "endpoint": "quay.io",
            "oauthToken": "",
            "insecure": False,
            "registryRobotCredentials": {"username": username, "password": password},
        },
        "skipTestIntegration": skip_test,
    }


def build_rhel_payload(username: str, password: str, *, skip_test: bool) -> dict[str, Any]:
    return {
        "name": RHEL_INTEGRATION_NAME,
        "type": "docker",
        "categories": ["REGISTRY"],
        "docker": {
            "endpoint": "registry.redhat.io",
            "username": username,
            "password": password,
            "insecure": False,
        },
        "skipTestIntegration": skip_test,
    }


def build_gar_payload(*, integration_id: str | None = None, skip_test: bool) -> dict[str, Any]:
    """Anonymous public docker registry for Google Artifact Registry (Online Boutique)."""
    payload: dict[str, Any] = {
        "name": GAR_INTEGRATION_NAME,
        "type": "docker",
        "categories": ["REGISTRY"],
        "docker": {
            "endpoint": GAR_ENDPOINT,
            "username": "",
            "password": "",
            "insecure": False,
        },
        "skipTestIntegration": skip_test,
    }
    if integration_id:
        payload["id"] = integration_id
    return payload


def rescan_unscanned_gar_images(
    base: str, authorization: str, *, creds: dict[str, Any] | None = None
) -> list[str]:
    """Best-effort rescan of images from GAR_ENDPOINT that still lack scan data."""
    code, body = central_request(
        base, authorization, "GET", "/v1/images", creds=creds
    )
    if code != 200:
        return [f"list images for rescan failed ({code})"]
    log: list[str] = []
    for img in body.get("images") or []:
        name = str(img.get("name") or "")
        if not name.startswith(f"{GAR_ENDPOINT}/"):
            continue
        notes = img.get("notes") or []
        comps = int(img.get("components") or 0)
        if comps > 0 and "MISSING_SCAN_DATA" not in notes:
            continue
        scode, sbody = central_request(
            base,
            authorization,
            "POST",
            "/v1/images/scan",
            {"imageName": name},
            creds=creds,
        )
        if scode not in (200, 201):
            log.append(f"rescan failed for {name} ({scode}): {sbody}")
            continue
        new_comps = (sbody or {}).get("components") if isinstance(sbody, dict) else None
        new_cves = (sbody or {}).get("cves") if isinstance(sbody, dict) else None
        log.append(f"rescanned {name} (components={new_comps}, cves={new_cves})")
    if not log:
        log.append(f"no unscanned {GAR_ENDPOINT} images needed a rescan")
    return log


def _load_pull_secret_bundle_from_oc(creds: dict[str, Any]) -> dict[str, Any]:
    """central-ocp only: ensure_oc(_central) + required hosts. Raises RuntimeError with phase hint."""
    try:
        ensure_oc(creds, secured_cluster_id=CENTRAL_ONLY_SC_ID)
    except RuntimeError as exc:
        raise RuntimeError(f"central-ocp:{exc}") from exc
    try:
        auths = load_pull_secret_auths()
    except RuntimeError as exc:
        raise RuntimeError(f"pull-secret:{exc}") from exc
    missing_hosts = [host for host in REQUIRED_PULL_SECRET_HOSTS if host not in auths]
    if missing_hosts:
        raise RuntimeError(
            "pull-secret:missing hosts: "
            + ", ".join(missing_hosts)
            + f"|present:{','.join(h for h in REQUIRED_PULL_SECRET_HOSTS if h in auths)}"
        )
    quay_user, quay_password = auth_entry(auths, "quay.io")
    rhel_user, rhel_password = auth_entry(auths, "registry.redhat.io")
    return {
        "quayUser": quay_user,
        "quayPassword": quay_password,
        "rhelUser": rhel_user,
        "rhelPassword": rhel_password,
        "pullSecretPresentHosts": list(REQUIRED_PULL_SECRET_HOSTS),
        "pullSecretHosts": {
            "quay.io": {
                "authPresent": True,
                "hasUsername": bool(quay_user),
                "hasPassword": bool(quay_password),
            },
            "registry.redhat.io": {
                "authPresent": True,
                "hasUsername": bool(rhel_user),
                "hasPassword": bool(rhel_password),
            },
        },
    }


def write_pull_secret_cache(bundle: dict[str, Any]) -> None:
    """Persist robot credentials for a following central-api invoke (mode 0600)."""
    PULL_SECRET_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "quayUser": bundle["quayUser"],
        "quayPassword": bundle["quayPassword"],
        "rhelUser": bundle["rhelUser"],
        "rhelPassword": bundle["rhelPassword"],
        "pullSecretPresentHosts": bundle["pullSecretPresentHosts"],
        "pullSecretHosts": bundle["pullSecretHosts"],
    }
    PULL_SECRET_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    PULL_SECRET_CACHE.chmod(0o600)


def read_pull_secret_cache() -> dict[str, Any]:
    """central-api only: credentials left by central-ocp (or a prior combined run)."""
    if not PULL_SECRET_CACHE.is_file():
        raise RuntimeError(
            "pull-secret-cache:missing - run central-ocp first "
            "(or omit --plane so both planes run in one process)"
        )
    try:
        payload = json.loads(PULL_SECRET_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"pull-secret-cache:unreadable ({exc})") from exc
    for key in ("quayUser", "quayPassword", "rhelUser", "rhelPassword"):
        if not str(payload.get(key) or "").strip():
            raise RuntimeError(f"pull-secret-cache:incomplete (missing {key})")
    hosts = payload.get("pullSecretHosts") or {}
    present = payload.get("pullSecretPresentHosts") or list(REQUIRED_PULL_SECRET_HOSTS)
    return {
        "quayUser": payload["quayUser"],
        "quayPassword": payload["quayPassword"],
        "rhelUser": payload["rhelUser"],
        "rhelPassword": payload["rhelPassword"],
        "pullSecretPresentHosts": list(present),
        "pullSecretHosts": hosts,
    }


def resolve_pull_secret_bundle(
    plane: str | None, creds: dict[str, Any]
) -> dict[str, Any]:
    """
    central-ocp / combined: read via oc and refresh cache.
    central-api alone: read cache only (never oc).
    """
    if plane == "central-api":
        return read_pull_secret_cache()
    bundle = _load_pull_secret_bundle_from_oc(creds)
    write_pull_secret_cache(bundle)
    return bundle


def _phase_error_from_bundle(exc: RuntimeError, *, central: str = "") -> dict[str, Any]:
    msg = str(exc)
    out: dict[str, Any] = {"state": "error", "message": msg}
    if central:
        out["central"] = central
    if msg.startswith("central-ocp:"):
        out["errorPhase"] = "central-ocp"
        out["message"] = msg[len("central-ocp:") :]
        return out
    if msg.startswith("pull-secret-cache:"):
        out["errorPhase"] = "pull-secret"
        out["message"] = msg[len("pull-secret-cache:") :]
        return out
    if msg.startswith("pull-secret:missing hosts:"):
        rest = msg[len("pull-secret:missing hosts:") :]
        missing_part, _, present_part = rest.partition("|present:")
        out["errorPhase"] = "pull-secret"
        out["message"] = f"pull-secret missing hosts: {missing_part}"
        out["pullSecretMissingHosts"] = [
            h.strip() for h in missing_part.split(",") if h.strip()
        ]
        out["pullSecretPresentHosts"] = [
            h.strip() for h in present_part.split(",") if h.strip()
        ]
        return out
    if msg.startswith("pull-secret:"):
        out["errorPhase"] = "pull-secret"
        out["message"] = msg[len("pull-secret:") :]
        return out
    out["errorPhase"] = "central-ocp"
    return out


def evaluate_ocp_only() -> dict[str, Any]:
    """central-ocp plane: pull-secret via oc, refresh cache, no Central API."""
    creds = load_lab_credentials()
    try:
        bundle = resolve_pull_secret_bundle("central-ocp", creds)
    except RuntimeError as exc:
        return _phase_error_from_bundle(exc)
    return {
        "state": "ok",
        "message": (
            "Central OpenShift pull-secret has quay.io and registry.redhat.io "
            "(cached for central-api)"
        ),
        "plane": "central-ocp",
        "pullSecretPresentHosts": bundle["pullSecretPresentHosts"],
        "pullSecretHosts": bundle["pullSecretHosts"],
        "ocpOnly": True,
    }


def evaluate(*, plane: str | None = None) -> dict[str, Any]:
    plane = normalize_plane(plane)

    if want_central_ocp(plane) and not want_central_api(plane):
        return evaluate_ocp_only()

    creds = load_lab_credentials()
    base, authorization = central_connection(creds)

    auth_error = check_central_auth(base, authorization, creds=creds)
    if auth_error:
        return {
            "state": "error",
            "message": auth_error,
            "errorPhase": "central-api",
            "central": base,
        }

    # central-api alone: cache only. Combined (plane None): oc + cache, then API.
    try:
        bundle = resolve_pull_secret_bundle(plane if plane else None, creds)
    except RuntimeError as exc:
        return _phase_error_from_bundle(exc, central=base)

    quay_user = bundle["quayUser"]
    quay_password = bundle["quayPassword"]
    rhel_user = bundle["rhelUser"]
    rhel_password = bundle["rhelPassword"]
    integrations = list_integrations(base, authorization, creds=creds)
    quay = find_quay_integration(integrations)
    rhel = find_rhel_integration(integrations)
    gar = find_gar_integration(integrations)

    quay_ok = quay_is_configured(quay, quay_user)
    rhel_ok = rhel_is_configured(rhel, rhel_user)
    gar_ok = gar_is_configured(gar)

    result: dict[str, Any] = {
        "central": base,
        "plane": plane or "both",
        "quayIntegrationId": quay.get("id") if quay else None,
        "rhelIntegrationId": rhel.get("id") if rhel else None,
        "garIntegrationId": gar.get("id") if gar else None,
        "quayPresent": quay is not None,
        "rhelPresent": rhel is not None,
        "garPresent": gar is not None,
        "quayConfigured": quay_ok,
        "rhelConfigured": rhel_ok,
        "garConfigured": gar_ok,
        "quayUser": quay_user,
        "rhelUser": rhel_user,
        "quayPassword": quay_password,
        "rhelPassword": rhel_password,
        "pullSecretPresentHosts": bundle["pullSecretPresentHosts"],
        "pullSecretHosts": bundle["pullSecretHosts"],
    }

    if quay_ok and rhel_ok and gar_ok:
        result.update(
            {
                "state": "ok",
                "message": (
                    "quay.io, registry.redhat.io, and "
                    f"{GAR_ENDPOINT} integrations configured"
                ),
            }
        )
        return result

    missing: list[str] = []
    if not quay_ok:
        missing.append("quay.io robot credentials on Public Quay.io")
    if not rhel_ok:
        missing.append("registry.redhat.io integration")
    if not gar_ok:
        missing.append(f"{GAR_ENDPOINT} public registry integration")
    result.update(
        {
            "state": "needs-run",
            "message": "missing: " + "; ".join(missing),
        }
    )
    return result


def _ready_fields(ok: bool) -> dict[str, str]:
    if ok:
        return {"tag": "ok", "tagLabel": "ready", "summary": "configured"}
    return {"tag": "warn", "tagLabel": "needs run", "summary": "missing or drifted"}


def _pull_secret_lines(host: str, host_meta: dict[str, Any] | None) -> list[str]:
    """Presence-only pull-secret facts; never usernames or passwords."""
    lines = [
        "Pull-secret source: Central OpenShift openshift-config/pull-secret",
        f"Host entry ({host}): present" if (host_meta or {}).get("authPresent") else f"Host entry ({host}): absent",
    ]
    if not host_meta:
        return lines
    user_ok = bool(host_meta.get("hasUsername"))
    pass_ok = bool(host_meta.get("hasPassword"))
    if user_ok and pass_ok:
        lines.append("Auth fields: username and password present (values not shown)")
    elif user_ok:
        lines.append("Auth fields: username present; password missing (values not shown)")
    elif pass_ok:
        lines.append("Auth fields: password present; username missing (values not shown)")
    else:
        lines.append("Auth fields: missing")
    return lines


def _integration_fold(
    *,
    title: str,
    host: str,
    present: bool,
    configured: bool,
    host_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    body = [
        f"Central integration: {'present' if present else 'absent'}",
        f"Credentials match pull-secret: {'yes' if configured else 'no'}",
        *_pull_secret_lines(host, host_meta),
    ]
    return {
        "group": "Integrations",
        "title": title,
        **_ready_fields(configured),
        "body": "\n".join(body),
        "bodyFormat": "prose",
    }


def _public_registry_fold(
    *,
    title: str,
    endpoint: str,
    present: bool,
    configured: bool,
) -> dict[str, Any]:
    body = [
        f"Central integration: {'present' if present else 'absent'}",
        f"Endpoint: {endpoint}",
        "Auth: anonymous public (no pull-secret)",
        "Used by: ms-demo Online Boutique images",
    ]
    return {
        "group": "Integrations",
        "title": title,
        **_ready_fields(configured),
        "body": "\n".join(body),
        "bodyFormat": "prose",
    }


def build_sections(result: dict[str, Any]) -> list[dict[str, Any]]:
    """GUI Status folds from evaluate()/apply() facts. Never includes secrets."""
    sections: list[dict[str, Any]] = []
    state = result.get("state", "error")
    message = str(result.get("message") or "").strip()
    phase = str(result.get("errorPhase") or "").strip()

    if result.get("ocpOnly"):
        host_meta = result.get("pullSecretHosts") or {}
        body = [
            "Plane: central-ocp (pull-secret only; no Central API)",
            *_pull_secret_lines("quay.io", host_meta.get("quay.io")),
            "",
            *_pull_secret_lines("registry.redhat.io", host_meta.get("registry.redhat.io")),
        ]
        ok = state == "ok"
        sections.append(
            {
                "group": "Central OpenShift",
                "title": "openshift-config/pull-secret",
                "tag": "ok" if ok else "error",
                "tagLabel": "ready" if ok else "error",
                "summary": "readable" if ok else "blocked",
                "body": "\n".join(body),
                "bodyFormat": "prose",
            }
        )
        return sections

    if "quayConfigured" not in result:
        title = {
            "central-api": "Central API",
            "central": "Central API",  # legacy
            "central-ocp": "Central OpenShift (oc)",
            "openshift": "Central OpenShift (oc)",  # legacy
            "pull-secret": "Pull secret",
        }.get(phase, "Status check")
        body_lines = [message or "Unable to evaluate registry integrations."]
        missing = result.get("pullSecretMissingHosts") or []
        present = result.get("pullSecretPresentHosts") or []
        if present:
            body_lines.append("Pull-secret hosts present: " + ", ".join(present))
        if missing:
            body_lines.append("Pull-secret hosts missing: " + ", ".join(missing))
        sections.append(
            {
                "group": "Integrations",
                "title": title,
                "tag": "error",
                "tagLabel": "error",
                "summary": "blocked",
                "body": "\n".join(body_lines),
                "bodyFormat": "prose",
            }
        )
        return sections

    host_meta = result.get("pullSecretHosts") or {}
    sections.append(
        _integration_fold(
            title="quay.io",
            host="quay.io",
            present=bool(result.get("quayPresent") or result.get("quayIntegrationId")),
            configured=bool(result.get("quayConfigured")),
            host_meta=host_meta.get("quay.io"),
        )
    )
    sections.append(
        _integration_fold(
            title="registry.redhat.io",
            host="registry.redhat.io",
            present=bool(result.get("rhelPresent") or result.get("rhelIntegrationId")),
            configured=bool(result.get("rhelConfigured")),
            host_meta=host_meta.get("registry.redhat.io"),
        )
    )
    sections.append(
        _public_registry_fold(
            title=GAR_ENDPOINT,
            endpoint=GAR_ENDPOINT,
            present=bool(result.get("garPresent") or result.get("garIntegrationId")),
            configured=bool(result.get("garConfigured")),
        )
    )

    actions = result.get("actions") or []
    if actions:
        sections.append(
            {
                "group": "Plan",
                "title": "Dry run",
                "tag": "ok" if state != "error" else "error",
                "tagLabel": "dry-run",
                "summary": f"{len(actions)} change(s)",
                "body": "\n".join(f"- {action}" for action in actions),
                "bodyFormat": "prose",
            }
        )

    return sections


def apply(*, dry_run: bool, plane: str | None = None) -> dict[str, Any]:
    plane = normalize_plane(plane)
    status = evaluate(plane=plane)
    if status["state"] == "error":
        return status

    # central-ocp plane: validate pull-secret only (no Central API mutations).
    if want_central_ocp(plane) and not want_central_api(plane):
        msg = (
            "central-ocp: pull-secret ready and cached for central-api "
            "(no Central API changes)"
        )
        if dry_run:
            return {
                **status,
                "state": "ok",
                "message": f"dry-run: {msg}",
                "actions": [msg],
                "log": ["Planned changes:", f"  - {msg}"],
            }
        return {
            **status,
            "state": "ok",
            "message": msg,
            "log": [msg],
        }

    if status["state"] == "ok":
        return {
            **status,
            "log": [
                "No changes planned. quay.io, registry.redhat.io, and "
                f"{GAR_ENDPOINT} already configured."
            ],
        }

    actions: list[str] = []
    if not status.get("quayConfigured"):
        actions.append(f"update {QUAY_INTEGRATION_NAME} with pull-secret quay.io credentials")
    if not status.get("rhelConfigured"):
        if status.get("rhelIntegrationId"):
            actions.append(f"update {RHEL_INTEGRATION_NAME} integration")
        else:
            actions.append(f"create {RHEL_INTEGRATION_NAME} integration")
    if not status.get("garConfigured"):
        if status.get("garIntegrationId"):
            actions.append(f"update {GAR_INTEGRATION_NAME} integration")
        else:
            actions.append(f"create {GAR_INTEGRATION_NAME} integration")
        actions.append(f"rescan unscanned images from {GAR_ENDPOINT}")

    if dry_run:
        return {
            **status,
            "state": "ok",
            "message": "dry-run: " + "; ".join(actions),
            "actions": actions,
            "log": ["Planned changes:"] + [f"  - {action}" for action in actions],
        }

    creds = load_lab_credentials()
    base, token = central_connection(creds)
    quay_user = status["quayUser"]
    quay_password = status["quayPassword"]
    rhel_user = status["rhelUser"]
    rhel_password = status["rhelPassword"]
    log: list[str] = []

    if not status.get("quayConfigured"):
        quay_id = status.get("quayIntegrationId")
        if not quay_id:
            return {"state": "error", "message": f"{QUAY_INTEGRATION_NAME} integration not found in Central"}
        code, body = central_request(
            base,
            token,
            "PUT",
            f"/v1/imageintegrations/{quay_id}",
            build_quay_payload(quay_id, quay_user, quay_password, skip_test=False),
            creds=creds,
        )
        if code != 200:
            return {"state": "error", "message": f"update {QUAY_INTEGRATION_NAME} failed ({code}): {body}"}
        log.append(f"updated {QUAY_INTEGRATION_NAME}")

    if not status.get("rhelConfigured"):
        if status.get("rhelIntegrationId"):
            rhel_id = status["rhelIntegrationId"]
            code, body = central_request(
                base,
                token,
                "PUT",
                f"/v1/imageintegrations/{rhel_id}",
                {
                    "id": rhel_id,
                    **build_rhel_payload(rhel_user, rhel_password, skip_test=False),
                },
                creds=creds,
            )
            action = "updated"
        else:
            code, body = central_request(
                base,
                token,
                "POST",
                "/v1/imageintegrations",
                build_rhel_payload(rhel_user, rhel_password, skip_test=False),
                creds=creds,
            )
            action = "created"
        if code != 200:
            return {"state": "error", "message": f"upsert {RHEL_INTEGRATION_NAME} failed ({code}): {body}"}
        log.append(f"{action} {RHEL_INTEGRATION_NAME}")

    if not status.get("garConfigured"):
        if status.get("garIntegrationId"):
            gar_id = status["garIntegrationId"]
            code, body = central_request(
                base,
                token,
                "PUT",
                f"/v1/imageintegrations/{gar_id}",
                build_gar_payload(integration_id=gar_id, skip_test=False),
                creds=creds,
            )
            action = "updated"
        else:
            code, body = central_request(
                base,
                token,
                "POST",
                "/v1/imageintegrations",
                build_gar_payload(skip_test=False),
                creds=creds,
            )
            action = "created"
        if code != 200:
            return {
                "state": "error",
                "message": f"upsert {GAR_INTEGRATION_NAME} failed ({code}): {body}",
            }
        log.append(f"{action} {GAR_INTEGRATION_NAME}")
        log.extend(rescan_unscanned_gar_images(base, token, creds=creds))

    final = evaluate(plane=plane)
    if final.get("state") == "ok":
        final["log"] = log or [
            "Applied registry integrations (pull-secret + public Artifact Registry)."
        ]
    else:
        final["log"] = log
    return final


def print_cli(result: dict[str, Any]) -> None:
    for line in result.get("log") or []:
        print(line)
    sections = build_sections(result)
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
    parser.add_argument("command", choices=["status", "run"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--plane",
        default="",
        help="central-api | central-ocp (omit = both; legacy central = both)",
    )
    parser.add_argument("--cli", action="store_true", help="Print human output and TSV for shell wrapper")
    args = parser.parse_args()

    try:
        plane = normalize_plane(args.plane)
        if args.command == "status":
            result = evaluate(plane=plane)
        else:
            result = apply(dry_run=args.dry_run, plane=plane)
    except ValueError as exc:
        result = {"state": "error", "message": str(exc), "errorPhase": "status"}
    except Exception as exc:  # noqa: BLE001 - module status contract
        result = {"state": "error", "message": str(exc), "errorPhase": "status"}

    if args.cli:
        print_cli(result)
    else:
        print(json.dumps(result))

    state = result.get("state", "error")
    if args.command == "status":
        return 0 if state in ("ok", "needs-run") else 1
    if args.dry_run:
        return 0 if state != "error" else 1
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
