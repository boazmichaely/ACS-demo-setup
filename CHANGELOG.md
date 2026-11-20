# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-11-20

### Added

- `acs-lightspeed` module: OpenShift Lightspeed on Central OCP (Operator, LLM Secret, OLSConfig, ols-user binding, NetworkPolicy) plus RHACS 5.0 Lightspeed connectivity checks; lab Integration Secrets for the LLM API token; Risk URL in status summaries.

### Changed

- `splunk-TA`: pin Splunk Operator Helm chart / image / CRDs to **3.2.0**.

### Fixed

- `splunk-TA`: configure Splunk Web `tools.proxy.on` / `tools.proxy.base` for the OpenShift edge Route so browsers no longer hit an https↔http redirect loop.

## [0.1.2] - 2026-11-17

### Added

- Multi-secured-cluster (multi-SC) module contract: modules declare `impactPlanes` (`central-side`, `central-ocp`, `secured-cluster`); the orchestrator fans out OpenShift work when secured-cluster ids are passed.
- GUI secured-cluster picker for multi-SC runs; Modules **Type** column driven by `impactPlanes`; impact picker always lists Central and secured clusters (disabled rows fade when not applicable).
- `securedClusterPolicy` enforcement so modules can require single vs multi SC selection; ACSCS-safe paths for modules that must not touch Central OpenShift incorrectly.
- Native `splunk-TA` module (lab Splunk + RHACS Technical Add-on) with shared Markdown help rendering and demo notes.
- Status-fold ready summaries that include clickable HTTPS deep links where useful: `ms-demo` shop URL, `init-demo` DEMO-category violations, `slack-notifier` channel URL, `syslog-notifier` viewer Route, `compliance-operator` Central Coverage, `splunk-TA` Splunk Web.

### Changed

- Modules live in `modules/<id>/` with entrypoint `modules/<id>/<id>.sh` (hard cutover; no flat `modules/<id>.sh`). Shared Python stays in `lib/`; shared orch-flag snippets stay as `modules/_*.sh`. Pre-layout recovery tag: `snapshot-pre-module-folders`.
- OpenShift demo modules migrated onto multi-SC orchestrator flags; Usage/help documents the new flags; skeleton and templates updated for the plane contract.
- Impact plane naming clarified for ACS Cloud Service (ACSCS) (`central-ocp` vs `central-side` vs `secured-cluster`); Setup UI no longer exposes a separate Target cluster control (quiet soft-default SC remains).
- `users-part1-ocp`: default install creates the same HTPasswd users on Central OpenShift (`central-ocp`) and selected secured clusters (`secured-cluster`, policy `multi`) so Act 2 Central SSO matches Act 1 console users.
- Slack: webhook and channel URL are per-lab credentials only (shared webhook secret removed); Integration Secrets Save behavior tightened.
- Splunk TA: prefer Splunkbase `.spl` for the RHACS TA; demo notes and screenshot under `docs/images`; Configuration section heading for the talk track.
- Syslog notifier viewer and module templates improved; empty-array `set -u` safety in shell helpers.
- Virt VM demo talk track points at GitHub; unused redesign handoff doc removed.
- Module help/CLI polish across the catalog (normalized Usage, small UX fixes).

### Fixed

- Update nudge: server-side GitHub compare via `/api/version` (no browser→GitHub fetch); dismiss is page-load only.
- Help menu version is a link to that version’s GitHub Release notes.

## [0.1.1] - 2026-11-04

### Changed

- Help menu Markdown docs (README, adding-a-module, users demo script) open on GitHub’s rendered pages instead of the local marked.js viewer.
- Update-banner “Install instructions” links to the README on GitHub.
- Status folds field map stays local (interactive HTML).

## [0.1.0] - 2026-11-04

### Added

- Multi-lab credentials UI and orchestrated demo modules.
- Slack notifier with DEMO policy category wiring.
- Module-name jump to Status folds.
- Installed version in the Help menu and soft update nudge when a newer GitHub Release exists.
- Release workflow (`v*` tags → GitHub Release from this changelog).

[Unreleased]: https://github.com/boazmichaely/ACS-demo-setup/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.3
[0.1.2]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.2
[0.1.1]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.1
[0.1.0]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.0
