/**
 * ACS demo setup GUI — PatternFly v5 (see REQUIREMENTS-GUI.md)
 */

const logEl = document.getElementById("log");
const modulesTbody = document.getElementById("modulesTbody");
const modSelectAll = document.getElementById("modSelectAll");
const modSelectionCount = document.getElementById("modSelectionCount");
const moduleBulkBar = document.getElementById("moduleBulkBar");
const modRefreshFeedback = document.getElementById("modRefreshFeedback");
const statusWrap = document.getElementById("statusWrap");
const statusRefreshIndicator = document.getElementById("statusRefreshIndicator");
const btnPreflightExpandAll = document.getElementById("btnPreflightExpandAll");
const credFilePath = document.getElementById("credFilePath");
const credSaveFeedback = document.getElementById("credSaveFeedback");

let registryModules = [];
let lastStatusModules = [];
let lastStatusMap = new Map();
let moduleMetaById = new Map();
let busy = false;

const fields = {
  centralOcpConsole: document.getElementById("centralOcpConsole"),
  centralOcpUser: document.getElementById("centralOcpUser"),
  centralOcpPassword: document.getElementById("centralOcpPassword"),
  centralConsole: document.getElementById("centralConsole"),
  centralApiToken: document.getElementById("centralApiToken"),
  centralApiTokenName: document.getElementById("centralApiTokenName"),
  centralApiTokenExpires: document.getElementById("centralApiTokenExpires"),
  centralAdminUser: document.getElementById("centralAdminUser"),
  centralAdminPassword: document.getElementById("centralAdminPassword"),
  securedSameAsCentral: document.getElementById("securedSameAsCentral"),
  securedOcpSection: document.getElementById("securedOcpSection"),
  securedOcpConsole: document.getElementById("securedOcpConsole"),
  securedOcpUser: document.getElementById("securedOcpUser"),
  securedOcpPassword: document.getElementById("securedOcpPassword"),
};

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function log(line) {
  if (!logEl) return;
  logEl.textContent += line;
  logEl.scrollTop = logEl.scrollHeight;
}

function logSection(title) {
  log(`\n── ${title} ${"─".repeat(Math.max(0, 48 - title.length))}\n`);
}

function parseStreamExitCode(line) {
  if (!line.startsWith("__EXIT__:")) return null;
  const code = Number(line.slice(9));
  return Number.isFinite(code) ? code : 1;
}

function clearLog() {
  if (logEl) logEl.textContent = "";
}

function setBusy(on) {
  busy = on;
  const ids = [
    "btnCredSave",
    "btnRefreshSelected",
    "btnRun",
    "btnDryRun",
    "btnRunFull",
    "btnStatus",
  ];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = on;
  }
}

function setCredFeedback(text, isError = false) {
  if (!credSaveFeedback) return;
  credSaveFeedback.textContent = text || "";
  credSaveFeedback.classList.toggle("cred-save-feedback--err", Boolean(isError));
}

function setModuleRefreshFeedback(text) {
  if (modRefreshFeedback) modRefreshFeedback.textContent = text || "";
}

