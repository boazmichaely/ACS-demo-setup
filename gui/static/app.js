const modulesBody = document.getElementById("modules-body");
const statusError = document.getElementById("status-error");
const refreshBtn = document.getElementById("refresh-btn");
const credentialsForm = document.getElementById("credentials-form");
const credentialsMessage = document.getElementById("credentials-message");
const credFilePath = document.getElementById("cred-file-path");
const securedSameCheckbox = document.getElementById("secured-same-as-central");
const securedOcpSection = document.getElementById("secured-ocp-section");
const outputDialog = document.getElementById("output-dialog");
const outputTitle = document.getElementById("output-title");
const outputBody = document.getElementById("output-body");

const fields = {
  centralOcpConsole: document.getElementById("central-ocp-console"),
  centralOcpUser: document.getElementById("central-ocp-user"),
  centralOcpPassword: document.getElementById("central-ocp-password"),
  centralConsole: document.getElementById("central-console"),
  centralApiToken: document.getElementById("central-api-token"),
  centralAdminUser: document.getElementById("central-admin-user"),
  centralAdminPassword: document.getElementById("central-admin-password"),
  securedOcpConsole: document.getElementById("secured-ocp-console"),
  securedOcpUser: document.getElementById("secured-ocp-user"),
  securedOcpPassword: document.getElementById("secured-ocp-password"),
};

const hints = {
  centralOcpPw: document.getElementById("central-ocp-pw-hint"),
  centralToken: document.getElementById("central-token-hint"),
  centralAdminPw: document.getElementById("central-admin-pw-hint"),
  securedOcpPw: document.getElementById("secured-ocp-pw-hint"),
};

function badgeClass(state) {
  if (state === "ok") return "badge badge-ok";
  if (state === "error") return "badge badge-error";
  return "badge badge-needs-run";
}

function showMessage(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle("cred-save-feedback--err", isError);
}

function secretHint(el, hasSecret, masked, label) {
  if (hasSecret) {
    el.textContent = `${label} saved (${masked}). Leave blank to keep.`;
  } else {
    el.textContent =
      label === "OCP admin password"
        ? "Optional — leave blank if you use oc login."
        : `No ${label.toLowerCase()} saved yet.`;
  }
}

function setSecuredSectionVisible(sameAsCentral) {
  securedOcpSection.hidden = sameAsCentral;
  securedOcpSection.classList.toggle("cred-subsection--disabled", sameAsCentral);
  fields.securedOcpConsole.disabled = sameAsCentral;
  fields.securedOcpUser.disabled = sameAsCentral;
  fields.securedOcpPassword.disabled = sameAsCentral;
}

securedSameCheckbox.addEventListener("change", () => {
  setSecuredSectionVisible(securedSameCheckbox.checked);
});

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

function renderModules(rows) {
  if (!rows.length) {
    modulesBody.innerHTML =
      '<tr><td colspan="5" class="loading">No modules in config.</td></tr>';
    return;
  }

  modulesBody.innerHTML = rows
    .map(
      (row) => `
    <tr data-module-id="${escapeHtml(row.id)}">
      <td>${row.number}</td>
      <td>
        <div class="module-label">${escapeHtml(row.label)}</div>
        <div class="module-id">${escapeHtml(row.id)}</div>
      </td>
      <td><span class="${badgeClass(row.state)}">${escapeHtml(row.state)}</span></td>
      <td>${escapeHtml(row.message || "")}</td>
      <td>
        <div class="actions">
          <button type="button" class="btn btn-small btn-run" data-dry-run="false">Run</button>
          <button type="button" class="btn btn-small btn-run" data-dry-run="true">Dry run</button>
        </div>
      </td>
    </tr>`
    )
    .join("");

  modulesBody.querySelectorAll(".btn-run").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tr = btn.closest("tr");
      const moduleId = tr?.dataset.moduleId;
      const dryRun = btn.dataset.dryRun === "true";
      if (moduleId) runModule(moduleId, dryRun);
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function authPrefValue() {
  const selected = credentialsForm.querySelector(
    'input[name="centralAuthPref"]:checked'
  );
  return selected?.value === "password" ? "password" : "apiToken";
}

function setAuthPref(value) {
  const radio = credentialsForm.querySelector(
    `input[name="centralAuthPref"][value="${value === "password" ? "password" : "apiToken"}"]`
  );
  if (radio) radio.checked = true;
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
  securedSameCheckbox.checked = sc.sameAsCentralCluster !== false;
  setSecuredSectionVisible(securedSameCheckbox.checked);
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
      sameAsCentralCluster: securedSameCheckbox.checked,
      openshift: {
        consoleUrl: fields.securedOcpConsole.value,
        adminUsername: fields.securedOcpUser.value,
        adminPassword: fields.securedOcpPassword.value,
      },
    },
  };
}

async function loadStatus() {
  showMessage(statusError, "");
  statusError.hidden = true;
  modulesBody.innerHTML =
    '<tr><td colspan="5" class="loading">Loading…</td></tr>';
  const rows = await api("/api/status");
  renderModules(rows);
}

async function runModule(moduleId, dryRun) {
  const label = dryRun ? "Dry run" : "Run";
  outputTitle.textContent = `${label}: ${moduleId}`;
  outputBody.textContent = "Running…";
  outputDialog.showModal();

  try {
    const result = await api(
      `/api/run/${encodeURIComponent(moduleId)}?dry_run=${dryRun}`,
      { method: "POST" }
    );
    const chunks = [
      `exit code: ${result.exit_code}`,
      result.stdout ? `stdout:\n${result.stdout}` : "",
      result.stderr ? `stderr:\n${result.stderr}` : "",
    ].filter(Boolean);
    outputBody.textContent = chunks.join("\n\n") || "(no output)";
    await loadStatus();
  } catch (err) {
    outputBody.textContent = String(err.message || err);
  }
}

credentialsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showMessage(credentialsMessage, "");
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
    showMessage(credentialsMessage, "Saved.");
  } catch (err) {
    showMessage(credentialsMessage, String(err.message || err), true);
  }
});

refreshBtn.addEventListener("click", () => {
  loadStatus().catch((err) => {
    statusError.textContent = String(err.message || err);
    statusError.hidden = false;
  });
});

async function init() {
  try {
    await loadCredentials();
    await loadStatus();
  } catch (err) {
    statusError.textContent = String(err.message || err);
    statusError.hidden = false;
    modulesBody.innerHTML =
      '<tr><td colspan="5" class="loading">Failed to load status.</td></tr>';
  }
}

init();
