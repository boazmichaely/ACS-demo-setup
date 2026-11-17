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
# RFC 5424 header after <PRI>: VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA
SYSLOG5424_RE = re.compile(
    r"^<(?P<pri>\d+)>"
    r"(?P<version>\d+)\s+"
    r"(?P<timestamp>\S+)\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<appName>\S+)\s+"
    r"(?P<procid>\S+)\s+"
    r"(?P<msgid>\S+)\s+"
    r"(?P<structuredData>\S+)\s*$"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_syslog_envelope(raw: str) -> dict[str, Any]:
    """Split syslog envelope from CEF payload. Never raises.

    Returns ok, header (PRI + RFC5424 fields when recognized), cefRaw (from CEF:),
    and error (empty on full success).
    """
    text = (raw or "").strip()
    out: dict[str, Any] = {
        "ok": False,
        "header": {},
        "cefRaw": "",
        "error": "",
    }
    idx = text.find("CEF:")
    if idx < 0:
        out["error"] = "no CEF: marker"
        out["cefRaw"] = text
        return out
    out["cefRaw"] = text[idx:]
    prefix = text[:idx].rstrip()
    if not prefix:
        out["ok"] = True
        return out
    m = SYSLOG5424_RE.match(prefix)
    if m:
        out["header"] = {
            "pri": m.group("pri"),
            "version": m.group("version"),
            "timestamp": m.group("timestamp"),
            "hostname": m.group("hostname"),
            "appName": m.group("appName"),
            "procid": m.group("procid"),
            "msgid": m.group("msgid"),
            "structuredData": m.group("structuredData"),
        }
        out["ok"] = True
        return out
    m2 = re.match(r"^<(?P<pri>\d+)>(?P<rest>.*)$", prefix, re.DOTALL)
    if m2:
        out["header"] = {
            "pri": m2.group("pri"),
            "rest": m2.group("rest").strip(),
        }
        out["ok"] = True
        out["error"] = "partial syslog header"
        return out
    out["header"] = {"rawPrefix": prefix}
    out["ok"] = True
    out["error"] = "unrecognized syslog header"
    return out


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
    envelope = parse_syslog_envelope(raw)
    cef_raw = envelope.get("cefRaw") or raw.strip()
    parsed = parse_cef(cef_raw)
    with _lock:
        _seq += 1
        msg = {
            "id": str(uuid.uuid4()),
            "seq": _seq,
            "receivedAt": _utc_now(),
            "peer": peer,
            "raw": raw.strip(),
            "cefRaw": cef_raw,
            "syslog": envelope,
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
    --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
    --sans: "Red Hat Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
    --list-width: 280px;
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
  header button {
    background: var(--accent); color: #fff; border: 0; border-radius: 3px;
    padding: 0.4rem 0.75rem; cursor: pointer; font: inherit;
  }
  header button.secondary {
    background: transparent; border: 1px solid #8a8d90; color: #fff;
  }
  main {
    display: flex; min-height: calc(100vh - 56px); width: 100%;
  }
  .list {
    flex: 0 0 var(--list-width); width: var(--list-width); max-width: 70vw;
    background: var(--panel); min-width: 180px; overflow: hidden;
    display: flex; flex-direction: column;
  }
  .splitter {
    flex: 0 0 6px; width: 6px; cursor: col-resize; background: var(--border);
    position: relative; z-index: 2;
  }
  .splitter:hover, .splitter.dragging { background: #8a8d90; }
  .detail {
    flex: 1 1 auto; min-width: 0; background: var(--panel); overflow: auto;
  }
  @media (max-width: 700px) {
    main { flex-direction: column; }
    .list { flex: 0 0 auto; width: 100% !important; max-width: none; max-height: 40vh; }
    .splitter { display: none; }
  }
  .toolbar {
    padding: 0.65rem 1rem; border-bottom: 1px solid var(--border);
    color: var(--muted); font-size: 0.85rem; flex: 0 0 auto;
  }
  ul#msgs {
    list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1 1 auto;
  }
  ul#msgs li {
    padding: 0.7rem 1rem; border-bottom: 1px solid var(--border); cursor: pointer;
  }
  ul#msgs li:hover { background: #fafafa; }
  ul#msgs li.selected { background: #f2f9f9; outline: 1px solid #bee1f4; }
  ul#msgs li .title { font-weight: 600; font-size: 0.95rem; }
  ul#msgs li .sub { color: var(--muted); font-size: 0.8rem; }
  .panel { padding: 1rem 1.25rem; max-width: 100%; }
  .panel h2 { margin: 0 0 0.75rem; font-size: 1rem; }
  .stack { display: flex; flex-direction: column; gap: 1.25rem; max-width: 100%; }
  .stack > div { min-width: 0; max-width: 100%; }
  pre.raw {
    background: #1b1b1b; color: #f0f0f0; padding: 0.85rem; border-radius: 4px;
    margin: 0; max-width: 100%; max-height: 14rem; overflow: auto;
    font-family: var(--mono); font-size: 0.78rem;
    white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  }
  table.fields { width: 100%; max-width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.88rem; }
  table.fields th, table.fields td {
    text-align: left; padding: 0.35rem 0.45rem; border-bottom: 1px solid var(--border);
    vertical-align: top; overflow-wrap: anywhere; word-break: break-word;
  }
  table.fields th { width: 28%; color: var(--muted); font-weight: 600; }
  .field-block { margin-top: 0.85rem; display: flex; flex-direction: column; gap: 0.4rem; max-width: 100%; }
  .field-block .label {
    font-size: 0.85rem; font-weight: 600; color: var(--ink);
    margin: 0; line-height: 1.35; overflow-wrap: anywhere;
  }
  pre.pretty {
    background: #f8f8f8; color: var(--ink); border: 1px solid var(--border);
    padding: 0.75rem 0.85rem; border-radius: 4px; margin: 0;
    max-width: 100%; max-height: min(60vh, 32rem); overflow: auto;
    font-family: var(--mono); font-size: 0.78rem; line-height: 1.45;
    white-space: pre; tab-size: 2;
  }
  pre.pretty .k { color: #5c3d8a; }
  pre.pretty .s { color: #116644; }
  pre.pretty .n { color: #0055aa; }
  pre.pretty .b { color: #aa5500; }
  pre.pretty .null { color: var(--muted); }
  .empty { color: var(--muted); padding: 2rem 1.25rem; }
  .badge { display: inline-block; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 3px; background: #e7e7e7; }
  .badge.ok { background: #e9f5e6; color: var(--ok); }
  body.resizing { cursor: col-resize; user-select: none; }
</style>
</head>
<body>
<header>
  <div>
    <h1>ACS Syslog CEF viewer</h1>
    <div class="meta">Generic receiver · ring buffer · syslog + CEF</div>
  </div>
  <div style="display:flex;gap:0.5rem;align-items:center;">
    <span class="meta" id="count">0 messages</span>
    <button type="button" class="secondary" id="btnRefresh">Refresh</button>
    <button type="button" id="btnClear">Clear buffer</button>
  </div>
</header>
<main id="layout">
  <section class="list" id="listPane">
    <div class="toolbar">Select a message</div>
    <ul id="msgs"></ul>
  </section>
  <div class="splitter" id="splitter" title="Drag to resize" role="separator" aria-orientation="vertical"></div>
  <section class="detail">
    <div id="detail" class="empty">Select a message.</div>
  </section>
</main>
<script>
const msgsEl = document.getElementById('msgs');
const detailEl = document.getElementById('detail');
const countEl = document.getElementById('count');
const listPane = document.getElementById('listPane');
const splitter = document.getElementById('splitter');
let cache = [];
let selectedId = null;

const LIST_KEY = 'acs-syslog-list-width';
(function restoreListWidth() {
  const saved = parseInt(localStorage.getItem(LIST_KEY) || '', 10);
  if (saved >= 180 && saved <= 800) {
    document.documentElement.style.setProperty('--list-width', saved + 'px');
  }
})();

function initSplitter() {
  let dragging = false;
  splitter.addEventListener('mousedown', (ev) => {
    ev.preventDefault();
    dragging = true;
    splitter.classList.add('dragging');
    document.body.classList.add('resizing');
  });
  window.addEventListener('mousemove', (ev) => {
    if (!dragging) return;
    const main = document.getElementById('layout');
    const rect = main.getBoundingClientRect();
    let w = ev.clientX - rect.left;
    w = Math.max(180, Math.min(w, Math.floor(rect.width * 0.7)));
    document.documentElement.style.setProperty('--list-width', w + 'px');
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove('dragging');
    document.body.classList.remove('resizing');
    const w = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--list-width'), 10);
    if (w) localStorage.setItem(LIST_KEY, String(w));
  });
}

function listFingerprint(msgs) {
  return msgs.map(m => m.id + ':' + m.seq).join('|');
}

let lastListFp = '';
let lastDetailId = null;

async function load() {
  const r = await fetch('/api/messages');
  const data = await r.json();
  const next = data.messages || [];
  cache = next;
  countEl.textContent = cache.length + ' message' + (cache.length === 1 ? '' : 's');

  const fp = listFingerprint(cache);
  const listScroll = msgsEl.scrollTop;
  const nearTop = listScroll < 48;
  const prevHeight = msgsEl.scrollHeight;
  if (fp !== lastListFp) {
    renderList({ restoreScroll: false });
    // Newest messages prepend: keep viewport on the same entries unless
    // the user was already at the top (follow new arrivals).
    if (nearTop) {
      msgsEl.scrollTop = 0;
    } else {
      msgsEl.scrollTop = listScroll + (msgsEl.scrollHeight - prevHeight);
    }
    lastListFp = fp;
  } else {
    // Same ids: only refresh selection highlight without wiping scroll.
    for (const li of msgsEl.querySelectorAll('li[data-id]')) {
      li.classList.toggle('selected', li.dataset.id === selectedId);
    }
  }

  const detailPane = document.querySelector('.detail');
  const detailScroll = detailPane ? detailPane.scrollTop : 0;
  if (selectedId) {
    const still = cache.find(m => m.id === selectedId);
    if (still) {
      // Re-render detail only when selection changes (click path also calls showDetail).
      if (lastDetailId !== selectedId) {
        showDetail(still);
        lastDetailId = selectedId;
      }
      if (detailPane) detailPane.scrollTop = detailScroll;
    } else {
      selectedId = null;
      lastDetailId = null;
      detailEl.className = 'empty';
      detailEl.textContent = 'Select a message.';
    }
  }
}

function renderList(opts) {
  const restoreScroll = !opts || opts.restoreScroll !== false;
  const listScroll = msgsEl.scrollTop;
  msgsEl.innerHTML = '';
  if (!cache.length) {
    msgsEl.innerHTML = '<li class="empty" style="border:0">Buffer empty. Run Central Syslog Test (Integrations → Syslog → Test).</li>';
    msgsEl.scrollTop = 0;
    return;
  }
  for (const m of cache) {
    const h = (m.parsed && m.parsed.header) || {};
    const li = document.createElement('li');
    if (m.id === selectedId) li.classList.add('selected');
    li.dataset.id = m.id;
    li.innerHTML = `
      <div class="title">${esc(h.name || '(no CEF name)')} <span class="badge">${esc(h.severity || '?')}</span>
        ${m.parsed && m.parsed.ok ? '<span class="badge ok">CEF</span>' : '<span class="badge">raw</span>'}
      </div>
      <div class="sub">#${m.seq} · ${esc(m.receivedAt)} · ${esc(h.signatureId || '')}</div>`;
    li.addEventListener('click', () => {
      selectedId = m.id;
      lastDetailId = m.id;
      renderList();
      showDetail(m);
    });
    msgsEl.appendChild(li);
  }
  if (restoreScroll) msgsEl.scrollTop = listScroll;
}

function tryParseJson(val) {
  const s = String(val == null ? '' : val).trim();
  if (!s || (s[0] !== '{' && s[0] !== '[')) return null;
  try { return JSON.parse(s); } catch (_) { return null; }
}

function highlightJson(obj) {
  const raw = JSON.stringify(obj, null, 2);
  return esc(raw)
    .replace(/("(?:\\.|[^"\\])*")(\s*:)/g, '<span class="k">$1</span>$2')
    .replace(/:\s*("(?:\\.|[^"\\])*")/g, ': <span class="s">$1</span>')
    .replace(/:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/g, ': <span class="n">$1</span>')
    .replace(/:\s*(true|false)\b/g, ': <span class="b">$1</span>')
    .replace(/:\s*(null)\b/g, ': <span class="null">$1</span>');
}

/** Full CEF key as label; content always below (never beside) for JSON blobs. */
function fieldLabel(k, header) {
  // Prefer the product-style title for the audit payload when CEF header is present.
  if (k === 'stackroxKubernetesSecurityPlatformAuditLog' && header) {
    const parts = [header.deviceVendor, header.deviceProduct, header.name || header.signatureId]
      .map(x => String(x || '').trim())
      .filter(Boolean);
    if (parts.length) return parts.join(' ');
  }
  return k;
}

/** Display-only: RFC3339 / ISO-8601 → "Nov 17, 2026 02:18:16 AM UTC". */
function formatTs(val) {
  const s = String(val == null ? '' : val).trim();
  if (!s) return '';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const mon = months[d.getUTCMonth()];
  const day = d.getUTCDate();
  const year = d.getUTCFullYear();
  let h = d.getUTCHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12;
  if (h === 0) h = 12;
  const hh = String(h).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  const ss = String(d.getUTCSeconds()).padStart(2, '0');
  return `${mon} ${day}, ${year} ${hh}:${mm}:${ss} ${ampm} UTC`;
}

function fieldRows(obj) {
  return Object.keys(obj).map(k => {
    const v = obj[k];
    if (tryParseJson(v) !== null) return '';
    return `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`;
  }).join('');
}

function jsonBlocks(obj, header) {
  return Object.keys(obj).map(k => {
    const parsed = tryParseJson(obj[k]);
    if (parsed === null) return '';
    const label = fieldLabel(k, header);
    return `<div class="field-block">
      <div class="label">${esc(label)}</div>
      <pre class="pretty">${highlightJson(parsed)}</pre>
    </div>`;
  }).join('');
}

function showDetail(m) {
  const h = (m.parsed && m.parsed.header) || {};
  const ext = (m.parsed && m.parsed.extensions) || {};
  const syslog = (m.syslog && m.syslog.header) || {};
  const cefRaw = m.cefRaw || (() => {
    const raw = m.raw || '';
    const i = raw.indexOf('CEF:');
    return i >= 0 ? raw.slice(i) : raw;
  })();
  const title = h.name || h.signatureId || 'Message';
  const syslogDisplay = Object.assign({}, syslog);
  if (syslogDisplay.timestamp) {
    syslogDisplay.timestamp = formatTs(syslogDisplay.timestamp);
  }
  let syslogBody = '<p class="empty">No syslog header</p>';
  if (m.syslog && m.syslog.ok && Object.keys(syslog).length) {
    const rows = fieldRows(syslogDisplay);
    syslogBody = rows
      ? `<table class="fields">${rows}</table>`
      : '<p class="empty">No syslog header fields</p>';
    if (m.syslog.error) {
      syslogBody += `<p class="hint" style="color:var(--muted);font-size:0.8rem;margin:0.5rem 0 0;">${esc(m.syslog.error)}</p>`;
    }
  } else if (m.syslog && m.syslog.error) {
    syslogBody = `<p class="empty">${esc(m.syslog.error)}</p>`;
  }
  let parsedBody = `<p class="empty">${esc((m.parsed && m.parsed.error) || 'Could not parse CEF')}</p>`;
  if (m.parsed && m.parsed.ok) {
    const rows = fieldRows(h) + fieldRows(ext);
    const blocks = jsonBlocks(h, h) + jsonBlocks(ext, h);
    parsedBody = `${rows ? `<table class="fields">${rows}</table>` : ''}${blocks || ''}`;
  }
  detailEl.className = 'panel';
  detailEl.innerHTML = `
    <h2>#${m.seq} · ${esc(title)}</h2>
    <p class="hint" style="color:var(--muted);font-size:0.85rem;margin:0 0 0.75rem;">Received ${esc(formatTs(m.receivedAt))} · peer ${esc(m.peer || '')}</p>
    <div class="stack">
      <div>
        <h2>Syslog header</h2>
        ${syslogBody}
      </div>
      <div>
        <h2>Raw CEF</h2>
        <pre class="raw">${esc(cefRaw)}</pre>
      </div>
      <div>
        <h2>Parsed CEF fields</h2>
        ${parsedBody}
      </div>
    </div>`;
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

initSplitter();
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
                    "cefRaw": m.get("cefRaw"),
                    "syslog": m.get("syslog"),
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