function setStatusIndicator(text) {
  if (statusRefreshIndicator) {
    statusRefreshIndicator.textContent = text || "";
    statusRefreshIndicator.classList.toggle("status-refresh-loading", Boolean(text));
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function uiStateFromOrchestrator(state) {
  switch (state) {
    case "ok":
      return { ui: "ready", label: "Ready", badge: "module-status-badge--ready", icon: "✓" };
    case "error":
      return {
        ui: "blocked",
        label: "Error",
        badge: "module-status-badge--blocked",
        icon: "⚠",
      };
    case "needs-run":
    default:
      return {
        ui: "partial",
        label: "Needs run",
        badge: "module-status-badge--partial",
        icon: "◐",
      };
  }
}

function statusMapFromModules(modules) {
  const map = new Map();
  for (const row of modules || []) {
    if (!row?.id) continue;
    map.set(row.id, {
      state: row.state || "",
      message: row.message || "",
      sections: Array.isArray(row.sections) ? row.sections : [],
    });
  }
  return map;
}

function bindSelectableSummaries(root) {
  if (!root) return;
  root.querySelectorAll("details > summary").forEach((summary) => {
    let pointerDown = null;
    summary.addEventListener("pointerdown", (e) => {
      pointerDown = { x: e.clientX, y: e.clientY };
    });
    summary.addEventListener("click", (e) => {
      const selected = window.getSelection()?.toString() ?? "";
      const dragged =
        pointerDown &&
        (Math.abs(e.clientX - pointerDown.x) > 4 || Math.abs(e.clientY - pointerDown.y) > 4);
      pointerDown = null;
      if (selected.length > 0 || dragged) {
        e.preventDefault();
      }
    });
  });
}

function renderSectionBody(item) {
  const format = item.bodyFormat || "prose";
  const body = item.body ?? "";

  if (format === "json") {
    const text = typeof body === "string" ? body : JSON.stringify(body, null, 2);
    return `<pre class="status-section-body status-section-body--json">${escapeHtml(text)}</pre>`;
  }

  const text = typeof body === "string" ? body : String(body ?? "");
  const paragraphs = text
    .split(/\n\n+/)
    .filter(Boolean)
    .map(
      (paragraph) =>
        `<p class="status-section-body__p">${escapeHtml(paragraph).replace(/\n/g, "<br>")}</p>`
    )
    .join("");
  return `<div class="status-section-body status-section-body--prose">${paragraphs}</div>`;
}

function renderSectionsHtml(sections) {
  if (!Array.isArray(sections) || !sections.length) return "";

  let currentGroup = null;
  let html = '<div class="status-sections">';

  for (const item of sections) {
    const group = item.group || "";
    if (group && group !== currentGroup) {
      currentGroup = group;
      html += `<p class="status-sections__group">${escapeHtml(group)}</p>`;
    }

    const tagKey = item.tag || "";
    const tagText = item.tagLabel || item.tag || "";
    const tag = tagKey
      ? `<span class="status-section-tag status-section-tag--${escapeHtml(tagKey)}">${escapeHtml(tagText)}</span>`
      : "";
    const summary = item.summary
      ? `<span class="status-section-summary">${escapeHtml(item.summary)}</span>`
      : "";
    const body = renderSectionBody(item);

    html += `<details class="status-section-json pf-block">
      <summary class="pf-block__summary status-section-json__summary">
        ${tag}<span class="status-section-json__title">${escapeHtml(item.title || "Section")}</span>${summary}
      </summary>
      <div class="pf-block__body">
        ${body}
      </div>
    </details>`;
  }

  html += "</div>";
  return html;
}

function dependsOnHintHtml(m) {
  const deps = m.dependsOn;
  if (!Array.isArray(deps) || deps.length === 0) return "";
  return `<div class="module-deps-hint">Requires: ${deps.map(escapeHtml).join(", ")}</div>`;
}

function moduleLineHtml(m) {
  const label = String(m.label ?? m.id ?? "");
  const idx = m.number != null ? `${escapeHtml(String(m.number))}.` : "";
  const parts = label.split(/\s+—\s+/);
  if (parts.length >= 2) {
    return `<span class="module-line">
      <span class="module-line__idx">${idx}</span>
      <strong class="module-line__slug">${escapeHtml(parts[0].trim())}</strong>
      <span class="module-line__sep"> - </span>
      <span class="module-line__desc">${escapeHtml(parts.slice(1).join(" — ").trim())}</span>
    </span>`;
  }
  return `<span class="module-line">
    <span class="module-line__idx">${idx}</span>
    <strong class="module-line__slug">${escapeHtml(label.trim())}</strong>
  </span>`;
}

function moduleCellHtml(m) {
  return `${moduleLineHtml(m)}${dependsOnHintHtml(m)}<div class="js-deps-lock-hint module-deps-lock-hint" hidden></div>`;
}

function missingDeps(moduleId) {
  const meta = moduleMetaById.get(moduleId);
  if (!meta?.dependsOn?.length) return [];
  return meta.dependsOn.filter((dep) => lastStatusMap.get(dep)?.state !== "ok");
}

function badgeHtml(moduleId) {
  const st = lastStatusMap.get(moduleId);
  if (!st) {
    return `<span class="module-status-badge module-status-badge--pending">…</span>`;
  }
  const mapped = uiStateFromOrchestrator(st.state);
  const title = escapeHtml(st.message);
  return `<span class="module-status-badge ${mapped.badge}" title="${title}">
    <span class="module-status-badge__icon" aria-hidden="true">${mapped.icon}</span>
    ${escapeHtml(mapped.label)}
  </span>`;
}

function moduleStatusCellHtml(moduleId) {
  return `<div class="module-status-split module-status-split--badge-only">${badgeHtml(moduleId)}</div>`;
}

function getModuleCheckboxes() {
  return [...modulesTbody.querySelectorAll("input.js-mod-cb[type=checkbox]")];
}

function collectCheckboxById() {
  const m = new Map();
  for (const tr of modulesTbody.querySelectorAll("tr[data-module-id]")) {
    const id = tr.dataset.moduleId;
    const cb = tr.querySelector("input.js-mod-cb");
    if (id && cb) m.set(id, cb);
  }
  return m;
}

function prereqMet(depId, statusMap, cbById) {
  const st = statusMap.get(depId);
  if (st?.state === "ok") return true;
  const cb = cbById.get(depId);
  return Boolean(cb?.checked);
}

function syncDependencyLocks() {
  const cbById = collectCheckboxById();
  for (const [id, meta] of moduleMetaById) {
    const tr = modulesTbody.querySelector(`tr[data-module-id="${CSS.escape(id)}"]`);
    if (!tr) continue;
    const cb = tr.querySelector("input.js-mod-cb");
    const hint = tr.querySelector(".js-deps-lock-hint");
    if (!cb) continue;

    const missing = (meta.dependsOn || []).filter(
      (dep) => !prereqMet(dep, lastStatusMap, cbById)
    );
    if (missing.length) {
      cb.checked = false;
      cb.disabled = true;
      tr.classList.add("module-row--locked");
      if (hint) {
        hint.textContent = `Locked: needs ${missing.join(", ")} ready or selected.`;
        hint.hidden = false;
      }
    } else {
      cb.disabled = false;
      tr.classList.remove("module-row--locked");
      if (hint) hint.hidden = true;
    }
  }
}

function syncMasterCheckbox() {
  const all = getModuleCheckboxes();
  const enabled = all.filter((c) => !c.disabled);
  const checked = enabled.filter((c) => c.checked).length;
  const n = enabled.length;
  modSelectAll.checked = n > 0 && checked === n;
  modSelectAll.indeterminate = checked > 0 && checked < n;
  modSelectionCount.textContent = `${checked} of ${all.length} selected`;
  moduleBulkBar.classList.toggle("bulk-toolbar--has-selection", checked > 0);
}

function applySelectAll(on) {
  if (!on) {
    getModuleCheckboxes().forEach((c) => {
      c.checked = false;
    });
    syncDependencyLocks();
    syncMasterCheckbox();
    return;
  }
  for (let pass = 0; pass < 5; pass++) {
    let anyNew = false;
    for (const m of registryModules) {
      const tr = modulesTbody.querySelector(`tr[data-module-id="${CSS.escape(m.id)}"]`);
      const cb = tr?.querySelector("input.js-mod-cb");
      if (cb && !cb.disabled) {
        if (!cb.checked) anyNew = true;
        cb.checked = true;
      }
    }
    syncDependencyLocks();
    if (!anyNew) break;
  }
  syncMasterCheckbox();
}

function renderModuleRows() {
  if (!registryModules.length) {
    modulesTbody.innerHTML =
      '<tr class="pf-v5-c-table__tr"><td class="pf-v5-c-table__td module-row-td" colspan="2">No modules.</td></tr>';
    return;
  }

  modulesTbody.innerHTML = registryModules
    .map((m) => {
      const id = escapeHtml(m.id);
      return `<tr class="pf-v5-c-table__tr" data-module-id="${id}">
        <td class="pf-v5-c-table__td module-row-td module-module-col">
          <div class="module-row">
            <label class="module-row__check pf-v5-c-check">
              <input class="pf-v5-c-check__input js-mod-cb" type="checkbox" data-module-id="${id}" />
            </label>
            <div class="module-row__label-wrap">
              <label class="module-row__label" for="mod-cb-${id}">${moduleCellHtml(m)}</label>
            </div>
          </div>
        </td>
        <td class="pf-v5-c-table__td module-row-td module-status-col js-status-cell" data-module-id="${id}">
          ${moduleStatusCellHtml(m.id)}
        </td>
      </tr>`;
    })
    .join("");

  modulesTbody.querySelectorAll("input.js-mod-cb").forEach((cb) => {
    cb.id = `mod-cb-${cb.dataset.moduleId}`;
    cb.addEventListener("change", () => {
      syncDependencyLocks();
      syncMasterCheckbox();
    });
  });

  syncDependencyLocks();
  syncMasterCheckbox();
  refreshStatusCells();
}

function refreshStatusCells() {
  modulesTbody.querySelectorAll(".js-status-cell").forEach((td) => {
    const id = td.dataset.moduleId;
    if (id) td.innerHTML = moduleStatusCellHtml(id);
  });
}

function renderStatusModulesPanel() {
  if (!statusWrap) return;

  const modules = lastStatusModules.length ? lastStatusModules : registryModules;
  if (!modules.length) {
    statusWrap.innerHTML =
      '<p class="pf-v5-c-helper-text">No status yet. Click Refresh status.</p>';
    btnPreflightExpandAll.disabled = true;
    return;
  }

  statusWrap.innerHTML = modules
    .map((row) => {
      const id = row.id;
      const st = lastStatusMap.get(id);
      const msg = escapeHtml(st?.message || row.message || "—");
      const sectionsHtml = renderSectionsHtml(st?.sections || row.sections || []);
      const missing = missingDeps(id);
      const canRun = missing.length === 0;
      const lockHint = missing.length
        ? `<p class="module-deps-lock-hint">Requires ready: ${escapeHtml(missing.join(", "))}</p>`
        : "";
      const depsHint =
        Array.isArray(row.dependsOn) && row.dependsOn.length
          ? `<p class="module-deps-hint">Depends on: ${row.dependsOn.map(escapeHtml).join(", ")}</p>`
          : "";

      return `<details class="pf-block" data-module-id="${escapeHtml(id)}" open>
        <summary class="pf-block__summary module-block-summary">
          <span class="module-block-summary__label">${moduleLineHtml(row)}</span>
          <span class="module-block-summary__badge">${badgeHtml(id)}</span>
        </summary>
        <div class="pf-block__body">
          <p class="module-block-message">${msg}</p>
          ${sectionsHtml}
          ${depsHint}
          ${lockHint}
          <div class="demo-actions-row">
            <button type="button" class="pf-v5-c-button pf-m-primary js-mod-run" data-module-id="${escapeHtml(id)}" ${canRun ? "" : "disabled"}>Run</button>
            <button type="button" class="pf-v5-c-button pf-m-secondary js-mod-dry-run" data-module-id="${escapeHtml(id)}" ${canRun ? "" : "disabled"}>Dry run</button>
          </div>
        </div>
      </details>`;
    })
    .join("");

  btnPreflightExpandAll.disabled = false;

  bindSelectableSummaries(statusWrap);

  statusWrap.querySelectorAll(".js-mod-run").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      runModule(btn.dataset.moduleId, false).catch((err) => log(`\n${err.message}\n`));
    });
  });
  statusWrap.querySelectorAll(".js-mod-dry-run").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      runModule(btn.dataset.moduleId, true).catch((err) => log(`\n${err.message}\n`));
    });
  });
}

