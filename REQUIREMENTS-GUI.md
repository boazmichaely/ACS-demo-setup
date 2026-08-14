# GUI requirements — look, feel, and interaction

Visual design and UX for the ACS demo setup web UI. **Functional** GUI behavior (API contract, secrets, localhost bind) stays in [REQUIREMENTS.md](REQUIREMENTS.md) §7.

Implementation target: **PatternFly v5** + local layout CSS. The current custom-dark stub in `gui/static/` is **not** compliant; bring the UI in line with this document.

---

## 1. Design system

| ID | Requirement |
|----|-------------|
| G-LF-1 | **PatternFly v5** core + addons via CDN (`@patternfly/patternfly@5.4.2` or compatible patch). Use `pf-v5-c-*` components (page, card, table, form, button, check). |
| G-LF-2 | **Local stylesheet** (`gui/static/demo-setup.css` or equivalent) for layout and status styling only — use **PF design tokens** (`--pf-v5-global--*`), not ad hoc hex colors except where this doc specifies badge semantics. |
| G-LF-3 | Base font size **112.5%** on `html` for slightly larger, readable lab UI. |
| G-LF-4 | **No external repo links** in the UI copy; file paths shown are local paths on the **user's** machine. |
| G-LF-5 | **Title:** page heading **"ACS demo setup"** (`pf-v5-c-title`, bold, tight letter-spacing). |
| G-LF-6 | **Favicon:** RHACS-related icon served by the GUI backend (inline data URI or static asset under `gui/static/`). |

---

## 2. Page layout

| ID | Requirement |
|----|-------------|
| G-LAY-1 | **Wide main column:** header and content use `max-width: min(1600px, 98vw)`, centered. |
| G-LAY-2 | Structure: `pf-v5-c-page` → main → **header** (title only) → **demo pad** (stacked sections). |
| G-LAY-3 | Vertical order (top to bottom): **Lab credentials** → **Modules** card → **Status** card → **Log** card. |
| G-LAY-4 | Section titles use `pf-v5-c-card__title-text` — xl, bold. Card headers: title left, actions right, wrap on narrow viewports. |

---

## 3. Central credentials panel

Outer collapsible **"Lab credentials"** (`cred-panel`), **collapsed by default**. Inner layout: two **fieldset** blocks (Central cluster, Secured cluster). See `config/lab-credentials.schema.json` for the persisted JSON shape.

| ID | Requirement |
|----|-------------|
| G-CRED-1 | **Standalone collapsible** — not controlled by Status "expand all". |
| G-CRED-2 | Toggle: left **3px primary accent**, chevron, title **"Lab credentials"**. |
| G-CRED-3 | Show **file path** (`lab-credentials.json` or `ACS_LAB_CREDENTIALS_FILE`). |
| G-CRED-4 | **Save** + inline feedback (`Saved` / error), `aria-live="polite"`. |
| G-CRED-5 | Blank password or API token on save **keeps** the existing value; GET never returns raw secrets (masked hints only). |

### 3.1 Central cluster fieldset

| Block | Fields | UX |
|-------|--------|-----|
| **OpenShift** | Console URL, admin username, admin password | Subsection title "OpenShift". Hint: admin password **optional** if the user uses `oc login`. |
| **RHACS Central** | Console URL, API token (plain text), admin username, admin password | Subsection title "RHACS Central". Radio: **Prefer API token** vs **Prefer admin password** when both are set. |

Short hint under fieldset legend: *Where RHACS Central runs (management cluster).*

### 3.2 Secured cluster fieldset

| Control | Behavior |
|---------|----------|
| **Same OpenShift cluster as Central** | Checkbox, **checked by default**. When checked, Secured OpenShift fields are hidden/disabled. |
| **OpenShift** (when not same) | Console URL, admin username, admin password — same optional admin semantics as Central cluster OCP block. |

Short hint: *Cluster where the sensor runs, when different from Central.*

### 3.3 Layout notes

- Full-width credentials block above the Modules card (not a narrow sidebar).
- Use paired username/password on one row at `min-width: 640px`.
- When PatternFly is ported, map fieldsets to `pf-v5-c-form` / `pf-v5-c-card` per §1.

---

## 4. Modules card

| ID | Requirement |
|----|-------------|
| G-MOD-1 | **Two-column table** in a bordered scroll region: **Module** | **State · detail**. |
| G-MOD-2 | Each row: **checkbox** + one-line label: `{n}. {slug} — {description}` (index bold, slug bold, description muted). |
| G-MOD-3 | **Dependency hints** under label when `dependsOn` is non-empty (muted small text). **Lock hint** (red, bold) when a dependency is not satisfied and the row cannot run. |
| G-MOD-4 | **Bulk toolbar** above table: "Select all" checkbox, selection count (`N of M selected`). Toolbar background **highlights blue** when selection &gt; 0. |
| G-MOD-5 | **Status cell:** badge + optional detail column (split layout). Badge on the left; detail text separated by a vertical rule. |
| G-MOD-6 | **Status badge mapping** from orchestrator `ok` \| `needs-run` \| `error`: |

