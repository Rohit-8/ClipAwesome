"""From suggested clips to finished files: get an editable copy of the source video, then export one or many clips."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from .downloads import DownloadManager, DownloadTask, get_formats, now_iso
from .editor import CaptionOptions, CropBox, EditError, EditorManager, EditSource, ExportRequest, display_size
from .models import Analysis, SourceVideo
from .sources.youtube import SourceError
from .store import Store

log = logging.getLogger("clipawesome.clipexport")

QUALITIES = (360, 480, 720, 1080, 1440, 2160)
FRAMES = {"9:16": 9 / 16, "1:1": 1.0}


class BatchOptions(BaseModel):
    clip_ids: list[str] = Field(..., min_length=1, max_length=30)
    download_quality: int = 720
    frame: Literal["original", "9:16", "1:1"] = "original"
    captions: Literal["off", "bold", "classic", "boxed"] = "off"
    normalize: bool = True
    quality: Literal["high", "balanced", "small"] = "balanced"


class Batch(BaseModel):
    id: str
    analysis_id: str
    status: Literal["preparing", "done", "error"] = "preparing"
    stage: str = "Starting"
    total: int
    export_ids: list[str] = []
    errors: list[str] = []
    created_at: str


def center_crop(src: EditSource, frame: str) -> CropBox | None:
    """Centred crop box (normalised 0–1) that turns the source frame into `frame`'s shape."""
    target = FRAMES.get(frame)
    if target is None:
        return None
    w, h = display_size(src)
    aspect = w / h
    if abs(aspect - target) < 0.01:
        return None
    if aspect > target:
        cw = target / aspect
        return CropBox(x=(1 - cw) / 2, y=0, w=cw, h=1)
    ch = aspect / target
    return CropBox(x=0, y=(1 - ch) / 2, w=1, h=ch)


def _height(task: DownloadTask) -> int:
    try:
        return int(task.option_id.lstrip("v"))
    except ValueError:
        return 0


