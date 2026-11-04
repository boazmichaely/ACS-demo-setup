# Signature integration demo (Red Hat Public)

Feature: ACS Cosign verification with Red Hat release key 3  
Module: `signature-integration`

## Before you start

- Lab credentials have working Central API access (token or admin password).
- Central can pull from Quay and `registry.access.redhat.com` (run `registries` on infra labs if pulls fail).

## What the module sets up

1. Signature Integration **Red Hat Public** (Cosign public key label `release-key-3`).
2. Inform policy **Images must be signed by Red Hat Public** (Build + Deploy, global).
3. Three signed images scanned into Central via the Central image-scan API (Verified by Red Hat Public), plus one unsigned contrast image for the talk track.

## Talk track (about 2–3 minutes)

1. Open **Platform Configuration → Integrations → Signature Integrations**. Show **Red Hat Public** and the release key 3 public key.
2. Open one primed image (for example UBI minimal or the OCP art-dev digest). Show **Verified** under Red Hat Public.
3. Open the Inform policy **Images must be signed by Red Hat Public**. Explain Build + Deploy, Inform only - unsigned images produce violations without blocking.
4. Contrast: show the unsigned nginx image (missing / failed verification) and any Inform violations for unsigned workloads.

## Commands

```bash
./modules/signature-integration.sh --status
./modules/signature-integration.sh --run
./modules/signature-integration.sh --uninstall          # policy only
./modules/signature-integration.sh --hard-delete        # interactive; type DELETE
```
