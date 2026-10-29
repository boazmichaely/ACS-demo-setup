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
const labStripName = document.getElementById("labStripName"); // optional / absent in shell
const labStripHint = document.getElementById("labStripHint");
const securedClusterList = document.getElementById("securedClusterList");
const btnMakeActive = document.getElementById("btnMakeActive");
const btnDeleteLab = document.getElementById("btnDeleteLab");

let registryModules = [];
let lastStatusModules = [];
let lastStatusMap = new Map();
let moduleMetaById = new Map();
let busy = false;
/** True after at least one successful /api/status response this page load. */
let statusReady = false;
/** True while a status refresh is in flight. */
let statusRefreshing = false;

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

function syncRefreshActionButtons() {
  const freeze = busy || statusRefreshing;
  const el = document.getElementById("btnStatus");
  if (el) el.disabled = freeze;
}

function dryRunMode() {
  return Boolean(document.getElementById("dryRunToggle")?.checked);
}

function syncDryRunToggleUi() {
  const wrap = document.getElementById("dryToggleWrap");
  if (wrap) wrap.classList.toggle("is-on", dryRunMode());
}

/** Open the log drawer if closed. Used when Dry run turns on (output is the point). */
function ensureLogDrawerOpen() {
  const drawer = document.getElementById("logDrawer");
  const toggle = document.getElementById("logDrawerToggle");
  if (!drawer || drawer.classList.contains("is-open")) return;
  drawer.classList.add("is-open");
  if (toggle) toggle.setAttribute("aria-expanded", "true");
}

function closeAllModuleMenus() {
  document.querySelectorAll(".demo-mod__menu").forEach((m) => {
    m.hidden = true;
  });
  document.querySelectorAll(".js-kebab").forEach((b) => b.setAttribute("aria-expanded", "false"));
}

function setBusy(on) {
  busy = on;
  // Module runs lock credentials + lab selectors. Status refresh must not.
  const ids = [
    "btnCredSave",
    "btnCredCancel",
    "btnAddLab",
    "btnDeleteLab",
    "btnMakeActive",
    "btnAddSecuredCluster",
    "btnRun",
    "btnUninstall",
    "btnRunFull",
    "dryRunToggle",
  ];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = on;
  }
  modulesTbody?.querySelectorAll(".js-kebab").forEach((btn) => {
    if (!btn.dataset.forceDisabled) btn.disabled = on;
  });
  if (on) closeAllModuleMenus();
  if (activeLabSelect) activeLabSelect.disabled = on;
  if (editLabSelect) editLabSelect.disabled = on;
  syncRefreshActionButtons();
  if (!on) {
    syncMakeActiveButton();
    syncDeleteLabButton();
    syncCredCancelButton();
    syncModuleMenuButtons();
  }
}

function setCredFeedback(text, isError = false) {
  if (!credSaveFeedback) return;
  credSaveFeedback.textContent = text || "";
  credSaveFeedback.classList.toggle("is-error", Boolean(isError));
}

function setModuleRefreshFeedback(text) {
  if (modRefreshFeedback) modRefreshFeedback.textContent = text || "";
}

function setStatusRefreshing(on, label = "Refreshing status…") {
  statusRefreshing = Boolean(on);
  const wrap = document.getElementById("statusRefreshBusy");
  const progress = document.getElementById("statusRefreshProgress");
  if (wrap) {
    wrap.hidden = !statusRefreshing;
    wrap.setAttribute("aria-hidden", statusRefreshing ? "false" : "true");
  }
  if (progress) {
    progress.hidden = !statusRefreshing;
    progress.setAttribute("aria-hidden", statusRefreshing ? "false" : "true");
  }
  if (statusRefreshIndicator) {
    statusRefreshIndicator.textContent = statusRefreshing ? label : "";
  }
  document.getElementById("modulesTable")?.setAttribute("aria-busy", statusRefreshing ? "true" : "false");
  document.querySelector(".demo-workbench")?.classList.toggle("is-status-refreshing", statusRefreshing);
  syncRefreshActionButtons();
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

function isScriptInstalled(moduleId) {
  const meta = moduleMetaById.get(moduleId);
  if (meta && typeof meta.scriptInstalled === "boolean") {
    return meta.scriptInstalled;
  }
  const st = lastStatusMap.get(moduleId);
  if (st?.message && /module script not installed/i.test(st.message)) {
    return false;
  }
  // Unknown until /api/modules loads — treat as installed so we do not flash-disable.
  return true;
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
    return `<pre class="demo-sec__body">${escapeHtml(text)}</pre>`;
  }

  const text = typeof body === "string" ? body : String(body ?? "");
  return `<div class="demo-sec__body">${escapeHtml(text).replace(/\n/g, "<br>")}</div>`;
}

function sectionExpandKey(moduleId, index, title) {
  return `${moduleId}::${index}::${title || ""}`;
}

