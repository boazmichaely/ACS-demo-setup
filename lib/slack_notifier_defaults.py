"""Committed defaults for the shared #acs-demo-notifier Incoming Webhook.

Lab credentials may override per lab. Empty override → use this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULTS_REL = Path("config") / "slack-notifier.defaults.json"

_FALLBACK = {
    "webhookUrl": "",
    "notifierName": "#acs-demo-notifier",
    "channelUrl": "",
}


def defaults_path(repo_root: Path | None = None) -> Path:
    return (repo_root or _REPO_ROOT) / _DEFAULTS_REL


def load_defaults(repo_root: Path | None = None) -> dict[str, str]:
    path = defaults_path(repo_root)
    out = dict(_FALLBACK)
    if not path.is_file():
        return out
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(raw, dict):
        return out
    for key in ("webhookUrl", "notifierName", "channelUrl"):
        val = (raw.get(key) or "").strip()
        if val:
            out[key] = val
    if not out.get("notifierName"):
        out["notifierName"] = "#acs-demo-notifier"
    return out


def effective_slack_notifier(
    raw: Any,
    *,
    repo_root: Path | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge lab override with committed defaults (override wins when non-empty)."""
    base = defaults if defaults is not None else load_defaults(repo_root)
    src = raw if isinstance(raw, dict) else {}
    wh = (src.get("webhookUrl") or "").strip() or (base.get("webhookUrl") or "")
    name = (src.get("notifierName") or "").strip() or (base.get("notifierName") or "")
    channel = (src.get("channelUrl") or "").strip() or (base.get("channelUrl") or "")
    return {
        "webhookUrl": wh,
        "notifierName": name or "#acs-demo-notifier",
        "channelUrl": channel,
    }


def store_slack_notifier_override(
    raw: Any,
    *,
    repo_root: Path | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """Persist only overrides; values equal to defaults are stored empty."""
    base = defaults if defaults is not None else load_defaults(repo_root)
    src = raw if isinstance(raw, dict) else {}
    wh_in = (src.get("webhookUrl") or "").strip()
    name_in = (src.get("notifierName") or "").strip()
    ch_in = (src.get("channelUrl") or "").strip()
    wh_def = (base.get("webhookUrl") or "").strip()
    name_def = (base.get("notifierName") or "").strip() or "#acs-demo-notifier"
    ch_def = (base.get("channelUrl") or "").strip()
    return {
        "webhookUrl": "" if (not wh_in or wh_in == wh_def) else wh_in,
        "notifierName": "" if (not name_in or name_in == name_def) else name_in,
        "channelUrl": "" if (not ch_in or ch_in == ch_def) else ch_in,
    }
