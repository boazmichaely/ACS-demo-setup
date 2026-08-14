/**
 * ACS demo setup GUI — PatternFly v5 (see REQUIREMENTS-GUI.md)
 */

const logEl = document.getElementById("log");
const statusWrap = document.getElementById("statusWrap");
const statusRefreshIndicator = document.getElementById("statusRefreshIndicator");
const btnModulesExpandAll = document.getElementById("btnModulesExpandAll");
const credFilePath = document.getElementById("credFilePath");
const credSaveFeedback = document.getElementById("credSaveFeedback");

let registryModules = [];
let lastStatusModules = [];
let lastStatusMap = new Map();
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
  for (const id of ["btnCredSave", "btnStatus", "btnRunFull"]) {
    const el = document.getElementById(id);
    if (el) el.disabled = on;
  }
  statusWrap?.querySelectorAll(".js-mod-run, .js-mod-dry-run").forEach((btn) => {
    btn.disabled = on;
  });
}

function setCredFeedback(text, isError = false) {
  if (!credSaveFeedback) return;
  credSaveFeedback.textContent = text || "";
  credSaveFeedback.classList.toggle("cred-save-feedback--err", Boolean(isError));
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
      return { label: "Ready", badge: "module-status-badge--ready", icon: "✓" };
    case "error":
      return { label: "Error", badge: "module-status-badge--blocked", icon: "⚠" };
    case "needs-run":
    default:
      return { label: "Needs run", badge: "module-status-badge--partial", icon: "◐" };
  }
}

function statusMapFromModules(modules) {
  const map = new Map();
  for (const row of modules || []) {
    if (!row?.id) continue;
    map.set(row.id, { state: row.state || "", message: row.message || "" });
  }
  return map;
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

function depsMet(moduleId) {
  const meta = registryModules.find((m) => m.id === moduleId);
  if (!meta?.dependsOn?.length) return true;
  return meta.dependsOn.every((dep) => lastStatusMap.get(dep)?.state === "ok");
}

function missingDeps(moduleId) {
  const meta = registryModules.find((m) => m.id === moduleId);
  if (!meta?.dependsOn?.length) return [];
  return meta.dependsOn.filter((dep) => lastStatusMap.get(dep)?.state !== "ok");
}

function renderModulesPanel() {
  if (!statusWrap) return;

  const modules = lastStatusModules.length ? lastStatusModules : registryModules;
  if (!modules.length) {
    statusWrap.innerHTML =
      '<p class="pf-v5-c-helper-text">No modules loaded.</p>';
    btnModulesExpandAll.disabled = true;
    return;
  }

  statusWrap.innerHTML = modules
    .map((row) => {
      const id = row.id;
      const st = lastStatusMap.get(id);
      const msg = escapeHtml(st?.message || row.message || "—");
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

  btnModulesExpandAll.disabled = false;

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
  if (!btnModulesExpandAll || !statusWrap) return;
  let expanded = false;
  btnModulesExpandAll.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    expanded = !expanded;
    statusWrap.querySelectorAll("details.pf-block").forEach((d) => {
      d.open = expanded;
    });
    btnModulesExpandAll.setAttribute(
      "aria-label",
      expanded ? "Collapse all modules" : "Expand all modules"
    );
  });
}

async function fetchStatus() {
  const data = await api("/api/status");
  lastStatusModules = data;
  lastStatusMap = statusMapFromModules(data);
}

async function refreshAllStatus() {
  setBusy(true);
  setStatusIndicator("Refreshing…");
  try {
    await fetchStatus();
    renderModulesPanel();
  } finally {
    setBusy(false);
    setStatusIndicator("");
  }
}

async function executeModuleRun(moduleId, dryRun) {
  const result = await api(
    `/api/run/${encodeURIComponent(moduleId)}?dry_run=${dryRun}`,
    { method: "POST" }
  );
  if (result.stdout) log(`${result.stdout}\n`);
  if (result.stderr) log(`${result.stderr}\n`);
  log(`exit code: ${result.exit_code}\n`);
}

async function runModule(moduleId, dryRun = false) {
  if (!moduleId) return;
  const label = dryRun ? "Dry run" : "Run";
  setBusy(true);
  logSection(`${label}: ${moduleId}`);

  try {
    await executeModuleRun(moduleId, dryRun);
    await fetchStatus();
    renderModulesPanel();
  } finally {
    setBusy(false);
  }
}

async function runAllModules(dryRun = false) {
  const ids = registryModules.map((m) => m.id);
  const label = dryRun ? "Dry run all" : "Run full install";
  setBusy(true);
  clearLog();
  logSection(label);

  try {
    for (const moduleId of ids) {
      logSection(`${dryRun ? "Dry run" : "Run"}: ${moduleId}`);
      await executeModuleRun(moduleId, dryRun);
    }
    await fetchStatus();
    renderModulesPanel();
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
}

document.getElementById("btnCredSave").addEventListener("click", saveCredentials);
document.getElementById("btnStatus").addEventListener("click", () => {
  refreshAllStatus().catch((e) => log(`\n${e.message}\n`));
});
document.getElementById("btnRunFull").addEventListener("click", () => {
  runAllModules(false).catch((e) => log(`\n${e.message}\n`));
});

setupExpandAll();

async function init() {
  try {
    await loadRegistry();
    await loadCredentials();
    await refreshAllStatus();
  } catch (err) {
    log(`\n${err.message}\n`);
    if (statusWrap) {
      statusWrap.innerHTML = `<p class="err">${escapeHtml(err.message)}</p>`;
    }
  }
}

init();