function captureStatusExpandState() {
  const moduleIds = new Set();
  const sectionKeys = new Set();
  if (!statusWrap) return { moduleIds, sectionKeys };

  statusWrap.querySelectorAll("details.demo-pf-block[data-module-id]").forEach((mod) => {
    const moduleId = mod.dataset.moduleId;
    if (!moduleId) return;
    if (mod.open) moduleIds.add(moduleId);
    mod.querySelectorAll("details.demo-sec").forEach((sec, index) => {
      if (!sec.open) return;
      const title =
        sec.querySelector(".demo-sec__title")?.textContent?.trim() || "";
      sectionKeys.add(sectionExpandKey(moduleId, index, title));
    });
  });
  return { moduleIds, sectionKeys };
}

function applyStatusExpandState(state, { defaultModulesOpen = false } = {}) {
  if (!statusWrap) return;
  const moduleIds = state?.moduleIds;
  const sectionKeys = state?.sectionKeys;

  statusWrap.querySelectorAll("details.demo-pf-block[data-module-id]").forEach((mod) => {
    const moduleId = mod.dataset.moduleId;
    if (!moduleId) return;
    if (moduleIds) {
      mod.open = moduleIds.has(moduleId);
    } else {
      mod.open = defaultModulesOpen;
    }
    mod.querySelectorAll("details.demo-sec").forEach((sec, index) => {
      const title =
        sec.querySelector(".demo-sec__title")?.textContent?.trim() || "";
      const key = sectionExpandKey(moduleId, index, title);
      sec.open = Boolean(sectionKeys && sectionKeys.has(key));
    });
  });
}

function renderSectionsHtml(sections, moduleId = "") {
  if (!Array.isArray(sections) || !sections.length) return "";

  let currentGroup = null;
  let html = "";
  let index = 0;

  for (const item of sections) {
    const group = item.group || "";
    if (group && group !== currentGroup) {
      currentGroup = group;
      html += `<p class="demo-sec-group">${escapeHtml(group)}</p>`;
    }

    const tagKey = String(item.tag || "").toLowerCase();
    const tagText = item.tagLabel || item.tag || "";
    let tagClass = "demo-sec__tag";
    if (tagKey === "ok" || tagKey === "ready") tagClass += " demo-sec__tag--ok";
    else if (tagKey === "error" || tagKey === "fail") tagClass += " demo-sec__tag--error";
    else if (tagKey) tagClass += " demo-sec__tag--warn";
    const tag = tagText
      ? `<span class="${tagClass}">${escapeHtml(tagText)}</span>`
      : "";
    const summary = item.summary
      ? `<span class="demo-sec__sum">${escapeHtml(item.summary)}</span>`
      : "";
    const body = renderSectionBody(item);
    const title = item.title || "Section";
    const key = sectionExpandKey(moduleId, index, title);

    html += `<details class="demo-sec" data-section-key="${escapeHtml(key)}">
      <summary>
        ${tag}<span class="demo-sec__title">${escapeHtml(title)}</span>${summary}
      </summary>
      ${body}
    </details>`;
    index += 1;
  }

  return html;
}

function dependsOnHintHtml(m) {
  const deps = m.dependsOn;
  if (!Array.isArray(deps) || deps.length === 0) return "";
  return `<span class="demo-mod__deps">Requires: ${deps.map(escapeHtml).join(", ")}</span>`;
}

function moduleCellHtml(m) {
  const idx = m.number != null ? `${escapeHtml(String(m.number))}.` : "";
  const id = String(m.id ?? "");
  return `<div class="demo-mod__line">
    <span class="demo-mod__idx">${idx}</span>
    <span class="demo-mod__slug">${escapeHtml(id)}</span>
    <span class="js-deps-lock-hint demo-mod__lock" hidden></span>
  </div>`;
}

function moduleDescriptionCellHtml(m) {
  const text = String(m.label ?? "").trim() || "—";
  // title = native tooltip when ellipsis clips the text
  return `<span title="${escapeHtml(text)}">${escapeHtml(text)}</span>`;
}

/** Size Module + State columns to content; Description keeps the leftover (ellipsis). */
function syncModulesColumnWidths() {
  const table = document.getElementById("modulesTable");
  if (!table || !table.tBodies?.[0]?.rows?.length) return;

  table.classList.add("is-measuring");
  table.style.removeProperty("--demo-mod-col");
  table.style.removeProperty("--demo-state-col");

  let mod = 0;
  let state = 0;
  table.querySelectorAll("thead th:nth-child(1), tbody td:nth-child(1)").forEach((el) => {
    mod = Math.max(mod, el.scrollWidth);
  });
  table.querySelectorAll("thead th:nth-child(3), tbody td:nth-child(3)").forEach((el) => {
    state = Math.max(state, el.scrollWidth);
  });

  table.classList.remove("is-measuring");
  table.style.setProperty("--demo-mod-col", `${Math.ceil(mod) + 4}px`);
  table.style.setProperty("--demo-state-col", `${Math.ceil(state) + 4}px`);
}

