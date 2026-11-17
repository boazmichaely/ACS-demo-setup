# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `users-part1-ocp`: default install creates the same HTPasswd users on Central OpenShift (`central-ocp`) and selected secured clusters (`secured-cluster`, policy `multi`) so Act 2 Central SSO matches Act 1 console users.
- Modules live in `modules/<id>/` with entrypoint `modules/<id>/<id>.sh` (hard cutover; no flat `modules/<id>.sh`). Shared Python stays in `lib/`; shared orch-flag snippets stay as `modules/_*.sh`. Recovery tag before this layout: `snapshot-pre-module-folders`.

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

[Unreleased]: https://github.com/boazmichaely/ACS-demo-setup/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.1
[0.1.0]: https://github.com/boazmichaely/ACS-demo-setup/releases/tag/v0.1.0