function setupExpandAll() {
  if (!btnPreflightExpandAll || !statusWrap) return;
  let expanded = false;
  btnPreflightExpandAll.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    expanded = !expanded;
    statusWrap.querySelectorAll("details.pf-block, details.status-section-json").forEach((d) => {
      d.open = expanded;
    });
    btnPreflightExpandAll.setAttribute(
      "aria-label",
      expanded ? "Collapse all modules" : "Expand all modules"
    );
  });
}

function selectedModuleIds() {
  return getModuleCheckboxes()
    .filter((c) => c.checked)
    .map((c) => c.dataset.moduleId)
    .filter(Boolean);
}

function topologicalRunOrder(ids) {
  const wanted = new Set(ids);
  const order = [];
  for (const m of registryModules) {
    if (wanted.has(m.id)) order.push(m.id);
  }
  return order;
}

async function fetchStatus(moduleIds = null) {
  const qs =
    moduleIds && moduleIds.length
      ? `?modules=${encodeURIComponent(moduleIds.join(","))}`
      : "";
  const data = await api(`/api/status${qs}`);
  if (!moduleIds) {
    lastStatusModules = data;
    lastStatusMap = statusMapFromModules(data);
    return;
  }
  const map = statusMapFromModules(lastStatusModules);
  for (const row of data) {
    map.set(row.id, {
      state: row.state,
      message: row.message,
      sections: Array.isArray(row.sections) ? row.sections : [],
    });
  }
  lastStatusModules = registryModules.map((m) => {
    const hit = data.find((r) => r.id === m.id);
    if (hit) return hit;
    return map.get(m.id)
      ? {
          ...m,
          state: map.get(m.id).state,
          message: map.get(m.id).message,
          sections: map.get(m.id).sections,
        }
      : { ...m, state: "needs-run", message: "not refreshed" };
  });
  lastStatusMap = statusMapFromModules(lastStatusModules);
}