function moduleActionsCellHtml(m) {
  const id = escapeHtml(m.id);
  if (m.scriptInstalled === false) {
    return `<td class="demo-mod__actions">
      <button type="button" class="pf-v6-c-button pf-m-plain js-kebab" disabled data-force-disabled="1" aria-label="No actions for ${id}">⋮</button>
    </td>`;
  }
  return `<td class="demo-mod__actions">
    <div class="demo-mod__menu-wrap">
      <button type="button" class="pf-v6-c-button pf-m-plain js-kebab" aria-label="Actions for ${id}" aria-expanded="false" data-module-id="${id}">⋮</button>
      <ul class="demo-mod__menu" hidden>
        <li><button type="button" class="js-mod-menu-run" data-module-id="${id}">Run</button></li>
        <li><button type="button" class="js-mod-menu-uninstall is-danger" data-module-id="${id}">Uninstall</button></li>
      </ul>
    </div>
  </td>`;
}

function syncModuleMenuButtons() {
  if (!modulesTbody) return;
  modulesTbody.querySelectorAll("tr[data-module-id]").forEach((tr) => {
    const id = tr.dataset.moduleId;
    const runBtn = tr.querySelector(".js-mod-menu-run");
    const kebab = tr.querySelector(".js-kebab");
    if (!id || !runBtn) return;
    const unavailable = !isScriptInstalled(id);
    const locked = missingDeps(id).length > 0;
    runBtn.disabled = unavailable || locked || busy;
    if (kebab && !kebab.dataset.forceDisabled) {
      kebab.disabled = busy;
    }
  });
}

function bindModuleMenus() {
  if (!modulesTbody || modulesTbody.dataset.menusBound === "1") return;
  modulesTbody.dataset.menusBound = "1";

  modulesTbody.addEventListener("click", (e) => {
    const kebab = e.target.closest(".js-kebab");
    if (kebab && modulesTbody.contains(kebab)) {
      e.preventDefault();
      e.stopPropagation();
      if (kebab.disabled) return;
      const wrap = kebab.closest(".demo-mod__menu-wrap");
      const menu = wrap?.querySelector(".demo-mod__menu");
      const open = menu && !menu.hidden;
      closeAllModuleMenus();
      if (menu && !open) {
        menu.hidden = false;
        kebab.setAttribute("aria-expanded", "true");
      }
      return;
    }

    const runBtn = e.target.closest(".js-mod-menu-run");
    if (runBtn && modulesTbody.contains(runBtn)) {
      e.preventDefault();
      e.stopPropagation();
      closeAllModuleMenus();
      if (runBtn.disabled) return;
      runModule(runBtn.dataset.moduleId, { dryRun: dryRunMode() }).catch((err) =>
        log(`\n${err.message}\n`)
      );
      return;
    }

    const uninstallBtn = e.target.closest(".js-mod-menu-uninstall");
    if (uninstallBtn && modulesTbody.contains(uninstallBtn)) {
      e.preventDefault();
      e.stopPropagation();
      closeAllModuleMenus();
      const id = uninstallBtn.dataset.moduleId;
      const dry = dryRunMode();
      if (
        !dry &&
        !window.confirm(
          `Uninstall module “${id}”? Some modules refuse uninstall and will fail with a message.`
        )
      ) {
        return;
      }
      runModule(id, { uninstall: true, dryRun: dry }).catch((err) =>
        log(`\n${err.message}\n`)
      );
    }
  });

  document.addEventListener("click", () => closeAllModuleMenus());
}

function missingDeps(moduleId) {
  const meta = moduleMetaById.get(moduleId);
  if (!meta?.dependsOn?.length) return [];
  return meta.dependsOn.filter((dep) => lastStatusMap.get(dep)?.state !== "ok");
}

function badgeHtml(moduleId, { linkToStatus = false } = {}) {
  let tone = "pf-m-grey";
  let label = "…";
  let title = "";
  if (!isScriptInstalled(moduleId)) {
    label = "not installed";
    title = "module script not installed";
  } else if (!statusReady) {
    label = "checking";
    title = "Refreshing status…";
  } else {
    const st = lastStatusMap.get(moduleId);
    if (st) {
      const mapped = uiStateFromOrchestrator(st.state);
      tone =
        mapped.ui === "ready" ? "pf-m-green" : mapped.ui === "blocked" ? "pf-m-red" : "pf-m-orange";
      label =
        mapped.ui === "ready" ? "ready" : mapped.ui === "blocked" ? "error" : "needs run";
      title = String(st.message || "");
    }
  }
  const inner = `<span class="pf-v6-c-label__content">${escapeHtml(label)}</span>`;
  const canJump = linkToStatus && isScriptInstalled(moduleId) && statusReady;
  if (canJump) {
    return `<a class="pf-v6-c-label ${tone} pf-m-compact demo-mod__status-link" href="#status-mod-${escapeHtml(moduleId)}" title="${escapeHtml(title || `Jump to ${moduleId} in Status`)}" data-status-jump="${escapeHtml(moduleId)}">${inner}</a>`;
  }
  return `<span class="pf-v6-c-label ${tone} pf-m-compact" title="${escapeHtml(title)}">${inner}</span>`;
}

