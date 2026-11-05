# Cutting a release

1. Move notes from `## [Unreleased]` into a new `## [X.Y.Z] - YYYY-MM-DD` section in [`CHANGELOG.md`](CHANGELOG.md).
2. Set [`VERSION`](VERSION) to `X.Y.Z` (no leading `v`).
3. Update changelog footer compare links if needed.
4. Commit on `main`.
5. Tag and push:

```bash
git tag "vX.Y.Z"
git push origin main
git push origin "vX.Y.Z"
```

6. Confirm the GitHub Release appears under
   [Releases](https://github.com/boazmichaely/ACS-demo-setup/releases)
   (created by [`.github/workflows/release.yml`](.github/workflows/release.yml)).

Mark experimental builds as **prerelease** in the GitHub UI so
`/releases/latest` (and the GUI update nudge) ignore them.

## Upgrade (users)

```bash
cd ~/code/acs-demo-setup   # or your clone path
git pull origin main
./serve.sh
```

Preview the update banner in the GUI without a newer release:
`http://127.0.0.1:8765/?updatePreview=1`
