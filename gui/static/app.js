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
/** Session-only last /api/run outcome per module. Cleared on page reload. */
let lastActionByModule = new Map();
let moduleMetaById = new Map();
let busy = false;
/** True after at least one successful /api/status response this page load. */
let statusReady = false;
/** True while a status refresh is in flight. */
let statusRefreshing = false;
/** Installed module ids still waiting in the current progressive refresh. */
let statusPendingIds = new Set();

/** In-memory v2 credentials document (activeLabId + labs[]). */
let credDoc = { activeLabId: "", labs: [] };
/** Lab id currently shown in the credentials form (independent of activeLabId). */
let editingLabId = "";
let labUiBusy = false;
/** When false, lab detail fields are read-only until the user hits Edit. */
let credEditMode = false;

const fields = {
  labName: document.getElementById("labName"),
  insecureSkipTlsVerify: document.getElementById("insecureSkipTlsVerify"),
  centralOcpConsole: document.getElementById("centralOcpConsole"),
  centralOcpUser: document.getElementById("centralOcpUser"),
  centralOcpPassword: document.getElementById("centralOcpPassword"),
  centralOcpApiToken: document.getElementById("centralOcpApiToken"),
  centralConsole: document.getElementById("centralConsole"),
  centralApiToken: document.getElementById("centralApiToken"),
  centralApiTokenName: document.getElementById("centralApiTokenName"),
  centralApiTokenExpires: document.getElementById("centralApiTokenExpires"),
  centralAdminUser: document.getElementById("centralAdminUser"),
  centralAdminPassword: document.getElementById("centralAdminPassword"),
  slackNotifierName: document.getElementById("slackNotifierName"),
  slackWebhookUrl: document.getElementById("slackWebhookUrl"),
  slackChannelUrl: document.getElementById("slackChannelUrl"),
};

function newId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyOpenshift() {
  return { consoleUrl: "", adminUsername: "", adminPassword: "", apiToken: "" };
}

function emptySecuredCluster(name = "production") {
  return {
    id: newId(),
    name,
    sameAsCentralCluster: true,
    openshift: emptyOpenshift(),
  };
}

function slackNotifierDefaults() {
  const d = credDoc?.slackNotifierDefaults || {};
  return {
    webhookUrl: (d.webhookUrl || "").trim(),
    notifierName: (d.notifierName || "").trim() || "#acs-demo-notifier",
    channelUrl: (d.channelUrl || "").trim(),
  };
}

function restoreSlackNotifierDefaults() {
  const defs = slackNotifierDefaults();
  if (fields.slackNotifierName) fields.slackNotifierName.value = defs.notifierName || "";
  if (fields.slackWebhookUrl) fields.slackWebhookUrl.value = defs.webhookUrl || "";
  if (fields.slackChannelUrl) fields.slackChannelUrl.value = defs.channelUrl || "";
  const lab = editingLab();
  if (lab) {
    lab.slackNotifier = { ...defs };
    updateFoldMetas(lab);
  }
}

function emptySlackNotifier() {
  return { ...slackNotifierDefaults() };
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
    slackNotifier: emptySlackNotifier(),
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

function runVerbLabel({ dryRun = false, uninstall = false } = {}) {
  if (uninstall && dryRun) return "Uninstall dry-run";
  if (uninstall) return "Uninstall";
  if (dryRun) return "Dry run";
  return "Run";
}

function formatLastActionWhen(d = new Date()) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function recordLastAction(moduleId, { verb, ok }) {
  if (!moduleId) return;
  lastActionByModule.set(moduleId, {
    verb,
    ok: Boolean(ok),
    when: formatLastActionWhen(),
  });
}

function lastActionHtml(moduleId) {
  const a = lastActionByModule.get(moduleId);
  if (!a) return "";
  const result = a.ok ? "ok" : "failed";
  const cls = a.ok ? "is-ok" : "is-fail";
  return `<span class="demo-pf-block__last ${cls}" title="Last action this session">${escapeHtml(a.verb)}: <span class="demo-pf-block__last-result">${result}</span> (${escapeHtml(a.when)})</span>`;
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

/** Open the log drawer if closed (module runs, Dry run toggle). */
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
    "btnCredEdit",
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
  syncRefreshActionButtons();
  if (!on) {
    syncCredChrome();
    syncModuleMenuButtons();
  } else if (editLabSelect) {
    editLabSelect.disabled = true;
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

function linkifyProseHtml(escaped) {
  // escaped is already HTML-escaped. Link http(s) URLs and local GUI help paths.
  let out = escaped.replace(
    /https?:\/\/[^\s<]+/g,
    (url) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
  );
  out = out.replace(
    /\/help\?doc=[A-Za-z0-9_-]+/g,
    (path) =>
      `<a href="${path}" target="_blank" rel="noopener noreferrer">${path}</a>`
  );
  return out;
}

function renderSectionBody(item) {
  const format = item.bodyFormat || "prose";
  const body = item.body ?? "";

  if (format === "json") {
    const text = typeof body === "string" ? body : JSON.stringify(body, null, 2);
    return `<pre class="demo-sec__body">${escapeHtml(text)}</pre>`;
  }

  const text = typeof body === "string" ? body : String(body ?? "");
  const withBreaks = linkifyProseHtml(escapeHtml(text)).replace(/\n/g, "<br>");
  return `<div class="demo-sec__body">${withBreaks}</div>`;
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

function setGroupExpandButton(btn, expanded) {
  if (!btn) return;
  btn.dataset.expanded = expanded ? "true" : "false";
  btn.classList.toggle("is-expanded", expanded);
  const group = btn.closest(".demo-sec-group-block")?.dataset.group || "group";
  const label = expanded
    ? `Collapse all sections in ${group}`
    : `Expand all sections in ${group}`;
  btn.setAttribute("aria-label", label);
  btn.setAttribute("title", expanded ? "Collapse all" : "Expand all");
  btn.setAttribute("aria-expanded", expanded ? "true" : "false");
}

function syncGroupExpandButtons(root) {
  if (!root) return;
  root.querySelectorAll(".demo-sec-group-block").forEach((block) => {
    const secs = [...block.querySelectorAll("details.demo-sec")];
    if (!secs.length) return;
    const allOpen = secs.every((d) => d.open);
    setGroupExpandButton(block.querySelector(".demo-sec-group__expand"), allOpen);
  });
}

function bindGroupExpandButtons(root) {
  if (!root) return;
  root.querySelectorAll(".demo-sec-group__expand").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const block = btn.closest(".demo-sec-group-block");
      if (!block) return;
      const expand = btn.dataset.expanded !== "true";
      block.querySelectorAll("details.demo-sec").forEach((d) => {
        d.open = expand;
      });
      setGroupExpandButton(btn, expand);
    });
  });
  root.querySelectorAll(".demo-sec-group-block details.demo-sec").forEach((sec) => {
    sec.addEventListener("toggle", () => {
      syncGroupExpandButtons(sec.closest(".demo-sec-group-block"));
    });
  });
}

