/**
 * Single Markdown → HTML entry point for the ACS demo setup GUI.
 *
 * All UI surfaces (module Help dialog, /static/help.html) must call
 * ACS.md.render(text). Do not call marked / DOMPurify directly from pages.
 *
 * Engine: marked + DOMPurify.
 */
(function (global) {
  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ensureExternalLinks(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("a[href]").forEach(function (a) {
      const href = a.getAttribute("href") || "";
      // Keep in-app anchors / relative help paths in the same tab.
      if (href.startsWith("#") || href.startsWith("/")) return;
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
  }

  function sanitize(html) {
    if (typeof global.DOMPurify !== "undefined" && global.DOMPurify.sanitize) {
      // Prefer hook so target/_blank survives sanitization.
      if (!global.__acsMdLinkHook) {
        global.DOMPurify.addHook("afterSanitizeAttributes", function (node) {
          if (node.tagName !== "A" || !node.hasAttribute("href")) return;
          const href = node.getAttribute("href") || "";
          if (href.startsWith("#") || href.startsWith("/")) return;
          node.setAttribute("target", "_blank");
          node.setAttribute("rel", "noopener noreferrer");
        });
        global.__acsMdLinkHook = true;
      }
      return global.DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ["target"],
      });
    }
    return html;
  }

  function render(src) {
    const m = global.marked;
    if (!m || typeof m.parse !== "function") {
      return (
        '<pre class="acs-md__fallback">' +
        escapeHtml(String(src || "")) +
        "</pre>"
      );
    }
    try {
      if (typeof m.setOptions === "function") {
        m.setOptions({ gfm: true, breaks: false });
      }
      const html = sanitize(m.parse(String(src || "")));
      const wrap = global.document
        ? global.document.createElement("div")
        : null;
      if (wrap) {
        wrap.className = "acs-md";
        wrap.innerHTML = html;
        ensureExternalLinks(wrap);
        return wrap.outerHTML;
      }
      return '<div class="acs-md">' + html + "</div>";
    } catch (err) {
      return (
        '<p class="acs-md__err">Markdown render failed: ' +
        escapeHtml(err && err.message ? err.message : err) +
        '</p><pre class="acs-md__fallback">' +
        escapeHtml(String(src || "")) +
        "</pre>"
      );
    }
  }

  global.ACS = global.ACS || {};
  global.ACS.md = { render };
})(typeof window !== "undefined" ? window : globalThis);