class ClipExporter:
    def __init__(self, store: Store, downloads: DownloadManager, editor: EditorManager):
        self.store = store
        self.downloads = downloads
        self.editor = editor
        self._batches: dict[str, Batch] = {}
        self._lock = threading.Lock()

    @staticmethod
    def source_of(analysis: Analysis, source_id: str) -> SourceVideo:
        source = next((s for s in analysis.sources if s.id == source_id), None)
        if source is None:
            raise EditError("That video isn't part of this analysis.")
        return source

    def _youtube_download(self, video_id: str, quality: int) -> DownloadTask | None:
        """The smallest finished (else running) video download of this video at `quality` or better."""
        tasks = [t for t in self.downloads.list() if t.video_id == video_id and t.option_id.startswith("v") and _height(t) >= quality]
        for status in (("done",), ("queued", "downloading", "merging")):
            match = sorted((t for t in tasks if t.status in status), key=_height)
            if match:
                return match[0]
        return None

    def ensure_source(self, analysis: Analysis, source_id: str, quality: int = 720) -> dict[str, Any]:
        """`{"status": "ready", "source": EditSource}` or `{"status": "downloading", "download": DownloadTask}`."""
        source = self.source_of(analysis, source_id)
        if source.platform == "local":
            path = self.store.media_file(source.media_id or "")
            if path is None:
                raise EditError("The analysed file is no longer on the server. Upload it in the editor instead.")
            return {"status": "ready", "source": self.editor.source_for_file(f"media:{source.media_id}", path, source.title)}

        video_id = source.video_id or ""
        task = self._youtube_download(video_id, quality)
        if task is None:
            info, options = get_formats(video_id)
            videos = sorted((o for o in options.values() if o.kind == "video" and o.available and o.height), key=lambda o: o.height or 0)
            if not videos:
                raise SourceError("No downloadable video format was found for this video.")
            fitting = [o for o in videos if (o.height or 0) <= quality]
            task = self.downloads.start(info, (fitting or videos)[-1 if fitting else 0])
        if task.status != "done":
            return {"status": "downloading", "download": task}
        path = self.downloads.file_path(task.id)
        if path is None:
            raise EditError("The downloaded file is missing. Download it again.")
        return {"status": "ready", "source": self.editor.source_for_download(task.id, path, path.name)}

    def _wait_source(self, analysis: Analysis, source_id: str, quality: int, stage: Callable[[str], None]) -> EditSource:
        while True:
            result = self.ensure_source(analysis, source_id, quality)
            if result["status"] == "ready":
                return result["source"]
            task: DownloadTask = result["download"]
            if task.status in ("error", "cancelled"):
                raise SourceError(task.error or "The download was cancelled.")
            stage(f"Downloading “{task.title}” ({round(task.progress * 100)}%)")
            time.sleep(2)

    def batch(self, batch_id: str) -> Batch | None:
        with self._lock:
            b = self._batches.get(batch_id)
            return b.model_copy(deep=True) if b else None

    def start_batch(self, analysis: Analysis, opts: BatchOptions, use_gpu: bool, whisper: dict[str, Any] | None) -> Batch:
        wanted = set(opts.clip_ids)
        clips = [c for c in analysis.clips if c.id in wanted]
        if not clips:
            raise EditError("None of those clips are in this analysis.")
        batch = Batch(id="b_" + uuid.uuid4().hex[:12], analysis_id=analysis.id, total=len(clips), created_at=now_iso())
        with self._lock:
            self._batches[batch.id] = batch
            for old in sorted(self._batches.values(), key=lambda b: b.created_at)[:-50]:
                self._batches.pop(old.id, None)
        threading.Thread(target=self._run, args=(batch.id, analysis, clips, opts, use_gpu, whisper), name="clip-batch", daemon=True).start()
        return batch.model_copy()

    def _set(self, batch_id: str, **fields: Any) -> None:
        with self._lock:
            b = self._batches.get(batch_id)
            if b is not None:
                for key, value in fields.items():
                    setattr(b, key, value)

    def _run(self, batch_id: str, analysis: Analysis, clips: list, opts: BatchOptions, use_gpu: bool, whisper: dict[str, Any] | None) -> None:
        exports: list[str] = []
        errors: list[str] = []
        sources = list(dict.fromkeys(c.source_id for c in clips))
        for i, sid in enumerate(sources, 1):
            group = [c for c in clips if c.source_id == sid]
            try:
                self._set(batch_id, stage=f"Getting video {i} of {len(sources)} ready…")
                src = self._wait_source(analysis, sid, opts.download_quality, lambda s: self._set(batch_id, stage=s))
            except Exception as err:
                errors.append(f"{len(group)} clip(s) skipped: {err}")
                continue
            lines = [(t.start, t.end, t.text) for t in analysis.transcripts.get(sid, [])]
            for clip in group:
                try:
                    req = ExportRequest(
                        source_id=src.id,
                        start=clip.start,
                        end=min(clip.end, src.duration),
                        crop=center_crop(src, opts.frame) if src.has_video else None,
                        format="mp4" if src.has_video else "mp3",
                        quality=opts.quality,
                        normalize=opts.normalize and src.has_audio,
                        captions=CaptionOptions(style=opts.captions) if opts.captions != "off" and src.has_video else None,
                        title=f"{clip.rank:02d} {clip.title}" if clip.rank else clip.title,
                    )
                    exports.append(self.editor.start(req, use_gpu, caption_lines=lines or None, whisper=whisper).id)
                except Exception as err:
                    errors.append(f"“{clip.title}”: {err}")
                self._set(batch_id, export_ids=list(exports), errors=list(errors), stage=f"Queued {len(exports)} of {len(clips)} exports")
        status = "done" if exports else "error"
        self._set(batch_id, status=status, export_ids=exports, errors=errors, stage=f"{len(exports)} export(s) queued" if exports else "Nothing could be exported")
