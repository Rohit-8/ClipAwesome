"""Machine capacity, performance profiles, a shared limit on CPU-heavy work, and disk-space checks."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GB = 1024**3
MB = 1024**2
DISK_RESERVE = 500 * MB  # always leave this much free so the OS and the app keep working


def cpu_count() -> int:
    n = (os.process_cpu_count() if hasattr(os, "process_cpu_count") else None) or os.cpu_count() or 1
    try:  # container CPU quota (cgroup v2)
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            n = min(n, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, n)


def _windows_memory() -> tuple[int, int] | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MemoryStatus()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
        return None
    return int(stat.ullTotalPhys), int(stat.ullAvailPhys)


def memory() -> tuple[int | None, int | None]:
    """(total, available) RAM in bytes, honouring a container memory limit."""
    if sys.platform == "win32":
        return _windows_memory() or (None, None)
    total = available = None
    try:
        info = {k: int(v.split()[0]) * 1024 for k, v in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}
        total, available = info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError):
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            pass
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if limit != "max":
            total = min(total or int(limit), int(limit))
            available = min(available or total, total)
    except (OSError, ValueError):
        pass
    return total, available


@dataclass(frozen=True)
class Profile:
    name: str
    heavy_slots: int  # CPU-heavy tasks (transcription, encoding) allowed at once
    threads: int  # CPU threads each heavy task may use
    whisper_model: str | None  # forces this model; None keeps the user's choice
    visual_analysis: str | None  # forces this scene-detection mode; None keeps the user's choice
    x264_preset: str
    chunk_sec: int  # audio held in memory per transcription chunk
    focused_over_sec: float | None  # "auto" focused transcription for videos longer than this; None = never


def recommended(cpus: int | None = None, ram: int | None = None) -> str:
    cpus = cpus or cpu_count()
    ram = ram if ram is not None else (memory()[0] or 8 * GB)
    if cpus <= 4 or ram < 7.5 * GB:  # 8 GB machines report a little under 8
        return "low"
    if cpus >= 12 and ram >= 15.5 * GB:
        return "high"
    return "balanced"


def profile(name: str, cpus: int | None = None) -> Profile:
    cpus = cpus or cpu_count()
    if name == "low":
        return Profile("low", 1, max(1, cpus // 2), "tiny", "off", "superfast", 300, 0)
    if name == "high":
        return Profile("high", 2, max(2, cpus // 2), None, None, "faster", 600, None)
    return Profile("balanced", 1, max(1, cpus - 1), None, None, "veryfast", 600, 1800)


class HeavyGate:
    """Counting gate whose size follows the active profile; waiters can be told they're queued."""

    def __init__(self, limit: int = 1):
        self._cond = threading.Condition()
        self._busy = 0
        self._limit = limit

    def set_limit(self, limit: int) -> None:
        with self._cond:
            self._limit = max(1, limit)
            self._cond.notify_all()

    @property
    def busy(self) -> int:
        return self._busy

    @contextmanager
    def slot(self, on_wait: Callable[[], None] | None = None) -> Iterator[None]:
        with self._cond:
            if self._busy >= self._limit and on_wait:
                on_wait()
            while self._busy >= self._limit:
                self._cond.wait()
            self._busy += 1
        try:
            yield
        finally:
            with self._cond:
                self._busy -= 1
                self._cond.notify_all()


heavy = HeavyGate()
_setting = "auto"
_active = profile(recommended())


def configure(setting: str) -> Profile:
    global _setting, _active
    _setting = setting
    _active = profile(recommended() if setting == "auto" else setting)
    heavy.set_limit(_active.heavy_slots)
    return _active


def active() -> Profile:
    return _active


def describe() -> dict[str, Any]:
    total, available = memory()
    return {
        "cpus": cpu_count(),
        "ram_gb": round(total / GB, 1) if total else None,
        "available_ram_gb": round(available / GB, 1) if available else None,
        "recommended": recommended(),
        "setting": _setting,
        "active": asdict(_active),
        "busy": heavy.busy,
    }


# ------------------------------------------------------------------ disk


def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def fmt_bytes(n: float) -> str:
    """Decimal units, matching the web UI's sizes."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def require_space(path: Path, need: int, what: str, error: type[Exception] = OSError) -> None:
    free = free_bytes(path)
    if free < need + DISK_RESERVE:
        raise error(
            f"Not enough disk space for {what}: it needs about {fmt_bytes(need)} but only {fmt_bytes(free)} is free. "
            "Free some space, or use Settings → Storage → Clean up."
        )