async function refreshAllStatus() {
  setBusy(true);
  setStatusIndicator("Refreshing…");
  try {
    await fetchStatus();
    refreshStatusCells();
    renderStatusModulesPanel();
    setModuleRefreshFeedback("Status updated.");
  } finally {
    setBusy(false);
    setStatusIndicator("");
  }
}

async function refreshSelectedStatus() {
  const ids = selectedModuleIds();
  if (!ids.length) {
    setModuleRefreshFeedback("Select at least one module.");
    return;
  }
  setBusy(true);
  setStatusIndicator("Refreshing…");
  try {
    await fetchStatus(ids);
    refreshStatusCells();
    renderStatusModulesPanel();
    setModuleRefreshFeedback(`Refreshed ${ids.length} module(s).`);
  } finally {
    setBusy(false);
    setStatusIndicator("");
  }
}

async function executeModuleRun(moduleId, dryRun) {
  const res = await fetch(
    `/api/run/${encodeURIComponent(moduleId)}?dry_run=${dryRun}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  if (!res.body) {
    throw new Error("No response body from module run");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let exitCode = 1;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = pending.indexOf("\n")) !== -1) {
      const line = pending.slice(0, idx);
      pending = pending.slice(idx + 1);
      const parsedExit = parseStreamExitCode(line);
      if (parsedExit !== null) {
        exitCode = parsedExit;
      } else {
        log(`${line}\n`);
      }
    }
  }

  if (pending) {
    const parsedExit = parseStreamExitCode(pending);
    if (parsedExit !== null) {
      exitCode = parsedExit;
    } else {
      log(`${pending}\n`);
    }
  }

  log(`exit code: ${exitCode}\n`);
  return { ok: exitCode === 0, exit_code: exitCode };
}

async function runModule(moduleId, dryRun = false) {
  if (!moduleId) return;
  const label = dryRun ? "Dry run" : "Run";
  setBusy(true);
  logSection(`${label}: ${moduleId}`);

  try {
    await executeModuleRun(moduleId, dryRun);
    await fetchStatus([moduleId]);
    refreshStatusCells();
    renderStatusModulesPanel();
  } finally {
    setBusy(false);
  }
}

async function runModules(ids, dryRun = false) {
  if (!ids.length) {
    setModuleRefreshFeedback("Select at least one module.");
    return;
  }
  const order = topologicalRunOrder(ids);
  const label = dryRun ? "Dry run" : "Run";
  setBusy(true);
  clearLog();
  logSection(`${label}: ${order.join(", ")}`);

  try {
    for (const moduleId of order) {
      if (order.length > 1) {
        log(`\n[${moduleId}]\n`);
      }
      await executeModuleRun(moduleId, dryRun);
    }
    await fetchStatus();
    refreshStatusCells();
    renderStatusModulesPanel();
    getModuleCheckboxes().forEach((c) => {
      c.checked = false;
    });
    syncMasterCheckbox();
  } finally {
    setBusy(false);
  }
}

async function saveCredentials() {
  setCredFeedback("");
  try {
    await api("/api/credentials", {
      method: "POST",
      body: JSON.stringify(buildCredentialsPayload()),
    });
    await loadCredentials();
    setCredFeedback("Saved.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  }
}

function authPrefValue() {
  const selected = document.querySelector('input[name="centralAuthPref"]:checked');
  return selected?.value === "password" ? "password" : "apiToken";
}

function setAuthPref(value) {
  const radio = document.querySelector(
    `input[name="centralAuthPref"][value="${value === "password" ? "password" : "apiToken"}"]`
  );
  if (radio) radio.checked = true;
}

function setSecuredSectionVisible(same) {
  const section = fields.securedOcpSection;
  const inputs = [
    fields.securedOcpConsole,
    fields.securedOcpUser,
    fields.securedOcpPassword,
  ];
  section.hidden = same;
  section.classList.toggle("cred-subsection--muted", same);
  inputs.forEach((el) => {
    if (el) el.disabled = same;
  });
}

fields.securedSameAsCentral.addEventListener("change", () => {
  setSecuredSectionVisible(fields.securedSameAsCentral.checked);
  syncCredentialCopyButtons();
});

function copyIconHtml(name) {
  return `<span class="material-symbols-outlined cred-copy-btn__icon" aria-hidden="true">${name}</span>`;
}

function createCopyButton(getText, label) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cred-copy-btn";
  btn.setAttribute("aria-label", `Copy ${label}`);
  btn.innerHTML = copyIconHtml("content_copy");
  btn.addEventListener("click", async () => {
    const text = getText();
    if (!text?.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    btn.innerHTML = copyIconHtml("done");
    btn.classList.add("cred-copy-btn--ok");
    window.setTimeout(() => {
      btn.innerHTML = copyIconHtml("content_copy");
      btn.classList.remove("cred-copy-btn--ok");
    }, 1200);
  });
  return btn;
}

function setupCredentialCopyButtons() {
  const form = document.getElementById("credForm");
  if (!form || form.dataset.copyWired === "1") return;
  form.dataset.copyWired = "1";

  form.querySelectorAll("input.pf-v5-c-form-control").forEach((input) => {
    const wrap = document.createElement("div");
    wrap.className = "cred-field-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const label = input.labels?.[0]?.textContent?.trim() || "value";
    wrap.appendChild(createCopyButton(() => input.value, label));
    input.addEventListener("input", syncCredentialCopyButtons);
  });

  const pathLine = document.querySelector(".cred-path-line");
  if (pathLine && credFilePath && !pathLine.querySelector(".cred-copy-btn")) {
    pathLine.appendChild(
      createCopyButton(() => credFilePath.textContent || "", "credentials file path")
    );
  }

  syncCredentialCopyButtons();
}

function syncCredentialCopyButtons() {
  const form = document.getElementById("credForm");
  if (!form) return;
  form.querySelectorAll(".cred-field-wrap").forEach((wrap) => {
    const input = wrap.querySelector("input.pf-v5-c-form-control");
    const btn = wrap.querySelector(".cred-copy-btn");
    if (!input || !btn) return;
    btn.disabled = input.disabled || !input.value.trim();
  });
  const pathBtn = document.querySelector(".cred-path-line .cred-copy-btn");
  if (pathBtn && credFilePath) {
    const path = credFilePath.textContent?.trim();
    pathBtn.disabled = !path || path === "—";
  }
}

function buildCredentialsPayload() {
  return {
    centralCluster: {
      openshift: {
        consoleUrl: fields.centralOcpConsole.value,
        adminUsername: fields.centralOcpUser.value,
        adminPassword: fields.centralOcpPassword.value,
      },
      central: {
        consoleUrl: fields.centralConsole.value,
        apiToken: fields.centralApiToken.value,
        apiTokenName: fields.centralApiTokenName.value,
        apiTokenExpires: fields.centralApiTokenExpires.value,
        adminUsername: fields.centralAdminUser.value,
        adminPassword: fields.centralAdminPassword.value,
        authPreference: authPrefValue(),
      },
    },
    securedCluster: {
      sameAsCentralCluster: fields.securedSameAsCentral.checked,
      openshift: {
        consoleUrl: fields.securedOcpConsole.value,
        adminUsername: fields.securedOcpUser.value,
        adminPassword: fields.securedOcpPassword.value,
      },
    },
  };
}

async function loadCredentials() {
  const data = await api("/api/credentials");
  credFilePath.textContent = data.filePath || "lab-credentials.json";

  const cc = data.centralCluster;
  fields.centralOcpConsole.value = cc.openshift.consoleUrl || "";
  fields.centralOcpUser.value = cc.openshift.adminUsername || "";
  fields.centralOcpPassword.value = cc.openshift.adminPassword || "";

  fields.centralConsole.value = cc.central.consoleUrl || "";
  fields.centralApiToken.value = cc.central.apiToken || "";
  fields.centralApiTokenName.value = cc.central.apiTokenName || "";
  fields.centralApiTokenExpires.value = cc.central.apiTokenExpires || "";
  fields.centralAdminUser.value = cc.central.adminUsername || "";
  fields.centralAdminPassword.value = cc.central.adminPassword || "";
  setAuthPref(cc.central.authPreference);

  const sc = data.securedCluster;
  fields.securedSameAsCentral.checked = sc.sameAsCentralCluster !== false;
  setSecuredSectionVisible(fields.securedSameAsCentral.checked);
  fields.securedOcpConsole.value = sc.openshift.consoleUrl || "";
  fields.securedOcpUser.value = sc.openshift.adminUsername || "";
  fields.securedOcpPassword.value = sc.openshift.adminPassword || "";
  syncCredentialCopyButtons();
}

async function loadRegistry() {
  registryModules = await api("/api/modules");
  moduleMetaById = new Map(registryModules.map((m) => [m.id, m]));
  renderModuleRows();
}

document.getElementById("btnCredSave").addEventListener("click", saveCredentials);
document.getElementById("btnStatus").addEventListener("click", () => {
  refreshAllStatus().catch((e) => log(`\n${e.message}\n`));
});
document.getElementById("btnRefreshSelected").addEventListener("click", () => {
  refreshSelectedStatus().catch((e) => setModuleRefreshFeedback(e.message));
});
document.getElementById("btnRun").addEventListener("click", () => {
  runModules(selectedModuleIds(), false).catch((e) => log(`\n${e.message}\n`));
});
document.getElementById("btnDryRun").addEventListener("click", () => {
  runModules(selectedModuleIds(), true).catch((e) => log(`\n${e.message}\n`));
});
document.getElementById("btnRunFull").addEventListener("click", () => {
  const allIds = registryModules.map((m) => m.id);
  applySelectAll(true);
  runModules(allIds, false).catch((e) => log(`\n${e.message}\n`));
});
modSelectAll.addEventListener("change", () => applySelectAll(modSelectAll.checked));

setupExpandAll();

async function init() {
  try {
    setupCredentialCopyButtons();
    await loadRegistry();
    await loadCredentials();
    await refreshAllStatus();
  } catch (err) {
    log(`\n${err.message}\n`);
    modulesTbody.innerHTML =
      '<tr class="pf-v5-c-table__tr"><td class="pf-v5-c-table__td module-row-td" colspan="2">Failed to load.</td></tr>';
  }
}

init();
