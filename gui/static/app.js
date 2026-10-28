/**
 * ACS demo setup GUI — PatternFly v6 + Felt (see REQUIREMENTS-GUI.md)
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
const activeLabSelect = document.getElementById("activeLabSelect");
const editLabSelect = document.getElementById("editLabSelect");
const labStripName = document.getElementById("labStripName");
const labStripHint = document.getElementById("labStripHint");
const securedClusterList = document.getElementById("securedClusterList");
const btnMakeActive = document.getElementById("btnMakeActive");
const btnDeleteLab = document.getElementById("btnDeleteLab");

let registryModules = [];
let lastStatusModules = [];
let lastStatusMap = new Map();
let moduleMetaById = new Map();
let busy = false;

/** In-memory v2 credentials document (activeLabId + labs[]). */
let credDoc = { activeLabId: "", labs: [] };
/** Lab id currently shown in the credentials form (independent of activeLabId). */
let editingLabId = "";
let labUiBusy = false;

const fields = {
  labName: document.getElementById("labName"),
  insecureSkipTlsVerify: document.getElementById("insecureSkipTlsVerify"),
  centralOcpConsole: document.getElementById("centralOcpConsole"),
  centralOcpUser: document.getElementById("centralOcpUser"),
  centralOcpPassword: document.getElementById("centralOcpPassword"),
  centralConsole: document.getElementById("centralConsole"),
  centralApiToken: document.getElementById("centralApiToken"),
  centralApiTokenName: document.getElementById("centralApiTokenName"),
  centralApiTokenExpires: document.getElementById("centralApiTokenExpires"),
  centralAdminUser: document.getElementById("centralAdminUser"),
  centralAdminPassword: document.getElementById("centralAdminPassword"),
};

function newId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyOpenshift() {
  return { consoleUrl: "", adminUsername: "", adminPassword: "" };
}

function emptySecuredCluster(name = "production") {
  return {
    id: newId(),
    name,
    sameAsCentralCluster: true,
    openshift: emptyOpenshift(),
  };
}

function emptyLab(name = "new-lab") {
  const sc = emptySecuredCluster("production");
  return {
    id: newId(),
    name,
    insecureSkipTlsVerify: false,
    centralCluster: {
      openshift: emptyOpenshift(),
      central: {
        consoleUrl: "",
        apiToken: "",
        apiTokenName: "",
        apiTokenExpires: "",
        adminUsername: "",
        adminPassword: "",
        authPreference: "apiToken",
      },
    },
    securedClusters: [sc],
    activeSecuredClusterId: sc.id,
  };
}

function labById(labId) {
  return (credDoc.labs || []).find((lab) => lab.id === labId) || null;
}

function activeLab() {
  return labById(credDoc.activeLabId) || (credDoc.labs || [])[0] || null;
}

function editingLab() {
  return labById(editingLabId) || activeLab();
}

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

function labContextLine(reason, summary) {
  const lab = activeLab();
  const meta = summary || summaryFromLab(lab) || {};
  const name = meta.name || lab?.name || lab?.id || "?";
  const host = meta.centralHost || hostOnly(
    ((lab?.centralCluster || {}).central || {}).consoleUrl || ""
  ) || "?";
  return `${reason} lab=${name} central=${host}`;
}