function renderSectionFoldsHtml(sections, moduleId, startIndex = 0) {
  if (!Array.isArray(sections) || !sections.length) {
    return { html: "", nextIndex: startIndex };
  }

  let currentGroup = null;
  let html = "";
  let index = startIndex;
  let groupOpen = false;

  const closeGroup = () => {
    if (groupOpen) {
      html += `</div>`;
      groupOpen = false;
    }
  };

  for (const item of sections) {
    const group = item.group || "";
    if (group !== currentGroup) {
      currentGroup = group;
      closeGroup();
      if (group) {
        html += `<div class="demo-sec-group-block" data-group="${escapeHtml(group)}">
          <div class="demo-sec-group">
            <button type="button" class="pf-v6-c-button pf-m-plain demo-sec-group__expand" data-expanded="false" aria-expanded="false" title="Expand all" aria-label="Expand all sections in ${escapeHtml(group)}">
              <span class="demo-sec-group__expand-icon" aria-hidden="true"></span>
            </button>
            <span class="demo-sec-group__label">${escapeHtml(group)}</span>
          </div>`;
        groupOpen = true;
      }
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
        <span class="demo-sec__toggle" aria-hidden="true"><span class="demo-sec__chev"></span></span>
        ${tag}<span class="demo-sec__title">${escapeHtml(title)}</span>${summary}
      </summary>
      ${body}
    </details>`;
    index += 1;
  }

  closeGroup();
  return { html, nextIndex: index };
}

function renderSectionsHtml(sections, moduleId = "") {
  if (!Array.isArray(sections) || !sections.length) return "";

  const clusterNames = [
    ...new Set(
      sections
        .map((s) => (s && s.cluster != null ? String(s.cluster).trim() : ""))
        .filter(Boolean)
    ),
  ];
  const multiCluster = clusterNames.length > 1;

  if (!multiCluster) {
    return renderSectionFoldsHtml(sections, moduleId, 0).html;
  }

  // Outer hierarchy: one block per secured cluster; reuse existing group folds inside.
  let html = "";
  let index = 0;
  for (const cluster of clusterNames) {
    const subset = sections.filter((s) => String(s.cluster || "").trim() == cluster);
    const inner = renderSectionFoldsHtml(subset, moduleId, index);
    index = inner.nextIndex;
    html += `<div class="demo-sec-cluster-block" data-cluster="${escapeHtml(cluster)}">
      <div class="demo-sec-cluster">
        <span class="demo-sec-cluster__label">${escapeHtml(cluster)}</span>
      </div>
      ${inner.html}
    </div>`;
  }
  // Sections without a cluster name (if any) after named clusters
  const orphan = sections.filter((s) => !String(s.cluster || "").trim());
  if (orphan.length) {
    const inner = renderSectionFoldsHtml(orphan, moduleId, index);
    html += inner.html;
  }
  return html;
}

function moduleCellHtml(m) {
  const idx = m.number != null ? `${escapeHtml(String(m.number))}.` : "";
  const id = String(m.id ?? "");
  const safe = escapeHtml(id);
  // Quiet link: looks like the bold module id; click jumps to Status fold.
  const slug =
    m.scriptInstalled === false
      ? `<span class="demo-mod__slug">${safe}</span>`
      : `<a class="demo-mod__slug demo-mod__slug-link" href="#status-mod-${safe}" title="Jump to ${safe} in Status" data-status-jump="${safe}">${safe}</a>`;
  return `<div class="demo-mod__line">
    <span class="demo-mod__idx">${idx}</span>
    ${slug}
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
        <li><button type="button" class="js-mod-menu-help" data-module-id="${id}">Help</button></li>
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
      return;
    }

    const helpBtn = e.target.closest(".js-mod-menu-help");
    if (helpBtn && modulesTbody.contains(helpBtn)) {
      e.preventDefault();
      e.stopPropagation();
      closeAllModuleMenus();
      showModuleHelp(helpBtn.dataset.moduleId).catch((err) =>
        log(`\n${err.message}\n`)
      );
    }
  });

  document.addEventListener("click", () => closeAllModuleMenus());
}

/**
 * Module --help is Markdown (preferred) or legacy "Header:" sections.
 * HTML rendering is only via ACS.md.render (gui/static/md-render.js).
 */
function legacyHelpToMarkdown(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let section = null; // null | "md" | "usage" | "environment" | "prose"
  let buf = [];

  const flush = () => {
    if (section === null && !buf.length) return;
    const body = buf.join("\n").replace(/^\n+|\n+$/g, "");
    buf = [];
    if (section === "usage" || section === "environment") {
      const fence = body || " ";
      const label = section === "usage" ? "Usage" : "Environment";
      out.push(`## ${label}\n\n\`\`\`\n${fence}\n\`\`\`\n`);
    } else if (section === "prose") {
      /* title already emitted */
      out.push(body ? `${body}\n` : "");
    } else if (body) {
      out.push(`${body}\n`);
    }
    section = null;
  };

  for (const line of lines) {
    if (/^#{1,6}\s/.test(line)) {
      flush();
      section = "md";
      buf.push(line);
      continue;
    }
    const usageInline = line.match(/^Usage:\s*(.*)$/);
    if (usageInline && section === null && buf.length === 0 && !out.length) {
      flush();
      section = "usage";
      if (usageInline[1]) buf.push(`Usage: ${usageInline[1]}`);
      else buf.push("Usage:");
      continue;
    }
    const header = line.match(/^([A-Za-z][A-Za-z0-9 /.+_-]{0,40}):\s*$/);
    if (header && section !== "md") {
      flush();
      const title = header[1];
      const key = title.toLowerCase();
      if (key === "usage") {
        section = "usage";
        buf.push("Usage:");
      } else if (key === "environment") {
        section = "environment";
      } else {
        section = "prose";
        out.push(`## ${title}\n`);
      }
      continue;
    }
    if (section === "usage" && buf.length === 1 && buf[0] === "Usage:" && line.trim()) {
      buf[0] = line.match(/^Usage:/) ? line : `Usage: ${line.trim()}`;
      continue;
    }
    buf.push(line);
  }
  flush();
  return out.join("\n").trim() + "\n";
}

function renderModuleHelpHtml(text) {
  const raw = String(text || "").trim();
  if (!raw) return `<p class="demo-mod-help__prose">(empty help)</p>`;
  const looksLikeMd = /^#{1,6}\s/m.test(raw);
  const md = looksLikeMd ? raw : legacyHelpToMarkdown(raw);
  if (!window.ACS || !ACS.md || typeof ACS.md.render !== "function") {
    return `<pre class="demo-mod-help__fallback">${escapeHtml(raw)}</pre>`;
  }
  return ACS.md.render(md);
}

