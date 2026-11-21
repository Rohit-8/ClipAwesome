"""Disk usage per data category and automatic cleanup of caches (never the user's own downloads or sources)."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import system
from .config import data_path

if TYPE_CHECKING:
    from .config import SettingsStore
    from .editor import EditorManager
    from .previews import PreviewManager

log = logging.getLogger("clipawesome.storage")

# (key, folder, label, cleaned automatically)
CATEGORIES = (
    ("downloads", "downloads", "YouTube downloads", False),
    ("editor_sources", "editor/sources", "Files opened in the editor", False),
    ("uploads", "uploads", "Files uploaded for analysis", False),
    ("exports", "editor/exports", "Finished exports", True),
    ("youtube_copies", "youtube_previews", "YouTube playback copies", True),
    ("audio_previews", "previews", "Audio preview copies", True),
    ("models", "models", "Whisper models", False),
    ("temp", "tmp", "Temporary files", True),
)
INTERVAL_SEC = 3600


def _size(path: Path) -> tuple[int, int]:
    total = count = 0
    if path.exists():
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                    count += 1
                except OSError:
                    pass
    return total, count


def _remove(path: Path) -> int:
    size = _size(path)[0] if path.is_dir() else (path.stat().st_size if path.exists() else 0)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return size


class Storage:
    def __init__(self, settings: SettingsStore, editor: EditorManager, previews: PreviewManager):
        self._settings = settings
        self._editor = editor
        self._previews = previews
        self._lock = threading.Lock()
        self._timer: threading.Thread | None = None

    def usage(self) -> dict[str, Any]:
        items = []
        for key, folder, label, auto in CATEGORIES:
            size, count = _size(data_path(*folder.split("/")))
            items.append({"key": key, "label": label, "bytes": size, "files": count, "auto_cleanup": auto})
        root = data_path()
        disk = shutil.disk_usage(root if root.exists() else root.parent)
        s = self._settings.load()
        return {
            "categories": items,
            "total_bytes": sum(i["bytes"] for i in items),
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
            "cleanup_days": s.cleanup_days,
            "cache_limit_gb": s.cache_limit_gb,
            "data_dir": str(root),
        }

    def cleanup(self, everything: bool = False) -> dict[str, Any]:
        """Removes expired caches. `everything` also clears all caches regardless of age (the \u201cClean up now\u201d button)."""
        with self._lock:
            s = self._settings.load()
            days = 0 if everything else s.cleanup_days
            cutoff = time.time() - days * 86400 if (days or everything) else None
            freed = {"exports": 0, "youtube_copies": 0, "audio_previews": 0, "temp": 0}

            freed["temp"] = self._clean_temp(0 if everything else 3600)

            if cutoff is not None:
                when = datetime.fromtimestamp(cutoff, timezone.utc) if not everything else datetime.now(timezone.utc) + timedelta(days=1)
                for task in self._editor.exports():
                    finished = task.finished_at or task.created_at
                    if task.status in ("done", "error", "cancelled") and datetime.fromisoformat(finished) < when:
                        size = _size(data_path("editor", "exports", task.id))[0]
                        if self._editor.delete(task.id):
                            freed["exports"] += size
                for mp3 in data_path("previews").glob("*.mp3"):
                    if everything or mp3.stat().st_mtime < cutoff:
                        freed["audio_previews"] += _remove(mp3)

            busy = self._previews.busy()
            copies = sorted(
                (p for p in self._previews.root.glob("*") if p.is_dir() and p.name not in busy),
                key=lambda p: p.stat().st_mtime,
            )
            limit = int(s.cache_limit_gb * system.GB) if s.cache_limit_gb else None
            total = sum(_size(p)[0] for p in copies)
            for folder in copies:
                expired = cutoff is not None and folder.stat().st_mtime < cutoff
                over = limit is not None and total > limit
                if everything or expired or over:
                    size = _remove(folder)
                    total -= size
                    freed["youtube_copies"] += size
            result = {"freed": freed, "freed_bytes": sum(freed.values())}
        if result["freed_bytes"]:
            log.info("Cleanup freed %s", system.fmt_bytes(result["freed_bytes"]))
        return result

    def _clean_temp(self, older_than_sec: int) -> int:
        freed = 0
        now = time.time()
        for entry in data_path("tmp").glob("*"):
            try:
                if now - entry.stat().st_mtime >= older_than_sec:
                    freed += _remove(entry)
            except OSError:
                pass
        return freed

    def startup_cleanup(self) -> None:
        # Leftovers in tmp/ are from runs that crashed or were killed; nothing can still be using them at startup.
        self._clean_temp(0)
        self.cleanup()
        if self._timer is None:
            self._timer = threading.Thread(target=self._loop, name="clip-cleanup", daemon=True)
            self._timer.start()

    def _loop(self) -> None:
        while True:
            time.sleep(INTERVAL_SEC)
            try:
                self.cleanup()
            except Exception:
                log.exception("Scheduled cleanup failed")
