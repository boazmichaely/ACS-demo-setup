# GUI requirements — look, feel, and interaction

Visual design and UX for the ACS demo setup web UI. **Functional** GUI behavior (API contract, secrets, localhost bind) stays in [REQUIREMENTS.md](REQUIREMENTS.md) §7.

Implementation target: **PatternFly v6** + **Project Felt** (`pf-v6-theme-felt`) + local layout CSS. Visual contract: `gui/static/mock-modern.html`. Recovery tag before this work: `snapshot-before-modern-gui`.

---

## 1. Design system

| ID | Requirement |
|----|-------------|
| G-LF-1 | **PatternFly v6** core + addons via CDN (`@patternfly/patternfly@6.6.0` or compatible). Use `pf-v6-c-*` components. |
| G-LF-2 | Root: `<html class="pf-v6-theme-felt">`. Optional dark: toggle `pf-v6-theme-dark` (Light / Dark / System in masthead; persist preference). |
| G-LF-3 | **Local stylesheet** (`gui/static/demo-setup.css`) is the single layout source of truth (shared with `mock-modern.html`). Prefer **PF6 Felt tokens** (`--pf-t--global--*`). |
| G-LF-4 | **Border radius:** use **md/sm** on tall panels, cards, folds, and Status blocks. **Pill** radius only on chips, labels, and small controls - never on tall containers (clips content). |
| G-LF-5 | Base font: browser default (`html { font-size: 100% }`). Do not invent a custom root scale. |
| G-LF-6 | **No external repo links** in UI copy; paths are local to the user's machine. |
| G-LF-7 | **Brand:** masthead logo (`favicon.png`) + title **"ACS demo setup"**. |
| G-LF-8 | **Favicon:** under `gui/static/`. |
| G-LF-9 | Live shell DOM uses `demo-*` layout classes matching the mock composition. Do not restyle a second legacy shell in parallel. |

---

## 2. Page layout

| ID | Requirement |
|----|-------------|
| G-LAY-1 | **Wide main column:** `max-width: min(1600px, 98vw)`, centered. |
| G-LAY-2 | Structure: `pf-v6-c-page pf-m-no-sidebar` → **`pf-v6-c-masthead`** → main → demo pad (stacked sections). |
| G-LAY-3 | Vertical order: **Lab credentials** → **Modules** card → **Status** card → **Log** drawer (fixed bottom). Active lab lives in the **masthead**, not a separate strip. |
| G-LAY-4 | Section titles use `pf-v6-c-card__title-text`. Prefer `pf-m-compact` cards. |
| G-LAY-5 | **Do not merge** Modules and Status into one card. Modules = select/run; Status = expandable detail. |

### Masthead

| Control | Behavior |
|---------|----------|
| Brand | Logo + ACS demo setup |
| Active lab | `<select>` changes **active lab only** (modules). Same rules as former lab strip (G-CRED-7). |
| oc chip | Visual OK / PROBLEM for active lab OpenShift (may be stub until wired to `--oc-status`). |
| Theme | Light / Dark / System toggle group |

---

## 3. Lab credentials (multi-lab)

Collapsible **"Lab credentials"** panel (**collapsed by default**). Schema **v2**: `activeLabId` + `labs[]`. See `config/lab-credentials.schema.json`.

| ID | Requirement |
|----|-------------|
| G-CRED-1 | Standalone collapsible - not controlled by Status expand-all. |
| G-CRED-2 | Toggle: left **3px brand accent**, chevron, title **"Lab credentials"**. |
| G-CRED-3 | Show **file path** + **copy** control. |
| G-CRED-4 | **Save** + inline feedback (`aria-live="polite"`). |
| G-CRED-5 | Blank password or API token on save **keeps** the existing value. |
| G-CRED-6 | **Skip TLS** maps to per-lab `insecureSkipTlsVerify`. |
| G-CRED-7 | **Active lab** only via masthead select. Does **not** change the credentials form. Disk-log `lab-switch`. |
| G-CRED-8 | Compact toolbar: **Edit** select, **Name**, **Add** / **Use as active** / **Delete**, **Skip TLS**. Delete confirms; disabled for active lab or sole lab. |
| G-CRED-9 | When Edit lab ≠ Active lab, show a clear **mismatch** hint. |
| G-CRED-10 | **Secrets are not masked** (`type="text"`). **Copy icons** on credential inputs (and file path). |