function moduleStatusCellHtml(moduleId) {
  return badgeHtml(moduleId, { linkToStatus: true });
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

    if (!isScriptInstalled(id)) {
      cb.checked = false;
      cb.disabled = true;
      tr.classList.add("demo-mod--unavailable");
      tr.classList.remove("demo-mod--locked");
      tr.setAttribute("aria-disabled", "true");
      if (hint) hint.hidden = true;
      continue;
    }

    tr.classList.remove("demo-mod--unavailable");
    tr.removeAttribute("aria-disabled");

    // Do not lock on missing deps until we have real status (avoids flash of false locks).
    if (!statusReady) {
      cb.disabled = false;
      tr.classList.remove("demo-mod--locked");
      if (hint) hint.hidden = true;
      continue;
    }

    const missing = (meta.dependsOn || []).filter(
      (dep) => !prereqMet(dep, lastStatusMap, cbById)
    );
    if (missing.length) {
      cb.checked = false;
      cb.disabled = true;
      tr.classList.add("demo-mod--locked");
      if (hint) {
        hint.textContent = `Locked: needs ${missing.join(", ")} ready or selected.`;
        hint.hidden = false;
      }
    } else {
      cb.disabled = false;
      tr.classList.remove("demo-mod--locked");
      if (hint) hint.hidden = true;
    }
  }
  syncModuleMenuButtons();
}

function syncMasterCheckbox() {
  const all = getModuleCheckboxes();
  const selectable = all.filter((c) => !c.disabled);
  const checked = selectable.filter((c) => c.checked).length;
  const n = selectable.length;
  const unavailable = all.length - n;
  modSelectAll.checked = n > 0 && checked === n;
  modSelectAll.indeterminate = checked > 0 && checked < n;
  modSelectionCount.textContent =
    unavailable > 0
      ? `${checked} of ${n} selectable selected (${unavailable} not installed)`
      : `${checked} of ${n} selected`;
  moduleBulkBar.classList.toggle("has-selection", checked > 0);
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
    modulesTbody.innerHTML = '<tr><td colspan="4">No modules.</td></tr>';
    return;
  }

  modulesTbody.innerHTML = registryModules
    .map((m) => {
      const id = escapeHtml(m.id);
      const unavailable = m.scriptInstalled === false;
      const rowClass = unavailable ? "demo-mod--unavailable" : "";
      const disabledAttr = unavailable ? " disabled" : "";
      const aria = unavailable ? ' aria-disabled="true"' : "";
      return `<tr class="${rowClass}" data-module-id="${id}"${aria}>
        <td>
          <div class="demo-mod__check">
            <input class="js-mod-cb" type="checkbox" data-module-id="${id}" id="mod-cb-${id}" aria-label="Select ${id}"${disabledAttr} />
            ${moduleCellHtml(m)}
          </div>
        </td>
        <td class="demo-mod__desc-cell">${moduleDescriptionCellHtml(m)}</td>
        <td class="js-status-cell" data-module-id="${id}">
          ${moduleStatusCellHtml(m.id)}
        </td>
        ${moduleActionsCellHtml(m)}
      </tr>`;
    })
    .join("");

  modulesTbody.querySelectorAll("input.js-mod-cb").forEach((cb) => {
    cb.addEventListener("change", () => {
      syncDependencyLocks();
      syncMasterCheckbox();
    });
  });
  bindStatusJumpLinks(modulesTbody);
  bindModuleMenus();

  syncDependencyLocks();
  syncMasterCheckbox();
  refreshStatusCells();
  syncModulesColumnWidths();
}

function jumpToStatusModule(moduleId) {
  if (!moduleId) return;
  const outer = document.getElementById("statusOuter");
  if (outer) outer.open = true;
  const target = document.getElementById(`status-mod-${moduleId}`);
  if (!target) return;
  target.open = true;
  target.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function bindStatusJumpLinks(root) {
  (root || modulesTbody).querySelectorAll("a.demo-mod__status-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      jumpToStatusModule(a.dataset.statusJump);
    });
  });
}

function refreshStatusCells() {
  modulesTbody.querySelectorAll(".js-status-cell").forEach((td) => {
    const id = td.dataset.moduleId;
    if (id) td.innerHTML = moduleStatusCellHtml(id);
  });
  bindStatusJumpLinks(modulesTbody);
  syncModulesColumnWidths();
}