async function showModuleHelp(moduleId) {
  if (!moduleId) return;
  const dialog = document.getElementById("moduleHelpDialog");
  const titleEl = document.getElementById("moduleHelpTitle");
  const bodyEl = document.getElementById("moduleHelpBody");
  if (!dialog || !bodyEl) {
    throw new Error("Module help dialog missing from page");
  }
  if (titleEl) titleEl.textContent = `${moduleId} - help`;
  bodyEl.innerHTML = `<p class="demo-mod-help__loading">Loading…</p>`;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  const data = await api(`/api/modules/${encodeURIComponent(moduleId)}/help`);
  bodyEl.innerHTML = renderModuleHelpHtml(data.text || "");
}

function setupModuleHelpDialog() {
  const dialog = document.getElementById("moduleHelpDialog");
  const closeBtn = document.getElementById("moduleHelpClose");
  if (!dialog) return;
  closeBtn?.addEventListener("click", () => {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  });
}

function depStatusKnown(depId) {
  if (!isScriptInstalled(depId)) return true;
  if (statusPendingIds.has(depId)) return false;
  const st = lastStatusMap.get(depId);
  if (!st) return false;
  const msg = String(st.message || "");
  if (msg === "not refreshed" || /^checking/i.test(msg)) return false;
  return true;
}

function missingDeps(moduleId, seen = new Set()) {
  const meta = moduleMetaById.get(moduleId);
  if (!meta?.dependsOn?.length) return [];
  if (seen.has(moduleId)) return [];
  seen.add(moduleId);
  const missing = [];
  for (const dep of meta.dependsOn) {
    // While a dependency's own status is still in flight, do not treat it as unmet
    // (statusReady flips true after the first module; premature locks gray the chain).
    if (!depStatusKnown(dep)) continue;
    const st = lastStatusMap.get(dep);
    if (st?.state !== "ok") {
      missing.push(dep);
      continue;
    }
    // Transitive: dep is ok itself but still waiting on its own deps.
    const nested = missingDeps(dep, seen);
    if (nested.length) missing.push(dep);
  }
  return missing;
}

function isDependencyLocked(moduleId) {
  return (
    statusReady &&
    !statusPendingIds.has(moduleId) &&
    isScriptInstalled(moduleId) &&
    missingDeps(moduleId).length > 0
  );
}

function badgeHtml(moduleId, { linkToStatus = false } = {}) {
  let tone = "pf-m-grey";
  let label = "…";
  let title = "";
  let locked = false;
  if (!isScriptInstalled(moduleId)) {
    label = "not installed";
    title = "module script not installed";
  } else if (!statusReady || statusPendingIds.has(moduleId)) {
    label = "checking";
    title = "Refreshing status…";
  } else if (isDependencyLocked(moduleId)) {
    locked = true;
    tone = "pf-m-grey";
    label = "needs run";
    const missing = missingDeps(moduleId);
    title = `Waiting on: ${missing.join(", ")}`;
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
  const lockIcon = locked
    ? `<span class="material-symbols-outlined demo-mod__lock-icon" aria-hidden="true">lock</span>`
    : "";
  const inner = `<span class="pf-v6-c-label__content">${lockIcon}${escapeHtml(label)}</span>`;
  const canJump =
    linkToStatus &&
    isScriptInstalled(moduleId) &&
    statusReady &&
    !statusPendingIds.has(moduleId);
  const lockClass = locked ? " demo-mod__status--locked" : "";
  if (canJump) {
    return `<a class="pf-v6-c-label ${tone} pf-m-compact demo-mod__status-link${lockClass}" href="#status-mod-${escapeHtml(moduleId)}" title="${escapeHtml(title || `Jump to ${moduleId} in Status`)}" data-status-jump="${escapeHtml(moduleId)}">${inner}</a>`;
  }
  return `<span class="pf-v6-c-label ${tone} pf-m-compact${lockClass}" title="${escapeHtml(title)}">${inner}</span>`;
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
  const cb = cbById.get(depId);
  if (cb?.checked) return true;
  if (!depStatusKnown(depId)) return true;
  const st = statusMap.get(depId);
  if (st?.state !== "ok") return false;
  // Transitive: checked/ok dep that is still dep-locked does not satisfy children.
  if (isScriptInstalled(depId) && missingDeps(depId).length > 0) return false;
  return true;
}

function syncDependencyLocks() {
  const cbById = collectCheckboxById();
  for (const [id, meta] of moduleMetaById) {
    const tr = modulesTbody.querySelector(`tr[data-module-id="${CSS.escape(id)}"]`);
    if (!tr) continue;
    const cb = tr.querySelector("input.js-mod-cb");
    if (!cb) continue;

    if (!isScriptInstalled(id)) {
      cb.checked = false;
      cb.disabled = true;
      tr.classList.add("demo-mod--unavailable");
      tr.classList.remove("demo-mod--locked");
      tr.setAttribute("aria-disabled", "true");
      continue;
    }

    tr.classList.remove("demo-mod--unavailable");
    tr.removeAttribute("aria-disabled");

    // Do not lock on missing deps until we have real status (avoids flash of false locks).
    if (!statusReady) {
      cb.disabled = false;
      tr.classList.remove("demo-mod--locked");
      continue;
    }

    const missing = (meta.dependsOn || []).filter(
      (dep) => !prereqMet(dep, lastStatusMap, cbById)
    );
    if (missing.length) {
      cb.checked = false;
      cb.disabled = true;
      tr.classList.add("demo-mod--locked");
    } else {
      cb.disabled = false;
      tr.classList.remove("demo-mod--locked");
    }
  }
  syncModuleMenuButtons();
}

function syncMasterCheckbox() {
  const all = getModuleCheckboxes();
  const selectable = all.filter((c) => !c.disabled);
  const checked = selectable.filter((c) => c.checked).length;
  const n = selectable.length;
  const notInstalled = all.filter((c) => {
    const id = c.dataset.moduleId;
    return id && !isScriptInstalled(id);
  }).length;
  const locked = all.length - n - notInstalled;
  modSelectAll.checked = n > 0 && checked === n;
  modSelectAll.indeterminate = checked > 0 && checked < n;
  const bits = [`${checked} of ${n} selected`];
  if (locked > 0) bits.push(`${locked} waiting on deps`);
  if (notInstalled > 0) bits.push(`${notInstalled} not installed`);
  modSelectionCount.textContent = bits.join(" · ");
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
  // "start" (not "nearest") so far-away folds actually scroll into view.
  target.scrollIntoView({ block: "start", behavior: "smooth" });
}

function bindStatusJumpLinks(root) {
  (root || modulesTbody)
    .querySelectorAll("a.demo-mod__status-link, a.demo-mod__slug-link")
    .forEach((a) => {
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
          ${lastActionHtml(id)}
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
  syncGroupExpandButtons(statusWrap);

  if (btnPreflightExpandAll) btnPreflightExpandAll.disabled = false;

  bindSelectableSummaries(statusWrap);
  bindGroupExpandButtons(statusWrap);
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
    statusWrap.querySelectorAll(".demo-sec-group__expand").forEach((btn) => {
      setGroupExpandButton(btn, expanded);
    });
    btnPreflightExpandAll.setAttribute(
      "aria-label",
      expanded ? "Collapse all modules" : "Expand all modules"
    );
    btnPreflightExpandAll.textContent = expanded ? "Collapse all" : "Expand all";
  });
}

const GITHUB_REPO = "boazmichaely/ACS-demo-setup";

function setupHelpMenu() {
  const toggle = document.getElementById("btnHelpMenu");
  const menu = document.getElementById("helpMenu");
  if (!toggle || !menu) return;

  const setOpen = (open) => {
    menu.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };

  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOpen(menu.hidden);
  });

  menu.addEventListener("click", (e) => {
    e.stopPropagation();
  });

  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });
}