Central fold collapsed by default; Secured clusters open by default. SC rows are OpenShift logins under this Central - not module targets.

---

## 4. Modules card

| ID | Requirement |
|----|-------------|
| G-MOD-1 | Three-column table: **Module** \| **Description** \| **State**. |
| G-MOD-2 | Module cell: checkbox + `{n}. {slug}`; description in its own column. |
| G-MOD-3 | Dependency lock hint when deps block run (only after status is loaded). |
| G-MOD-4 | Bulk toolbar: Select all + count; highlight when selection &gt; 0. |
| G-MOD-5 | Status cell: badge (detail via title / Status jump). Pending **checking** while refresh runs. |
| G-MOD-6 | Badge mapping `ok` / `needs-run` / `error` (ready / needs-run / error). |
| G-MOD-7 | **Not installed** (no `modules/<id>.sh`): row **grayed out**, checkbox **disabled**, not selectable; badge **not installed**. Count selectable rows only in bulk toolbar. |
| G-MOD-8 | Actions: primary **Run selected**; secondary Dry run / Run full install / Refresh selected (quieter than primary). |

---

## 5. Status card

| ID | Requirement |
|----|-------------|
| G-STAT-1 | Card title **"Status"**; Refresh status + indicator. |
| G-STAT-2 | Outer Modules panel open by default; nested modules/sections collapsed initially. |
| G-STAT-3 | Expand-all toggles nested sections only. |
| G-STAT-4 | Nested `details.pf-block` with left accent. |
| G-STAT-5 | **Omit modules whose scripts are not installed** - they must not appear in Status. |

---

## 6. Log

| ID | Requirement |
|----|-------------|
| G-LOG-1 | **Bottom drawer** (collapsed bar with preview; expand for full console). Not a mid-page card as the primary presentation. |
| G-LOG-2 | Monospace stream; scrollable expanded panel. |
| G-LOG-3 | Append run/refresh output; delimit runs. |
| G-LOG-4 | `role="log"`. |
| G-LOG-5 | Tee to `logs/gui-YYYY-MM-DD.log` (3 calendar-day retention) - unchanged. |
| G-LOG-6 | Page-load: pane empty; disk gets `page-load` divider. |

---

## 7. Interaction and feedback

| ID | Requirement |
|----|-------------|
| G-UX-1 | Refresh status = all installed modules; Refresh selected = checked selectable modules. |
| G-UX-2 | Run selected in dependency order; confirm destructive modules (REQUIREMENTS R-GUI-5). |
| G-UX-3 | Disable controls while in flight. |
| G-UX-4 | Errors use danger colors; do not print secrets into the log stream from the GUI. |
| G-UX-5 | Keyboard: focusable controls, `focus-visible` outlines. |
| G-UX-6 | `demo-sr-only` for visually hidden labels. |

---

## 8. Assets

| Asset | Requirement |
|-------|-------------|
| PatternFly CSS | CDN 6.6.x `patternfly.min.css` + `patternfly-addons.min.css` |
| Material Symbols | `unfold_more`, `content_copy`, `done` |
| `demo-setup.css` | Layout/badge/collapsible; token-based (+ optional v5 bridge) |
| `mock-modern.html` | Visual contract until live matches; keep until port complete |
| Favicon | `gui/static/favicon.png` |

---

## 9. Compliance checklist

Milestone: **shell port** + not-installed module rules.

- [x] PatternFly v6 + Felt; theme toggle
- [x] Masthead with Active lab (+ oc chip stub OK)
- [x] Credentials collapsible; Active ≠ Edit preserved
- [x] Modules + Status as separate cards; Log drawer
- [x] No tall pill-radius panels
- [x] Functional APIs still work (REQUIREMENTS.md §7)
- [x] G-MOD-7 / G-STAT-5 (gray not-installed; omit from Status)

---

## 10. Follow-ups

| Area | Notes |
|------|--------|
| Not-installed modules | Enforce G-MOD-7 / G-STAT-5 in live `app.js` |
| oc chip | Wire to orchestrator `--oc-status` JSON or lightweight API |
| Module scripts | Real status when `modules/<id>.sh` exist |
| Destructive run confirm | Dialog when module documents destructive `--run` |