function renderStatusModulesPanel() {
  if (!statusWrap) return;

  const statusPanelMeta = document.getElementById("statusPanelMeta");
  if (!statusReady) {
    statusWrap.innerHTML = statusRefreshing
      ? `<p class="pf-v6-c-helper-text demo-status-pending">
          <svg class="pf-v6-c-spinner pf-m-md" role="presentation" viewBox="0 0 100 100" aria-hidden="true">
            <circle class="pf-v6-c-spinner__path" cx="50" cy="50" r="45" fill="none"></circle>
          </svg>
          Checking module status…
        </p>`
      : '<p class="pf-v6-c-helper-text">No status yet. Click Refresh status.</p>';
    if (btnPreflightExpandAll) btnPreflightExpandAll.disabled = true;
    if (statusPanelMeta) statusPanelMeta.textContent = statusRefreshing ? "refreshing…" : "";
    return;
  }

  const rawModules = lastStatusModules.length ? lastStatusModules : registryModules;
  const modules = rawModules.filter((row) => isScriptInstalled(row.id));
  if (!rawModules.length) {
    statusWrap.innerHTML =
      '<p class="pf-v6-c-helper-text">No status yet. Click Refresh status.</p>';
    if (btnPreflightExpandAll) btnPreflightExpandAll.disabled = true;
    if (statusPanelMeta) statusPanelMeta.textContent = "";
    return;
  }
  if (!modules.length) {
    statusWrap.innerHTML =
      '<p class="pf-v6-c-helper-text">No installed module scripts to show.</p>';
    if (btnPreflightExpandAll) btnPreflightExpandAll.disabled = true;
    if (statusPanelMeta) statusPanelMeta.textContent = "0 installed";
    return;
  }

  const hadModules = Boolean(statusWrap.querySelector("details.demo-pf-block[data-module-id]"));
  const savedExpand = hadModules ? captureStatusExpandState() : null;

  if (statusPanelMeta) {
    const n = modules.length;
    statusPanelMeta.textContent = `${n} installed`;
  }

  statusWrap.innerHTML = modules
    .map((row) => {
      const id = row.id;
      const st = lastStatusMap.get(id);
      const rawMsg = String(st?.message || row.message || "").trim();
      const msg = escapeHtml(rawMsg || "—");
      const sectionsHtml = renderSectionsHtml(st?.sections || row.sections || [], id);
      const missing = missingDeps(id);
      const lockHtml = missing.length
        ? `<p class="demo-mod__lock">Requires ready: ${escapeHtml(missing.join(", "))}</p>`
        : "";
      const depsHtml =
        Array.isArray(row.dependsOn) && row.dependsOn.length
          ? `<p class="demo-mod__deps">Depends on: ${row.dependsOn.map(escapeHtml).join(", ")}</p>`
          : "";

      return `<details class="demo-pf-block" id="status-mod-${escapeHtml(id)}" data-module-id="${escapeHtml(id)}">
        <summary class="demo-pf-block__summary">
          <span class="demo-pf-block__chev" aria-hidden="true"></span>
          <span class="demo-pf-block__name">${escapeHtml(id)}</span>
          ${badgeHtml(id)}
          <span class="demo-pf-block__msg">${msg}</span>
        </summary>
        <div class="demo-pf-block__body">
          ${sectionsHtml || `<p class="demo-pf-block__body--empty">No section details.</p>`}
          ${depsHtml}
          ${lockHtml}
        </div>
      </details>`;
    })
    .join("");

  // Hard refresh / first paint: leave modules collapsed. Later refreshes keep user expand state.
  applyStatusExpandState(savedExpand, { defaultModulesOpen: false });

  if (btnPreflightExpandAll) btnPreflightExpandAll.disabled = false;

  bindSelectableSummaries(statusWrap);
}

