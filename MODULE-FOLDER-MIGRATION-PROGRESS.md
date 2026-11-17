# Module folder migration - resume progress

**Status: DONE** (2026-11-17)

**Plan:** `~/.cursor/plans/module_folder_migration_c85ecf0c.plan.md`  
**Recovery tag (pre-migration):** `snapshot-pre-module-folders` @ `15ba058`  
https://github.com/boazmichaely/ACS-demo-setup/tree/snapshot-pre-module-folders  

**Migration commit:** `3804bbf` on `main`  
https://github.com/boazmichaely/ACS-demo-setup/commit/3804bbf

## Checklist

- [x] Step 0 GitHub backup tag
- [x] Nested-only resolver (acs-setup + gui)
- [x] All 12 modules moved + path fixes
- [x] Docs/templates/static/CHANGELOG
- [x] Verify help + status for all 12
- [x] Pushed to `origin/main`

## Verified status

All 12 installed modules returned `ok` on `--status` after the cutover.

## Resume after reboot

Nothing left to do for this migration. If you need the old layout: check out or Download ZIP from `snapshot-pre-module-folders`.
