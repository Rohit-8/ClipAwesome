"""Simple video editing with FFmpeg: trim, crop, rotate/flip, resize, mute and convert (MP4 / MP3 / GIF)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .config import data_path, read_json, write_json
from .downloads import ffmpeg_path, now_iso
from .sources.local_media import probe

log = logging.getLogger("clipawesome.editor")

ACTIVE = ("queued", "running")
CRF = {"high": 18, "balanced": 23, "small": 28}
HEIGHTS = (2160, 1440, 1080, 720, 480, 360)
GIF_MAX_SEC = 60.0


class EditError(ValueError):
    pass


class CropBox(BaseModel):
    """Normalised to the displayed frame (0–1), so it is independent of the source resolution."""

    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)
    w: float = Field(..., gt=0.01, le=1)
    h: float = Field(..., gt=0.01, le=1)

    @model_validator(mode="after")
    def _inside(self) -> CropBox:
        self.w = min(self.w, 1 - self.x)
        self.h = min(self.h, 1 - self.y)
        if self.w <= 0.01 or self.h <= 0.01:
            raise ValueError("crop box is outside the frame")
        return self


class ExportRequest(BaseModel):
    source_id: str = Field(..., min_length=3, max_length=40)
    start: float = Field(0, ge=0)
    end: float = Field(..., gt=0)
    crop: CropBox | None = None
    rotate: Literal[0, 90, 180, 270] = 0
    flip_h: bool = False
    flip_v: bool = False
    height: int | None = None
    mute: bool = False
    format: Literal["mp4", "mp3", "gif"] = "mp4"
    quality: Literal["high", "balanced", "small"] = "balanced"
    fast: bool = False

    @model_validator(mode="after")
    def _check(self) -> ExportRequest:
        if self.height is not None and self.height not in HEIGHTS:
            raise ValueError(f"height must be one of {HEIGHTS}")
        if self.end - self.start < 0.1:
            raise ValueError("the end must be after the start")
        return self

    @property
    def transforms(self) -> bool:
        return bool(self.crop or self.rotate or self.flip_h or self.flip_v or self.height)


class EditSource(BaseModel):
    id: str
    name: str
    kind: Literal["upload", "download"]
    download_id: str | None = None
    path: str = Field("", exclude=True)
    duration: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    size: int
    created_at: str


class ExportTask(BaseModel):
    id: str
    source_id: str
    source_name: str
    label: str
    format: str
    status: Literal["queued", "running", "done", "error", "cancelled"] = "queued"
    progress: float = 0.0
    speed: float | None = None
    eta: float | None = None
    file_name: str | None = None
    file_size: int | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


# ------------------------------------------------------------------ command building


def _fmt_t(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}-{s % 3600 // 60:02d}-{s % 60:02d}" if s >= 3600 else f"{s // 60}-{s % 60:02d}"


def output_name(source_name: str, req: ExportRequest, source_ext: str) -> str:
    base = re.split(r"[\\/]", source_name)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = re.sub(r"[^\w\-. ()\[\]]+", "_", stem).strip(" ._") or "video"
    ext = source_ext.lstrip(".").lower() if req.fast else req.format
    return f"{stem[:80]} [{_fmt_t(req.start)} to {_fmt_t(req.end)}].{ext}"


def describe(req: ExportRequest) -> str:
    parts = [req.format.upper() if not req.fast else "Fast cut"]
    if req.crop:
        parts.append("cropped")
    if req.rotate:
        parts.append(f"rotated {req.rotate}°")
    if req.flip_h or req.flip_v:
        parts.append("flipped")
    if req.height:
        parts.append(f"{req.height}p")
    if req.mute and req.format != "mp3":
        parts.append("no audio")
    return " · ".join(parts)


def validate(req: ExportRequest, src: EditSource) -> None:
    if req.start >= src.duration:
        raise EditError("The start is past the end of the video.")
    if req.format in ("mp4", "gif") and not src.has_video:
        raise EditError("This file has no video track — export it as MP3.")
    if req.format == "mp3" and not src.has_audio:
        raise EditError("This file has no audio track.")
    if req.format == "gif" and min(req.end, src.duration) - req.start > GIF_MAX_SEC:
        raise EditError(f"GIFs are limited to {int(GIF_MAX_SEC)} seconds — trim the range first.")
    if req.fast and (req.transforms or req.format != "mp4"):
        raise EditError("Fast cut only trims. Turn it off to crop, rotate, resize or convert.")


def _video_filters(req: ExportRequest) -> list[str]:
    vf: list[str] = []
    if req.crop:
        c = req.crop
        vf.append(f"crop=trunc(iw*{c.w:.6f}/2+0.01)*2:trunc(ih*{c.h:.6f}/2+0.01)*2:trunc(iw*{c.x:.6f}):trunc(ih*{c.y:.6f})")
    vf += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(req.rotate, [])
    if req.flip_h:
        vf.append("hflip")
    if req.flip_v:
        vf.append("vflip")
    return vf


def build_command(ffmpeg: str, src: EditSource, req: ExportRequest, out: Path) -> list[str]:
    end = min(req.end, src.duration)
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
    args += ["-ss", f"{req.start:.3f}", "-i", src.path, "-t", f"{end - req.start:.3f}"]

    if req.fast:
        args += ["-map", "0:v:0?"] + ([] if req.mute else ["-map", "0:a:0?"])
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        return args + [str(out)]

    if req.format == "mp3":
        return args + ["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(out)]

    vf = _video_filters(req)
    if req.format == "gif":
        size = f"scale=-2:'min({req.height},ih)':flags=lanczos" if req.height else "scale='min(480,iw)':-2:flags=lanczos"
        vf += ["fps=12", size, "split[a][b]", "[a]palettegen=stats_mode=diff[p]", "[b][p]paletteuse=dither=bayer:bayer_scale=4"]
        return args + ["-map", "0:v:0", "-an", "-vf", ",".join(vf[:-2]) + ";" + ";".join(vf[-2:]), "-loop", "0", str(out)]

    if req.height:
        vf.append(f"scale=-2:'min({req.height},ih)'")
    args += ["-map", "0:v:0"] + ([] if req.mute or not src.has_audio else ["-map", "0:a:0"])
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF[req.quality]), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    args += ["-an"] if req.mute or not src.has_audio else ["-c:a", "aac", "-b:a", "160k"]
    return args + [str(out)]


# ------------------------------------------------------------------ manager


def _ttl_hours() -> float:
    try:
        return float(os.environ.get("CLIPAWESOME_DOWNLOAD_TTL_HOURS", "0"))
    except ValueError:
        return 0.0


class EditorManager:
    def __init__(self, root: Path | None = None):
        self._root = root
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clip-edit")
        self._sources: dict[str, EditSource] = {}
        self._tasks: dict[str, ExportTask] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root or data_path("editor")

    def _src_dir(self, source_id: str) -> Path:
        return self.root / "sources" / source_id

    def _exp_dir(self, task_id: str) -> Path:
        return self.root / "exports" / task_id

    # ---- persistence

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for meta in (self.root / "sources").glob("s_*/source.json"):
            try:
                src = EditSource.model_validate(read_json(meta, {}))
                src.path = read_json(meta, {}).get("path", "")
                self._sources[src.id] = src
            except Exception:
                continue
        for meta in (self.root / "exports").glob("e_*/task.json"):
            try:
                task = ExportTask.model_validate(read_json(meta, {}))
            except Exception:
                continue
            if task.status in ACTIVE:
                task.status, task.error = "error", "The server restarted during this export."
                write_json(meta, task.model_dump())
            self._tasks[task.id] = task

    def _save_source(self, src: EditSource) -> None:
        folder = self._src_dir(src.id)
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "source.json", {**src.model_dump(), "path": src.path})

    def _save_task(self, task: ExportTask) -> None:
        folder = self._exp_dir(task.id)
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "task.json", task.model_dump())

    def _purge_expired(self) -> None:
        ttl = _ttl_hours()
        if ttl <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
        busy = {t.source_id for t in self._tasks.values() if t.status in ACTIVE}
        for task in list(self._tasks.values()):
            if task.status not in ACTIVE and datetime.fromisoformat(task.finished_at or task.created_at) < cutoff:
                self._tasks.pop(task.id, None)
                shutil.rmtree(self._exp_dir(task.id), ignore_errors=True)
        for src in list(self._sources.values()):
            if src.id not in busy and datetime.fromisoformat(src.created_at) < cutoff:
                self._sources.pop(src.id, None)
                shutil.rmtree(self._src_dir(src.id), ignore_errors=True)

    # ---- sources

    def new_upload_path(self, filename: str) -> tuple[str, Path]:
        source_id = "s_" + uuid.uuid4().hex[:12]
        folder = self._src_dir(source_id)
        folder.mkdir(parents=True, exist_ok=True)
        return source_id, folder / ("source" + Path(filename).suffix.lower())

    def add_source(self, source_id: str, path: Path, name: str, kind: str, download_id: str | None = None) -> EditSource:
        try:
            info = probe(path)
        except Exception as err:
            raise EditError(f"Could not read this file as audio/video ({type(err).__name__}).") from err
        if info.duration <= 0:
            raise EditError("Could not read the length of this file.")
        src = EditSource(
            id=source_id,
            name=name,
            kind=kind,  # type: ignore[arg-type]
            download_id=download_id,
            path=str(path),
            duration=info.duration,
            has_video=info.has_video,
            has_audio=info.has_audio,
            width=info.width,
            height=info.height,
            fps=info.fps,
            size=path.stat().st_size,
            created_at=now_iso(),
        )
        with self._lock:
            self._load()
            self._sources[src.id] = src
        self._save_source(src)
        return src

    def source_for_download(self, download_id: str, path: Path, name: str) -> EditSource:
        with self._lock:
            self._load()
            existing = next((s for s in self._sources.values() if s.download_id == download_id and Path(s.path).is_file()), None)
        if existing:
            return existing
        return self.add_source("s_" + uuid.uuid4().hex[:12], path, name, "download", download_id)

    def sources(self) -> list[EditSource]:
        with self._lock:
            self._load()
            self._purge_expired()
            live = [s for s in self._sources.values() if Path(s.path).is_file()]
        return sorted(live, key=lambda s: s.created_at, reverse=True)

    def source(self, source_id: str) -> EditSource | None:
        with self._lock:
            self._load()
            src = self._sources.get(source_id)
        return src if src and Path(src.path).is_file() else None

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            self._load()
            if any(t.source_id == source_id and t.status in ACTIVE for t in self._tasks.values()):
                return False
            if self._sources.pop(source_id, None) is None:
                return False
        shutil.rmtree(self._src_dir(source_id), ignore_errors=True)
        return True

    # ---- exports

    def exports(self) -> list[ExportTask]:
        with self._lock:
            self._load()
            self._purge_expired()
            return sorted((t.model_copy() for t in self._tasks.values()), key=lambda t: t.created_at, reverse=True)

    def export(self, task_id: str) -> ExportTask | None:
        with self._lock:
            self._load()
            task = self._tasks.get(task_id)
            return task.model_copy() if task else None

    def start(self, req: ExportRequest) -> ExportTask:
        src = self.source(req.source_id)
        if src is None:
            raise EditError("That video is no longer available — open it again.")
        validate(req, src)
        ffmpeg = ffmpeg_path()
        if ffmpeg is None:
            raise EditError("FFmpeg is not available on this server.")
        task = ExportTask(
            id="e_" + uuid.uuid4().hex[:12],
            source_id=src.id,
            source_name=src.name,
            label=describe(req),
            format=Path(output_name(src.name, req, Path(src.path).suffix)).suffix.lstrip("."),
            created_at=now_iso(),
        )
        with self._lock:
            self._tasks[task.id] = task
        self._save_task(task)
        self._executor.submit(self._run, task.id, ffmpeg, src, req)
        return task.model_copy()

    def cancel(self, task_id: str) -> ExportTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status in ACTIVE:
                self._cancel.add(task_id)
                if task.status == "queued":
                    task.status, task.finished_at = "cancelled", now_iso()
                proc = self._procs.get(task_id)
                if proc and proc.poll() is None:
                    proc.terminate()
            snapshot = task.model_copy()
        self._save_task(snapshot)
        return snapshot

    def delete(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in ACTIVE:
                return False
            self._tasks.pop(task_id, None)
        shutil.rmtree(self._exp_dir(task_id), ignore_errors=True)
        return True

    def file_path(self, task_id: str) -> Path | None:
        task = self.export(task_id)
        if task is None or task.status != "done" or not task.file_name:
            return None
        path = self._exp_dir(task_id) / task.file_name
        return path if path.is_file() else None

    def _update(self, task_id: str, persist: bool = False, **fields: object) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            for key, value in fields.items():
                setattr(task, key, value)
            snapshot = task.model_copy()
        if persist:
            self._save_task(snapshot)

    def _run(self, task_id: str, ffmpeg: str, src: EditSource, req: ExportRequest) -> None:
        if task_id in self._cancel:
            self._cancel.discard(task_id)
            return
        folder = self._exp_dir(task_id)
        out = folder / output_name(src.name, req, Path(src.path).suffix)
        total = max(0.1, min(req.end, src.duration) - req.start)
        log_path = folder / "ffmpeg.log"
        self._update(task_id, persist=True, status="running", progress=0.0)
        try:
            with log_path.open("w", encoding="utf-8", errors="replace") as log_fh:
                proc = subprocess.Popen(
                    build_command(ffmpeg, src, req, out),
                    stdout=subprocess.PIPE,
                    stderr=log_fh,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                with self._lock:
                    self._procs[task_id] = proc
                speed: float | None = None
                assert proc.stdout is not None
                for line in proc.stdout:
                    key, _, value = line.strip().partition("=")
                    if key == "speed" and value.endswith("x"):
                        try:
                            speed = float(value[:-1])
                        except ValueError:
                            speed = None
                    elif key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
                        done = max(0.0, int(value) / 1_000_000)
                        eta = (total - done) / speed if speed else None
                        self._update(task_id, progress=min(0.99, done / total), speed=speed, eta=eta)
                code = proc.wait()
            if task_id in self._cancel:
                raise InterruptedError
            if code != 0 or not out.is_file():
                tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
                raise EditError("FFmpeg failed: " + (" | ".join(tail) or f"exit code {code}"))
            log_path.unlink(missing_ok=True)
            self._update(
                task_id, persist=True, status="done", progress=1.0, speed=None, eta=None,
                file_name=out.name, file_size=out.stat().st_size, finished_at=now_iso(),
            )
        except Exception as err:
            cancelled = task_id in self._cancel
            out.unlink(missing_ok=True)
            if not cancelled:
                log.warning("Export %s failed: %s", task_id, err)
            self._update(
                task_id, persist=True, status="cancelled" if cancelled else "error",
                error=None if cancelled else (str(err) or type(err).__name__)[:400],
                speed=None, eta=None, finished_at=now_iso(),
            )
        finally:
            with self._lock:
                self._procs.pop(task_id, None)
            self._cancel.discard(task_id)