function setupExpandAll() {
  if (!btnPreflightExpandAll || !statusWrap) return;
  let expanded = false;
  btnPreflightExpandAll.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    expanded = !expanded;
    statusWrap.querySelectorAll("details.demo-pf-block, details.demo-sec").forEach((d) => {
      d.open = expanded;
    });
    btnPreflightExpandAll.setAttribute(
      "aria-label",
      expanded ? "Collapse all modules" : "Expand all modules"
    );
    btnPreflightExpandAll.textContent = expanded ? "Collapse all" : "Expand all";
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

/** Bumped each status refresh so a newer refresh can supersede an older one. */
let statusRefreshGeneration = 0;

async function refreshAllStatus() {
  const gen = ++statusRefreshGeneration;
  setStatusRefreshing(true);
  refreshStatusCells();
  renderStatusModulesPanel();
  try {
    await fetchStatus();
    if (gen !== statusRefreshGeneration) return;
    statusReady = true;
    setModuleRefreshFeedback("Status updated.");
  } finally {
    if (gen === statusRefreshGeneration) {
      setStatusRefreshing(false);
      refreshStatusCells();
      syncDependencyLocks();
      syncMasterCheckbox();
      renderStatusModulesPanel();
    }
  }
}

async function executeModuleRun(moduleId, { dryRun = false, uninstall = false } = {}) {
  const params = new URLSearchParams();
  if (dryRun) params.set("dry_run", "true");
  if (uninstall) params.set("uninstall", "true");
  const qs = params.toString();
  const res = await fetch(
    `/api/run/${encodeURIComponent(moduleId)}${qs ? `?${qs}` : ""}`,
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

async function runModule(moduleId, { dryRun = false, uninstall = false } = {}) {
  if (!moduleId) return;
  let label = "Run";
  if (uninstall && dryRun) label = "Uninstall dry-run";
  else if (uninstall) label = "Uninstall";
  else if (dryRun) label = "Dry run";
  setBusy(true);
  logSection(`${label}: ${moduleId}`);

  try {
    await executeModuleRun(moduleId, { dryRun, uninstall });
    await fetchStatus([moduleId]);
    refreshStatusCells();
    renderStatusModulesPanel();
  } finally {
    setBusy(false);
  }
}

async function runModules(ids, { dryRun = false, uninstall = false } = {}) {
  if (!ids.length) {
    setModuleRefreshFeedback("Select at least one module.");
    return;
  }
  if (uninstall && !dryRun) {
    const labelList = ids.join(", ");
    if (
      !window.confirm(
        `Uninstall selected module(s): ${labelList}?\n\nSome modules refuse uninstall and will fail with a message.`
      )
    ) {
      return;
    }
  }
  const order = uninstall ? [...ids] : topologicalRunOrder(ids);
  let label = "Run";
  if (uninstall && dryRun) label = "Uninstall dry-run";
  else if (uninstall) label = "Uninstall";
  else if (dryRun) label = "Dry run";
  setBusy(true);
  clearLog();
  logSection(`${label}: ${order.join(", ")}`);

  try {
    for (const moduleId of order) {
      if (order.length > 1) {
        log(`\n[${moduleId}]\n`);
      }
      await executeModuleRun(moduleId, { dryRun, uninstall });
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
  syncCredCancelButton();
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

function createLaunchButton(getUrl, label) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cred-copy-btn cred-launch-btn";
  btn.setAttribute("aria-label", `Open ${label}`);
  btn.title = `Open ${label}`;
  btn.innerHTML = copyIconHtml("open_in_new");
  btn.addEventListener("click", () => {
    const raw = String(getUrl() || "").trim();
    if (!raw) return;
    const href = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    window.open(href, "_blank", "noopener,noreferrer");
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
  if (input.type === "url") {
    wrap.appendChild(createLaunchButton(() => input.value, label));
  }
  input.addEventListener("input", syncCredentialCopyButtons);
}

function setupCredentialCopyButtons() {
  const form = document.getElementById("credForm");
  if (!form) return;

  form.querySelectorAll("input.pf-v6-c-form-control").forEach((input) => {
    wrapInputWithCopy(input);
  });

  const pathLine = document.getElementById("credPathLine");
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
    if (!input) return;
    const empty = input.disabled || !input.value.trim();
    wrap.querySelectorAll(".cred-copy-btn").forEach((btn) => {
      btn.disabled = empty;
    });
  });
  const pathBtn = document.querySelector("#credPathLine .cred-copy-btn");
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
  return [...securedClusterList.querySelectorAll(".demo-sc-row")].map((row) => {
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

function preferredOpenshiftForLab(lab) {
  if (!lab) return emptyOpenshift();
  const clusters = lab.securedClusters || [];
  const sc =
    clusters.find((c) => c.id === lab.activeSecuredClusterId) || clusters[0] || null;
  if (sc && sc.sameAsCentralCluster === false) {
    return sc.openshift || emptyOpenshift();
  }
  return (lab.centralCluster || {}).openshift || emptyOpenshift();
}

function updateCredPanelChrome() {
  const mismatch = document.getElementById("credDualMismatch");
  if (!mismatch) return;
  const lab = editingLab();
  const active = activeLab();
  const same = Boolean(editingLabId) && editingLabId === credDoc.activeLabId;
  mismatch.hidden = !(lab && active && same);
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
  updateCredPanelChrome();
}

function scRemoteBodyHtml(sc, ocp) {
  return `<label class="demo-field">
      <span>Name</span>
      <input class="pf-v6-c-form-control js-sc-name" type="text" value="${escapeHtml(sc.name || "")}" spellcheck="false" />
    </label>
    <label class="pf-v6-c-check">
      <input class="pf-v6-c-check__input js-sc-same" type="checkbox" />
      <span class="pf-v6-c-check__label">Same as Central</span>
    </label>
    <label class="demo-field">
      <span>Console URL</span>
      <input class="pf-v6-c-form-control js-sc-console" type="url" value="${escapeHtml(ocp.consoleUrl || "")}" spellcheck="false" />
    </label>
    <div class="demo-field-row">
      <label class="demo-field">
        <span>User</span>
        <input class="pf-v6-c-form-control js-sc-user" type="text" value="${escapeHtml(ocp.adminUsername || "")}" spellcheck="false" />
      </label>
      <label class="demo-field">
        <span>Password</span>
        <input class="pf-v6-c-form-control js-sc-password" type="text" value="${escapeHtml(ocp.adminPassword || "")}" spellcheck="false" autocomplete="off" />
      </label>
    </div>`;
}

function scSameBodyHtml() {
  return `<label class="pf-v6-c-check">
      <input class="pf-v6-c-check__input js-sc-same" type="checkbox" checked />
      <span class="pf-v6-c-check__label">Same as Central</span>
    </label>
    <p class="demo-sc-hint" style="margin:0">Uses Central OpenShift console/user/password.</p>`;
}

function renderSecuredClusters(lab) {
  if (!securedClusterList) return;
  const clusters = lab.securedClusters || [];

  if (!clusters.length) {
    securedClusterList.innerHTML =
      '<p class="demo-sc-empty">No secured clusters. Add one when a module needs sensor-side OpenShift.</p>';
    updateFoldMetas(lab);
    return;
  }

  securedClusterList.innerHTML = clusters
    .map((sc) => {
      const same = sc.sameAsCentralCluster !== false;
      const ocp = sc.openshift || emptyOpenshift();
      const badgeClass = same ? "pf-m-blue" : "pf-m-grey";
      const badgeText = same ? "Same as Central" : "Remote OCP";
      const body = same ? scSameBodyHtml() : scRemoteBodyHtml(sc, ocp);
      return `<details class="demo-sc-row" data-sc-id="${escapeHtml(sc.id)}">
        <summary class="demo-sc-row__summary">
          <span class="demo-sc-row__name js-sc-title">${escapeHtml(sc.name || "secured")}</span>
          <span class="pf-v6-c-label pf-m-compact ${badgeClass} js-sc-badge"><span class="pf-v6-c-label__content">${badgeText}</span></span>
          <span class="demo-sc-row__hint js-sc-sub">${escapeHtml(scSubLabel(sc))}</span>
          <button type="button" class="pf-v6-c-button pf-m-link pf-m-danger pf-m-inline js-sc-remove"
            title="Remove secured cluster">Remove</button>
        </summary>
        <div class="demo-sc-row__body">${body}</div>
      </details>`;
    })
    .join("");

  securedClusterList.querySelectorAll(".demo-sc-row").forEach((row) => {
    bindSecuredClusterRow(row);
  });

  updateFoldMetas(lab);
  setupCredentialCopyButtons();
}

function refreshScRowChrome(row) {
  const sameCb = row.querySelector(".js-sc-same");
  const titleEl = row.querySelector(".js-sc-title");
  const subEl = row.querySelector(".js-sc-sub");
  const badgeEl = row.querySelector(".js-sc-badge .pf-v6-c-label__content");
  const badgeWrap = row.querySelector(".js-sc-badge");
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
  if (badgeEl) badgeEl.textContent = same ? "Same as Central" : "Remote OCP";
  if (badgeWrap) {
    badgeWrap.classList.toggle("pf-m-blue", same);
    badgeWrap.classList.toggle("pf-m-grey", !same);
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
  const body = row.querySelector(".demo-sc-row__body");
  if (!body || !sameCb) return;

  const same = Boolean(sameCb.checked);
  const name =
    (row.querySelector(".js-sc-name")?.value || titleEl?.textContent || "").trim() || "secured";
  const ocp = {
    consoleUrl: row.querySelector(".js-sc-console")?.value || "",
    adminUsername: row.querySelector(".js-sc-user")?.value || "",
    adminPassword: row.querySelector(".js-sc-password")?.value || "",
  };

  body.innerHTML = same
    ? scSameBodyHtml()
    : scRemoteBodyHtml({ name }, ocp);

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
    // DOM-only: do not mutate credDoc here or dirty tracking / Save will miss the removal.
    row.remove();
    const remaining = readSecuredClustersFromDom();
    const lab = editingLab();
    updateFoldMetas({
      ...(lab || {}),
      securedClusters: remaining,
      activeSecuredClusterId: preferredScId(remaining),
    });
    if (!remaining.length && securedClusterList) {
      securedClusterList.innerHTML =
        '<p class="demo-sc-empty">No secured clusters. Add one when a module needs sensor-side OpenShift.</p>';
    }
    syncCredCancelButton();
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
  updateCredPanelChrome();
}

function syncMakeActiveButton() {
  if (!btnMakeActive) return;
  const same = Boolean(editingLabId) && editingLabId === credDoc.activeLabId;
  btnMakeActive.disabled = busy || labUiBusy || same || !editingLabId;
  btnMakeActive.textContent = same ? "Already active" : "Use as active";
  updateCredPanelChrome();
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
  captureSavedEditingLabFingerprint();
  syncCredCancelButton();
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
  // Do not hold lab UI / await here: status can take a long time.
  log("Refreshing module status for the new active lab…\n");
  refreshAllStatus()
    .then(() => log("Status refresh finished.\n"))
    .catch((err) => log(`\nStatus refresh failed: ${err.message || err}\n`));
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

function normalizeLabForCompare(lab) {
  if (!lab) return null;
  return {
    id: lab.id || "",
    name: (lab.name || "").trim(),
    insecureSkipTlsVerify: Boolean(lab.insecureSkipTlsVerify),
    centralCluster: lab.centralCluster || {},
    securedClusters: lab.securedClusters || [],
    activeSecuredClusterId: lab.activeSecuredClusterId || "",
  };
}

/**
 * Fingerprint of the editing lab as last loaded/saved.
 * Always captured from the form (not credDoc): fold/SC chrome handlers mutate
 * the in-memory lab, so a file-object baseline would never look dirty.
 */
let savedEditingLabFingerprint = "";

function captureSavedEditingLabFingerprint() {
  savedEditingLabFingerprint = JSON.stringify(editingLabFormSnapshot() || null);
}

function editingLabFormSnapshot() {
  const payload = buildCredentialsPayload();
  return normalizeLabForCompare(
    (payload.labs || []).find((lab) => lab.id === editingLabId)
  );
}

function isEditingLabDirty() {
  if (!editingLabId || !savedEditingLabFingerprint) return false;
  return JSON.stringify(editingLabFormSnapshot()) !== savedEditingLabFingerprint;
}

function syncCredCancelButton() {
  const btn = document.getElementById("btnCredCancel");
  if (!btn) return;
  btn.disabled = busy || labUiBusy || !isEditingLabDirty();
}

async function cancelEditingLab() {
  if (labUiBusy) return;
  if (!isEditingLabDirty()) {
    setCredFeedback("No unsaved changes.");
    return;
  }
  labUiBusy = true;
  setCredFeedback("");
  try {
    const data = await api("/api/credentials");
    applyCredentialsResponse(data, { keepEditingId: editingLabId });
    setCredFeedback("Reverted to file.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
    syncCredCancelButton();
  }
}

async function switchEditingLab(labId) {
  if (!labId || labId === editingLabId || labUiBusy) return;
  if (isEditingLabDirty()) {
    const ok = window.confirm(
      "You have unsaved edits. Switching labs discards them. Continue?"
    );
    if (!ok) {
      fillLabSelects();
      return;
    }
  }
  labUiBusy = true;
  setCredFeedback("");
  try {
    // Always reload from disk so the form shows file state, not in-memory edits.
    const data = await api("/api/credentials");
    applyCredentialsResponse(data, { keepEditingId: labId });
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    fillLabSelects();
  } finally {
    labUiBusy = false;
    syncMakeActiveButton();
    syncDeleteLabButton();
    syncCredCancelButton();
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
  // Draft in DOM only; Save writes it. Avoid mutating credDoc so dirty tracking works.
  const draft = {
    ...lab,
    securedClusters: [...current, sc],
    activeSecuredClusterId: preferredScId([...current, sc]),
  };
  renderSecuredClusters(draft);
  const row = securedClusterList?.querySelector(`[data-sc-id="${CSS.escape(sc.id)}"]`);
  if (row) row.open = true;
  syncCredCancelButton();
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
fields.labName?.addEventListener("input", refreshFoldMetasFromForm);
fields.centralOcpConsole?.addEventListener("input", refreshFoldMetasFromForm);

document.getElementById("btnCredSave").addEventListener("click", (e) => {
  e.preventDefault();
  saveCredentials();
});
document.getElementById("btnCredCancel")?.addEventListener("click", (e) => {
  e.preventDefault();
  cancelEditingLab().catch((err) => setCredFeedback(err.message, true));
});

// Keep Cancel enabled/disabled as the form changes.
const credFormEl = document.getElementById("credForm");
credFormEl?.addEventListener("input", () => syncCredCancelButton());
credFormEl?.addEventListener("change", () => syncCredCancelButton());
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
let editLabSelectPrior = "";
editLabSelect?.addEventListener("focus", () => {
  editLabSelectPrior = editLabSelect.value;
});
editLabSelect?.addEventListener("change", () => {
  const next = editLabSelect.value;
  switchEditingLab(next)
    .then(() => {
      editLabSelectPrior = editLabSelect.value;
    })
    .catch((e) => {
      editLabSelect.value = editLabSelectPrior || editingLabId;
      setCredFeedback(e.message, true);
    });
});
document.getElementById("btnStatus").addEventListener("click", () => {
  (async () => {
    logLabEvent("status-refresh");
    log("Refreshing module status…\n");
    await refreshAllStatus();
    log("Status refresh finished.\n");
  })().catch((e) => log(`\n${e.message}\n`));
});
document.getElementById("dryRunToggle")?.addEventListener("change", () => {
  syncDryRunToggleUi();
  if (dryRunMode()) ensureLogDrawerOpen();
});
document.getElementById("btnRun").addEventListener("click", () => {
  runModules(selectedModuleIds(), { dryRun: dryRunMode() }).catch((e) =>
    log(`\n${e.message}\n`)
  );
});
document.getElementById("btnUninstall")?.addEventListener("click", () => {
  runModules(selectedModuleIds(), { uninstall: true, dryRun: dryRunMode() }).catch((e) =>
    log(`\n${e.message}\n`)
  );
});
document.getElementById("btnRunFull").addEventListener("click", () => {
  const allIds = registryModules.map((m) => m.id);
  applySelectAll(true);
  runModules(allIds, { dryRun: dryRunMode() }).catch((e) => log(`\n${e.message}\n`));
});
modSelectAll.addEventListener("change", () => applySelectAll(modSelectAll.checked));

setupExpandAll();
syncDryRunToggleUi();

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
      '<tr><td colspan="4">Failed to load.</td></tr>';
  }
}

let modulesColResizeTimer = 0;
window.addEventListener("resize", () => {
  window.clearTimeout(modulesColResizeTimer);
  modulesColResizeTimer = window.setTimeout(() => syncModulesColumnWidths(), 100);
});

init();