function releaseUrlForVersion(version) {
  const v = String(version || "")
    .trim()
    .replace(/^v/i, "");
  if (!v) return `https://github.com/${GITHUB_REPO}/releases`;
  return `https://github.com/${GITHUB_REPO}/releases/tag/v${v}`;
}

function setHelpMenuVersion(version, releaseUrl) {
  const el = document.getElementById("helpMenuVersion");
  if (!el) return;
  const v = String(version || "").trim();
  if (!v) {
    el.textContent = "Version unknown";
    el.removeAttribute("href");
    return;
  }
  el.textContent = `Version ${v}`;
  el.href = (releaseUrl || "").trim() || releaseUrlForVersion(v);
  el.title = `Release notes for v${v.replace(/^v/i, "")}`;
}

function hideUpdateBanner() {
  const banner = document.getElementById("updateBanner");
  if (banner) banner.hidden = true;
}

function showUpdateBanner({ tag, htmlUrl }) {
  const banner = document.getElementById("updateBanner");
  if (!banner) return;
  const verEl = document.getElementById("updateBannerVersion");
  const link = document.getElementById("updateBannerReleaseLink");
  const label = String(tag || "").trim() || "newer";
  if (verEl) verEl.textContent = label.startsWith("v") ? label : `v${label}`;
  if (link) {
    link.href =
      htmlUrl || `https://github.com/${GITHUB_REPO}/releases`;
  }
  banner.hidden = false;
}

function setupUpdateBannerDismiss() {
  const btn = document.getElementById("updateBannerDismiss");
  if (!btn || btn.dataset.bound === "1") return;
  btn.dataset.bound = "1";
  // Hide for this page view only - refresh shows the nudge again if still outdated.
  btn.addEventListener("click", () => hideUpdateBanner());
}

function wantsUpdatePreview() {
  try {
    return new URLSearchParams(window.location.search).get("updatePreview") === "1";
  } catch {
    return false;
  }
}

async function loadInstalledVersionAndMaybeNudge() {
  setupUpdateBannerDismiss();
  try {
    if (wantsUpdatePreview()) {
      setHelpMenuVersion("0.1.0", releaseUrlForVersion("0.1.0"));
      showUpdateBanner({
        tag: "v0.2.0",
        htmlUrl: `https://github.com/${GITHUB_REPO}/releases`,
      });
      return;
    }

    const resp = await fetch("/api/version");
    if (!resp.ok) {
      setHelpMenuVersion("");
      return;
    }
    const data = await resp.json();
    const version = String(data?.version || "").trim();
    const releaseUrl = String(data?.releaseUrl || "").trim();
    setHelpMenuVersion(version || "", releaseUrl);

    // Server already compared to GitHub - no second browser-side fetch.
    if (data?.updateAvailable) {
      showUpdateBanner({
        tag: String(data.latestTag || "").trim(),
        htmlUrl: String(data.latestReleaseUrl || "").trim(),
      });
    } else {
      hideUpdateBanner();
    }
  } catch {
    setHelpMenuVersion("");
  }
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

function catalogModuleIndex(moduleId) {
  const idx = registryModules.findIndex((m) => m.id === moduleId);
  return idx >= 0 ? idx : 999;
}

function statusComplexityOf(moduleId) {
  const raw = moduleMetaById.get(moduleId)?.statusComplexity;
  const n = Number(raw);
  if (Number.isFinite(n) && n >= 1 && n <= 10) return n;
  return 5;
}

function statusRefreshOrder(moduleIds) {
  return [...moduleIds].sort((a, b) => {
    const ca = statusComplexityOf(a);
    const cb = statusComplexityOf(b);
    if (ca !== cb) return ca - cb;
    return catalogModuleIndex(a) - catalogModuleIndex(b);
  });
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
  const byId = new Map(
    (lastStatusModules || []).map((row) => [row.id, row]).filter(([id]) => id)
  );
  for (const row of data) {
    if (row?.id) byId.set(row.id, row);
  }
  lastStatusModules = registryModules.map((m) => {
    const hit = byId.get(m.id);
    if (hit) {
      return {
        ...m,
        ...hit,
        id: m.id,
        sections: Array.isArray(hit.sections) ? hit.sections : [],
      };
    }
    return {
      ...m,
      state: "needs-run",
      message: statusPendingIds.has(m.id) ? "checking…" : "not refreshed",
      sections: [],
    };
  });
  lastStatusMap = statusMapFromModules(lastStatusModules);
}

/** Bumped each status refresh so a newer refresh can supersede an older one. */
let statusRefreshGeneration = 0;

async function refreshAllStatus() {
  const gen = ++statusRefreshGeneration;
  const installed = registryModules
    .filter((m) => isScriptInstalled(m.id))
    .map((m) => m.id);
  const order = statusRefreshOrder(installed);
  statusPendingIds = new Set(order);
  const total = order.length;

  setStatusRefreshing(
    true,
    total ? `Refreshing status (0/${total})…` : "Refreshing status…"
  );
  refreshStatusCells();
  renderStatusModulesPanel();

  try {
    if (!total) {
      statusReady = true;
      setModuleRefreshFeedback("No installed modules to refresh.");
      return;
    }

    let done = 0;
    for (const id of order) {
      if (gen !== statusRefreshGeneration) return;
      await fetchStatus([id]);
      if (gen !== statusRefreshGeneration) return;
      statusPendingIds.delete(id);
      done += 1;
      statusReady = true;
      setStatusRefreshing(true, `Refreshing status (${done}/${total})…`);
      refreshStatusCells();
      syncDependencyLocks();
      syncMasterCheckbox();
      renderStatusModulesPanel();
    }
    if (gen !== statusRefreshGeneration) return;
    setModuleRefreshFeedback("Status updated.");
  } finally {
    if (gen === statusRefreshGeneration) {
      statusPendingIds = new Set();
      setStatusRefreshing(false);
      refreshStatusCells();
      syncDependencyLocks();
      syncMasterCheckbox();
      renderStatusModulesPanel();
    }
  }
}

/** Modules that accept orchestrator --plane / --secured-cluster-id fan-out. */
const ORCHESTRATOR_PLANE_MODULES = new Set(["compliance-operator"]);

function moduleImpactPlanes(moduleId) {
  const raw = moduleMetaById.get(moduleId)?.impactPlanes;
  return Array.isArray(raw) ? raw.map((p) => String(p).toLowerCase()) : [];
}

function moduleNeedsScPicker(moduleId) {
  if (!ORCHESTRATOR_PLANE_MODULES.has(moduleId)) return false;
  return moduleImpactPlanes(moduleId).includes("openshift");
}

/**
 * Pre-launch multi-select for OpenShift-impact modules.
 * Resolves to selected secured-cluster ids, or null if the user cancels.
 * Returns [] when the lab has no SCs (caller runs without fan-out flags).
 */
function pickSecuredClusterIds(moduleId, { uninstall = false } = {}) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("scPickerDialog");
    const list = document.getElementById("scPickerList");
    const form = document.getElementById("scPickerForm");
    const title = document.getElementById("scPickerTitle");
    const closeBtn = document.getElementById("scPickerClose");
    if (!dialog || !list || !form) {
      resolve([]);
      return;
    }

    const lab = activeLab();
    const clusters = lab?.securedClusters || [];
    if (!clusters.length) {
      resolve([]);
      return;
    }

    const verb = uninstall ? "Uninstall" : "Install";
    if (title) title.textContent = `${verb} ${moduleId} - select clusters`;

    const activeId = (lab.activeSecuredClusterId || "").trim();
    list.innerHTML = clusters
      .map((sc) => {
        const id = sc.id || "";
        const name = sc.name || id;
        const checked = !activeId || id === activeId ? "checked" : "";
        const same = sc.sameAsCentralCluster
          ? `<small>same OpenShift as Central (cred shortcut)</small>`
          : "";
        return `<label class="demo-sc-picker__row">
          <input type="checkbox" name="sc" value="${escapeHtml(id)}" ${checked} />
          <span class="demo-sc-picker__row-meta">
            <span>${escapeHtml(name)}</span>
            ${same}
          </span>
        </label>`;
      })
      .join("");

    const finish = (ids) => {
      dialog.removeEventListener("close", onDialogClose);
      form.removeEventListener("submit", onSubmit);
      if (closeBtn) closeBtn.removeEventListener("click", onCancelClick);
      if (dialog.open) dialog.close();
      resolve(ids);
    };

    const onCancelClick = () => finish(null);

    const onSubmit = (e) => {
      e.preventDefault();
      const submitter = e.submitter;
      const value = submitter?.value || "confirm";
      if (value === "cancel") {
        finish(null);
        return;
      }
      const selected = [...list.querySelectorAll('input[name="sc"]:checked')].map(
        (el) => el.value
      );
      if (!selected.length) {
        window.alert("Select at least one secured cluster.");
        return;
      }
      finish(selected);
    };

    const onDialogClose = () => {
      // Esc / backdrop without an explicit finish
      if (dialog.returnValue === "cancel") finish(null);
    };

    form.addEventListener("submit", onSubmit);
    if (closeBtn) closeBtn.addEventListener("click", onCancelClick);
    dialog.addEventListener("close", onDialogClose);
    dialog.showModal();
  });
}

