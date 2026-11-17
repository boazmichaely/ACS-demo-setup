# Syslog notifier demo talk track

**Audience:** customer or field engineer who already knows ACS policies.  
**Goal:** show that ACS can forward alerts as **syslog/CEF** to any collector - here a tiny generic sink you control - without implying a specific SIEM product.

Catalog planes: `secured-cluster` (receiver + viewer) then `central-api` (notifier + Central Test).

## Setup (once)

```bash
./scripts/acs-setup.sh --run --module syslog-notifier \
  --secured-cluster-id <sc-id> --include-central
```

Or both planes in one process:

```bash
./modules/syslog-notifier.sh --run
```

`--status` prints the **Viewer Route URL**. Open that URL in a browser. Do not look for a new demo-setup button - Status is the deep link.

## 60–90 second script

1. **What syslog is**  
   Syslog is a protocol, not a product. Customers already run collectors (rsyslog, Splunk UF, QRadar, Elastic). ACS speaks that dialect so alerts land in the existing SOC pipeline.

2. **What ACS sends**  
   Platform Configuration → Integrations → Syslog. Format is **CEF** (Common Event Format) - structured, but not JSON. Point at our lab LoadBalancer host port `5140`, extra field `source=rhacs`.

3. **Prove the wire**  
   Click **Test** on the notifier (the module also runs Test on install). Refresh the viewer. You should see a new row within seconds.

4. **Read it properly**  
   Select the message: **raw CEF** above, **parsed header + extensions** below (same width). That is the contract a SIEM parser consumes. Drag the divider to give the list more or less room.

5. **Close**  
   In production this pod is replaced by their real collector. ACS configuration stays the same: host, port, facility, CEF, optional TLS later.

## Status vs viewer

| Surface | Shows |
| --- | --- |
| Module Status | Receiver health, syslog `host:5140`, **viewer URL**, notifier summary |
| Viewer UI | Ring of last 100 messages, raw + parsed, resizable list, clear buffer |

## Cleanup

```bash
./modules/syslog-notifier.sh --uninstall
```

Deletes the Syslog notifier and removes namespace `acs-syslog-demo`.

## Docs

- [Integrating by using the syslog protocol (RHACS)](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_security_for_kubernetes/4.11/html/integrating/integrate-using-syslog-protocol)
