#!/usr/bin/env python3
"""ACS Signature Integration (Red Hat Public) + Inform policy + image priming."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.central import (  # noqa: E402
    central_connection,
    central_request,
    check_central_auth,
    load_lab_credentials,
    ssl_context_for_central,
)
from lib.demo_policies import (  # noqa: E402
    DEMO_CATEGORY,
    ensure_managed_policy,
    find_policy_by_name,
)


def _auth_header(authorization: str) -> str:
    auth = (authorization or "").strip()
    if not auth:
        raise RuntimeError("empty Central Authorization header")
    lower = auth.lower()
    if lower.startswith("bearer ") or lower.startswith("basic "):
        return auth
    return f"Bearer {auth}"

MODULE_ID = "signature-integration"
INTEGRATION_NAME = "Red Hat Public"
POLICY_NAME = "Images must be signed by Red Hat Public"
KEY_LABEL = "release-key-3"
ASSET_DIR = Path(__file__).resolve().parent / "signature-integration"
PUB_KEY_PATH = ASSET_DIR / "red-hat-release-key-3.pub"
IMAGES_PATH = ASSET_DIR / "images.txt"
# Fingerprint of committed PEM (sha256 of file bytes including trailing newline).
EXPECTED_PEM_SHA256 = "64f89557ea8030ff839a45bb194594262a83502cdc69a4b04786e9d975a5c5aa"


def emit_status_line(state: str, message: str) -> None:
    print(f"{MODULE_ID}\t{state}\t{message}")


def emit_sections(sections: list[dict[str, Any]]) -> None:
    print(
        "ACS_SECTIONS_JSON="
        + json.dumps({"sections": sections}, separators=(",", ":"))
    )


def load_pub_pem() -> str:
    if not PUB_KEY_PATH.is_file():
        raise RuntimeError(f"missing public key asset: {PUB_KEY_PATH}")
    pem = PUB_KEY_PATH.read_text(encoding="utf-8")
    if not pem.endswith("\n"):
        pem += "\n"
    digest = hashlib.sha256(pem.encode()).hexdigest()
    if digest != EXPECTED_PEM_SHA256:
        raise RuntimeError(
            f"public key fingerprint mismatch for {PUB_KEY_PATH}: "
            f"got {digest}, expected {EXPECTED_PEM_SHA256}"
        )
    return pem


def pem_fingerprint(pem: str) -> str:
    text = pem if pem.endswith("\n") else pem + "\n"
    return hashlib.sha256(text.encode()).hexdigest()


def load_image_list() -> tuple[list[str], list[str]]:
    if not IMAGES_PATH.is_file():
        raise RuntimeError(f"missing images list: {IMAGES_PATH}")
    signed: list[str] = []
    unsigned: list[str] = []
    for raw in IMAGES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise RuntimeError(f"bad images.txt line: {raw!r}")
        flag, ref = parts
        if flag == "signed=yes":
            signed.append(ref)
        elif flag == "signed=no":
            unsigned.append(ref)
        else:
            raise RuntimeError(f"bad images.txt flag: {flag!r}")
    if len(signed) < 3:
        raise RuntimeError(f"images.txt must list at least 3 signed refs (got {len(signed)})")
    return signed, unsigned


def list_signature_integrations(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> list[dict[str, Any]]:
    code, body = central_request(
        base, authorization, "GET", "/v1/signatureintegrations", creds=creds
    )
    if code != 200:
        raise RuntimeError(f"GET /v1/signatureintegrations failed ({code}): {body}")
    return list((body or {}).get("integrations") or [])


def find_integration_by_name(
    integrations: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    for item in integrations:
        if item.get("name") == name:
            return item
    return None


def integration_pem_ok(integration: dict[str, Any] | None, expected_pem: str) -> bool:
    if not integration:
        return False
    keys = ((integration.get("cosign") or {}).get("publicKeys")) or []
    if not keys:
        return False
    got = (keys[0].get("publicKeyPemEnc") or "").strip() + "\n"
    exp = expected_pem.strip() + "\n"
    return (
        pem_fingerprint(got) == pem_fingerprint(exp)
        and (keys[0].get("name") or "") == KEY_LABEL
    )


def build_integration_payload(
    *, integration_id: str, pem: str
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": INTEGRATION_NAME,
        "cosign": {
            "publicKeys": [
                {
                    "name": KEY_LABEL,
                    "publicKeyPemEnc": pem.strip() + "\n",
                }
            ]
        },
        "cosignCertificates": [],
    }
    if integration_id:
        payload["id"] = integration_id
    return payload


def ensure_integration(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    pem: str,
    dry_run: bool,
) -> dict[str, Any]:
    integrations = list_signature_integrations(base, authorization, creds=creds)
    # Never touch product "Red Hat"
    existing = find_integration_by_name(integrations, INTEGRATION_NAME)
    if existing and integration_pem_ok(existing, pem):
        print(f"integration '{INTEGRATION_NAME}' already ok (id={existing.get('id')})")
        return existing

    payload = build_integration_payload(
        integration_id=(existing or {}).get("id") or "",
        pem=pem,
    )
    if dry_run:
        action = "update" if existing else "create"
        print(f"dry-run: would {action} Signature Integration '{INTEGRATION_NAME}'")
        return existing or {"name": INTEGRATION_NAME, "id": "(new)"}

    if existing:
        iid = existing["id"]
        code, body = central_request(
            base,
            authorization,
            "PUT",
            f"/v1/signatureintegrations/{iid}",
            payload,
            creds=creds,
        )
        action = "updated"
    else:
        # POST body should not require empty id
        payload.pop("id", None)
        code, body = central_request(
            base,
            authorization,
            "POST",
            "/v1/signatureintegrations",
            payload,
            creds=creds,
        )
        action = "created"

    if code not in (200, 201):
        raise RuntimeError(
            f"{action} Signature Integration '{INTEGRATION_NAME}' failed "
            f"({code}): {body}"
        )
    result = body if isinstance(body, dict) and body.get("id") else None
    if not result:
        integrations = list_signature_integrations(base, authorization, creds=creds)
        result = find_integration_by_name(integrations, INTEGRATION_NAME)
    if not result:
        raise RuntimeError(f"could not reload integration '{INTEGRATION_NAME}' after {action}")
    print(f"{action} Signature Integration '{INTEGRATION_NAME}' (id={result.get('id')})")
    return result


def build_policy_payload(integration_id: str, *, policy_id: str = "") -> dict[str, Any]:
    policy: dict[str, Any] = {
        "name": POLICY_NAME,
        "description": (
            "Alert when an image is not verified by the Red Hat Public "
            "Cosign signature integration (Red Hat release key 3)."
        ),
        "rationale": (
            "Container images should be signed so ACS can verify provenance "
            "with Red Hat release key 3."
        ),
        "remediation": (
            "Use an image signed with Red Hat release key 3, or update the "
            "Red Hat Public signature integration."
        ),
        "disabled": False,
        "categories": ["Supply Chain Security", DEMO_CATEGORY],
        "lifecycleStages": ["BUILD", "DEPLOY"],
        "eventSource": "NOT_APPLICABLE",
        "severity": "HIGH_SEVERITY",
        "enforcementActions": [],
        "policyVersion": "1.1",
        "policySections": [
            {
                "sectionName": "Image must be verified by Red Hat Public",
                "policyGroups": [
                    {
                        "fieldName": "Image Signature Verified By",
                        "booleanOperator": "OR",
                        "negate": False,
                        "values": [{"value": integration_id}],
                    }
                ],
            }
        ],
        "scope": [],
    }
    if policy_id:
        policy["id"] = policy_id
    return policy


def policy_matches(
    policy: dict[str, Any] | None, integration_id: str
) -> bool:
    if not policy:
        return False
    if policy.get("disabled"):
        return False
    if DEMO_CATEGORY not in (policy.get("categories") or []):
        return False
    stages = set(policy.get("lifecycleStages") or [])
    if stages != {"BUILD", "DEPLOY"}:
        return False
    if policy.get("enforcementActions"):
        return False
    sections = policy.get("policySections") or []
    found = False
    for section in sections:
        for group in section.get("policyGroups") or []:
            if group.get("fieldName") != "Image Signature Verified By":
                continue
            for val in group.get("values") or []:
                if val.get("value") == integration_id:
                    found = True
    return found


def ensure_policy(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    integration_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    existing = find_policy_by_name(base, authorization, POLICY_NAME, creds=creds)
    full_existing: dict[str, Any] | None = None
    if existing:
        code, loaded = central_request(
            base,
            authorization,
            "GET",
            f"/v1/policies/{existing['id']}",
            creds=creds,
        )
        full_existing = loaded if code == 200 and isinstance(loaded, dict) else existing
        if policy_matches(full_existing, integration_id):
            print(f"policy '{POLICY_NAME}' already ok (id={full_existing.get('id')})")
            return full_existing

    payload = build_policy_payload(
        integration_id,
        policy_id=(full_existing or {}).get("id") or "",
    )
    result = ensure_managed_policy(
        base,
        authorization,
        payload,
        creds=creds,
        dry_run=dry_run,
        preserve_notifiers=True,
    )
    if dry_run:
        return result
    action = "updated" if existing else "created"
    print(f"{action} policy '{POLICY_NAME}' (id={result.get('id')})")
    return result


def image_id_from_ref(ref: str) -> str:
    if "@sha256:" in ref:
        return ref.rsplit("@", 1)[1]
    raise RuntimeError(f"image ref must be digest-pinned (@sha256:…): {ref}")


def verification_status_for(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    image_ref: str,
    integration_id: str,
) -> str:
    iid = image_id_from_ref(image_ref)
    code, body = central_request(
        base, authorization, "GET", f"/v1/images/{iid}", creds=creds
    )
    if code == 404:
        return "MISSING"
    if code != 200 or not isinstance(body, dict):
        return f"ERROR:{code}"
    results = (body.get("signatureVerificationData") or {}).get("results") or []
    for row in results:
        if row.get("verifierId") == integration_id:
            return str(row.get("status") or "UNKNOWN")
    notes = body.get("notes") or []
    if not results:
        return "NO_RESULTS"
    return "NOT_CHECKED"


def scan_image_via_central(
    base: str,
    authorization: str,
    image_ref: str,
    *,
    creds: dict[str, Any],
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Prime an image in Central (same outcome as ``roxctl image scan``).

    Uses ``POST /v1/images/scan`` so lab-credentials Basic or Bearer auth both work.
    """
    import urllib.error
    import urllib.request

    # force=True so Central re-verifies against newly created Signature Integrations
    payload = json.dumps({"imageName": image_ref, "force": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/v1/images/scan",
        data=payload,
        method="POST",
        headers={
            "Authorization": _auth_header(authorization),
            "Content-Type": "application/json",
        },
    )
    context = ssl_context_for_central(creds)
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            body: Any = json.loads(raw) if raw else {}
            if response.status not in (200, 201):
                raise RuntimeError(
                    f"image scan failed for {image_ref} ({response.status}): {body}"
                )
            return body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        raise RuntimeError(
            f"image scan failed for {image_ref} ({exc.code}): {parsed}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"image scan unreachable for {image_ref}: {exc.reason}") from exc


def prime_signed_images(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    signed: list[str],
    integration_id: str,
    dry_run: bool,
) -> list[tuple[str, str]]:
    outcomes: list[tuple[str, str]] = []
    for ref in signed:
        if dry_run:
            print(f"dry-run: would Central image scan {ref}")
            outcomes.append((ref, "DRY_RUN"))
            continue
        print(f"scanning {ref} …")
        scanned = scan_image_via_central(base, authorization, ref, creds=creds)
        # Prefer verification from scan response; fall back to GET
        status = "UNKNOWN"
        for row in (scanned.get("signatureVerificationData") or {}).get("results") or []:
            if row.get("verifierId") == integration_id:
                status = str(row.get("status") or "UNKNOWN")
                break
        if status != "VERIFIED":
            status = verification_status_for(
                base,
                authorization,
                creds=creds,
                image_ref=ref,
                integration_id=integration_id,
            )
        if status != "VERIFIED":
            print(f"  verification status={status}; re-scanning …")
            scanned = scan_image_via_central(base, authorization, ref, creds=creds)
            status = "UNKNOWN"
            for row in (scanned.get("signatureVerificationData") or {}).get("results") or []:
                if row.get("verifierId") == integration_id:
                    status = str(row.get("status") or "UNKNOWN")
                    break
            if status != "VERIFIED":
                status = verification_status_for(
                    base,
                    authorization,
                    creds=creds,
                    image_ref=ref,
                    integration_id=integration_id,
                )
        print(f"  {ref} -> {status}")
        outcomes.append((ref, status))
        if status != "VERIFIED":
            raise RuntimeError(
                f"signed image not VERIFIED by '{INTEGRATION_NAME}': "
                f"{ref} (status={status})"
            )
    return outcomes


def prime_unsigned_contrast(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    unsigned: list[str],
    dry_run: bool,
) -> None:
    for ref in unsigned:
        if dry_run:
            print(f"dry-run: would Central image scan (contrast) {ref}")
            continue
        try:
            print(f"scanning contrast (unsigned) {ref} …")
            scan_image_via_central(base, authorization, ref, creds=creds)
            print(f"  contrast scan ok: {ref}")
        except RuntimeError as exc:
            print(f"  contrast scan skipped/failed (non-fatal): {exc}")


def delete_policy(
    base: str, authorization: str, *, creds: dict[str, Any], dry_run: bool
) -> str:
    existing = find_policy_by_name(base, authorization, POLICY_NAME, creds=creds)
    if not existing:
        msg = f"policy '{POLICY_NAME}' not found"
        print(msg)
        return msg
    if dry_run:
        msg = f"dry-run: would delete policy '{POLICY_NAME}' (id={existing.get('id')})"
        print(msg)
        return msg
    code, body = central_request(
        base,
        authorization,
        "DELETE",
        f"/v1/policies/{existing['id']}",
        creds=creds,
    )
    if code not in (200, 204):
        raise RuntimeError(f"delete policy failed ({code}): {body}")
    msg = f"deleted policy '{POLICY_NAME}' (id={existing.get('id')})"
    print(msg)
    return msg


def delete_integration(
    base: str, authorization: str, *, creds: dict[str, Any], dry_run: bool
) -> str:
    integrations = list_signature_integrations(base, authorization, creds=creds)
    existing = find_integration_by_name(integrations, INTEGRATION_NAME)
    if not existing:
        msg = f"integration '{INTEGRATION_NAME}' not found"
        print(msg)
        return msg
    if dry_run:
        msg = (
            f"dry-run: would delete Signature Integration '{INTEGRATION_NAME}' "
            f"(id={existing.get('id')})"
        )
        print(msg)
        return msg
    code, body = central_request(
        base,
        authorization,
        "DELETE",
        f"/v1/signatureintegrations/{existing['id']}",
        creds=creds,
    )
    if code not in (200, 204):
        raise RuntimeError(f"delete integration failed ({code}): {body}")
    msg = f"deleted Signature Integration '{INTEGRATION_NAME}' (id={existing.get('id')})"
    print(msg)
    return msg


def collect_hard_delete_inventory(
    base: str, authorization: str, *, creds: dict[str, Any]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pol = find_policy_by_name(base, authorization, POLICY_NAME, creds=creds)
    if pol:
        rows.append(
            {
                "kind": "policy",
                "name": POLICY_NAME,
                "id": str(pol.get("id") or ""),
            }
        )
    else:
        rows.append({"kind": "policy", "name": POLICY_NAME, "id": "(not found)"})
    integrations = list_signature_integrations(base, authorization, creds=creds)
    integ = find_integration_by_name(integrations, INTEGRATION_NAME)
    if integ:
        rows.append(
            {
                "kind": "signature-integration",
                "name": INTEGRATION_NAME,
                "id": str(integ.get("id") or ""),
            }
        )
    else:
        rows.append(
            {
                "kind": "signature-integration",
                "name": INTEGRATION_NAME,
                "id": "(not found)",
            }
        )
    return rows


def print_hard_delete_inventory(rows: list[dict[str, str]]) -> None:
    print("Hard-delete inventory (will be removed if confirmed):")
    for row in rows:
        print(f"  - {row['kind']}: {row['name']}  id={row['id']}")
    sys.stdout.flush()


def assess_status(
    base: str,
    authorization: str,
    *,
    creds: dict[str, Any],
    pem: str,
    signed: list[str],
) -> tuple[str, str, list[dict[str, Any]]]:
    auth_err = check_central_auth(base, authorization, creds=creds)
    if auth_err:
        sections = [
            {
                "group": "Central",
                "title": "Auth",
                "tag": "error",
                "body": auth_err,
                "bodyFormat": "prose",
            }
        ]
        return "error", auth_err, sections

    integrations = list_signature_integrations(base, authorization, creds=creds)
    integ = find_integration_by_name(integrations, INTEGRATION_NAME)
    integ_ok = integration_pem_ok(integ, pem)
    integ_id = (integ or {}).get("id") or ""

    pol = None
    if integ_id:
        listed = find_policy_by_name(base, authorization, POLICY_NAME, creds=creds)
        if listed:
            code, full = central_request(
                base,
                authorization,
                "GET",
                f"/v1/policies/{listed['id']}",
                creds=creds,
            )
            pol = full if code == 200 and isinstance(full, dict) else listed
    pol_ok = bool(integ_id) and policy_matches(pol, integ_id)

    image_rows: list[dict[str, str]] = []
    verified = 0
    if integ_id:
        for ref in signed:
            st = verification_status_for(
                base,
                authorization,
                creds=creds,
                image_ref=ref,
                integration_id=integ_id,
            )
            image_rows.append({"image": ref, "status": st})
            if st == "VERIFIED":
                verified += 1
    images_ok = verified >= 3 and verified == len(signed)

    sections = [
        {
            "group": "Signature integration",
            "title": INTEGRATION_NAME,
            "summary": "ok" if integ_ok else "needs-run",
            "tag": "ok" if integ_ok else "error",
            "body": {
                "name": INTEGRATION_NAME,
                "present": bool(integ),
                "id": integ_id or None,
                "pemFingerprintMatch": integ_ok,
                "keyLabel": KEY_LABEL,
            },
            "bodyFormat": "json",
        },
        {
            "group": "Policy",
            "title": POLICY_NAME,
            "summary": "ok" if pol_ok else "needs-run",
            "tag": "ok" if pol_ok else "error",
            "body": {
                "name": POLICY_NAME,
                "present": bool(pol),
                "id": (pol or {}).get("id"),
                "informBuildDeploy": pol_ok,
                "linkedIntegrationId": integ_id or None,
            },
            "bodyFormat": "json",
        },
        {
            "group": "Primed images",
            "title": "Signed digests",
            "summary": f"{verified}/{len(signed)} VERIFIED",
            "tag": "ok" if images_ok else "error",
            "body": {"images": image_rows},
            "bodyFormat": "json",
        },
    ]

    if integ_ok and pol_ok and images_ok:
        return (
            "ok",
            f"{INTEGRATION_NAME} + policy ready; {verified}/{len(signed)} signed images VERIFIED",
            sections,
        )
    missing: list[str] = []
    if not integ_ok:
        missing.append("integration")
    if not pol_ok:
        missing.append("policy")
    if not images_ok:
        missing.append(f"signed images ({verified}/{len(signed)} VERIFIED)")
    return "needs-run", "needs-run: " + ", ".join(missing), sections


def cmd_status(_: argparse.Namespace) -> int:
    try:
        pem = load_pub_pem()
        signed, _unsigned = load_image_list()
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        state, message, sections = assess_status(
            base, authorization, creds=creds, pem=pem, signed=signed
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
        pem = load_pub_pem()
        signed, unsigned = load_image_list()
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        auth_err = check_central_auth(base, authorization, creds=creds)
        if auth_err:
            emit_status_line("error", auth_err)
            return 1

        integ = ensure_integration(
            base, authorization, creds=creds, pem=pem, dry_run=dry_run
        )
        integ_id = str(integ.get("id") or "")
        if not dry_run and not integ_id:
            raise RuntimeError("missing integration id after ensure")

        if dry_run:
            ensure_policy(
                base,
                authorization,
                creds=creds,
                integration_id=integ_id or "(pending)",
                dry_run=True,
            )
            prime_signed_images(
                base,
                authorization,
                creds=creds,
                signed=signed,
                integration_id=integ_id or "(pending)",
                dry_run=True,
            )
            prime_unsigned_contrast(
                base,
                authorization,
                creds=creds,
                unsigned=unsigned,
                dry_run=True,
            )
            emit_status_line("ok", "dry-run only")
            return 0

        ensure_policy(
            base,
            authorization,
            creds=creds,
            integration_id=integ_id,
            dry_run=False,
        )
        prime_signed_images(
            base,
            authorization,
            creds=creds,
            signed=signed,
            integration_id=integ_id,
            dry_run=False,
        )
        prime_unsigned_contrast(
            base,
            authorization,
            creds=creds,
            unsigned=unsigned,
            dry_run=False,
        )

        state, message, sections = assess_status(
            base, authorization, creds=creds, pem=pem, signed=signed
        )
        emit_sections(sections)
        emit_status_line(state, message)
        return 0 if state == "ok" else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        emit_status_line("error", str(exc))
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    dry_run = bool(args.dry_run)
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        delete_policy(base, authorization, creds=creds, dry_run=dry_run)
        emit_status_line(
            "ok",
            "uninstalled policy only; Red Hat Public integration left in place"
            if not dry_run
            else "dry-run uninstall (policy only)",
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        emit_status_line("error", str(exc))
        return 1


def cmd_hard_delete_inventory(args: argparse.Namespace) -> int:
    """Print inventory for shell hard-delete flow (no mutations)."""
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        rows = collect_hard_delete_inventory(base, authorization, creds=creds)
        print_hard_delete_inventory(rows)
        # Machine-readable trailer for the shell
        print("ACS_HARD_DELETE_JSON=" + json.dumps({"items": rows}))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_hard_delete_apply(args: argparse.Namespace) -> int:
    """Delete policy + Red Hat Public after shell confirmation."""
    dry_run = bool(args.dry_run)
    try:
        creds = load_lab_credentials()
        base, authorization = central_connection(creds)
        delete_policy(base, authorization, creds=creds, dry_run=dry_run)
        delete_integration(base, authorization, creds=creds, dry_run=dry_run)
        emit_status_line(
            "ok",
            "hard-delete complete"
            if not dry_run
            else "dry-run hard-delete inventory applied as no-op deletes",
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        emit_status_line("error", str(exc))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Helper for module {MODULE_ID}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status")
    p_status.add_argument("--cli", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--cli", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_un = sub.add_parser("uninstall")
    p_un.add_argument("--dry-run", action="store_true")
    p_un.add_argument("--cli", action="store_true")
    p_un.set_defaults(func=cmd_uninstall)

    p_inv = sub.add_parser("hard-delete-inventory")
    p_inv.add_argument("--cli", action="store_true")
    p_inv.set_defaults(func=cmd_hard_delete_inventory)

    p_hd = sub.add_parser("hard-delete-apply")
    p_hd.add_argument("--dry-run", action="store_true")
    p_hd.add_argument("--cli", action="store_true")
    p_hd.set_defaults(func=cmd_hard_delete_apply)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
