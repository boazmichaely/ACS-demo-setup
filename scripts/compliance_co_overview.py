#!/usr/bin/env python3
"""Compliance Operator cluster overview with RHACS origin discovery and curated JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
NS = os.environ.get("COMPLIANCE_OPERATOR_NAMESPACE", "openshift-compliance")

ACS_LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
ACS_LABEL_CREATED_BY = "app.kubernetes.io/created-by"
ACS_LABEL_NAME = "app.kubernetes.io/name"
ACS_OWNER_ANNOTATION = "owner"

SKIP_META_KEYS = frozenset({"resourceVersion", "generation", "managedFields", "uid"})


def run_oc(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["oc", *args],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None


def need_oc() -> None:
    if not run_oc("whoami"):
        print("error: oc not logged in", file=sys.stderr)
        raise SystemExit(1)


def section(title: str) -> None:
    print()
    print("═" * 62)
    print(f"  {title}")
    print("═" * 62)
    print()


def subsection(title: str, *, intro: str | None = None) -> None:
    print()
    print(f"── {title} ──")
    print()
    if intro:
        for line in intro.splitlines():
            print(f"  {line}")
        print()


def minor_heading(title: str) -> None:
    print(f"  · {title}")
    print()


def is_tty() -> bool:
    return sys.stdout.isatty()


TAG_INFO: dict[str, dict[str, str]] = {
    "acs": {
        "label": "RHACS sensor-managed",
        "summary": "RHACS sensor-managed CR",
        "marker": "ACS",
        "legend": (
            "RHACS sensor applied this object on the cluster "
            "(labels app.kubernetes.io/managed-by=sensor and app.kubernetes.io/name=stackrox, "
            "or created-by=sensor with owner=stackrox). "
            "Includes RHACS-owned ScanSetting/ScanSettingBinding CRs (not the cluster default)."
        ),
    },
    "acs-derived": {
        "label": "CO child of RHACS",
        "summary": "CO workload for RHACS schedule",
        "marker": "ACS-derived",
        "legend": (
            "Compliance Operator child (ComplianceSuite or ComplianceScan) created because an "
            "RHACS-managed ScanSettingBinding ran — linked by suite name or owner reference, "
            "but not directly labeled by the sensor."
        ),
    },
    "local": {
        "label": "local (not RHACS)",
        "summary": "Not RHACS-managed",
        "marker": "local",
        "legend": "On the cluster and not tied to RHACS (manual CO use or cluster defaults).",
    },
}


def tag_summary(tag: str) -> str | None:
    return TAG_INFO.get(tag, {}).get("summary")


TAG_LEGEND = {key: info["legend"] for key, info in TAG_INFO.items()}


def origin_marker(origin: str) -> str:
    marker = TAG_INFO.get(origin, {}).get("marker", origin)
    bracketed = f"[{marker}]"
    if origin in TAG_INFO and is_tty():
        return f"\033[1;33m{bracketed}\033[0m"
    return bracketed


def is_acs_sensor_managed(item: dict[str, Any]) -> bool:
    meta = item.get("metadata") or {}
    labels = meta.get("labels") or {}
    annotations = meta.get("annotations") or {}
    if labels.get(ACS_LABEL_MANAGED_BY) == "sensor" and labels.get(ACS_LABEL_NAME) == "stackrox":
        return True
    if labels.get(ACS_LABEL_CREATED_BY) == "sensor" and annotations.get(ACS_OWNER_ANNOTATION) == "stackrox":
        return True
    return False


NOISY_ANNOTATION_KEYS = frozenset(
    {
        "alm-examples",
        "kubectl.kubernetes.io/last-applied-configuration",
        "operatorframework.io/properties",
    }
)


def trim_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for key in ("name", "namespace", "creationTimestamp"):
        if meta.get(key):
            out[key] = meta[key]
    labels = meta.get("labels") or {}
    if labels:
        out["labels"] = labels
    annotations = {
        key: value
        for key, value in (meta.get("annotations") or {}).items()
        if key not in NOISY_ANNOTATION_KEYS
    }
    if annotations:
        out["annotations"] = annotations
    owners = meta.get("ownerReferences") or []
    if owners:
        out["ownerReferences"] = [
            {"kind": owner.get("kind"), "name": owner.get("name")}
            for owner in owners
            if owner.get("name")
        ]
    return out


def trim_conditions(conditions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cond in conditions or []:
        row = {
            key: cond[key]
            for key in ("type", "status", "reason", "message")
            if cond.get(key) not in (None, "")
        }
        if row:
            out.append(row)
    return out


def trim_status(status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    out: dict[str, Any] = {}
    for key in ("phase", "result", "errorMessage", "currentIndex"):
        if status.get(key) not in (None, ""):
            out[key] = status[key]
    conditions = trim_conditions(status.get("conditions"))
    if conditions:
        out["conditions"] = conditions
    return out or None


def trim_scan_setting(item: dict[str, Any]) -> dict[str, Any]:
    skip = {"metadata", "status", "kind", "apiVersion"}
    body = {key: value for key, value in item.items() if key not in skip}
    trimmed = {
        "apiVersion": item.get("apiVersion"),
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        **body,
    }
    status = trim_status(item.get("status"))
    if status:
        trimmed["status"] = status
    return trimmed


def trim_scan_setting_binding(item: dict[str, Any]) -> dict[str, Any]:
    skip = {"metadata", "status", "kind", "apiVersion"}
    body = {key: value for key, value in item.items() if key not in skip}
    trimmed = {
        "apiVersion": item.get("apiVersion"),
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        **body,
    }
    status = trim_status(item.get("status"))
    if status:
        trimmed["status"] = status
    return trimmed


def trim_compliance_suite(item: dict[str, Any]) -> dict[str, Any]:
    skip = {"metadata", "status", "kind", "apiVersion"}
    body = {key: value for key, value in item.items() if key not in skip}
    trimmed = {
        "apiVersion": item.get("apiVersion"),
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        **body,
    }
    status = trim_status(item.get("status"))
    if status:
        trimmed["status"] = status
    return trimmed


def trim_compliance_scan(item: dict[str, Any]) -> dict[str, Any]:
    skip = {"metadata", "status", "kind", "apiVersion"}
    body = {key: value for key, value in item.items() if key not in skip}
    trimmed = {
        "apiVersion": item.get("apiVersion"),
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        **body,
    }
    status = item.get("status") or {}
    status_out: dict[str, Any] = {}
    for key in ("phase", "result", "errorMessage"):
        if status.get(key) not in (None, ""):
            status_out[key] = status[key]
    conditions = trim_conditions(status.get("conditions"))
    if conditions:
        status_out["conditions"] = conditions
    if status_out:
        trimmed["status"] = status_out
    return trimmed


def trim_subscription(item: dict[str, Any]) -> dict[str, Any]:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    return {
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        "spec": {
            "name": spec.get("name"),
            "source": spec.get("source"),
            "sourceNamespace": spec.get("sourceNamespace"),
            "channel": spec.get("channel"),
            "installPlanApproval": spec.get("installPlanApproval"),
        },
        "status": {
            "state": status.get("state"),
            "currentCSV": status.get("currentCSV"),
            "installedCSV": status.get("installedCSV"),
        },
    }


def trim_csv(item: dict[str, Any]) -> dict[str, Any]:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    return {
        "kind": item.get("kind"),
        "metadata": trim_metadata(item.get("metadata")),
        "spec": {
            "displayName": spec.get("displayName"),
            "version": spec.get("version"),
            "provider": (spec.get("provider") or {}).get("name"),
        },
        "status": {
            "phase": status.get("phase"),
            "reason": status.get("reason"),
        },
    }


def trim_deployment(item: dict[str, Any], *, role: str) -> dict[str, Any]:
    spec = item.get("spec") or {}
    template = (spec.get("template") or {}).get("spec") or {}
    containers = []
    for container in template.get("containers") or []:
        containers.append(
            {
                "name": container.get("name"),
                "image": container.get("image"),
                "resources": container.get("resources"),
            }
        )
    meta = item.get("metadata") or {}
    status = item.get("status") or {}
    out: dict[str, Any] = {
        "kind": item.get("kind"),
        "role": role,
        "metadata": trim_metadata(meta),
        "replicas": spec.get("replicas"),
        "readyReplicas": status.get("readyReplicas"),
        "selector": (spec.get("selector") or {}).get("matchLabels"),
        "containers": containers,
    }
    labels = meta.get("labels") or {}
    if labels:
        out["deploymentLabels"] = labels
    bundle = labels.get("profile-bundle")
    if bundle:
        out["profileBundle"] = bundle
    return out


def deployment_role(name: str) -> str:
    if name == "compliance-operator":
        return "Compliance Operator controller (reconciles all CO CRs)"
    if name.endswith("-pp"):
        bundle = name.split("-", 1)[0]
        return f"Profile parser for {bundle!r} content bundle (populates Profile/Rule CRs)"
    return "Compliance Operator workload"


def get_list(resource: str) -> list[dict[str, Any]]:
    raw = run_oc("get", resource, "-n", NS, "-o", "json")
    if not raw:
        return []
    return json.loads(raw).get("items") or []


def secured_cluster_name_from_oc() -> str | None:
    for namespace in ("stackrox", "rhacs-operator"):
        raw = run_oc("get", "securedcluster", "-n", namespace, "-o", "json")
        if not raw:
            continue
        for item in json.loads(raw).get("items") or []:
            name = ((item.get("spec") or {}).get("clusterName") or "").strip()
            if name:
                return name
    return None


def central_context() -> tuple[str | None, str | None, str | None]:
    """Return (base_url, token, error_message)."""
    creds_path = os.environ.get("ACS_LAB_CREDENTIALS_FILE", "").strip()
    path = Path(creds_path).expanduser() if creds_path else ROOT / "lab-credentials.json"
    if not path.is_file():
        return None, None, f"no credentials file at {path}"

    sys.path.insert(0, str(ROOT))
    try:
        from lib.central import (  # noqa: WPS433
            central_api_base,
            central_api_token,
            check_central_auth,
            load_lab_credentials,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return None, None, f"could not import lib.central: {exc}"

    try:
        creds = load_lab_credentials(ROOT)
        base = central_api_base(creds)
        token = central_api_token(creds)
        auth_err = check_central_auth(base, token)
        if auth_err:
            return None, None, auth_err
        return base, token, None
    except Exception as exc:
        return None, None, str(exc)


def central_cluster_id(base: str, token: str, cluster_name: str) -> str | None:
    sys.path.insert(0, str(ROOT))
    from lib.central import central_request  # noqa: WPS433

    code, body = central_request(base, token, "GET", "/v1/clusters")
    if code != 200:
        return None
    for cluster in body.get("clusters") or []:
        if cluster.get("name") == cluster_name:
            return cluster.get("id")
    return None


def central_scan_configs(base: str, token: str) -> list[dict[str, Any]]:
    sys.path.insert(0, str(ROOT))
    from lib.central import central_request  # noqa: WPS433

    code, body = central_request(base, token, "GET", "/v2/compliance/scan/configurations")
    if code != 200:
        return []
    return body.get("configurations") or []


def config_targets_cluster(cfg: dict[str, Any], cluster_id: str) -> bool:
    clusters = cfg.get("clusters") or []
    if cluster_id in clusters:
        return True
    for row in cfg.get("clusterStatus") or []:
        if row.get("clusterId") == cluster_id:
            return True
    return False


def suite_names_for_scan(item: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    meta = item.get("metadata") or {}
    for owner in meta.get("ownerReferences") or []:
        if owner.get("kind") == "ComplianceSuite" and owner.get("name"):
            names.add(owner["name"])
    suite_label = (meta.get("labels") or {}).get("compliance.openshift.io/suite")
    if suite_label:
        names.add(suite_label)
    return names


def print_json_block(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def print_object_block(origin: str | None, data: dict[str, Any]) -> None:
    if origin:
        print(f"  {origin_marker(origin)}")
    for line in json.dumps(data, indent=2, sort_keys=True).splitlines():
        print(f"  {line}")
    print()


def make_section(
    group: str,
    title: str,
    body: Any,
    *,
    source: str | None = None,
    kind: str | None = None,
    api_type: str | None = None,
    tag: str | None = None,
    tag_label: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"group": group, "title": title, "body": body}
    if source:
        row["source"] = source
    if kind:
        row["kind"] = kind
    if api_type:
        row["apiType"] = api_type
    if tag:
        row["tag"] = tag
        label = tag_label or TAG_INFO.get(tag, {}).get("label")
        if label:
            row["tagLabel"] = label
    if summary:
        row["summary"] = summary
    return row


def make_co_section(
    group: str,
    kind: str,
    name: str,
    body: Any,
    *,
    tag: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    return make_section(
        group,
        f"{kind}/{name}",
        body,
        source="compliance-operator",
        kind=kind,
        tag=tag,
        summary=summary,
    )


def make_central_section(
    group: str,
    scan_name: str,
    body: Any,
    *,
    summary: str | None = None,
) -> dict[str, Any]:
    return make_section(
        group,
        f"ComplianceScanConfiguration/{scan_name}",
        body,
        source="rhacs-central",
        api_type="ComplianceScanConfiguration",
        tag="acs",
        summary=summary,
    )


def deploy_summary(item: dict[str, Any]) -> str:
    status = item.get("status") or {}
    ready = status.get("readyReplicas")
    replicas = (item.get("spec") or {}).get("replicas")
    if ready is not None and replicas is not None:
        return f"{ready}/{replicas} ready"
    return ""


def build_overview_sections() -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    if not run_oc("whoami"):
        return [make_section("Cluster", "OpenShift", {"error": "oc not logged in"})]

    server = (run_oc("whoami", "--show-server") or "?").strip()
    sections.append(
        make_section(
            "Context",
            "Cluster API",
            {"server": server, "namespace": NS, "time": datetime.now().astimezone().isoformat()},
        )
    )

    group_workloads = "1. Workloads"
    sections.append(
        make_section(
            group_workloads,
            "About workloads",
            {
                "intro": (
                    "Running operator machinery installed by OLM: Subscription, ClusterServiceVersion, "
                    "and Deployments (controller plus profile-parser pods)."
                )
            },
        )
    )

    subscriptions = get_list("subscription")
    compliance_subs = [
        item
        for item in subscriptions
        if "compliance" in ((item.get("metadata") or {}).get("name") or "").lower()
        or "compliance" in ((item.get("spec") or {}).get("name") or "").lower()
    ]
    for item in compliance_subs:
        name = (item.get("metadata") or {}).get("name", "?")
        body = trim_subscription(item)
        sections.append(
            make_section(
                group_workloads,
                f"Subscription/{name}",
                body,
                summary=(body.get("status") or {}).get("state"),
            )
        )

    csvs = get_list("csv")
    for item in csvs:
        if "compliance-operator" not in ((item.get("metadata") or {}).get("name") or ""):
            continue
        name = (item.get("metadata") or {}).get("name", "?")
        body = trim_csv(item)
        sections.append(
            make_section(
                group_workloads,
                f"ClusterServiceVersion/{name}",
                body,
                summary=(body.get("status") or {}).get("phase"),
            )
        )

    deployments = get_list("deploy")
    operator_deploy = [
        item for item in deployments if (item.get("metadata") or {}).get("name") == "compliance-operator"
    ]
    if operator_deploy:
        item = operator_deploy[0]
        name = (item.get("metadata") or {}).get("name", "?")
        sections.append(
            make_section(
                group_workloads,
                f"Deployment/{name}",
                trim_deployment(item, role=deployment_role(name)),
                summary=deploy_summary(item),
            )
        )

    for item in sorted(
        [row for row in deployments if ((row.get("metadata") or {}).get("name") or "").endswith("-pp")],
        key=lambda row: (row.get("metadata") or {}).get("name", ""),
    ):
        name = (item.get("metadata") or {}).get("name", "?")
        sections.append(
            make_section(
                group_workloads,
                f"Deployment/{name}",
                trim_deployment(item, role=deployment_role(name)),
                summary=deploy_summary(item),
            )
        )

    group_config = "2. CO configuration"
    sections.append(
        make_section(
            group_config,
            "About CO configuration",
            {
                "source": "compliance-operator",
                "intro": (
                    "Compliance Operator CRs on the secured cluster (not RHACS Central DB). "
                    "ScanSetting holds schedule/suite settings; ScanSettingBinding binds profiles. "
                    "RHACS sensor creates dedicated pairs (not cluster default). "
                    "Sensor-managed CRs are tagged [ACS]; other on-cluster config is [local]."
                ),
                "tagLegend": {key: TAG_LEGEND[key] for key in ("acs", "local")},
            },
            source="compliance-operator",
            summary="ScanSetting and ScanSettingBinding CRs",
        )
    )

    bindings = get_list("scansettingbinding")
    acs_schedule_names = {
        (item.get("metadata") or {}).get("name", "")
        for item in bindings
        if is_acs_sensor_managed(item)
    }
    acs_schedule_names.discard("")

    for item in sorted(get_list("scansetting"), key=lambda row: (row.get("metadata") or {}).get("name", "")):
        name = (item.get("metadata") or {}).get("name", "?")
        tag = "acs" if is_acs_sensor_managed(item) else "local"
        body = trim_scan_setting(item)
        sections.append(
            make_co_section(
                group_config,
                "ScanSetting",
                name,
                body,
                tag=tag,
                summary=tag_summary(tag)
                or (body.get("schedule") or body.get("ComplianceSuiteSettings", {}).get("Schedule") or ""),
            )
        )

    for item in sorted(bindings, key=lambda row: (row.get("metadata") or {}).get("name", "")):
        name = (item.get("metadata") or {}).get("name", "?")
        tag = "acs" if is_acs_sensor_managed(item) else "local"
        body = trim_scan_setting_binding(item)
        sections.append(
            make_co_section(
                group_config,
                "ScanSettingBinding",
                name,
                body,
                tag=tag,
                summary=tag_summary(tag),
            )
        )

    group_profiles = "3. Profile catalog"
    counts: dict[str, int] = {}
    for resource, label in {
        "profiles.compliance.openshift.io": "profiles",
        "rules.compliance.openshift.io": "rules",
        "tailoredprofiles.compliance.openshift.io": "tailoredProfiles",
        "benchmarks.compliance.openshift.io": "benchmarks",
    }.items():
        raw = run_oc("get", resource, "-n", NS, "--no-headers")
        counts[label] = len(raw.splitlines()) if raw else 0
    sections.append(
        make_section(
            group_profiles,
            "Counts",
            counts,
            summary="Profile, Rule, TailoredProfile, Benchmark CR totals",
        )
    )

    group_central = "4. RHACS Central"
    secured_name = secured_cluster_name_from_oc()
    base, token, central_err = central_context()
    cluster_id: str | None = None
    central_configs: list[dict[str, Any]] = []
    if base and token and secured_name:
        cluster_id = central_cluster_id(base, token, secured_name)
        if cluster_id:
            central_configs = [
                cfg for cfg in central_scan_configs(base, token) if config_targets_cluster(cfg, cluster_id)
            ]

    sections.append(
        make_section(
            group_central,
            "About RHACS Central",
            {
                "source": "rhacs-central",
                "apiType": "ComplianceScanConfiguration",
                "apiPath": "/v2/compliance/scan/configurations",
                "intro": (
                    "RHACS Central database objects (REST API, not Kubernetes CRs). "
                    "No kind field — type is ComplianceScanConfiguration; primary id is UUID, "
                    "display name is scanName. Sensor reconciles each config to on-cluster "
                    "ScanSetting + ScanSettingBinding CRs (group 2) with matching scanName."
                ),
                "securedClusterName": secured_name,
                "centralClusterId": cluster_id,
                "centralError": central_err,
            },
            source="rhacs-central",
            api_type="ComplianceScanConfiguration",
            summary="Central scan schedules (DB, not CRs)",
        )
    )

    for cfg in sorted(central_configs, key=lambda row: row.get("scanName") or ""):
        scan_name = cfg.get("scanName") or cfg.get("id") or "?"
        body = trim_central_scan_config(cfg, cluster_id)
        config_id = body.get("id") or "?"
        profiles = ", ".join(body.get("profiles") or []) or "no profiles"
        sections.append(
            make_central_section(
                group_central,
                scan_name,
                body,
                summary=f"id={config_id} · {profiles}",
            )
        )

    group_scan = "5. CO scan activity"
    sections.append(
        make_section(
            group_scan,
            "About CO scan activity",
            {
                "source": "compliance-operator",
                "intro": (
                    "Compliance Operator CRs created when a ScanSettingBinding runs. "
                    "ComplianceSuite orchestrates; ComplianceScan is per-profile execution. "
                    "Linked to RHACS Central by matching scanName (group 4). "
                    "CO children of an RHACS schedule are [ACS-derived]; other scans are [local]."
                ),
                "tagLegend": TAG_LEGEND,
                "acsScheduleNames": sorted(acs_schedule_names),
            },
            source="compliance-operator",
            summary="ComplianceSuite and ComplianceScan CRs",
        )
    )

    for item in sorted(get_list("compliancesuite"), key=lambda row: (row.get("metadata") or {}).get("name", "")):
        name = (item.get("metadata") or {}).get("name", "?")
        if is_acs_sensor_managed(item):
            tag = "acs"
        elif name in acs_schedule_names:
            tag = "acs-derived"
        else:
            tag = "local"
        body = trim_compliance_suite(item)
        status = body.get("status") or {}
        sections.append(
            make_co_section(
                group_scan,
                "ComplianceSuite",
                name,
                body,
                tag=tag,
                summary=" · ".join(
                    x for x in (tag_summary(tag), status.get("phase"), status.get("result")) if x
                ),
            )
        )

    for item in sorted(get_list("compliancescan"), key=lambda row: (row.get("metadata") or {}).get("name", "")):
        name = (item.get("metadata") or {}).get("name", "?")
        if is_acs_sensor_managed(item):
            tag = "acs"
        elif suite_names_for_scan(item) & acs_schedule_names or name in acs_schedule_names:
            tag = "acs-derived"
        else:
            tag = "local"
        body = trim_compliance_scan(item)
        status = body.get("status") or {}
        sections.append(
            make_co_section(
                group_scan,
                "ComplianceScan",
                name,
                body,
                tag=tag,
                summary=" · ".join(
                    x
                    for x in (
                        tag_summary(tag),
                        status.get("phase"),
                        status.get("result"),
                    )
                    if x
                ),
            )
        )

    return sections


def emit_sections_json() -> None:
    payload = {"sections": build_overview_sections()}
    print(f"ACS_SECTIONS_JSON={json.dumps(payload, separators=(',', ':'))}")


def print_checklist() -> None:
    section("What to watch (and what this script skips)")
    print("  Shown above — the objects that matter for RHACS + Compliance Operator demos:")
    print()
    print("  Group 1  Workloads (stays after OLM install)")
    print("           Subscription, CSV, compliance-operator Deployment,")
    print("           *-pp profile-parser Deployments")
    print()
    print("  Group 2  CO configuration (Compliance Operator CRs on cluster)")
    print("           ScanSetting, ScanSettingBinding")
    print()
    print("  Group 3  Profile catalog (content library; large, mostly static)")
    print("           Profile, Rule, TailoredProfile, Benchmark CR counts")
    print()
    print("  Group 4  RHACS Central (DB objects via REST API, not CRs)")
    print("           ComplianceScanConfiguration (GET /v2/compliance/scan/configurations)")
    print()
    print("  Group 5  CO scan activity (appears when a schedule runs)")
    print("           ComplianceSuite, ComplianceScan")
    print()
    print("  Origin tags:")
    print("    [ACS]          RHACS sensor applied the CR on-cluster")
    print("    [ACS-derived]  CO suite/scan spawned for an RHACS schedule")
    print("    [local]        On-cluster, not RHACS-managed")
    print()
    print("  Not listed here (usually too noisy or secondary for before/after compare):")
    print("    ComplianceCheckResult   per-check outcomes (hundreds per scan)")
    print("    ComplianceRemediation   auto-remediation objects")
    print("    Scan pods / *-rs Deployments   ephemeral scan workloads")
    print("    Result ConfigMaps       raw ARF/XCCDF blobs")
    print("    Individual Profile/Rule objects   use counts in group 3")
    print()
    print("  RHACS Central also holds aggregated compliance results (not on-cluster).")
    print()


def trim_central_scan_config(cfg: dict[str, Any], cluster_id: str | None) -> dict[str, Any]:
    scan_cfg = cfg.get("scanConfig") or {}
    config_id = cfg.get("id")
    out: dict[str, Any] = {
        "source": "rhacs-central",
        "apiType": "ComplianceScanConfiguration",
        "apiPath": f"/v2/compliance/scan/configurations/{config_id}" if config_id else None,
        "id": config_id,
        "scanName": cfg.get("scanName"),
        "profiles": scan_cfg.get("profiles") or [],
        "oneTimeScan": scan_cfg.get("oneTimeScan"),
        "description": scan_cfg.get("description"),
        "scanSchedule": scan_cfg.get("scanSchedule"),
        "clusters": cfg.get("clusters") or [],
    }
    cluster_status = []
    for row in cfg.get("clusterStatus") or []:
        if cluster_id and row.get("clusterId") != cluster_id:
            continue
        cluster_status.append(
            {
                "clusterId": row.get("clusterId"),
                "clusterName": row.get("clusterName"),
                "errors": row.get("errors") or [],
                "suiteStatus": row.get("suiteStatus"),
            }
        )
    if cluster_status:
        out["clusterStatus"] = cluster_status
    for key in ("createdTime", "lastUpdatedTime", "lastExecutedTime"):
        if cfg.get(key):
            out[key] = cfg.get(key)
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Compliance Operator cluster overview")
    parser.add_argument(
        "--sections-json",
        action="store_true",
        help="Emit ACS_SECTIONS_JSON=... for GUI module status",
    )
    args = parser.parse_args()
    if args.sections_json:
        emit_sections_json()
        return

    need_oc()
    sections = build_overview_sections()
    section(f"Compliance Operator overview — namespace: {NS}")
    print("Origin tags: [ACS] RHACS sensor-managed · [ACS-derived] CO child of RHACS · [local] other")
    print()

    current_group = None
    for row in sections:
        group = row.get("group") or ""
        if group != current_group:
            current_group = group
            if group:
                print()
                print(f"── {group} ──")
                print()
        tag = row.get("tag")
        minor_heading(row.get("title", "?"))
        print_object_block(tag, row.get("body") or {})

    print_checklist()
    section("Tips")
    print("  Compare before/after:")
    print("    ./scripts/compliance-co-overview.sh | tee /tmp/co-before.txt")
    print("    ./scripts/compliance-co-overview.sh | tee /tmp/co-after.txt")
    print()


if __name__ == "__main__":
    main()
