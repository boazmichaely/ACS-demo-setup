#!/usr/bin/env python3
"""Generic TCP syslog/CEF receiver with in-memory ring buffer and HTML viewer.

Listens:
  - TCP :5140  syslog (newline or octet-counting frames; CEF payload)
  - HTTP :8080 viewer UI + JSON API

Env:
  RING_SIZE   max buffered messages (default 100)
  SYSLOG_PORT default 5140
  HTTP_PORT   default 8080
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

RING_SIZE = max(1, int(os.environ.get("RING_SIZE", "100")))
SYSLOG_PORT = int(os.environ.get("SYSLOG_PORT", "5140"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))

_lock = threading.Lock()
_messages: deque[dict[str, Any]] = deque(maxlen=RING_SIZE)
_seq = 0

CEF_RE = re.compile(r"CEF:(\d+)\|")
PRI_RE = re.compile(r"^<\d+>")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_cef(raw: str) -> dict[str, Any]:
    """Parse CEF header + extension map. Returns structured fields; never raises."""
    text = (raw or "").strip()
    text = PRI_RE.sub("", text).strip()
    idx = text.find("CEF:")
    if idx < 0:
        return {"ok": False, "error": "no CEF: marker", "header": {}, "extensions": {}}
    text = text[idx:]
    if not CEF_RE.match(text):
        return {
            "ok": False,
            "error": "malformed CEF header",
            "header": {},
            "extensions": {},
        }
    # Split on unescaped pipes after "CEF:" → 7 header fields + extension remainder.
    parts: list[str] = []
    buf: list[str] = []
    i = 4  # after CEF:
    while i < len(text) and len(parts) < 7:
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == "|":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if len(parts) < 7:
        return {
            "ok": False,
            "error": f"expected 7 header fields, got {len(parts)}",
            "header": {},
            "extensions": {},
        }
    extension_raw = text[i:]
    header = {
        "cefVersion": parts[0],
        "deviceVendor": parts[1],
        "deviceProduct": parts[2],
        "deviceVersion": parts[3],
        "signatureId": parts[4],
        "name": parts[5],
        "severity": parts[6],
    }
    return {
        "ok": True,
        "error": "",
        "header": header,
        "extensions": _parse_extensions(extension_raw),
    }


def _parse_extensions(raw: str) -> dict[str, str]:
    """Parse CEF extension key=value pairs (space-separated, backslash escapes)."""
    out: dict[str, str] = {}
    if not raw or not raw.strip():
        return out
    s = raw.strip()
    key = ""
    key_chars: list[str] = []
    val_chars: list[str] = []
    state = "key"
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if state == "key":
                key_chars.append(nxt)
            else:
                val_chars.append(nxt)
            i += 2
            continue
        if state == "key":
            if ch == "=":
                key = "".join(key_chars).strip()
                key_chars = []
                val_chars = []
                state = "val"
                i += 1
                continue
            key_chars.append(ch)
            i += 1
            continue
        if ch == " ":
            rest = s[i + 1 :]
            if re.match(r"[A-Za-z][A-Za-z0-9.]*=", rest):
                if key:
                    out[key] = "".join(val_chars)
                key = ""
                key_chars = []
                val_chars = []
                state = "key"
                i += 1
                continue
            val_chars.append(ch)
            i += 1
            continue
        val_chars.append(ch)
        i += 1
    if state == "val" and key:
        out[key] = "".join(val_chars)
    return out


def store_message(raw: str, peer: str) -> dict[str, Any]:
    global _seq
    parsed = parse_cef(raw)
    with _lock:
        _seq += 1
        msg = {
            "id": str(uuid.uuid4()),
            "seq": _seq,
            "receivedAt": _utc_now(),
            "peer": peer,
            "raw": raw.strip(),
            "parsed": parsed,
        }
        _messages.appendleft(msg)
        return msg


def list_messages() -> list[dict[str, Any]]:
    with _lock:
        return list(_messages)


def get_message(msg_id: str) -> dict[str, Any] | None:
    with _lock:
        for m in _messages:
            if m.get("id") == msg_id:
                return m
    return None


def clear_messages() -> int:
    with _lock:
        n = len(_messages)
        _messages.clear()
        return n


def _read_syslog_frame(conn: socket.socket) -> str | None:
    """Read one syslog frame (octet-counting or newline-delimited)."""
    conn.settimeout(120.0)
    first = conn.recv(1)
    if not first:
        return None
    if first.isdigit() or (first >= b"0" and first <= b"9"):
        # Possible octet counting: LEN SP MSG
        buf = first
        while True:
            ch = conn.recv(1)
            if not ch:
                return buf.decode("utf-8", errors="replace") if buf else None
            if ch == b" ":
                break
            if not ch.isdigit():
                # Not octet counting; treat as start of line
                rest = _recv_until_newline(conn, max_bytes=1_048_576)
                return (buf + ch + (rest or b"")).decode("utf-8", errors="replace")
            buf += ch
            if len(buf) > 10:
                rest = _recv_until_newline(conn, max_bytes=1_048_576)
                return (buf + (rest or b"")).decode("utf-8", errors="replace")
        try:
            length = int(buf.decode("ascii"))
        except ValueError:
            rest = _recv_until_newline(conn, max_bytes=1_048_576)
            return (buf + b" " + (rest or b"")).decode("utf-8", errors="replace")
        length = max(0, min(length, 1_048_576))
        data = b""
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", errors="replace")
    # Newline-delimited (or CEF starting with <PRI> / letter)
    rest = _recv_until_newline(conn, max_bytes=1_048_576)
    return (first + (rest or b"")).decode("utf-8", errors="replace")


def _recv_until_newline(conn: socket.socket, *, max_bytes: int) -> bytes:
    data = b""
    while len(data) < max_bytes:
        chunk = conn.recv(1)
        if not chunk:
            break
        if chunk in (b"\n", b"\0"):
            break
        if chunk == b"\r":
            continue
        data += chunk
    return data


def _syslog_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    try:
        while True:
            frame = _read_syslog_frame(conn)
            if frame is None:
                break
            text = frame.strip()
            if not text:
                continue
            store_message(text, peer)
    except (OSError, TimeoutError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _syslog_server() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", SYSLOG_PORT))
    sock.listen(64)
    print(f"syslog-receiver: TCP syslog on 0.0.0.0:{SYSLOG_PORT}", flush=True)
    while True:
        conn, addr = sock.accept()
        t = threading.Thread(target=_syslog_client, args=(conn, addr), daemon=True)
        t.start()


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>ACS Syslog CEF viewer</title>
<style>
  :root {
    --bg: #f5f5f5;
    --panel: #fff;
    --ink: #151515;
    --muted: #6a6e73;
    --border: #d2d2d2;
    --accent: #ee0000;
    --ok: #3e8635;
    --diff: #f0ab00;
    --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
    --sans: "Red Hat Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: var(--sans); color: var(--ink); background: var(--bg);
  }
  header {
    background: #1b1b1b; color: #fff; padding: 0.85rem 1.25rem;
    display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 1.1rem; margin: 0; font-weight: 600; }
  header .meta { color: #c7c7c7; font-size: 0.85rem; }
  header button, .toolbar button {
    background: var(--accent); color: #fff; border: 0; border-radius: 3px;
    padding: 0.4rem 0.75rem; cursor: pointer; font: inherit;
  }
  header button.secondary, .toolbar button.secondary {
    background: transparent; border: 1px solid #8a8d90; color: #fff;
  }
  .toolbar button.secondary { color: var(--ink); border-color: var(--border); background: #fff; }
  main { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.4fr); gap: 0; min-height: calc(100vh - 56px); }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .list, .detail { background: var(--panel); border-right: 1px solid var(--border); }
  .detail { border-right: 0; }
  .toolbar { padding: 0.65rem 1rem; border-bottom: 1px solid var(--border); display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
  .toolbar .hint { color: var(--muted); font-size: 0.85rem; }
  ul#msgs { list-style: none; margin: 0; padding: 0; max-height: calc(100vh - 120px); overflow: auto; }
  ul#msgs li {
    padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); cursor: pointer;
    display: grid; grid-template-columns: auto 1fr; gap: 0.5rem 0.75rem; align-items: start;
  }
  ul#msgs li:hover { background: #fafafa; }
  ul#msgs li.selected { background: #f2f9f9; outline: 1px solid #bee1f4; }
  ul#msgs li .chk { margin-top: 0.2rem; }
  ul#msgs li .title { font-weight: 600; font-size: 0.95rem; }
  ul#msgs li .sub { color: var(--muted); font-size: 0.8rem; }
  .panel { padding: 1rem 1.25rem; }
  .panel h2 { margin: 0 0 0.75rem; font-size: 1rem; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 700px) { .grid2 { grid-template-columns: 1fr; } }
  pre.raw {
    background: #1b1b1b; color: #f0f0f0; padding: 0.85rem; border-radius: 4px;
    overflow: auto; font-family: var(--mono); font-size: 0.78rem; white-space: pre-wrap; word-break: break-word;
  }
  table.fields { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  table.fields th, table.fields td { text-align: left; padding: 0.35rem 0.45rem; border-bottom: 1px solid var(--border); vertical-align: top; }
  table.fields th { width: 32%; color: var(--muted); font-weight: 600; }
  .diff-row td { background: #fff4ce; }
  .empty { color: var(--muted); padding: 2rem 1.25rem; }
  .badge { display: inline-block; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 3px; background: #e7e7e7; }
  .badge.ok { background: #e9f5e6; color: var(--ok); }
</style>
</head>
<body>
<header>
  <div>
    <h1>ACS Syslog CEF viewer</h1>
    <div class="meta">Generic receiver · ring buffer · raw + parsed · compare</div>
  </div>
  <div style="display:flex;gap:0.5rem;align-items:center;">
    <span class="meta" id="count">0 messages</span>
    <button type="button" class="secondary" id="btnRefresh">Refresh</button>
    <button type="button" id="btnClear">Clear buffer</button>
  </div>
</header>
<main>
  <section class="list">
    <div class="toolbar">
      <button type="button" class="secondary" id="btnCompare">Compare selected (2)</button>
      <span class="hint">Check two messages to diff extension fields</span>
    </div>
    <ul id="msgs"></ul>
  </section>
  <section class="detail">
    <div id="detail" class="empty">Select a message, or pick two and Compare.</div>
  </section>
</main>
<script>
const msgsEl = document.getElementById('msgs');
const detailEl = document.getElementById('detail');
const countEl = document.getElementById('count');
let cache = [];
let selectedId = null;

async function load() {
  const r = await fetch('/api/messages');
  const data = await r.json();
  cache = data.messages || [];
  countEl.textContent = cache.length + ' message' + (cache.length === 1 ? '' : 's');
  renderList();
  if (selectedId) {
    const still = cache.find(m => m.id === selectedId);
    if (still) showDetail(still);
    else { selectedId = null; detailEl.className = 'empty'; detailEl.textContent = 'Select a message, or pick two and Compare.'; }
  }
}

function renderList() {
  msgsEl.innerHTML = '';
  if (!cache.length) {
    msgsEl.innerHTML = '<li class="empty" style="border:0">Buffer empty. Run Central Syslog Test or trip a DEMO policy.</li>';
    return;
  }
  for (const m of cache) {
    const h = (m.parsed && m.parsed.header) || {};
    const li = document.createElement('li');
    if (m.id === selectedId) li.classList.add('selected');
    li.dataset.id = m.id;
    li.innerHTML = `
      <input class="chk" type="checkbox" data-id="${m.id}" />
      <div>
        <div class="title">${esc(h.name || '(no CEF name)')} <span class="badge">${esc(h.severity || '?')}</span>
          ${m.parsed && m.parsed.ok ? '<span class="badge ok">CEF</span>' : '<span class="badge">raw</span>'}
        </div>
        <div class="sub">#${m.seq} · ${esc(m.receivedAt)} · ${esc(h.signatureId || '')}</div>
      </div>`;
    li.addEventListener('click', (ev) => {
      if (ev.target.tagName === 'INPUT') return;
      selectedId = m.id;
      renderList();
      showDetail(m);
    });
    msgsEl.appendChild(li);
  }
}

function checkedIds() {
  return [...msgsEl.querySelectorAll('input.chk:checked')].map(el => el.dataset.id);
}

function showDetail(m) {
  const h = (m.parsed && m.parsed.header) || {};
  const ext = (m.parsed && m.parsed.extensions) || {};
  const rows = Object.keys(h).map(k => `<tr><th>${esc(k)}</th><td>${esc(String(h[k]))}</td></tr>`).join('')
    + Object.keys(ext).map(k => `<tr><th>${esc(k)}</th><td>${esc(String(ext[k]))}</td></tr>`).join('');
  detailEl.className = 'panel';
  detailEl.innerHTML = `
    <h2>Message #${m.seq}</h2>
    <p class="hint" style="color:var(--muted);font-size:0.85rem;">Received ${esc(m.receivedAt)} from ${esc(m.peer || '')}</p>
    <div class="grid2">
      <div>
        <h2>Raw CEF</h2>
        <pre class="raw">${esc(m.raw || '')}</pre>
      </div>
      <div>
        <h2>Parsed fields</h2>
        ${m.parsed && m.parsed.ok ? `<table class="fields">${rows}</table>` : `<p class="empty">${esc((m.parsed && m.parsed.error) || 'Could not parse CEF')}</p>`}
      </div>
    </div>`;
}

function showCompare(a, b) {
  const ea = (a.parsed && a.parsed.extensions) || {};
  const eb = (b.parsed && b.parsed.extensions) || {};
  const ha = (a.parsed && a.parsed.header) || {};
  const hb = (b.parsed && b.parsed.header) || {};
  const keys = Array.from(new Set([...Object.keys(ea), ...Object.keys(eb)])).sort();
  const hkeys = Array.from(new Set([...Object.keys(ha), ...Object.keys(hb)]));
  const hrows = hkeys.map(k => {
    const va = String(ha[k] ?? '');
    const vb = String(hb[k] ?? '');
    const diff = va !== vb ? ' class="diff-row"' : '';
    return `<tr${diff}><th>${esc(k)}</th><td>${esc(va)}</td><td>${esc(vb)}</td></tr>`;
  }).join('');
  const erows = keys.map(k => {
    const va = String(ea[k] ?? '');
    const vb = String(eb[k] ?? '');
    const diff = va !== vb ? ' class="diff-row"' : '';
    return `<tr${diff}><th>${esc(k)}</th><td>${esc(va)}</td><td>${esc(vb)}</td></tr>`;
  }).join('');
  detailEl.className = 'panel';
  detailEl.innerHTML = `
    <h2>Compare #${a.seq} vs #${b.seq}</h2>
    <p class="hint" style="color:var(--muted);font-size:0.85rem;">Highlighted rows differ (CEF header + extensions). Use two Central Tests with CEF vs CEF legacy field order to show wire impact.</p>
    <div class="grid2">
      <div><h2>Raw A</h2><pre class="raw">${esc(a.raw || '')}</pre></div>
      <div><h2>Raw B</h2><pre class="raw">${esc(b.raw || '')}</pre></div>
    </div>
    <h2 style="margin-top:1.25rem;">Header</h2>
    <table class="fields"><tr><th>Field</th><th>A</th><th>B</th></tr>${hrows}</table>
    <h2 style="margin-top:1.25rem;">Extensions</h2>
    <table class="fields"><tr><th>Key</th><th>A</th><th>B</th></tr>${erows || '<tr><td colspan="3" class="empty">No extension keys</td></tr>'}</table>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

document.getElementById('btnRefresh').onclick = () => load();
document.getElementById('btnClear').onclick = async () => {
  if (!confirm('Clear the ring buffer?')) return;
  await fetch('/api/clear', { method: 'POST' });
  selectedId = null;
  await load();
  detailEl.className = 'empty';
  detailEl.textContent = 'Buffer cleared.';
};
document.getElementById('btnCompare').onclick = () => {
  const ids = checkedIds();
  if (ids.length !== 2) { alert('Select exactly two messages'); return; }
  const a = cache.find(m => m.id === ids[0]);
  const b = cache.find(m => m.id === ids[1]);
  if (!a || !b) return;
  showCompare(a, b);
};

load();
setInterval(load, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "acs-syslog-viewer/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"http: {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: Any) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/messages":
            msgs = list_messages()
            # slim list for UI
            slim = [
                {
                    "id": m["id"],
                    "seq": m["seq"],
                    "receivedAt": m["receivedAt"],
                    "peer": m.get("peer"),
                    "raw": m.get("raw"),
                    "parsed": m.get("parsed"),
                }
                for m in msgs
            ]
            self._send_json(200, {"messages": slim, "ringSize": RING_SIZE})
            return
        if path.startswith("/api/messages/"):
            msg_id = path.split("/", 3)[-1]
            msg = get_message(msg_id)
            if not msg:
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, msg)
            return
        if path == "/healthz":
            self._send_json(200, {"ok": True, "count": len(list_messages())})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/clear":
            n = clear_messages()
            self._send_json(200, {"cleared": n})
            return
        # Optional: inject a test CEF locally
        if path == "/api/inject":
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            qs = parse_qs(parsed.query)
            if not raw and "raw" in qs:
                raw = qs["raw"][0]
            if not raw:
                self._send_json(400, {"error": "empty body"})
                return
            msg = store_message(raw, "inject")
            self._send_json(200, msg)
            return
        self._send_json(404, {"error": "not found"})


def main() -> None:
    threading.Thread(target=_syslog_server, daemon=True).start()
    # Give syslog socket a moment
    time.sleep(0.2)
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"syslog-receiver: HTTP viewer on 0.0.0.0:{HTTP_PORT} (ring={RING_SIZE})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
