# Splunk + RHACS Technology Add-on demo

Feature: Splunk SIEM lab with RHACS TA  
Module: `splunk-TA`

## Before you start

- Lab credentials have working OpenShift admin access (`oc` via this tool).
- [`helm`](https://helm.sh/docs/intro/install/) on PATH (on macOS: `brew install helm`).
- RHACS TA `.tgz` on disk (see [Install the Technology Add-on package](#install-the-technology-add-on-package) below).

## Install the Technology Add-on package

The add-on is **not** in this git repo (Splunkbase license). Download it yourself:

1. Open [Splunkbase app 5315 - Red Hat Advanced Cluster Security](https://splunkbase.splunk.com/app/5315) and sign in.
2. Download the Technology Add-on as a `.tgz` (keep Splunkbase’s filename).
3. Place it under `~/code/Splunk/` (or pass `--ta-dir`).

```bash
mkdir -p ~/code/Splunk
# copy the downloaded .tgz into ~/code/Splunk/
./modules/splunk-TA.sh --run
```

Stack only (no TA yet): `./modules/splunk-TA.sh --run --skip-ta`

Product reference: [RHACS 4.10 - Integrating with Splunk](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.10/html/integrating/integrate-with-splunk).

## What the module sets up

1. Namespace `splunk-demo`.
2. Splunk Operator (Helm) + Standalone Splunk Free + PVCs + Route `splunk-web`.
3. Installs the RHACS Technology Add-on into the Splunk pod from your local `.tgz`.

It does **not** configure Central endpoint, API token, or modular inputs in the Splunk UI - that is the talk track below.

## Talk track (about 2 minutes)

1. Open Splunk Web (URL from module Status → Splunk Web Route). Sign in as `admin` (password from the Standalone secret; `--help` shows the `oc get secret` command).
2. **Apps → Red Hat Advanced Cluster Security**.
3. **Configuration → Add-on Settings**: Central endpoint as `host:443` (no `https://` prefix unless the field help says otherwise). Paste an RHACS API token (Integrations → Authentication, Analyst / read).
4. **Create New Input** three times: ACS Compliance, ACS Vulnerability Management, ACS Violations (lab defaults for Violations: interval 60s, index `default`, checkpoint from `2000-01-01T00:00:00.000Z`).
5. Search: `index=* sourcetype="stackrox*"` after demo traffic / violations.

## Commands

```bash
./modules/splunk-TA.sh --help
./modules/splunk-TA.sh --status
./modules/splunk-TA.sh --run --dry-run
./modules/splunk-TA.sh --run
./modules/splunk-TA.sh --run --skip-ta
./modules/splunk-TA.sh --run --ta-dir /path/to/dir
./modules/splunk-TA.sh --uninstall --dry-run
./modules/splunk-TA.sh --uninstall
```

## Notes

- Uninstall removes Standalone, Helm release, and the namespace. Cluster-scoped Splunk Operator CRDs stay.
- Never commit passwords, API tokens, or the Splunkbase `.tgz`.
