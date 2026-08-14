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
  centralAdminUser: document.getElementById("centralAdminUser"),
  centralAdminPassword: document.getElementById("centralAdminPassword"),
  securedSameAsCentral: document.getElementById("securedSameAsCentral"),
  securedOcpSection: document.getElementById("securedOcpSection"),
  securedOcpConsole: document.getElementById("securedOcpConsole"),
  securedOcpUser: document.getElementById("securedOcpUser"),
  securedOcpPassword: document.getElementById("securedOcpPassword"),
};

const hints = {
  centralOcpPw: document.getElementById("centralOcpPwHint"),
  centralToken: document.getElementById("centralTokenHint"),
  centralAdminPw: document.getElementById("centralAdminPwHint"),
  securedOcpPw: document.getElementById("securedOcpPwHint"),
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
    });
  }
  return map;
}

function dependsOnHintHtml(m) {
  const deps = m.dependsOn;
  if (!Array.isArray(deps) || deps.length === 0) return "";
  return `<div class="module-deps-hint">Requires: ${deps.map(escapeHtml).join(", ")}</div>`;
}

function moduleCellHtml(m) {
  const label = String(m.label ?? "");
  const idx = m.number != null ? `${escapeHtml(String(m.number))}.` : "";
  const parts = label.split(/\s+—\s+/);
  let inner;
  if (parts.length >= 2) {
    inner = `<span class="module-line">
      <span class="module-line__idx">${idx}</span>
      <strong class="module-line__slug">${escapeHtml(parts[0].trim())}</strong>
      <span class="module-line__sep"> - </span>
      <span class="module-line__desc">${escapeHtml(parts.slice(1).join(" — ").trim())}</span>
    </span>`;
  } else {
    inner = `<span class="module-line">
      <span class="module-line__idx">${idx}</span>
      <strong class="module-line__slug">${escapeHtml(label.trim())}</strong>
    </span>`;
  }
  return `${inner}${dependsOnHintHtml(m)}<div class="js-deps-lock-hint module-deps-lock-hint" hidden></div>`;
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

function statusDetailHtml(moduleId) {
  const st = lastStatusMap.get(moduleId);
  const msg = st?.message ? escapeHtml(st.message) : "—";
  return `<div class="sc-overall">${msg}</div>`;
}

function moduleStatusCellHtml(moduleId) {
  return `<div class="module-status-split">
    <div class="module-status-split__badge">${badgeHtml(moduleId)}</div>
    <div class="module-status-split__detail">${statusDetailHtml(moduleId)}</div>
  </div>`;
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

function renderPreflightPanel() {
  if (!statusWrap) return;
  const modules = lastStatusModules;
  if (!modules.length) {
    statusWrap.innerHTML = '<p class="pf-v5-c-helper-text">No status yet. Click Refresh status.</p>';
    btnPreflightExpandAll.disabled = true;
    return;
  }

  let ok = 0;
  let needs = 0;
  let err = 0;
  for (const row of modules) {
    if (row.state === "ok") ok++;
    else if (row.state === "error") err++;
    else needs++;
  }

  let bannerClass = "ok";
  let bannerText = `All ${ok} module(s) ready.`;
  if (err > 0) {
    bannerClass = "bad";
    bannerText = `${err} module(s) in error, ${needs} need run, ${ok} ready.`;
  } else if (needs > 0) {
    bannerClass = "partial";
    bannerText = `${needs} module(s) need run, ${ok} ready.`;
  }

  const rows = modules
    .map((row) => {
      const mapped = uiStateFromOrchestrator(row.state);
      const okCell =
        row.state === "ok" ? "yes" : row.state === "error" ? "no" : "—";
      const okCls =
        row.state === "ok"
          ? "state-ready"
          : row.state === "error"
            ? "state-blocked"
            : "state-partial";
      return `<tr>
        <td>${escapeHtml(row.label || row.id)}</td>
        <td class="${okCls}">${escapeHtml(okCell)}</td>
        <td>${escapeHtml(row.message || "")}</td>
      </tr>`;
    })
    .join("");

  const blocks = modules
    .map((row) => {
      const mapped = uiStateFromOrchestrator(row.state);
      return `<details class="pf-block">
        <summary class="pf-block__summary">${escapeHtml(row.id)} · ${escapeHtml(mapped.label)}</summary>
        <div class="pf-block__body">
          <p>${escapeHtml(row.message || "—")}</p>
        </div>
      </details>`;
    })
    .join("");

  statusWrap.innerHTML = `
    <div class="pfBanner ${bannerClass}">${escapeHtml(bannerText)}</div>
    <table class="status compact preflight-checks">
      <thead><tr><th>Module</th><th>OK</th><th>Detail</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${blocks}
  `;

  btnPreflightExpandAll.disabled = false;
}

function setupExpandAll() {
  if (!btnPreflightExpandAll || !statusWrap) return;
  let expanded = false;
  btnPreflightExpandAll.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    expanded = !expanded;
    statusWrap.querySelectorAll("details.pf-block").forEach((d) => {
      d.open = expanded;
    });
    btnPreflightExpandAll.setAttribute(
      "aria-label",
      expanded ? "Collapse all sections" : "Expand all sections"
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
    map.set(row.id, { state: row.state, message: row.message });
  }
  lastStatusModules = registryModules.map((m) => {
    const hit = data.find((r) => r.id === m.id);
    if (hit) return hit;
    return map.get(m.id)
      ? { ...m, state: map.get(m.id).state, message: map.get(m.id).message }
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
    renderPreflightPanel();
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
    renderPreflightPanel();
    setModuleRefreshFeedback(`Refreshed ${ids.length} module(s).`);
  } finally {
    setBusy(false);
    setStatusIndicator("");
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
      logSection(`${label} ${moduleId}`);
      const result = await api(
        `/api/run/${encodeURIComponent(moduleId)}?dry_run=${dryRun}`,
        { method: "POST" }
      );
      if (result.stdout) log(`${result.stdout}\n`);
      if (result.stderr) log(`${result.stderr}\n`);
      log(`exit code: ${result.exit_code}\n`);
    }
    await fetchStatus();
    refreshStatusCells();
    renderPreflightPanel();
    getModuleCheckboxes().forEach((c) => {
      c.checked = false;
    });
    syncMasterCheckbox();
  } finally {
    setBusy(false);
  }
}

function secretHint(el, hasSecret, masked, label) {
  if (!el) return;
  if (hasSecret) {
    el.textContent = `${label} saved (${masked}). Leave blank to keep.`;
  } else if (label.includes("OCP")) {
    el.textContent = "Optional — leave blank if you use oc login.";
  } else {
    el.textContent = `No ${label.toLowerCase()} saved yet.`;
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
});

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
  fields.centralOcpPassword.value = "";
  secretHint(
    hints.centralOcpPw,
    cc.openshift.hasAdminPassword,
    cc.openshift.adminPasswordMasked,
    "OCP admin password"
  );

  fields.centralConsole.value = cc.central.consoleUrl || "";
  fields.centralApiToken.value = "";
  secretHint(
    hints.centralToken,
    cc.central.hasApiToken,
    cc.central.apiTokenMasked,
    "API token"
  );
  fields.centralAdminUser.value = cc.central.adminUsername || "";
  fields.centralAdminPassword.value = "";
  secretHint(
    hints.centralAdminPw,
    cc.central.hasAdminPassword,
    cc.central.adminPasswordMasked,
    "Central admin password"
  );
  setAuthPref(cc.central.authPreference);

  const sc = data.securedCluster;
  fields.securedSameAsCentral.checked = sc.sameAsCentralCluster !== false;
  setSecuredSectionVisible(fields.securedSameAsCentral.checked);
  fields.securedOcpConsole.value = sc.openshift.consoleUrl || "";
  fields.securedOcpUser.value = sc.openshift.adminUsername || "";
  fields.securedOcpPassword.value = "";
  secretHint(
    hints.securedOcpPw,
    sc.openshift.hasAdminPassword,
    sc.openshift.adminPasswordMasked,
    "OCP admin password"
  );
}

async function saveCredentials() {
  setCredFeedback("");
  try {
    await api("/api/credentials", {
      method: "POST",
      body: JSON.stringify(buildCredentialsPayload()),
    });
    fields.centralOcpPassword.value = "";
    fields.centralApiToken.value = "";
    fields.centralAdminPassword.value = "";
    fields.securedOcpPassword.value = "";
    await loadCredentials();
    setCredFeedback("Saved.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  }
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