| Orchestrator state | Badge class | Label (examples) |
|--------------------|-------------|------------------|
| `ok` | `module-status-badge--ready` (green) | Ready / Installed |
| `needs-run` | `module-status-badge--partial` (gold) or `--absent` (grey) | Needs run / Not configured |
| `error` | `module-status-badge--blocked` (red) | Error / Blocked |

Additional badge styles for future use: `--deferred` (dashed), `--pending`, `--unknown` — keep CSS definitions.

| G-MOD-7 | **Actions row** below table (PF buttons, md size): **Refresh selected**, **Run selected** (primary), **Run full install** (secondary, tooltip with canonical module order). |
| G-MOD-8 | **Run full install** selects all modules in registry order (respecting dependencies for execution, not necessarily all checkboxes). |
| G-MOD-9 | Per-module **Dry run** may appear as secondary control on row or in actions when module supports it (see REQUIREMENTS §9 D-5). |

---

## 5. Status card (preflight and detail)

| ID | Requirement |
|----|-------------|
| G-STAT-1 | Card title **"Status"**; header action **"Refresh status"** (secondary) + **refresh indicator** text (`aria-live="polite"`). |
| G-STAT-2 | Outer **Preflight** panel: expandable `<details class="status-panel">`, **open by default**, same visual language as credentials (left accent, chevron). |
| G-STAT-3 | **Expand all** icon button in preflight summary (Material Symbols `unfold_more`), toggles nested sections only — does **not** toggle the outer panel. Disabled when no nested sections. |
| G-STAT-4 | Nested sections use `details.pf-block` — chevron via CSS, left accent, light grey body background. |
| G-STAT-5 | **Preflight checks table:** compact bordered table; fixed column widths for Name / OK / Detail; long text wraps in Detail column only. |
| G-STAT-6 | **Banners** for summary outcomes: `pfBanner` variants `ok` / `bad` / `partial` (green / red / gold). |
| G-STAT-7 | Module-specific breakdowns (e.g. secured-cluster levels, roxctl env consistency) render inside nested blocks when the status API provides structured detail — not required until those modules ship. |

---

## 6. Log card

| ID | Requirement |
|----|-------------|
| G-LOG-1 | Card title **"Log"**; body is a single **`demo-log`** pane (not a modal). |
| G-LOG-2 | **Dark monospace** stream: PF black-850 background, light text, `pre-wrap`, scrollable **`min-height: 12rem`**, **`max-height: 22rem`**. |
| G-LOG-3 | Append **stdout/stderr** from run and refresh operations; clear or separate runs with a visible delimiter (implementation choice). |
| G-LOG-4 | `role="log"` and `aria-label="Script output"`. |

---

## 7. Interaction and feedback

| ID | Requirement |
|----|-------------|
| G-UX-1 | **Refresh status** runs full status (all modules + preflight when implemented); **Refresh selected** runs status for checked modules only. |
| G-UX-2 | **Run selected** runs checked modules in dependency order; confirm before destructive modules (per REQUIREMENTS R-GUI-5). |
| G-UX-3 | Disable run/refresh controls while a request is in flight; show loading in refresh indicator. |
| G-UX-4 | Errors use PF danger colors (`.err`, red badges); never surface secrets in log (mask tokens). |
| G-UX-5 | **Keyboard:** focusable controls, `focus-visible` outline on expand-all button (primary color, 2px offset). |
| G-UX-6 | **Screen reader:** `demo-sr-only` class available for visually hidden labels. |

---

## 8. Assets and dependencies

| Asset | Requirement |
|-------|-------------|
| PatternFly CSS | CDN 5.4.2 `patternfly.min.css` + `patternfly-addons.css` |
| Material Symbols | Subset font for `unfold_more` only (Google Fonts link or local) |
| `demo-setup.css` | Port layout/badge/collapsible rules from prior lab GUI; keep token-based |
| Favicon | `favicon.png` / RHACS branding under `gui/static/` |

---

## 9. Compliance checklist

Milestone: **GUI shell** (module scripts may still be stubs).

- [x] PatternFly v5 loaded; no custom dark-theme replacement
- [x] Wide column layout (1600px / 98vw)
- [x] Credentials collapsible, collapsed by default, Save + feedback
- [x] Modules table with checkboxes, badges, bulk bar, action buttons (+ dry run)
- [x] Status card with preflight panel + expand-all
- [x] Log pane (not dialog-only)
- [x] Matches functional requirements in REQUIREMENTS.md §7 (API-backed)

---

## 10. Follow-ups

| Area | Notes |
|------|--------|
| Module scripts | Rows show real status when `modules/NN-*.sh` exist |
| Preflight depth | Extra nested breakdowns when status JSON adds structured fields (M3, M2) |
| Destructive run confirm | Dialog before run when module documents destructive `--run` |
