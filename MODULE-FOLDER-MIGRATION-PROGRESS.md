# Module folder migration - resume progress

**Plan:** `~/.cursor/plans/module_folder_migration_c85ecf0c.plan.md`  
**Started:** 2026-11-17  
**Recovery tag:** `snapshot-pre-module-folders` @ `15ba058`  
**URL:** https://github.com/boazmichaely/ACS-demo-setup/tree/snapshot-pre-module-folders

## Checklist

- [x] **Step 0 - GitHub backup** — tag `snapshot-pre-module-folders` @ `15ba058`
- [x] Flip resolver: `scripts/acs-setup.sh` + `gui/app.py` nested-only; HELP_DOCS paths
- [x] Migrate all 12 modules (git mv + ROOT/HELPER/LIB/ASSET/Python/demo URL fixes)
- [x] Docs/templates/static URLs + CHANGELOG
- [x] Verify: all 12 `--help` OK; all 12 `--status` OK; no flat `modules/<id>.sh` (only `_central_*.sh` at root); deleted `modules/test.sh`

## Verified status (2026-11-17)

| id | status |
| --- | --- |
| registries | ok |
| signature-integration | ok |
| compliance-operator | ok |
| virt-vm-demo | ok |
| ms-demo | ok |
| init-demo | ok |
| users-part1-ocp | ok |
| users-part2-oauth | ok |
| users-part3-acs | ok |
| slack-notifier | ok |
| syslog-notifier | ok |
| splunk-TA | ok |

## Notes

- Hard cutover complete locally; next: commit + push to `origin/main`.
- If reboot before push: working tree holds the migration; recovery still available via tag above.

## Last update

Verification green. Committing and pushing migration to GitHub.
