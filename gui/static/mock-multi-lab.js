/**
 * Visual-mock only. Compact layout; Central folded closed by default.
 */
(function () {
  const LABS = {
    "bm-50rc4": {
      name: "bm-50rc4 (OCP 5 lab)",
      skipTls: true,
      ocpConsole:
        "https://console-openshift-console.apps.bm-50rc4-on-ocp5.ocp.infra.rox.systems",
      ocpUser: "kubeadmin",
      centralConsole:
        "https://central-stackrox.apps.bm-50rc4-on-ocp5.ocp.infra.rox.systems",
      tokenName: "Cursor-exp-2026-12-31",
      hasToken: true,
      securedClusters: [
        { id: "production", title: "production", sameAsCentral: true, open: false },
        {
          id: "edge-west",
          title: "edge-west",
          sameAsCentral: false,
          open: false,
          consoleUrl:
            "https://console-openshift-console.apps.edge-west.example.com",
          user: "kubeadmin",
        },
      ],
    },
    acscs: {
      name: "ACSCS",
      skipTls: false,
      ocpConsole: "",
      ocpUser: "",
      centralConsole:
        "https://acs-crk41vjao4tlkd9ulr8g.acs.rhcloud.com/main/dashboard",
      tokenName: "",
      hasToken: false,
      securedClusters: [
        {
          id: "customer-prod",
          title: "customer-prod",
          sameAsCentral: false,
          open: false,
          consoleUrl:
            "https://console-openshift-console.apps.customer-prod.example.com",
          user: "kubeadmin",
        },
        {
          id: "customer-edge",
          title: "customer-edge",
          sameAsCentral: false,
          open: false,
          consoleUrl:
            "https://console-openshift-console.apps.customer-edge.example.com",
          user: "kubeadmin",
        },
      ],
    },
  };

  let activeLabId = "bm-50rc4";
  let editingLabId = "bm-50rc4";

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function hostOf(url) {
    return String(url || "")
      .replace(/^https?:\/\//, "")
      .replace(/\/.*$/, "");
  }

  function scSub(sc) {
    if (sc.sameAsCentral) return "Same OpenShift as Central";
    return hostOf(sc.consoleUrl) || "needs OCP login";
  }

  function scRowHtml(sc) {
    const openAttr = sc.open ? " open" : "";
    const badge = sc.sameAsCentral
      ? `<span class="sc-row__badge">Same as Central</span>`
      : `<span class="sc-row__badge sc-row__badge--remote">Remote</span>`;

    const nameField = sc.sameAsCentral
      ? ""
      : `<label class="sc-inline">
          <span class="sc-inline__label">Name</span>
          <input class="pf-v5-c-form-control sc-inline__input" type="text" readonly value="${esc(sc.title)}" />
        </label>`;

    const ocpFields = sc.sameAsCentral
      ? `<p class="sc-row__note">Uses Central OpenShift credentials above.</p>`
      : `<div class="pf-v5-c-form__group">
          <label class="pf-v5-c-form__label">Console URL</label>
          <input class="pf-v5-c-form-control" type="text" readonly value="${esc(sc.consoleUrl || "")}" />
        </div>
        <div class="cred-form-row cred-form-row--pair">
          <div class="pf-v5-c-form__group">
            <label class="pf-v5-c-form__label">User</label>
            <input class="pf-v5-c-form-control" type="text" readonly value="${esc(sc.user || "")}" />
          </div>
          <div class="pf-v5-c-form__group">
            <label class="pf-v5-c-form__label">Password</label>
            <input class="pf-v5-c-form-control" type="text" readonly value="••••••••" />
          </div>
        </div>`;

    return `
      <details class="sc-row"${openAttr}>
        <summary class="sc-row__summary">
          <span class="sc-row__chev" aria-hidden="true"></span>
          <span class="sc-row__title">${esc(sc.title)}</span>
          ${badge}
          <span class="sc-row__sub">${esc(scSub(sc))}</span>
          <button type="button" class="pf-v5-c-button pf-m-plain sc-row__remove" disabled
            title="Remove" onclick="event.preventDefault(); event.stopPropagation();">Remove</button>
        </summary>
        <div class="sc-row__body">
          <div class="sc-row__top">
            ${nameField}
            <label class="pf-v5-c-check cred-same-cluster">
              <input class="pf-v5-c-check__input" type="checkbox"${sc.sameAsCentral ? " checked" : ""} disabled />
              <span class="pf-v5-c-check__label">Same as Central</span>
            </label>
          </div>
          ${ocpFields}
        </div>
      </details>`;
  }

  function stamp() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function appendLog(line) {
    const el = document.getElementById("mockLog");
    if (!el) return;
    el.textContent += `${line}\n`;
    el.scrollTop = el.scrollHeight;
  }

  function renderActiveStrip() {
    const lab = LABS[activeLabId];
    if (!lab) return;
    document.getElementById("mockLabName").textContent = lab.name;
    document.getElementById("mockLabHint").textContent =
      `Central · ${hostOf(lab.centralConsole)}`;
    document.getElementById("mockActiveLabSelect").value = activeLabId;
  }

  function renderEditingForm() {
    const lab = LABS[editingLabId];
    if (!lab) return;

    document.getElementById("mockEditLabSelect").value = editingLabId;
    document.getElementById("mockLabDisplayName").value = lab.name;
    document.getElementById("mockSkipTls").checked = Boolean(lab.skipTls);
    document.getElementById("mockOcpConsole").value = lab.ocpConsole || "";
    document.getElementById("mockOcpUser").value = lab.ocpUser || "";
    document.getElementById("mockCentralConsole").value = lab.centralConsole || "";
    document.getElementById("mockTokenName").value = lab.tokenName || "";

    const tokenBit = lab.hasToken ? "token set" : "no token";
    document.getElementById("mockCentralSummary").textContent =
      `${hostOf(lab.centralConsole) || "no Central URL"} · ${tokenBit}`;

    const n = lab.securedClusters.length;
    const remote = lab.securedClusters.filter((s) => !s.sameAsCentral).length;
    document.getElementById("mockScSummary").textContent =
      `${n} cluster${n === 1 ? "" : "s"}${remote ? ` · ${remote} remote` : ""}`;

    document.getElementById("mockScList").innerHTML = lab.securedClusters
      .map(scRowHtml)
      .join("");
  }

  function render({ reason }) {
    renderActiveStrip();
    renderEditingForm();
    appendLog(
      `── ${stamp()} ${reason} active=${activeLabId} editing=${editingLabId}`
    );
  }

  const activeSel = document.getElementById("mockActiveLabSelect");
  const editSel = document.getElementById("mockEditLabSelect");
  if (!activeSel || !editSel) return;

  render({ reason: "page-load" });
  activeSel.addEventListener("change", () => {
    activeLabId = activeSel.value;
    render({ reason: "active-lab" });
  });
  editSel.addEventListener("change", () => {
    editingLabId = editSel.value;
    render({ reason: "edit-lab" });
  });
})();
