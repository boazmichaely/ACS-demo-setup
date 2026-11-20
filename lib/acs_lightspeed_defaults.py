"""Committed defaults for OpenShift Lightspeed LLM settings (non-secret).

apiToken is intentionally empty here - it is credentials-only (per lab).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULTS_REL = Path("config") / "acs-lightspeed.defaults.json"

_FALLBACK = {
    "provider": "openai",
    "model": "gpt-4o",
    "url": "https://api.openai.com/v1",
    "apiToken": "",
}

VALID_PROVIDERS = frozenset({"openai"})


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
    for key in ("provider", "model", "url", "apiToken"):
        val = (raw.get(key) or "").strip()
        if val:
            out[key] = val
    provider = (out.get("provider") or "openai").strip().lower()
    out["provider"] = provider if provider in VALID_PROVIDERS else "openai"
    if not out.get("model"):
        out["model"] = "gpt-4o"
    if not out.get("url"):
        out["url"] = "https://api.openai.com/v1"
    return out


def effective_open_shift_lightspeed(
    raw: Any,
    *,
    repo_root: Path | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge lab override with committed defaults (override wins when non-empty)."""
    base = defaults if defaults is not None else load_defaults(repo_root)
    src = raw if isinstance(raw, dict) else {}
    provider = (src.get("provider") or "").strip().lower() or (
        base.get("provider") or "openai"
    )
    if provider not in VALID_PROVIDERS:
        provider = "openai"
    model = (src.get("model") or "").strip() or (base.get("model") or "gpt-4o")
    url = (src.get("url") or "").strip() or (base.get("url") or "https://api.openai.com/v1")
    token = (src.get("apiToken") or "").strip() or (base.get("apiToken") or "")
    return {
        "provider": provider,
        "model": model,
        "url": url,
        "apiToken": token,
    }


def store_open_shift_lightspeed_override(
    raw: Any,
    *,
    existing: dict[str, Any] | None = None,
    repo_root: Path | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """Persist overrides; blank apiToken keeps the previously stored secret."""
    base = defaults if defaults is not None else load_defaults(repo_root)
    src = raw if isinstance(raw, dict) else {}
    prev = existing if isinstance(existing, dict) else {}
    provider_in = (src.get("provider") or "").strip().lower()
    model_in = (src.get("model") or "").strip()
    url_in = (src.get("url") or "").strip()
    token_in = (src.get("apiToken") or "").strip()
    provider_def = (base.get("provider") or "openai").strip().lower()
    model_def = (base.get("model") or "gpt-4o").strip()
    url_def = (base.get("url") or "https://api.openai.com/v1").strip()
    token_prev = (prev.get("apiToken") or "").strip()
    provider = provider_in or provider_def
    if provider not in VALID_PROVIDERS:
        provider = "openai"
    return {
        "provider": "" if provider == provider_def else provider,
        "model": "" if (not model_in or model_in == model_def) else model_in,
        "url": "" if (not url_in or url_in == url_def) else url_in,
        "apiToken": token_in if token_in else token_prev,
    }