function logLabEvent(reason, summary) {
  logSection(labContextLine(reason, summary));
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
    "btnAddLab",
    "btnDeleteLab",
    "btnMakeActive",
    "btnAddSecuredCluster",
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
  if (activeLabSelect) activeLabSelect.disabled = on;
  if (editLabSelect) editLabSelect.disabled = on;
  if (!on) {
    syncMakeActiveButton();
    syncDeleteLabButton();
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

function sectionExpandKey(moduleId, index, title) {
  return `${moduleId}::${index}::${title || ""}`;
}

function captureStatusExpandState() {
  const moduleIds = new Set();
  const sectionKeys = new Set();
  if (!statusWrap) return { moduleIds, sectionKeys };

  statusWrap.querySelectorAll("details.pf-block[data-module-id]").forEach((mod) => {
    const moduleId = mod.dataset.moduleId;
    if (!moduleId) return;
    if (mod.open) moduleIds.add(moduleId);
    mod.querySelectorAll("details.status-section-json").forEach((sec, index) => {
      if (!sec.open) return;
      const title =
        sec.querySelector(".status-section-json__title")?.textContent?.trim() || "";
      sectionKeys.add(sectionExpandKey(moduleId, index, title));
    });
  });
  return { moduleIds, sectionKeys };
}

function applyStatusExpandState(state, { defaultModulesOpen = false } = {}) {
  if (!statusWrap) return;
  const moduleIds = state?.moduleIds;
  const sectionKeys = state?.sectionKeys;

  statusWrap.querySelectorAll("details.pf-block[data-module-id]").forEach((mod) => {
    const moduleId = mod.dataset.moduleId;
    if (!moduleId) return;
    if (moduleIds) {
      mod.open = moduleIds.has(moduleId);
    } else {
      mod.open = defaultModulesOpen;
    }
    mod.querySelectorAll("details.status-section-json").forEach((sec, index) => {
      const title =
        sec.querySelector(".status-section-json__title")?.textContent?.trim() || "";
      const key = sectionExpandKey(moduleId, index, title);
      sec.open = Boolean(sectionKeys && sectionKeys.has(key));
    });
  });
}

function renderSectionsHtml(sections, moduleId = "") {
  if (!Array.isArray(sections) || !sections.length) return "";

  let currentGroup = null;
  let html = '<div class="status-sections">';
  let index = 0;

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
    const title = item.title || "Section";
    const key = sectionExpandKey(moduleId, index, title);

    html += `<details class="status-section-json pf-block" data-section-key="${escapeHtml(key)}">
      <summary class="pf-block__summary status-section-json__summary">
        ${tag}<span class="status-section-json__title">${escapeHtml(title)}</span>${summary}
      </summary>
      <div class="pf-block__body">
        ${body}
      </div>
    </details>`;
    index += 1;
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
      '<tr class="pf-v6-c-table__tr"><td class="pf-v6-c-table__td module-row-td" colspan="2">No modules.</td></tr>';
    return;
  }

  modulesTbody.innerHTML = registryModules
    .map((m) => {
      const id = escapeHtml(m.id);
      return `<tr class="pf-v6-c-table__tr" data-module-id="${id}">
        <td class="pf-v6-c-table__td module-row-td module-module-col">
          <div class="module-row">
            <label class="module-row__check pf-v6-c-check">
              <input class="pf-v6-c-check__input js-mod-cb" type="checkbox" data-module-id="${id}" />
            </label>
            <div class="module-row__label-wrap">
              <label class="module-row__label" for="mod-cb-${id}">${moduleCellHtml(m)}</label>
            </div>
          </div>
        </td>
        <td class="pf-v6-c-table__td module-row-td module-status-col js-status-cell" data-module-id="${id}">
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
      '<p class="pf-v6-c-helper-text">No status yet. Click Refresh status.</p>';
    btnPreflightExpandAll.disabled = true;
    return;
  }

  const hadModules = Boolean(statusWrap.querySelector("details.pf-block[data-module-id]"));
  const savedExpand = hadModules ? captureStatusExpandState() : null;

  statusWrap.innerHTML = modules
    .map((row) => {
      const id = row.id;
      const st = lastStatusMap.get(id);
      const msg = escapeHtml(st?.message || row.message || "—");
      const sectionsHtml = renderSectionsHtml(st?.sections || row.sections || [], id);
      const missing = missingDeps(id);
      const canRun = missing.length === 0;
      const lockHint = missing.length
        ? `<p class="module-deps-lock-hint">Requires ready: ${escapeHtml(missing.join(", "))}</p>`
        : "";
      const depsHint =
        Array.isArray(row.dependsOn) && row.dependsOn.length
          ? `<p class="module-deps-hint">Depends on: ${row.dependsOn.map(escapeHtml).join(", ")}</p>`
          : "";

      return `<details class="pf-block" data-module-id="${escapeHtml(id)}">
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
            <button type="button" class="pf-v6-c-button pf-m-primary js-mod-run" data-module-id="${escapeHtml(id)}" ${canRun ? "" : "disabled"}>Run</button>
            <button type="button" class="pf-v6-c-button pf-m-secondary js-mod-dry-run" data-module-id="${escapeHtml(id)}" ${canRun ? "" : "disabled"}>Dry run</button>
          </div>
        </div>
      </details>`;
    })
    .join("");

  // Hard refresh / first paint: leave modules collapsed. Later refreshes keep user expand state.
  applyStatusExpandState(savedExpand, { defaultModulesOpen: false });

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
    const data = await persistEditingLab();
    applyCredentialsResponse(data, { keepEditingId: editingLabId });
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

function wrapInputWithCopy(input) {
  if (!input || input.closest(".cred-field-wrap")) return;
  const wrap = document.createElement("div");
  wrap.className = "cred-field-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const label = input.labels?.[0]?.textContent?.trim() || "value";
  wrap.appendChild(createCopyButton(() => input.value, label));
  input.addEventListener("input", syncCredentialCopyButtons);
}

function setupCredentialCopyButtons() {
  const form = document.getElementById("credForm");
  if (!form) return;

  form.querySelectorAll("input.pf-v6-c-form-control").forEach((input) => {
    wrapInputWithCopy(input);
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
    const input = wrap.querySelector("input.pf-v6-c-form-control");
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

function hostOnly(url) {
  return String(url || "")
    .replace(/^https?:\/\//i, "")
    .replace(/\/.*$/, "");
}

function scSubLabel(sc) {
  if (sc.sameAsCentralCluster) return "Same OpenShift as Central";
  return hostOnly(sc.openshift?.consoleUrl) || "needs OCP login";
}

function preferredScId(clusters) {
  const list = clusters || [];
  const same = list.find((sc) => sc.sameAsCentralCluster !== false);
  return (same || list[0] || {}).id || "";
}

function readSecuredClustersFromDom() {
  if (!securedClusterList) return [];
  return [...securedClusterList.querySelectorAll(".sc-row")].map((row) => {
    const id = row.dataset.scId || newId();
    const same = Boolean(row.querySelector(".js-sc-same")?.checked);
    return {
      id,
      name: (row.querySelector(".js-sc-name")?.value || row.querySelector(".js-sc-title")?.textContent || "")
        .trim() || "secured",
      sameAsCentralCluster: same,
      openshift: {
        consoleUrl: row.querySelector(".js-sc-console")?.value || "",
        adminUsername: row.querySelector(".js-sc-user")?.value || "",
        adminPassword: row.querySelector(".js-sc-password")?.value || "",
      },
    };
  });
}

function updateFoldMetas(lab) {
  const centralMeta = document.getElementById("centralFoldMeta");
  const scMeta = document.getElementById("scFoldMeta");
  const central = ((lab?.centralCluster || {}).central || {});
  const host = hostOnly(central.consoleUrl);
  const tokenBit = (central.apiToken || "").trim() ? "token set" : "no token";
  if (centralMeta) {
    centralMeta.textContent = host ? `${host} · ${tokenBit}` : tokenBit;
  }
  const clusters = lab?.securedClusters || [];
  const remote = clusters.filter((sc) => sc.sameAsCentralCluster === false).length;
  if (scMeta) {
    const n = clusters.length;
    scMeta.textContent = `${n} cluster${n === 1 ? "" : "s"}${remote ? ` · ${remote} remote` : ""}`;
  }
}

function renderSecuredClusters(lab) {
  if (!securedClusterList) return;
  const clusters = lab.securedClusters || [];

  securedClusterList.innerHTML = clusters
    .map((sc) => {
      const same = sc.sameAsCentralCluster !== false;
      const ocp = sc.openshift || emptyOpenshift();
      const badge = same
        ? `<span class="sc-row__badge">Same as Central</span>`
        : `<span class="sc-row__badge sc-row__badge--remote">Remote</span>`;
      const nameField = same
        ? ""
        : `<label class="sc-inline">
            <span class="sc-inline__label">Name</span>
            <input class="pf-v6-c-form-control sc-inline__input js-sc-name" type="text" value="${escapeHtml(sc.name || "")}" spellcheck="false" />
          </label>`;
      const ocpFields = same
        ? `<p class="sc-row__note">Uses Central OpenShift credentials above.</p>`
        : `<div class="sc-row__ocp">
            <div class="pf-v6-c-form__group">
              <label class="pf-v6-c-form__label">Console URL</label>
              <input class="pf-v6-c-form-control js-sc-console" type="url" value="${escapeHtml(ocp.consoleUrl || "")}" spellcheck="false" />
            </div>
            <div class="cred-form-row cred-form-row--pair">
              <div class="pf-v6-c-form__group">
                <label class="pf-v6-c-form__label">User</label>
                <input class="pf-v6-c-form-control js-sc-user" type="text" value="${escapeHtml(ocp.adminUsername || "")}" spellcheck="false" />
              </div>
              <div class="pf-v6-c-form__group">
                <label class="pf-v6-c-form__label">Password</label>
                <input class="pf-v6-c-form-control js-sc-password" type="text" value="${escapeHtml(ocp.adminPassword || "")}" placeholder="Optional if using oc login" spellcheck="false" />
              </div>
            </div>
          </div>`;
      return `<details class="sc-row" data-sc-id="${escapeHtml(sc.id)}">
        <summary class="sc-row__summary">
          <span class="sc-row__chev" aria-hidden="true"></span>
          <span class="sc-row__title js-sc-title">${escapeHtml(sc.name || "secured")}</span>
          ${badge}
          <span class="sc-row__sub js-sc-sub">${escapeHtml(scSubLabel(sc))}</span>
          <button type="button" class="pf-v6-c-button pf-m-plain sc-row__remove js-sc-remove"
            title="Remove secured cluster">Remove</button>
        </summary>
        <div class="sc-row__body">
          <div class="sc-row__top">
            ${nameField}
            <label class="pf-v6-c-check cred-same-cluster">
              <input class="pf-v6-c-check__input js-sc-same" type="checkbox"${same ? " checked" : ""} />
              <span class="pf-v6-c-check__label">Same as Central</span>
            </label>
          </div>
          ${ocpFields}
        </div>
      </details>`;
    })
    .join("");

  securedClusterList.querySelectorAll(".sc-row").forEach((row) => {
    bindSecuredClusterRow(row);
  });

  updateFoldMetas(lab);
  setupCredentialCopyButtons();
}

function refreshScRowChrome(row) {
  const sameCb = row.querySelector(".js-sc-same");
  const titleEl = row.querySelector(".js-sc-title");
  const subEl = row.querySelector(".js-sc-sub");
  const badgeEl = row.querySelector(".sc-row__badge");
  const same = Boolean(sameCb?.checked);
  const nameInput = row.querySelector(".js-sc-name");
  const name = (nameInput?.value || titleEl?.textContent || "").trim() || "secured";
  if (titleEl) titleEl.textContent = name;
  if (subEl) {
    subEl.textContent = scSubLabel({
      sameAsCentralCluster: same,
      openshift: { consoleUrl: row.querySelector(".js-sc-console")?.value || "" },
    });
  }
  if (badgeEl) {
    badgeEl.textContent = same ? "Same as Central" : "Remote";
    badgeEl.classList.toggle("sc-row__badge--remote", !same);
  }
  const lab = editingLab();
  if (lab) {
    lab.securedClusters = readSecuredClustersFromDom();
    lab.activeSecuredClusterId = preferredScId(lab.securedClusters);
    updateFoldMetas(lab);
  }
}

function wireScRowBodyControls(row) {
  const sameCb = row.querySelector(".js-sc-same");
  sameCb?.addEventListener("change", () => applyScSameToggle(row));
  row.querySelector(".js-sc-name")?.addEventListener("input", () => refreshScRowChrome(row));
  row.querySelector(".js-sc-console")?.addEventListener("input", () => refreshScRowChrome(row));
}

function applyScSameToggle(row) {
  const sameCb = row.querySelector(".js-sc-same");
  const titleEl = row.querySelector(".js-sc-title");
  const body = row.querySelector(".sc-row__body");
  if (!body || !sameCb) return;

  const same = Boolean(sameCb.checked);
  const name =
    (row.querySelector(".js-sc-name")?.value || titleEl?.textContent || "").trim() || "secured";
  const ocp = {
    consoleUrl: row.querySelector(".js-sc-console")?.value || "",
    adminUsername: row.querySelector(".js-sc-user")?.value || "",
    adminPassword: row.querySelector(".js-sc-password")?.value || "",
  };

  if (same) {
    body.innerHTML = `
      <div class="sc-row__top">
        <label class="pf-v6-c-check cred-same-cluster">
          <input class="pf-v6-c-check__input js-sc-same" type="checkbox" checked />
          <span class="pf-v6-c-check__label">Same as Central</span>
        </label>
      </div>
      <p class="sc-row__note">Uses Central OpenShift credentials above.</p>`;
  } else {
    body.innerHTML = `
      <div class="sc-row__top">
        <label class="sc-inline">
          <span class="sc-inline__label">Name</span>
          <input class="pf-v6-c-form-control sc-inline__input js-sc-name" type="text" value="${escapeHtml(name)}" spellcheck="false" />
        </label>
        <label class="pf-v6-c-check cred-same-cluster">
          <input class="pf-v6-c-check__input js-sc-same" type="checkbox" />
          <span class="pf-v6-c-check__label">Same as Central</span>
        </label>
      </div>
      <div class="sc-row__ocp">
        <div class="pf-v6-c-form__group">
          <label class="pf-v6-c-form__label">Console URL</label>
          <input class="pf-v6-c-form-control js-sc-console" type="url" value="${escapeHtml(ocp.consoleUrl)}" spellcheck="false" />
        </div>
        <div class="cred-form-row cred-form-row--pair">
          <div class="pf-v6-c-form__group">
            <label class="pf-v6-c-form__label">User</label>
            <input class="pf-v6-c-form-control js-sc-user" type="text" value="${escapeHtml(ocp.adminUsername)}" spellcheck="false" />
          </div>
          <div class="pf-v6-c-form__group">
            <label class="pf-v6-c-form__label">Password</label>
            <input class="pf-v6-c-form-control js-sc-password" type="text" value="${escapeHtml(ocp.adminPassword)}" placeholder="Optional if using oc login" spellcheck="false" />
          </div>
        </div>
      </div>`;
  }

  row.open = true;
  wireScRowBodyControls(row);
  refreshScRowChrome(row);
  setupCredentialCopyButtons();
}

function bindSecuredClusterRow(row) {
  wireScRowBodyControls(row);
  row.querySelector(".js-sc-remove")?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const rows = securedClusterList.querySelectorAll(".sc-row");
    if (rows.length <= 1) {
      setCredFeedback("Keep at least one secured cluster.", true);
      return;
    }
    row.remove();
    const lab = editingLab();
    if (lab) {
      lab.securedClusters = readSecuredClustersFromDom();
      lab.activeSecuredClusterId = preferredScId(lab.securedClusters);
      updateFoldMetas(lab);
    }
  });
}

function summaryFromLab(lab) {
  if (!lab) return null;
  let centralHost = "";
  try {
    let cu = ((lab.centralCluster || {}).central || {}).consoleUrl || "";
    if (cu) {
      if (!/^https?:\/\//i.test(cu)) cu = `https://${cu}`;
      centralHost = new URL(cu).hostname || cu;
    }
  } catch {
    centralHost = "";
  }
  return {
    name: lab.name || lab.id || "",
    centralHost,
  };
}

function updateLabStrip(summary) {
  const lab = activeLab();
  const meta = summary || summaryFromLab(lab);
  const name = meta?.name || lab?.name || lab?.id || "—";
  if (labStripName) labStripName.textContent = name;
  if (labStripHint) {
    const host = meta?.centralHost || "";
    labStripHint.textContent = host ? `Central · ${host}` : "";
  }
}

function syncMakeActiveButton() {
  if (!btnMakeActive) return;
  const same = Boolean(editingLabId) && editingLabId === credDoc.activeLabId;
  btnMakeActive.disabled = busy || labUiBusy || same || !editingLabId;
  btnMakeActive.textContent = same ? "Already active" : "Use as active";
}

function syncDeleteLabButton() {
  if (!btnDeleteLab) return;
  const labs = credDoc.labs || [];
  const editingIsActive =
    Boolean(editingLabId) && editingLabId === credDoc.activeLabId;
  let reason = "";
  if (labs.length <= 1) {
    reason = "Keep at least one lab.";
  } else if (editingIsActive) {
    reason = "Switch active to another lab before deleting this one.";
  }
  btnDeleteLab.disabled = busy || labUiBusy || Boolean(reason);
  btnDeleteLab.title = reason || "Delete the lab being edited";
}

function fillLabSelects() {
  const labs = credDoc.labs || [];
  const options = labs
    .map(
      (lab) =>
        `<option value="${escapeHtml(lab.id)}">${escapeHtml(lab.name || lab.id)}</option>`
    )
    .join("");

  if (activeLabSelect) {
    activeLabSelect.innerHTML = options;
    activeLabSelect.value = credDoc.activeLabId || labs[0]?.id || "";
  }
  if (editLabSelect) {
    editLabSelect.innerHTML = options;
    editLabSelect.value = editingLabId || credDoc.activeLabId || labs[0]?.id || "";
  }
  syncMakeActiveButton();
  syncDeleteLabButton();
}

function fillEditingLabForm() {
  const lab = editingLab();
  if (!lab) return;
  editingLabId = lab.id;

  if (fields.labName) fields.labName.value = lab.name || "";
  if (fields.insecureSkipTlsVerify) {
    fields.insecureSkipTlsVerify.checked = Boolean(lab.insecureSkipTlsVerify);
  }

  const cc = lab.centralCluster || {};
  const ocp = cc.openshift || emptyOpenshift();
  const central = cc.central || {};

  fields.centralOcpConsole.value = ocp.consoleUrl || "";
  fields.centralOcpUser.value = ocp.adminUsername || "";
  fields.centralOcpPassword.value = ocp.adminPassword || "";

  fields.centralConsole.value = central.consoleUrl || "";
  fields.centralApiToken.value = central.apiToken || "";
  fields.centralApiTokenName.value = central.apiTokenName || "";
  fields.centralApiTokenExpires.value = central.apiTokenExpires || "";
  fields.centralAdminUser.value = central.adminUsername || "";
  fields.centralAdminPassword.value = central.adminPassword || "";
  setAuthPref(central.authPreference);

  const centralFold = document.getElementById("centralFold");
  if (centralFold) centralFold.open = false;

  renderSecuredClusters(lab);
  updateFoldMetas(lab);
  syncCredentialCopyButtons();
  syncMakeActiveButton();
  syncDeleteLabButton();
}

function buildCredentialsPayload() {
  const lab = editingLab() || emptyLab();
  const scRows = readSecuredClustersFromDom();
  const activeSc = preferredScId(scRows) || lab.activeSecuredClusterId;

  const updatedLab = {
    id: lab.id,
    name: (fields.labName?.value || lab.name || lab.id).trim(),
    insecureSkipTlsVerify: Boolean(fields.insecureSkipTlsVerify?.checked),
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
    securedClusters: scRows,
    activeSecuredClusterId: activeSc,
  };

  const labs = (credDoc.labs || []).map((existing) =>
    existing.id === updatedLab.id ? updatedLab : existing
  );
  if (!labs.some((l) => l.id === updatedLab.id)) {
    labs.push(updatedLab);
  }

  return {
    activeLabId: credDoc.activeLabId || updatedLab.id,
    labs,
  };
}

function applyCredentialsResponse(data, { keepEditingId } = {}) {
  credFilePath.textContent = data.filePath || "lab-credentials.json";
  credDoc = {
    activeLabId: data.activeLabId || "",
    labs: Array.isArray(data.labs) ? data.labs : [],
  };
  if (!credDoc.labs.length) {
    const lab = emptyLab("default");
    credDoc = { activeLabId: lab.id, labs: [lab] };
  }
  if (keepEditingId && labById(keepEditingId)) {
    editingLabId = keepEditingId;
  } else if (!labById(editingLabId)) {
    editingLabId = credDoc.activeLabId || credDoc.labs[0].id;
  }
  fillLabSelects();
  fillEditingLabForm();
  updateLabStrip(data.activeLabSummary);
}

async function loadCredentials() {
  const data = await api("/api/credentials");
  editingLabId = data.activeLabId || data.labs?.[0]?.id || "";
  applyCredentialsResponse(data, { keepEditingId: editingLabId });
}

async function persistEditingLab() {
  const payload = buildCredentialsPayload();
  const data = await api("/api/credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  credDoc = {
    activeLabId: data.activeLabId || payload.activeLabId,
    labs: Array.isArray(data.labs) ? data.labs : payload.labs,
  };
  return data;
}

async function setActiveLabOnly(labId) {
  if (!labId || labId === credDoc.activeLabId) {
    syncMakeActiveButton();
    return;
  }
  const data = await api("/api/credentials/active-lab", {
    method: "POST",
    body: JSON.stringify({ labId }),
  });
  credDoc.activeLabId = data.activeLabId || labId;
  if (Array.isArray(data.labs)) {
    credDoc.labs = data.labs;
  }
  fillLabSelects();
  updateLabStrip(data.activeLabSummary);
  logLabEvent("lab-switch", data.activeLabSummary);
  log("Refreshing module status for the new active lab…\n");
  await refreshAllStatus();
  log("Status refresh finished.\n");
}

async function switchActiveLab(labId) {
  if (!labId || labId === credDoc.activeLabId || labUiBusy) return;
  labUiBusy = true;
  setCredFeedback("");
  try {
    // Keep credentials edits for the lab being edited; do not change the form.
    await persistEditingLab();
    await setActiveLabOnly(labId);
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    fillLabSelects();
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
  }
}

async function switchEditingLab(labId) {
  if (!labId || labId === editingLabId || labUiBusy) return;
  labUiBusy = true;
  setCredFeedback("");
  try {
    await persistEditingLab();
    editingLabId = labId;
    fillLabSelects();
    fillEditingLabForm();
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    fillLabSelects();
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
  }
}

async function makeEditingLabActive() {
  if (!editingLabId || editingLabId === credDoc.activeLabId || labUiBusy) return;
  labUiBusy = true;
  setCredFeedback("");
  try {
    await persistEditingLab();
    await setActiveLabOnly(editingLabId);
    setCredFeedback("Active lab updated.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
  }
}

async function addLab() {
  const name = window.prompt("Display name for the new lab?", "new-lab");
  if (name == null) return;
  const lab = emptyLab(name.trim() || "new-lab");
  labUiBusy = true;
  setCredFeedback("");
  try {
    const payload = buildCredentialsPayload();
    payload.labs.push(lab);
    // Do not activate the new lab unless it is the only one.
    if (payload.labs.length === 1) {
      payload.activeLabId = lab.id;
    }
    const data = await api("/api/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    editingLabId = lab.id;
    applyCredentialsResponse(data, { keepEditingId: lab.id });
    setCredFeedback("Lab added (not active). Edit it, then Use as active when ready.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
  }
}

async function deleteEditingLab() {
  const lab = editingLab();
  if (!lab) return;
  if ((credDoc.labs || []).length <= 1) {
    setCredFeedback("Keep at least one lab.", true);
    return;
  }
  if (lab.id === credDoc.activeLabId) {
    setCredFeedback("Switch active to another lab before deleting this one.", true);
    syncDeleteLabButton();
    return;
  }
  const label = lab.name || lab.id;
  if (!window.confirm(`Delete lab “${label}”? This cannot be undone.`)) return;

  labUiBusy = true;
  setCredFeedback("");
  try {
    const payload = buildCredentialsPayload();
    const remaining = payload.labs.filter((item) => item.id !== lab.id);
    if (!remaining.length) {
      setCredFeedback("Keep at least one lab.", true);
      return;
    }
    const activeId = payload.activeLabId;
    if (activeId === lab.id) {
      setCredFeedback("Switch active to another lab before deleting this one.", true);
      return;
    }
    const data = await api("/api/credentials", {
      method: "POST",
      body: JSON.stringify({ activeLabId: activeId, labs: remaining }),
    });
    editingLabId = activeId;
    applyCredentialsResponse(data, { keepEditingId: activeId });
    setCredFeedback("Lab deleted.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
  }
}

function addSecuredCluster() {
  const lab = editingLab();
  if (!lab) return;
  const current = readSecuredClustersFromDom();
  const sc = emptySecuredCluster(`secured-${current.length + 1}`);
  sc.sameAsCentralCluster = false;
  lab.securedClusters = [...current, sc];
  lab.activeSecuredClusterId = preferredScId(lab.securedClusters);
  renderSecuredClusters(lab);
  // Expand the new remote SC for editing
  const row = securedClusterList?.querySelector(`[data-sc-id="${CSS.escape(sc.id)}"]`);
  if (row) row.open = true;
}

async function loadRegistry() {
  registryModules = await api("/api/modules");
  moduleMetaById = new Map(registryModules.map((m) => [m.id, m]));
  renderModuleRows();
}

function refreshFoldMetasFromForm() {
  const lab = editingLab() || emptyLab();
  lab.name = fields.labName?.value || lab.name;
  lab.insecureSkipTlsVerify = Boolean(fields.insecureSkipTlsVerify?.checked);
  lab.centralCluster = {
    openshift: {
      consoleUrl: fields.centralOcpConsole?.value || "",
      adminUsername: fields.centralOcpUser?.value || "",
      adminPassword: fields.centralOcpPassword?.value || "",
    },
    central: {
      consoleUrl: fields.centralConsole?.value || "",
      apiToken: fields.centralApiToken?.value || "",
      apiTokenName: fields.centralApiTokenName?.value || "",
      apiTokenExpires: fields.centralApiTokenExpires?.value || "",
      adminUsername: fields.centralAdminUser?.value || "",
      adminPassword: fields.centralAdminPassword?.value || "",
      authPreference: authPrefValue(),
    },
  };
  lab.securedClusters = readSecuredClustersFromDom();
  updateFoldMetas(lab);
}

fields.centralConsole?.addEventListener("input", refreshFoldMetasFromForm);
fields.centralApiToken?.addEventListener("input", refreshFoldMetasFromForm);

document.getElementById("btnCredSave").addEventListener("click", saveCredentials);
document.getElementById("btnAddLab")?.addEventListener("click", () => {
  addLab().catch((e) => setCredFeedback(e.message, true));
});
document.getElementById("btnDeleteLab")?.addEventListener("click", () => {
  deleteEditingLab().catch((e) => setCredFeedback(e.message, true));
});
document.getElementById("btnMakeActive")?.addEventListener("click", () => {
  makeEditingLabActive().catch((e) => setCredFeedback(e.message, true));
});
document.getElementById("btnAddSecuredCluster")?.addEventListener("click", addSecuredCluster);
activeLabSelect?.addEventListener("change", () => {
  switchActiveLab(activeLabSelect.value).catch((e) => setCredFeedback(e.message, true));
});
editLabSelect?.addEventListener("change", () => {
  switchEditingLab(editLabSelect.value).catch((e) => setCredFeedback(e.message, true));
});
document.getElementById("btnStatus").addEventListener("click", () => {
  (async () => {
    logLabEvent("status-refresh");
    log("Refreshing module status…\n");
    await refreshAllStatus();
    log("Status refresh finished.\n");
  })().catch((e) => log(`\n${e.message}\n`));
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

async function markPageLoadInDiskLog() {
  try {
    await fetch("/api/log/page-load", { method: "POST" });
  } catch {
    /* disk marker is best-effort */
  }
}

async function init() {
  try {
    // Hard refresh starts with an empty Log pane; tee'd files under logs/ keep history.
    if (logEl) logEl.textContent = "";
    await markPageLoadInDiskLog();
    setupCredentialCopyButtons();
    await loadRegistry();
    await loadCredentials();
    logLabEvent("page-load");
    log("Refreshing module status…\n");
    await refreshAllStatus();
    log("Status refresh finished.\n");
  } catch (err) {
    log(`\n${err.message}\n`);
    modulesTbody.innerHTML =
      '<tr class="pf-v6-c-table__tr"><td class="pf-v6-c-table__td module-row-td" colspan="2">Failed to load.</td></tr>';
  }
}

init();
