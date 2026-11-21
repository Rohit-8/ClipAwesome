"""YouTube downloads: list resolutions with sizes, then download/merge one in the background."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yt_dlp
from pydantic import BaseModel, Field

from . import system
from .config import data_path, read_json, write_json
from .sources import youtube
from .sources.youtube import SourceError

log = logging.getLogger("clipawesome.downloads")

INFO_TTL_SEC = 15 * 60
ACTIVE = ("queued", "downloading", "merging")
_CODEC_RANK = {"avc1": 3, "vp9": 2, "vp09": 2, "av01": 1}
_CODEC_NAME = {"avc1": "H.264", "vp9": "VP9", "vp09": "VP9", "av01": "AV1"}


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=500)


class StartDownloadRequest(DownloadRequest):
    option_id: str = Field(..., min_length=1, max_length=40)


class DownloadOption(BaseModel):
    id: str
    kind: Literal["video", "audio"]
    label: str
    quality: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    hdr: bool = False
    ext: str
    codec: str
    bitrate_kbps: float | None = None
    size: int | None = None
    approx: bool = False
    available: bool = True
    reason: str | None = None
    format_spec: str = Field("", exclude=True)


class DownloadInfo(BaseModel):
    video_id: str
    url: str
    title: str
    channel: str | None = None
    duration: float
    thumbnail: str | None = None
    license: str | None = None
    creative_commons: bool = False
    ffmpeg: bool
    options: list[DownloadOption]


class DownloadTask(BaseModel):
    id: str
    video_id: str
    title: str
    channel: str | None = None
    thumbnail: str | None = None
    option_id: str
    label: str
    ext: str
    status: Literal["queued", "downloading", "merging", "done", "error", "cancelled"] = "queued"
    stage: str = "Queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    file_name: str | None = None
    file_size: int | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ffmpeg_path() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


# ------------------------------------------------------------------ format selection


def _size(f: dict[str, Any], duration: float) -> tuple[int | None, bool]:
    if f.get("filesize"):
        return int(f["filesize"]), False
    if f.get("filesize_approx"):
        return int(f["filesize_approx"]), True
    if f.get("tbr") and duration:
        return int(float(f["tbr"]) * 125 * duration), True
    return None, True


def _codec(f: dict[str, Any]) -> str:
    return (f.get("vcodec") or "").split(".")[0]


def _quality_name(p: int) -> str:
    for limit, name in ((4320, "8K"), (2160, "4K"), (1440, "2K"), (1080, "Full HD"), (720, "HD"), (480, "SD")):
        if p >= limit:
            return name
    return "Low"


def _short_side(f: dict[str, Any]) -> int | None:
    w, h = f.get("width"), f.get("height")
    if w and h:
        return int(min(w, h))
    return int(h) if h else None


def _best_audio(audios: list[dict[str, Any]], ext: str | None = None) -> dict[str, Any] | None:
    pool = [a for a in audios if ext is None or a.get("ext") == ext]
    if not pool:
        return None
    return max(
        pool,
        key=lambda a: (
            a.get("language_preference") or 0,
            "drc" not in str(a.get("format_id")),
            (a.get("audio_channels") or 2) <= 2,
            a.get("abr") or a.get("tbr") or 0,
        ),
    )


def build_options(info: dict[str, Any], has_ffmpeg: bool) -> list[DownloadOption]:
    duration = float(info.get("duration") or 0)
    fmts = [
        f
        for f in info.get("formats") or []
        if f.get("format_id") and f.get("ext") != "mhtml" and not f.get("has_drm") and f.get("format_note") != "storyboard"
    ]
    direct = [f for f in fmts if str(f.get("protocol", "https")).startswith("http")]
    fmts = direct or fmts

    videos = [f for f in fmts if (f.get("vcodec") or "none") != "none" and _short_side(f)]
    audios = [
        f
        for f in fmts
        if (f.get("vcodec") or "none") == "none" and (f.get("acodec") or "none").split(".")[0] in ("mp4a", "opus")
    ]

    groups: dict[int, list[dict[str, Any]]] = {}
    for f in videos:
        groups.setdefault(_short_side(f) or 0, []).append(f)

    options: list[DownloadOption] = []
    for p in sorted(groups, reverse=True):
        v = max(
            groups[p],
            key=lambda f: (
                (f.get("dynamic_range") or "SDR") == "SDR",
                round(f.get("fps") or 0),
                _CODEC_RANK.get(_codec(f), 0),
                f.get("tbr") or 0,
            ),
        )
        v_size, approx = _size(v, duration)
        muxed = (v.get("acodec") or "none") != "none"
        if muxed:
            spec, ext, size = str(v["format_id"]), v.get("ext") or "mp4", v_size
        else:
            a = _best_audio(audios, "m4a" if v.get("ext") == "mp4" else "webm") or _best_audio(audios)
            if a is None:
                continue
            a_size, a_approx = _size(a, duration)
            spec = f"{v['format_id']}+{a['format_id']}"
            if (v.get("ext"), a.get("ext")) == ("mp4", "m4a"):
                ext = "mp4"
            elif (v.get("ext"), a.get("ext")) == ("webm", "webm"):
                ext = "webm"
            else:
                ext = "mkv"
            size = v_size + a_size if v_size and a_size else None
            approx = approx or a_approx
        fps = float(v["fps"]) if v.get("fps") else None
        hdr = (v.get("dynamic_range") or "SDR") != "SDR"
        options.append(
            DownloadOption(
                id=f"v{p}",
                kind="video",
                label=f"{p}p",
                quality=_quality_name(p),
                width=v.get("width"),
                height=v.get("height"),
                fps=fps,
                hdr=hdr,
                ext=ext,
                codec=_CODEC_NAME.get(_codec(v), _codec(v).upper() or "video"),
                bitrate_kbps=v.get("tbr"),
                size=size,
                approx=approx,
                available=muxed or has_ffmpeg,
                reason=None if muxed or has_ffmpeg else "Needs FFmpeg to merge video and audio",
                format_spec=f"{spec}/bv*[height<={v.get('height') or p}]+ba/b",
            )
        )

    for ext, name, codec in (("m4a", "M4A", "AAC"), ("webm", "Opus", "Opus")):
        a = _best_audio(audios, ext)
        if a is None:
            continue
        size, approx = _size(a, duration)
        abr = a.get("abr") or a.get("tbr")
        options.append(
            DownloadOption(
                id=f"a-{ext}",
                kind="audio",
                label=f"Audio · {name}",
                quality=f"{round(abr)} kbps" if abr else "Audio",
                ext=ext,
                codec=codec,
                bitrate_kbps=abr,
                size=size,
                approx=approx,
                format_spec=f"{a['format_id']}/bestaudio[ext={ext}]/bestaudio",
            )
        )
    return options


_info_cache: dict[str, tuple[float, DownloadInfo, dict[str, DownloadOption]]] = {}
_cache_lock = threading.Lock()


def get_formats(video_id: str, fresh: bool = False) -> tuple[DownloadInfo, dict[str, DownloadOption]]:
    with _cache_lock:
        hit = _info_cache.get(video_id)
        if hit and not fresh and time.monotonic() - hit[0] < INFO_TTL_SEC:
            return hit[1], hit[2]
    raw = youtube.fetch_info(video_id)
    if raw.get("is_live") or raw.get("live_status") in ("is_live", "is_upcoming"):
        raise SourceError("Live streams and premieres can't be downloaded until they have ended.")
    options = build_options(raw, ffmpeg_path() is not None)
    if not options:
        raise SourceError("YouTube returned no downloadable formats for this video.")
    license_ = raw.get("license")
    info = DownloadInfo(
        video_id=video_id,
        url=youtube.watch_url(video_id),
        title=raw.get("title") or video_id,
        channel=raw.get("channel") or raw.get("uploader"),
        duration=float(raw.get("duration") or 0),
        thumbnail=raw.get("thumbnail") or youtube.thumbnail_url(video_id),
        license=license_,
        creative_commons="creative commons" in (license_ or "").lower(),
        ffmpeg=ffmpeg_path() is not None,
        options=options,
    )
    by_id = {o.id: o for o in options}
    with _cache_lock:
        _info_cache[video_id] = (time.monotonic(), info, by_id)
    return info, by_id


# ------------------------------------------------------------------ background downloads


class _Cancelled(Exception):
    pass


class DownloadManager:
    def __init__(self, root: Path | None = None, max_workers: int = 2):
        self._root = root
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="clip-dl")
        self._tasks: dict[str, DownloadTask] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root or data_path("downloads")

    @staticmethod
    def ttl_hours() -> float:
        try:
            return float(os.environ.get("CLIPAWESOME_DOWNLOAD_TTL_HOURS", "0"))
        except ValueError:
            return 0.0

    def _dir(self, task_id: str) -> Path:
        return self.root / task_id

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.root.is_dir():
            return
        for meta in self.root.glob("d_*/task.json"):
            try:
                task = DownloadTask.model_validate(read_json(meta, {}))
            except Exception:
                continue
            if task.status in ACTIVE:
                task.status, task.stage, task.error = "error", "Interrupted", "The server restarted during this download."
                write_json(meta, task.model_dump())
            self._tasks[task.id] = task

    def _purge_expired(self) -> None:
        ttl = self.ttl_hours()
        if ttl <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
        for task in list(self._tasks.values()):
            if task.status not in ACTIVE and task.finished_at and datetime.fromisoformat(task.finished_at) < cutoff:
                self._tasks.pop(task.id, None)
                shutil.rmtree(self._dir(task.id), ignore_errors=True)

    def _save(self, task: DownloadTask) -> None:
        folder = self._dir(task.id)
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "task.json", task.model_dump())

    def _update(self, task_id: str, persist: bool = False, **fields: Any) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            for key, value in fields.items():
                setattr(task, key, value)
            snapshot = task.model_copy()
        if persist:
            self._save(snapshot)

    def list(self) -> list[DownloadTask]:
        with self._lock:
            self._load()
            self._purge_expired()
            return sorted((t.model_copy() for t in self._tasks.values()), key=lambda t: t.created_at, reverse=True)

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            self._load()
            task = self._tasks.get(task_id)
            return task.model_copy() if task else None

    def start(self, info: DownloadInfo, option: DownloadOption) -> DownloadTask:
        if not option.available:
            raise SourceError(option.reason or "This format is not available.")
        # Unknown sizes: assume ~4 Mbit/s, a typical 1080p stream.
        system.require_space(self.root, int((option.size or info.duration * 500_000) * 1.1), "this download", SourceError)
        task = DownloadTask(
            id="d_" + uuid.uuid4().hex[:12],
            video_id=info.video_id,
            title=info.title,
            channel=info.channel,
            thumbnail=info.thumbnail,
            option_id=option.id,
            label=f"{option.label} · {option.ext.upper()}" if option.kind == "video" else option.label,
            ext=option.ext,
            total_bytes=option.size,
            created_at=now_iso(),
        )
        with self._lock:
            self._load()
            self._purge_expired()
            self._tasks[task.id] = task
        self._save(task)
        self._executor.submit(self._run, task.id, info, option)
        return task.model_copy()

    def cancel(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status in ACTIVE:
                self._cancel.add(task_id)
                if task.status == "queued":
                    task.status, task.stage, task.finished_at = "cancelled", "Cancelled", now_iso()
            snapshot = task.model_copy()
        self._save(snapshot)
        return snapshot

    def delete(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in ACTIVE:
                return False
            self._tasks.pop(task_id, None)
        shutil.rmtree(self._dir(task_id), ignore_errors=True)
        return True

    def file_path(self, task_id: str) -> Path | None:
        task = self.get(task_id)
        if task is None or task.status != "done" or not task.file_name:
            return None
        path = self._dir(task_id) / task.file_name
        return path if path.is_file() else None

    def _clear_media(self, task_id: str) -> None:
        for f in self._dir(task_id).iterdir():
            if f.name != "task.json":
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink(missing_ok=True)

    def _run(self, task_id: str, info: DownloadInfo, option: DownloadOption) -> None:
        if task_id in self._cancel:
            self._cancel.discard(task_id)
            return
        folder = self._dir(task_id)
        expected = option.size or 0
        done: dict[str, int] = {}
        last = [0.0]

        def hook(d: dict[str, Any]) -> None:
            if task_id in self._cancel:
                raise _Cancelled()
            name = d.get("filename") or "file"
            if d.get("status") == "finished":
                done[name] = int(d.get("total_bytes") or d.get("downloaded_bytes") or done.get(name, 0))
                return
            if d.get("status") != "downloading":
                return
            done[name] = int(d.get("downloaded_bytes") or 0)
            now = time.monotonic()
            if now - last[0] < 0.4:
                return
            last[0] = now
            fmt = d.get("info_dict") or {}
            part = "video" if (fmt.get("vcodec") or "none") != "none" else "audio"
            total = max(expected, int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0))
            got = sum(done.values())
            self._update(
                task_id,
                status="downloading",
                stage=f"Downloading {part}" if option.kind == "video" else "Downloading",
                downloaded_bytes=got,
                total_bytes=max(total, got) or None,
                progress=min(0.99, got / total) if total else 0.0,
                speed=d.get("speed"),
                eta=d.get("eta"),
            )

        def pp_hook(d: dict[str, Any]) -> None:
            if task_id in self._cancel:
                raise _Cancelled()
            if d.get("status") == "started" and d.get("postprocessor") == "Merger":
                self._update(task_id, status="merging", stage="Merging video and audio", speed=None, eta=None, progress=0.99)

        opts = youtube.base_opts()
        opts.update(
            {
                "skip_download": False,
                "format": option.format_spec,
                "outtmpl": str(folder / "%(title).120B [%(id)s].%(ext)s"),
                "windowsfilenames": True,
                "overwrites": True,
                "retries": 5,
                "fragment_retries": 5,
                "progress_hooks": [hook],
                "postprocessor_hooks": [pp_hook],
            }
        )
        if option.kind == "video" and "+" in option.format_spec.split("/")[0]:
            opts["merge_output_format"] = option.ext
        ffmpeg = ffmpeg_path()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        self._update(task_id, persist=True, status="downloading", stage="Starting")
        try:
            def run() -> dict:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(info.url, download=True)

            result = youtube.retry_blocked(run)
            files = result.get("requested_downloads") or []
            path = Path(files[0]["filepath"]) if files and files[0].get("filepath") else None
            if path is None or not path.is_file():
                raise SourceError("The download finished but the file was not found.")
            size = path.stat().st_size
            self._update(
                task_id,
                persist=True,
                status="done",
                stage="Ready",
                progress=1.0,
                file_name=path.name,
                file_size=size,
                downloaded_bytes=size,
                total_bytes=size,
                speed=None,
                eta=None,
                finished_at=now_iso(),
            )
        except Exception as err:
            cancelled = task_id in self._cancel
            if not cancelled:
                log.warning("Download %s failed: %s", task_id, err)
            self._clear_media(task_id)
            message = None if cancelled else (youtube._clean_error(err) if isinstance(err, yt_dlp.utils.DownloadError) else str(err) or type(err).__name__)
            self._update(
                task_id,
                persist=True,
                status="cancelled" if cancelled else "error",
                stage="Cancelled" if cancelled else "Failed",
                error=message,
                speed=None,
                eta=None,
                finished_at=now_iso(),
            )
        finally:
            self._cancel.discard(task_id)
