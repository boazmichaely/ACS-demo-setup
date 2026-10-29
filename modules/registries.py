#!/usr/bin/env python3
"""Configure ACS image registry integrations from the secured-cluster pull secret."""

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
from lib.openshift import ensure_oc  # noqa: E402

MODULE_ID = "registries"
QUAY_INTEGRATION_NAME = "Public Quay.io"
RHEL_INTEGRATION_NAME = "registry.redhat.io"
REQUIRED_PULL_SECRET_HOSTS = ("quay.io", "registry.redhat.io")


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


def evaluate() -> dict[str, Any]:
    creds = load_lab_credentials()
    base, authorization = central_connection(creds)

    auth_error = check_central_auth(base, authorization, creds=creds)
    if auth_error:
        return {
            "state": "error",
            "message": auth_error,
            "errorPhase": "central",
            "central": base,
        }

    try:
        ensure_oc(creds)
    except RuntimeError as exc:
        return {
            "state": "error",
            "message": str(exc),
            "errorPhase": "openshift",
            "central": base,
        }

    try:
        auths = load_pull_secret_auths()
    except RuntimeError as exc:
        return {
            "state": "error",
            "message": str(exc),
            "errorPhase": "pull-secret",
            "central": base,
        }

    missing_hosts = [host for host in REQUIRED_PULL_SECRET_HOSTS if host not in auths]
    if missing_hosts:
        return {
            "state": "error",
            "message": f"pull-secret missing hosts: {', '.join(missing_hosts)}",
            "errorPhase": "pull-secret",
            "central": base,
            "pullSecretMissingHosts": missing_hosts,
            "pullSecretPresentHosts": [
                host for host in REQUIRED_PULL_SECRET_HOSTS if host in auths
            ],
        }

    quay_user, quay_password = auth_entry(auths, "quay.io")
    rhel_user, rhel_password = auth_entry(auths, "registry.redhat.io")
    integrations = list_integrations(base, authorization, creds=creds)
    quay = find_quay_integration(integrations)
    rhel = find_rhel_integration(integrations)

    quay_ok = quay_is_configured(quay, quay_user)
    rhel_ok = rhel_is_configured(rhel, rhel_user)

    result: dict[str, Any] = {
        "central": base,
        "quayIntegrationId": quay.get("id") if quay else None,
        "rhelIntegrationId": rhel.get("id") if rhel else None,
        "quayPresent": quay is not None,
        "rhelPresent": rhel is not None,
        "quayConfigured": quay_ok,
        "rhelConfigured": rhel_ok,
        "quayUser": quay_user,
        "rhelUser": rhel_user,
        "quayPassword": quay_password,
        "rhelPassword": rhel_password,
        "pullSecretPresentHosts": list(REQUIRED_PULL_SECRET_HOSTS),
        # Presence-only facts for Status folds (never emit values).
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

    if quay_ok and rhel_ok:
        result.update(
            {
                "state": "ok",
                "message": "quay.io and registry.redhat.io integrations configured",
            }
        )
        return result

    missing: list[str] = []
    if not quay_ok:
        missing.append("quay.io robot credentials on Public Quay.io")
    if not rhel_ok:
        missing.append("registry.redhat.io integration")
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
        "Pull-secret source: openshift-config/pull-secret",
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


def build_sections(result: dict[str, Any]) -> list[dict[str, Any]]:
    """GUI Status folds from evaluate()/apply() facts. Never includes secrets."""
    sections: list[dict[str, Any]] = []
    state = result.get("state", "error")
    message = str(result.get("message") or "").strip()
    phase = str(result.get("errorPhase") or "").strip()

    if "quayConfigured" not in result:
        title = {
            "central": "Central API",
            "openshift": "OpenShift (oc)",
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


def apply(*, dry_run: bool) -> dict[str, Any]:
    status = evaluate()
    if status["state"] == "error":
        return status
    if status["state"] == "ok":
        return {
            **status,
            "log": ["No changes planned. quay.io and registry.redhat.io already match pull-secret."],
        }

    actions: list[str] = []
    if not status.get("quayConfigured"):
        actions.append(f"update {QUAY_INTEGRATION_NAME} with pull-secret quay.io credentials")
    if not status.get("rhelConfigured"):
        if status.get("rhelIntegrationId"):
            actions.append(f"update {RHEL_INTEGRATION_NAME} integration")
        else:
            actions.append(f"create {RHEL_INTEGRATION_NAME} integration")

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
        )
        if code != 200:
            return {"state": "error", "message": f"update {QUAY_INTEGRATION_NAME} failed ({code}): {body}"}

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
            )
        else:
            code, body = central_request(
                base,
                token,
                "POST",
                "/v1/imageintegrations",
                build_rhel_payload(rhel_user, rhel_password, skip_test=False),
            )
        if code != 200:
            return {"state": "error", "message": f"upsert {RHEL_INTEGRATION_NAME} failed ({code}): {body}"}

    final = evaluate()
    if final.get("state") == "ok":
        final["log"] = ["Applied registry integrations from secured-cluster pull-secret."]
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
    parser.add_argument("--cli", action="store_true", help="Print human output and TSV for shell wrapper")
    args = parser.parse_args()

    try:
        if args.command == "status":
            result = evaluate()
        else:
            result = apply(dry_run=args.dry_run)
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
