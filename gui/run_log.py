"""Dated rotating GUI run logs (tee target for /api/run streams).

Keeps up to three calendar-day files: today and the previous two days.
Named ``gui-YYYY-MM-DD.log`` under ``<repo>/logs/``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

LOG_DIR_NAME = "logs"
LOG_PREFIX = "gui-"
LOG_SUFFIX = ".log"
KEEP_DAYS = 3  # today + (KEEP_DAYS - 1) prior days


def logs_dir(repo_root: Path) -> Path:
    return repo_root / LOG_DIR_NAME


def log_path_for(repo_root: Path, day: date) -> Path:
    return logs_dir(repo_root) / f"{LOG_PREFIX}{day.isoformat()}{LOG_SUFFIX}"


def today_log_path(repo_root: Path) -> Path:
    return log_path_for(repo_root, date.today())


def _parse_day_from_name(name: str) -> date | None:
    if not (name.startswith(LOG_PREFIX) and name.endswith(LOG_SUFFIX)):
        return None
    mid = name[len(LOG_PREFIX) : -len(LOG_SUFFIX)]
    try:
        return date.fromisoformat(mid)
    except ValueError:
        return None


def ensure_today_log(repo_root: Path) -> Path:
    """Return today's log path, creating it if needed and pruning older files.

    First run of the day: create ``gui-YYYY-MM-DD.log`` and delete any log
    files older than (today - 2 days), leaving at most three dated files.
    Same day: reuse/append to the existing file (no prune).
    First run ever: just create today's file.
    """
    directory = logs_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    today = date.today()
    path = log_path_for(repo_root, today)

    if not path.is_file():
        cutoff = today - timedelta(days=KEEP_DAYS - 1)
        for existing in directory.glob(f"{LOG_PREFIX}*{LOG_SUFFIX}"):
            day = _parse_day_from_name(existing.name)
            if day is not None and day < cutoff:
                existing.unlink(missing_ok=True)
        path.touch()

    return path


def read_today_log(repo_root: Path) -> str:
    """Return today's log text, or empty string if none yet."""
    path = today_log_path(repo_root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def append_today_log(repo_root: Path, text: str) -> None:
    if not text:
        return
    path = ensure_today_log(repo_root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def begin_run(repo_root: Path, module_id: str, *, dry_run: bool) -> None:
    mode = "dry-run" if dry_run else "run"
    header = f"\n── {_stamp()} {mode} {module_id} {'─' * 8}\n"
    append_today_log(repo_root, header)


def mark_page_load(repo_root: Path) -> None:
    """Divider for GUI hard refresh / page load (disk log only; pane stays empty)."""
    header = f"\n── {_stamp()} page-load {'─' * 8}\n"
    append_today_log(repo_root, header)