async function executeModuleRun(
  moduleId,
  { dryRun = false, uninstall = false, securedClusterIds = null } = {}
) {
  const params = new URLSearchParams();
  if (dryRun) params.set("dry_run", "true");
  if (uninstall) params.set("uninstall", "true");
  for (const id of securedClusterIds || []) {
    if (id) params.append("secured_cluster_id", id);
  }
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
  let securedClusterIds = null;
  if (moduleNeedsScPicker(moduleId)) {
    securedClusterIds = await pickSecuredClusterIds(moduleId, { uninstall });
    if (securedClusterIds === null) return;
  }
  const label = runVerbLabel({ dryRun, uninstall });
  setBusy(true);
  ensureLogDrawerOpen();
  logSection(`${label}: ${moduleId}`);

  try {
    const result = await executeModuleRun(moduleId, {
      dryRun,
      uninstall,
      securedClusterIds,
    });
    recordLastAction(moduleId, { verb: label, ok: result.ok });
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
  /** @type {Map<string, string[]|null>} */
  const scByModule = new Map();
  for (const moduleId of order) {
    if (!moduleNeedsScPicker(moduleId)) {
      scByModule.set(moduleId, null);
      continue;
    }
    const picked = await pickSecuredClusterIds(moduleId, { uninstall });
    if (picked === null) return;
    scByModule.set(moduleId, picked);
  }
  const label = runVerbLabel({ dryRun, uninstall });
  setBusy(true);
  ensureLogDrawerOpen();
  clearLog();
  logSection(`${label}: ${order.join(", ")}`);

  try {
    for (const moduleId of order) {
      if (order.length > 1) {
        log(`\n[${moduleId}]\n`);
      }
      const result = await executeModuleRun(moduleId, {
        dryRun,
        uninstall,
        securedClusterIds: scByModule.get(moduleId),
      });
      recordLastAction(moduleId, { verb: label, ok: result.ok });
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
  if (!credEditMode) return;
  setCredFeedback("");
  try {
    const data = await persistEditingLab();
    applyCredentialsResponse(data, { keepEditingId: editingLabId });
    setCredEditMode(false);
    setCredFeedback("Saved.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    syncCredChrome();
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
    // Keep copy/launch usable in read-only mode; only empty values disable them.
    const empty = !input.value.trim();
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

/** First cluster id only - used when creating/repairing, never as a silent same-as-Central heuristic. */
function firstScId(clusters) {
  return (clusters || [])[0]?.id || "";
}

/** Prefer the SC marked same-as-Central (Central's cluster) for Setup target default. */
function centralClusterScId(clusters) {
  const hit = (clusters || []).find((sc) => sc.sameAsCentralCluster !== false);
  return hit?.id || "";
}

function defaultSetupTargetId(clusters) {
  return centralClusterScId(clusters) || firstScId(clusters);
}

function firstRemoteScId(clusters) {
  const hit = (clusters || []).find((sc) => sc.sameAsCentralCluster === false);
  return hit?.id || "";
}

/** User-selected Target cluster for Setup, else lab value, else Central's SC. */
function readActiveScIdFromDom(clusters) {
  const list = clusters || [];
  const sameCb = document.getElementById("setupTargetSameAsCentral");
  if (sameCb?.checked) {
    return defaultSetupTargetId(list);
  }
  const sel = document.getElementById("setupTargetCluster");
  const fromSelect = (sel?.value || "").trim();
  if (fromSelect && list.some((c) => c.id === fromSelect)) return fromSelect;
  const lab = editingLab();
  const prev = lab?.activeSecuredClusterId || "";
  if (prev && list.some((c) => c.id === prev)) {
    const prevSc = list.find((c) => c.id === prev);
    if (prevSc && prevSc.sameAsCentralCluster === false) return prev;
  }
  return firstRemoteScId(list) || defaultSetupTargetId(list);
}

function setupTargetOptionLabel(sc) {
  return (sc.name || sc.id || "secured").trim() || "secured";
}

function syncSetupTargetControl(lab) {
  const block = document.getElementById("setupTargetBlock");
  const sameCb = document.getElementById("setupTargetSameAsCentral");
  const sel = document.getElementById("setupTargetCluster");
  const warn = document.getElementById("setupTargetWarn");
  if (!sameCb || !sel) return;

  const clusters = lab?.securedClusters || [];
  const centralId = centralClusterScId(clusters);
  let activeId =
    (lab?.activeSecuredClusterId &&
      clusters.some((c) => c.id === lab.activeSecuredClusterId) &&
      lab.activeSecuredClusterId) ||
    defaultSetupTargetId(clusters);

  const activeSc = clusters.find((c) => c.id === activeId);
  const sameAsCentral = Boolean(
    !clusters.length || !activeSc || activeSc.sameAsCentralCluster !== false
  );
  sameCb.checked = sameAsCentral;
  sameCb.disabled = !clusters.length;
  block?.classList.toggle("is-not-central", !sameAsCentral);

  if (sameAsCentral) {
    activeId = defaultSetupTargetId(clusters);
    sel.hidden = true;
    if (warn) warn.hidden = true;
  } else {
    sel.hidden = false;
    if (warn) warn.hidden = false;
    const remotes = clusters.filter((sc) => sc.sameAsCentralCluster === false);
    const options = remotes.length ? remotes : clusters.filter((sc) => sc.id !== centralId);
    sel.innerHTML = options
      .map(
        (sc) =>
          `<option value="${escapeHtml(sc.id)}">${escapeHtml(setupTargetOptionLabel(sc))}</option>`
      )
      .join("");
    if (!options.length) {
      sel.innerHTML = `<option value="">No remote secured clusters</option>`;
      sel.value = "";
      activeId = defaultSetupTargetId(clusters);
    } else if (activeId && options.some((c) => c.id === activeId)) {
      sel.value = activeId;
    } else {
      activeId = options[0].id;
      sel.value = activeId;
    }
  }

  if (lab) lab.activeSecuredClusterId = activeId;
  syncScModulesBadges(activeId);
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
        apiToken: row.querySelector(".js-sc-token")?.value || "",
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
  const mismatchText = document.getElementById("credDualMismatchText");
  const badge = document.getElementById("labActiveBadge");
  const detailLabel = document.getElementById("credDetailLabLabel");
  const lab = editingLab();
  const active = activeLab();
  const same = Boolean(editingLabId) && editingLabId === credDoc.activeLabId;
  if (badge) badge.hidden = !(lab && same);
  if (detailLabel) {
    detailLabel.textContent = lab?.name || lab?.id || "—";
  }
  if (!mismatch) return;
  if (lab && active && !same) {
    mismatch.hidden = false;
    if (mismatchText) {
      const viewing = lab.name || lab.id;
      const using = active.name || active.id;
      mismatchText.textContent = `Viewing “${viewing}”. Modules still use active lab “${using}”.`;
    }
  } else {
    mismatch.hidden = true;
  }
}

function updateFoldMetas(lab) {
  const centralMeta = document.getElementById("centralFoldMeta");
  const scMeta = document.getElementById("scFoldMeta");
  const slackMeta = document.getElementById("slackFoldMeta");
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
  const sn = lab?.slackNotifier || emptySlackNotifier();
  const defs = slackNotifierDefaults();
  const snName = (sn.notifierName || defs.notifierName || "#acs-demo-notifier").trim();
  const wh = (sn.webhookUrl || "").trim() || (defs.webhookUrl || "").trim();
  const ch = (sn.channelUrl || "").trim() || (defs.channelUrl || "").trim();
  const usingDefault =
    (!wh || wh === (defs.webhookUrl || "").trim()) &&
    (!sn.notifierName || sn.notifierName === defs.notifierName) &&
    (!ch || ch === (defs.channelUrl || "").trim());
  const whBit = !wh ? "no webhook" : usingDefault ? "default" : "custom";
  if (slackMeta) {
    slackMeta.textContent = `${snName} · ${whBit}`;
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
      <span>OpenShift Console URL</span>
      <input class="pf-v6-c-form-control js-sc-console" type="url" value="${escapeHtml(ocp.consoleUrl || "")}" spellcheck="false" />
    </label>
    <div class="demo-field-row">
      <label class="demo-field">
        <span>User</span>
        <input class="pf-v6-c-form-control js-sc-user" type="text" value="${escapeHtml(ocp.adminUsername || "")}" spellcheck="false" />
      </label>
      <label class="demo-field">
        <span>Password</span>
        <input class="pf-v6-c-form-control js-sc-password" type="text" value="${escapeHtml(ocp.adminPassword || "")}" spellcheck="false" autocomplete="off" placeholder="Or use API token" />
      </label>
    </div>
    <label class="demo-field">
      <span>API token</span>
      <input class="pf-v6-c-form-control js-sc-token" type="text" value="${escapeHtml(ocp.apiToken || "")}" spellcheck="false" autocomplete="off" placeholder="oc login --token=… (SSO labs)" />
    </label>`;
}

function scSameBodyHtml() {
  return `<label class="pf-v6-c-check">
      <input class="pf-v6-c-check__input js-sc-same" type="checkbox" checked />
      <span class="pf-v6-c-check__label">Same as Central</span>
    </label>
    <p class="demo-sc-hint" style="margin:0">Uses Central OpenShift console / user / password / API token.</p>`;
}

function renderSecuredClusters(lab) {
  if (!securedClusterList) return;
  const clusters = lab.securedClusters || [];
  const activeId =
    (lab.activeSecuredClusterId &&
      clusters.some((c) => c.id === lab.activeSecuredClusterId) &&
      lab.activeSecuredClusterId) ||
    defaultSetupTargetId(clusters);

  syncSetupTargetControl({ ...lab, activeSecuredClusterId: activeId });

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
      const isActive = sc.id === activeId;
      const modulesBadge = isActive
        ? `<span class="pf-v6-c-label pf-m-compact pf-m-green js-sc-modules-badge"><span class="pf-v6-c-label__content">Setup target</span></span>`
        : `<span class="pf-v6-c-label pf-m-compact pf-m-green js-sc-modules-badge" hidden><span class="pf-v6-c-label__content">Setup target</span></span>`;
      const body = same ? scSameBodyHtml() : scRemoteBodyHtml(sc, ocp);
      return `<details class="demo-sc-row" data-sc-id="${escapeHtml(sc.id)}">
        <summary class="demo-sc-row__summary">
          <span class="demo-sc-row__name js-sc-title">${escapeHtml(sc.name || "secured")}</span>
          <span class="pf-v6-c-label pf-m-compact ${badgeClass} js-sc-badge"><span class="pf-v6-c-label__content">${badgeText}</span></span>
          ${modulesBadge}
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

  updateFoldMetas({ ...lab, activeSecuredClusterId: activeId });
  setupCredentialCopyButtons();
  syncCredChrome();
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
    lab.activeSecuredClusterId = readActiveScIdFromDom(lab.securedClusters);
    syncSetupTargetControl(lab);
    updateFoldMetas(lab);
  }
}

function syncScModulesBadges(activeId) {
  securedClusterList?.querySelectorAll(".demo-sc-row").forEach((row) => {
    const badge = row.querySelector(".js-sc-modules-badge");
    if (!badge) return;
    badge.hidden = row.dataset.scId !== activeId;
  });
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
    apiToken: row.querySelector(".js-sc-token")?.value || "",
  };

  body.innerHTML = same ? scSameBodyHtml() : scRemoteBodyHtml({ name }, ocp);

  row.open = true;
  wireScRowBodyControls(row);
  refreshScRowChrome(row);
  setupCredentialCopyButtons();
  const lab = editingLab();
  if (lab) {
    lab.securedClusters = readSecuredClustersFromDom();
    lab.activeSecuredClusterId = readActiveScIdFromDom(lab.securedClusters);
    syncSetupTargetControl(lab);
  }
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
    let activeId = lab?.activeSecuredClusterId || "";
    if (!remaining.some((c) => c.id === activeId)) {
      activeId = defaultSetupTargetId(remaining);
    }
    if (lab) {
      lab.securedClusters = remaining;
      lab.activeSecuredClusterId = activeId;
      syncSetupTargetControl(lab);
    } else {
      syncScModulesBadges(activeId);
    }
    updateFoldMetas({
      ...(lab || {}),
      securedClusters: remaining,
      activeSecuredClusterId: activeId,
    });
    if (!remaining.length && securedClusterList) {
      securedClusterList.innerHTML =
        '<p class="demo-sc-empty">No secured clusters. Add one when a module needs sensor-side OpenShift.</p>';
    }
    syncCredChrome();
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
  const catalogLocked = busy || labUiBusy || credEditMode;
  btnMakeActive.disabled = catalogLocked || same || !editingLabId;
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
  } else if (credEditMode) {
    reason = "Save or Cancel lab edits first.";
  }
  btnDeleteLab.disabled = busy || labUiBusy || Boolean(reason);
  btnDeleteLab.title = reason || "Delete the selected lab";
}

function fillLabSelects() {
  const labs = credDoc.labs || [];
  const options = labs
    .map((lab) => {
      const label = lab.name || lab.id;
      const activeMark = lab.id === credDoc.activeLabId ? " (active)" : "";
      return `<option value="${escapeHtml(lab.id)}">${escapeHtml(label)}${activeMark}</option>`;
    })
    .join("");

  if (activeLabSelect) {
    activeLabSelect.innerHTML = options;
    activeLabSelect.value = credDoc.activeLabId || labs[0]?.id || "";
  }
  if (editLabSelect) {
    editLabSelect.innerHTML = options;
    editLabSelect.value = editingLabId || credDoc.activeLabId || labs[0]?.id || "";
  }
  syncCredChrome();
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
  if (fields.centralOcpApiToken) fields.centralOcpApiToken.value = ocp.apiToken || "";

  fields.centralConsole.value = central.consoleUrl || "";
  fields.centralApiToken.value = central.apiToken || "";
  fields.centralApiTokenName.value = central.apiTokenName || "";
  fields.centralApiTokenExpires.value = central.apiTokenExpires || "";
  fields.centralAdminUser.value = central.adminUsername || "";
  fields.centralAdminPassword.value = central.adminPassword || "";
  setAuthPref(central.authPreference);

  const sn = lab.slackNotifier || emptySlackNotifier();
  const snDefs = slackNotifierDefaults();
  if (fields.slackNotifierName) {
    fields.slackNotifierName.value =
      sn.notifierName || snDefs.notifierName || "#acs-demo-notifier";
  }
  if (fields.slackWebhookUrl) {
    fields.slackWebhookUrl.value = sn.webhookUrl || snDefs.webhookUrl || "";
  }
  if (fields.slackChannelUrl) {
    fields.slackChannelUrl.value = sn.channelUrl || snDefs.channelUrl || "";
  }

  const centralFold = document.getElementById("centralFold");
  if (centralFold) centralFold.open = false;
  const slackFold = document.getElementById("slackFold");
  if (slackFold) slackFold.open = false;

  renderSecuredClusters(lab);
  updateFoldMetas(lab);
  syncCredentialCopyButtons();
  syncCredChrome();
}

function buildCredentialsPayload() {
  const lab = editingLab() || emptyLab();
  const scRows = readSecuredClustersFromDom();
  const activeSc = readActiveScIdFromDom(scRows);

  const updatedLab = {
    id: lab.id,
    name: (fields.labName?.value || lab.name || lab.id).trim(),
    insecureSkipTlsVerify: Boolean(fields.insecureSkipTlsVerify?.checked),
    centralCluster: {
      openshift: {
        consoleUrl: fields.centralOcpConsole.value,
        adminUsername: fields.centralOcpUser.value,
        adminPassword: fields.centralOcpPassword.value,
        apiToken: fields.centralOcpApiToken?.value || "",
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
    slackNotifier: {
      webhookUrl: fields.slackWebhookUrl?.value || "",
      notifierName: (fields.slackNotifierName?.value || "").trim() || "#acs-demo-notifier",
      channelUrl: fields.slackChannelUrl?.value || "",
    },
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
  syncCredChrome();
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
    syncCredChrome();
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
  if (credEditMode) {
    setCredFeedback("Save or Cancel lab edits before switching the active lab.", true);
    fillLabSelects();
    return;
  }
  labUiBusy = true;
  setCredFeedback("");
  try {
    await setActiveLabOnly(labId);
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    fillLabSelects();
  } finally {
    labUiBusy = false;
    syncCredChrome();
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

function setCredEditMode(on) {
  credEditMode = Boolean(on);
  syncCredChrome();
}

function syncCredChrome() {
  const form = document.getElementById("credForm");
  const btnEdit = document.getElementById("btnCredEdit");
  const btnSave = document.getElementById("btnCredSave");
  const btnCancel = document.getElementById("btnCredCancel");
  const btnAdd = document.getElementById("btnAddLab");
  const btnAddSc = document.getElementById("btnAddSecuredCluster");
  const dirty = isEditingLabDirty();
  const catalogLocked = busy || labUiBusy || credEditMode;

  if (form) form.classList.toggle("is-readonly", !credEditMode);
  if (btnEdit) {
    btnEdit.hidden = credEditMode;
    btnEdit.disabled = busy || labUiBusy;
  }
  if (btnSave) {
    btnSave.hidden = !credEditMode;
    btnSave.disabled = busy || labUiBusy || !dirty;
  }
  if (btnCancel) {
    btnCancel.hidden = !credEditMode;
    btnCancel.disabled = busy || labUiBusy;
  }
  if (editLabSelect) editLabSelect.disabled = catalogLocked;
  if (btnAdd) {
    btnAdd.disabled = catalogLocked;
    btnAdd.title = credEditMode
      ? "Save or Cancel lab edits first."
      : "Add a new lab to this file";
  }

  form?.querySelectorAll("input, select, textarea").forEach((el) => {
    el.disabled = !credEditMode || busy || labUiBusy;
  });
  form?.querySelectorAll("button.js-sc-remove").forEach((el) => {
    el.disabled = !credEditMode || busy || labUiBusy;
  });
  if (btnAddSc) btnAddSc.disabled = !credEditMode || busy || labUiBusy;

  syncMakeActiveButton();
  syncDeleteLabButton();
  syncCredentialCopyButtons();
  updateCredPanelChrome();
}

async function cancelEditingLab() {
  if (labUiBusy || !credEditMode) return;
  labUiBusy = true;
  setCredFeedback("");
  try {
    if (isEditingLabDirty()) {
      const data = await api("/api/credentials");
      applyCredentialsResponse(data, { keepEditingId: editingLabId });
      setCredFeedback("Reverted to file.");
    } else {
      setCredFeedback("");
    }
    setCredEditMode(false);
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncCredChrome();
  }
}

async function switchEditingLab(labId) {
  if (!labId || labId === editingLabId || labUiBusy) return;
  if (credEditMode) {
    setCredFeedback("Save or Cancel lab edits before switching labs.", true);
    fillLabSelects();
    return;
  }
  labUiBusy = true;
  setCredFeedback("");
  try {
    // Always reload from disk so the form shows file state, not in-memory edits.
    const data = await api("/api/credentials");
    applyCredentialsResponse(data, { keepEditingId: labId });
    setCredEditMode(false);
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
    fillLabSelects();
  } finally {
    labUiBusy = false;
    syncCredChrome();
  }
}

async function makeEditingLabActive() {
  if (!editingLabId || editingLabId === credDoc.activeLabId || labUiBusy || credEditMode) {
    return;
  }
  labUiBusy = true;
  setCredFeedback("");
  try {
    await setActiveLabOnly(editingLabId);
    setCredFeedback("Active lab updated.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncCredChrome();
  }
}

async function addLab() {
  if (credEditMode) {
    setCredFeedback("Save or Cancel lab edits before adding a lab.", true);
    return;
  }
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
    setCredEditMode(true);
    setCredFeedback("Lab added. Fill in details, Save, then Use as active when ready.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncCredChrome();
  }
}

async function deleteEditingLab() {
  if (credEditMode) {
    setCredFeedback("Save or Cancel lab edits before deleting a lab.", true);
    return;
  }
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
    setCredEditMode(false);
    setCredFeedback("Lab deleted.");
  } catch (err) {
    setCredFeedback(String(err.message || err), true);
  } finally {
    labUiBusy = false;
    syncCredChrome();
  }
}

function addSecuredCluster() {
  if (!credEditMode) return;
  const lab = editingLab();
  if (!lab) return;
  const current = readSecuredClustersFromDom();
  const sc = emptySecuredCluster(`secured-${current.length + 1}`);
  sc.sameAsCentralCluster = false;
  const next = [...current, sc];
  // Keep existing Setup target; only default to Central's cluster when none yet.
  let activeId = lab.activeSecuredClusterId || "";
  if (!current.some((c) => c.id === activeId)) {
    activeId = defaultSetupTargetId(next);
  }
  // Draft in DOM only; Save writes it. Avoid mutating credDoc so dirty tracking works.
  const draft = {
    ...lab,
    securedClusters: next,
    activeSecuredClusterId: activeId,
  };
  renderSecuredClusters(draft);
  const row = securedClusterList?.querySelector(`[data-sc-id="${CSS.escape(sc.id)}"]`);
  if (row) row.open = true;
  syncCredChrome();
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
      apiToken: fields.centralOcpApiToken?.value || "",
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
  lab.activeSecuredClusterId = readActiveScIdFromDom(lab.securedClusters);
  updateFoldMetas(lab);
}

fields.centralConsole?.addEventListener("input", refreshFoldMetasFromForm);
fields.centralApiToken?.addEventListener("input", refreshFoldMetasFromForm);
fields.labName?.addEventListener("input", refreshFoldMetasFromForm);
fields.centralOcpConsole?.addEventListener("input", refreshFoldMetasFromForm);

document.getElementById("btnCredEdit")?.addEventListener("click", (e) => {
  e.preventDefault();
  if (busy || labUiBusy) return;
  setCredFeedback("");
  setCredEditMode(true);
});
document.getElementById("btnCredSave")?.addEventListener("click", (e) => {
  e.preventDefault();
  saveCredentials();
});
document.getElementById("btnCredCancel")?.addEventListener("click", (e) => {
  e.preventDefault();
  cancelEditingLab().catch((err) => setCredFeedback(err.message, true));
});

// Keep Save enabled/disabled as the form changes while editing.
const credFormEl = document.getElementById("credForm");
credFormEl?.addEventListener("input", () => {
  if (credEditMode) syncCredChrome();
});
credFormEl?.addEventListener("change", () => {
  if (credEditMode) syncCredChrome();
});
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

function onSetupTargetControlChange() {
  const lab = editingLab();
  if (!lab) return;
  lab.securedClusters = readSecuredClustersFromDom();
  // If leaving "Same as Central" with an empty/stale select, seed first remote first.
  const sameCb = document.getElementById("setupTargetSameAsCentral");
  if (!sameCb?.checked) {
    const sel = document.getElementById("setupTargetCluster");
    const remotes = lab.securedClusters.filter((sc) => sc.sameAsCentralCluster === false);
    const cur = (sel?.value || "").trim();
    if (!cur || !remotes.some((c) => c.id === cur)) {
      const seed =
        (lab.activeSecuredClusterId &&
          remotes.some((c) => c.id === lab.activeSecuredClusterId) &&
          lab.activeSecuredClusterId) ||
        firstRemoteScId(lab.securedClusters);
      if (sel && seed) {
        sel.innerHTML = remotes
          .map(
            (sc) =>
              `<option value="${escapeHtml(sc.id)}">${escapeHtml(setupTargetOptionLabel(sc))}</option>`
          )
          .join("");
        sel.value = seed;
      }
    }
  }
  lab.activeSecuredClusterId = readActiveScIdFromDom(lab.securedClusters);
  syncSetupTargetControl(lab);
  updateFoldMetas(lab);
  syncCredChrome();
}

document
  .getElementById("setupTargetSameAsCentral")
  ?.addEventListener("change", onSetupTargetControlChange);
document
  .getElementById("setupTargetCluster")
  ?.addEventListener("change", onSetupTargetControlChange);
document.getElementById("btnSlackRestoreDefaults")?.addEventListener("click", (e) => {
  e.preventDefault();
  restoreSlackNotifierDefaults();
});
document.getElementById("btnSlackOpenChannel")?.addEventListener("click", (e) => {
  e.preventDefault();
  const raw = (
    fields.slackChannelUrl?.value ||
    slackNotifierDefaults().channelUrl ||
    ""
  ).trim();
  if (!raw) return;
  const href = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  window.open(href, "_blank", "noopener,noreferrer");
});
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
setupHelpMenu();
setupModuleHelpDialog();
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
    // Version + soft update nudge (non-blocking vs status refresh).
    void loadInstalledVersionAndMaybeNudge();
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
