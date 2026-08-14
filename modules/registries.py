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
    central_api_base,
    central_api_token,
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
)

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


def list_integrations(base: str, token: str) -> list[dict[str, Any]]:
    code, body = central_request(base, token, "GET", "/v1/imageintegrations")
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
    base = central_api_base(creds)
    token = central_api_token(creds)

    auth_error = check_central_auth(base, token)
    if auth_error:
        return {"state": "error", "message": auth_error}

    auths = load_pull_secret_auths()
    missing_hosts = [host for host in REQUIRED_PULL_SECRET_HOSTS if host not in auths]
    if missing_hosts:
        return {
            "state": "error",
            "message": f"pull-secret missing hosts: {', '.join(missing_hosts)}",
        }

    quay_user, quay_password = auth_entry(auths, "quay.io")
    rhel_user, rhel_password = auth_entry(auths, "registry.redhat.io")
    integrations = list_integrations(base, token)
    quay = find_quay_integration(integrations)
    rhel = find_rhel_integration(integrations)

    quay_ok = quay_is_configured(quay, quay_user)
    rhel_ok = rhel_is_configured(rhel, rhel_user)

    result: dict[str, Any] = {
        "central": base,
        "quayIntegrationId": quay.get("id") if quay else None,
        "rhelIntegrationId": rhel.get("id") if rhel else None,
        "quayConfigured": quay_ok,
        "rhelConfigured": rhel_ok,
        "quayUser": quay_user,
        "rhelUser": rhel_user,
        "quayPassword": quay_password,
        "rhelPassword": rhel_password,
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
            "state": "ok",
            "message": "dry-run: " + "; ".join(actions),
            "actions": actions,
            "log": ["Planned changes:"] + [f"  - {action}" for action in actions],
            "central": status.get("central"),
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
        result = {"state": "error", "message": str(exc)}

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
