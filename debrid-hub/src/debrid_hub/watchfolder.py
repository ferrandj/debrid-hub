from __future__ import annotations

import asyncio
import contextlib
import re
import time
from datetime import datetime
from pathlib import Path

from .config import Settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_LABEL_LEN = 80


def sanitize_label(label: str) -> str:
    """Turn a free-form name (a link's filename, a batch description) into
    something safe to use as a path component."""
    cleaned = _UNSAFE.sub("_", (label or "").strip()).strip("_.")
    return cleaned[:_MAX_LABEL_LEN].strip("_.") or "download"


def drop_filename(label: str, now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{sanitize_label(label)}_{ts}.txt"


def write_drop(folder: str, label: str, urls: list[str]) -> Path:
    """Write one text file, one URL per line, into `folder` (created if
    missing) so JDownloader2's FolderWatch extension can pick it up."""
    if not folder:
        raise ValueError("No watch folder configured (set DEBRID_HUB_WATCH_DIR).")
    if not urls:
        raise ValueError("No URLs to write.")
    dest_dir = Path(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / drop_filename(label)
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return path


def purge_expired(folder: str, max_age_minutes: int) -> int:
    """Delete files in `folder` whose mtime is older than `max_age_minutes`.
    Returns how many were removed. No-op if either is unset."""
    if not folder or max_age_minutes <= 0:
        return 0
    dest_dir = Path(folder)
    if not dest_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_minutes * 60
    removed = 0
    for entry in dest_dir.iterdir():
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            with contextlib.suppress(OSError):
                entry.unlink()
                removed += 1
    return removed


class WatchFolderCleaner:
    """Background task that periodically purges aged-out files from the
    watch folder, per `settings.watch_cleanup_minutes`."""

    _MAX_CHECK_INTERVAL = 3600  # never wait longer than an hour between sweeps

    def __init__(self, settings: Settings):
        self._settings = settings
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._settings.watch_dir and self._settings.watch_cleanup_minutes > 0:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        interval = min(self._settings.watch_cleanup_minutes * 60, self._MAX_CHECK_INTERVAL)
        while True:
            await asyncio.sleep(interval)
            purge_expired(self._settings.watch_dir, self._settings.watch_cleanup_minutes)
