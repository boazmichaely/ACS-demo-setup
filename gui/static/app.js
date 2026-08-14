const modulesBody = document.getElementById("modules-body");
const statusError = document.getElementById("status-error");
const refreshBtn = document.getElementById("refresh-btn");
const credentialsForm = document.getElementById("credentials-form");
const endpointInput = document.getElementById("endpoint");
const tokenInput = document.getElementById("token");
const tokenHint = document.getElementById("token-hint");
const credentialsMessage = document.getElementById("credentials-message");
const outputDialog = document.getElementById("output-dialog");
const outputTitle = document.getElementById("output-title");
const outputBody = document.getElementById("output-body");

function badgeClass(state) {
  if (state === "ok") return "badge badge-ok";
  if (state === "error") return "badge badge-error";
  return "badge badge-needs-run";
}

function showMessage(el, text, isError = false) {
  el.textContent = text;
  el.hidden = !text;
  el.classList.toggle("message-error", isError);
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

async function loadCredentials() {
  const data = await api("/api/credentials");
  endpointInput.value = data.endpoint || "";
  if (data.has_token) {
    tokenHint.textContent = `Saved token: ${data.token_masked} (leave blank to keep)`;
  } else {
    tokenHint.textContent = "No token saved yet.";
  }
}

async function loadStatus() {
  showMessage(statusError, "");
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
      body: JSON.stringify({
        endpoint: endpointInput.value,
        token: tokenInput.value,
      }),
    });
    tokenInput.value = "";
    await loadCredentials();
    showMessage(credentialsMessage, "Credentials saved.");
  } catch (err) {
    showMessage(credentialsMessage, String(err.message || err), true);
  }
});

refreshBtn.addEventListener("click", () => {
  loadStatus().catch((err) => showMessage(statusError, String(err.message || err), true));
});

async function init() {
  try {
    await loadCredentials();
    await loadStatus();
  } catch (err) {
    showMessage(statusError, String(err.message || err), true);
    modulesBody.innerHTML =
      '<tr><td colspan="5" class="loading">Failed to load status.</td></tr>';
  }
}

init();
