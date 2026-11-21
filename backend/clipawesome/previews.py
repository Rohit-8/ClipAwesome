"""Server-side playable copies of YouTube videos, for browsers that can't show YouTube's embedded player."""

from __future__ import annotations

import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import yt_dlp
from pydantic import BaseModel

from .config import data_path
from .downloads import DownloadManager, ffmpeg_path
from .editor import make_preview_audio
from .sources import youtube
from .sources.local_media import probe

log = logging.getLogger("clipawesome.previews")

# YouTube's progressive 360p MP4 (format 18) needs no merging; the rest are fallbacks for videos without it.
PREVIEW_FORMAT = "18/b[height<=480][vcodec^=avc1][acodec^=mp4a]/bv*[height<=480][vcodec^=avc1]+ba[ext=m4a]/b[height<=480]/b"
KEEP = 10
PLAYABLE = (".mp4", ".webm", ".m4v")


class PreviewStatus(BaseModel):
    video_id: str
    status: Literal["none", "downloading", "ready", "error"] = "none"
    progress: float = 0.0
    size: int | None = None
    audio_codec: str | None = None
    reused_download: bool = False
    error: str | None = None


class PreviewManager:
    def __init__(self, downloads: DownloadManager, root: Path | None = None):
        self._downloads = downloads
        self._root = root
        self._jobs: dict[str, PreviewStatus] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clip-preview")

    @property
    def root(self) -> Path:
        return self._root or data_path("youtube_previews")

    @staticmethod
    def _check(video_id: str) -> str:
        # The id becomes a folder name, so only accept a bare 11-character YouTube id.
        if youtube.parse_video_id(video_id) != video_id:
            raise ValueError("Not a YouTube video id")
        return video_id

    def _own_file(self, video_id: str) -> Path | None:
        return next((p for p in sorted((self.root / video_id).glob("preview.*")) if p.suffix in PLAYABLE), None)

    def _downloaded_file(self, video_id: str) -> Path | None:
        for task in self._downloads.list():
            if task.video_id == video_id and task.status == "done" and f".{task.ext}" in PLAYABLE:
                path = self._downloads.file_path(task.id)
                if path is not None:
                    return path
        return None

    def file(self, video_id: str) -> Path | None:
        video_id = self._check(video_id)
        return self._downloaded_file(video_id) or self._own_file(video_id)

    def status(self, video_id: str) -> PreviewStatus:
        video_id = self._check(video_id)
        with self._lock:
            job = self._jobs.get(video_id)
        if job and job.status in ("downloading", "error"):
            return job.model_copy()
        path = self.file(video_id)
        if path is None:
            return PreviewStatus(video_id=video_id)
        try:
            codec = probe(path).audio_codec
        except Exception:
            codec = None
        reused = path.parent != self.root / video_id
        return PreviewStatus(video_id=video_id, status="ready", progress=1.0, size=path.stat().st_size, audio_codec=codec, reused_download=reused)

    def start(self, video_id: str) -> PreviewStatus:
        current = self.status(video_id)
        if current.status in ("ready", "downloading"):
            return current
        with self._lock:
            running = self._jobs.get(video_id)
            if running and running.status == "downloading":  # another request started it meanwhile
                return running.model_copy()
            job = self._jobs[video_id] = PreviewStatus(video_id=video_id, status="downloading")
        self._executor.submit(self._run, video_id)
        return job.model_copy()

    def audio(self, video_id: str) -> Path | None:
        path = self.file(video_id)
        if path is None:
            return None
        return make_preview_audio(path, self.root / video_id / "audio.mp3")

    def _update(self, video_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(video_id)
            if job is not None:
                for key, value in fields.items():
                    setattr(job, key, value)

    def _run(self, video_id: str) -> None:
        folder = self.root / video_id
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)

        def hook(d: dict[str, Any]) -> None:
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if d.get("status") == "downloading" and total:
                self._update(video_id, progress=min(0.99, (d.get("downloaded_bytes") or 0) / total))

        opts = youtube.base_opts()
        opts.update({
            "skip_download": False,
            "format": PREVIEW_FORMAT,
            "outtmpl": str(folder / "preview.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
        })
        ffmpeg = ffmpeg_path()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        def run() -> None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(youtube.watch_url(video_id), download=True)

        try:
            youtube.retry_blocked(run)
            if self._own_file(video_id) is None:
                raise youtube.SourceError("The download finished but no playable file was produced.")
            with self._lock:
                self._jobs.pop(video_id, None)
            self._prune()
        except Exception as err:
            message = youtube._clean_error(err) if isinstance(err, yt_dlp.utils.DownloadError) else str(err) or type(err).__name__
            log.warning("Preview %s failed: %s", video_id, message)
            shutil.rmtree(folder, ignore_errors=True)
            self._update(video_id, status="error", error=message[:300])

    def _prune(self) -> None:
        with self._lock:
            busy = {vid for vid, job in self._jobs.items() if job.status == "downloading"}
        folders = sorted((p for p in self.root.iterdir() if p.is_dir() and p.name not in busy), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in folders[KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
