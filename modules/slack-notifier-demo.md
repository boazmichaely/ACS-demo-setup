# Slack notifier demo

Feature: Central → Slack alerts  
Module: `slack-notifier`

## Before you start

- Lab credentials have working Central API access.
- Defaults in `config/slack-notifier.defaults.json` point at `#acs-demo-notifier` (or override name / webhook / channel URL in Lab credentials).

## What the module sets up

1. A Slack notifier in Central (Integrations → Notifier Integrations → Slack) named like `#acs-demo-notifier`.
2. On every `--run`, Central’s fixed Test message, then a second lab-context ping (lab name, Central host, secured cluster).
3. Attachment of that notifier to every Central policy with category **DEMO** (from modules such as `init-demo` and `signature-integration`). Status folds list each DEMO policy as wired or missing.

If DEMO policies are missing the category (older installs), re-run the policy modules first, then `slack-notifier --run`.

## Talk track (about 1 minute)

1. Open **Platform Configuration → Integrations → Notifier Integrations**. Show the Slack notifier and the webhook target channel.
2. Open a DEMO policy and show the Slack notifier attached under Notifiers.
3. Trigger a demo alert (or re-run the module) and open the Slack channel link from the module Status fold.
4. Optional: show Lab credentials → Slack notifier if you use a personal channel override.

## Commands

```bash
./modules/slack-notifier.sh --status
./modules/slack-notifier.sh --run
./modules/slack-notifier.sh --run --dry-run
./modules/slack-notifier.sh --uninstall
```
