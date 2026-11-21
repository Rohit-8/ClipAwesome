"""Simple video editing with FFmpeg: trim, crop, rotate/flip, resize, mute, convert (MP4 / MP3 / GIF) and merge clips."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import av
from pydantic import BaseModel, Field, model_validator

from . import captions as cap
from . import gpu, system
from .config import data_path, read_json, write_json
from .downloads import ffmpeg_path, now_iso
from .sources import transcribe
from .sources.local_media import probe

log = logging.getLogger("clipawesome.editor")

ACTIVE = ("queued", "running")
HEIGHTS = (2160, 1440, 1080, 720, 480, 360)
GIF_MAX_SEC = 60.0
MAX_MERGE_CLIPS = 20
FRAME_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
FFMPEG_HEAD = ("-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1")
# -14 LUFS integrated is what YouTube, Instagram, TikTok and Spotify normalise to, so clips play at a consistent level.
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
CAPTIONS_FILE = "captions.ass"


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


class CaptionOptions(BaseModel):
    style: Literal["bold", "classic", "boxed"] = "bold"
    position: Literal["bottom", "center"] = "bottom"
    # Use this analysis' transcript (same video, same timeline); otherwise the clip is transcribed with Whisper.
    analysis_id: str | None = Field(None, max_length=40)
    analysis_source: str | None = Field(None, max_length=40)


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
    normalize: bool = False
    captions: CaptionOptions | None = None
    title: str | None = Field(None, max_length=120)

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
    kind: Literal["upload", "download", "analysis"]
    download_id: str | None = None
    origin: str | None = None  # dedupe key for files opened from an analysis ("media:<id>")
    path: str = Field("", exclude=True)
    duration: float
    has_video: bool
    has_audio: bool
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    rotation: int = 0
    fps: float | None = None
    size: int
    created_at: str


class MergeClip(BaseModel):
    source_id: str = Field(..., min_length=3, max_length=40)
    start: float = Field(0, ge=0)
    end: float = Field(..., gt=0)

    @model_validator(mode="after")
    def _check(self) -> MergeClip:
        if self.end - self.start < 0.1:
            raise ValueError("each clip must end after it starts")
        return self


class MergeRequest(BaseModel):
    clips: list[MergeClip] = Field(..., min_length=2, max_length=MAX_MERGE_CLIPS)
    frame: Literal["first", "16:9", "9:16", "1:1"] = "first"
    fit: Literal["pad", "crop"] = "pad"
    resolution: int | None = None  # short side of the output frame
    mute: bool = False
    format: Literal["mp4", "mp3"] = "mp4"
    quality: Literal["high", "balanced", "small"] = "balanced"
    fast: bool = False
    normalize: bool = False

    @model_validator(mode="after")
    def _check(self) -> MergeRequest:
        if self.resolution is not None and self.resolution not in HEIGHTS:
            raise ValueError(f"resolution must be one of {HEIGHTS}")
        return self


class ExportTask(BaseModel):
    id: str
    source_id: str
    source_ids: list[str] = Field(default_factory=list)
    source_name: str
    label: str
    format: str
    encoder: str | None = None
    status: Literal["queued", "running", "done", "error", "cancelled"] = "queued"
    stage: str | None = None
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


def _safe_stem(name: str) -> str:
    base = re.split(r"[\\/]", name)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return re.sub(r"[^\w\-. ()\[\]]+", "_", stem).strip(" ._") or "video"


def _safe_title(title: str) -> str:
    """A clip title as a file stem: `Moment · 10:04` → `Moment - 10-04` (no extension stripping)."""
    t = re.sub(r"(\d):(\d)", r"\1-\2", title)
    t = re.sub(r"\s*[·•|:/\\]+\s*", " - ", t)
    t = re.sub(r"[^\w\-. ()\[\]]+", " ", t)
    return re.sub(r"\s+", " ", t).strip(" ._-") or "clip"


def _even(n: float) -> int:
    return max(2, round(n / 2) * 2)


def output_name(source_name: str, req: ExportRequest, source_ext: str) -> str:
    ext = source_ext.lstrip(".").lower() if req.fast else req.format
    stem = _safe_title(req.title) if req.title else _safe_stem(source_name)
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
    if req.captions:
        parts.append("captions")
    if req.normalize:
        parts.append("−14 LUFS")
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
    if req.fast and (req.transforms or req.format != "mp4" or req.captions or req.normalize):
        raise EditError("Fast cut only trims. Turn it off to crop, rotate, resize, add captions, even out the volume or convert.")
    if req.captions and req.format != "mp4":
        raise EditError("Captions can only be added to MP4 video exports.")
    if req.normalize and (req.format == "gif" or req.mute or not src.has_audio):
        raise EditError("Volume levelling needs an export that keeps the audio.")


def output_size(src: EditSource, req: ExportRequest) -> tuple[int, int]:
    """Pixel size of the exported video (mirrors the crop/rotate/scale filters)."""
    w, h = display_size(src)
    if req.crop:
        w, h = 2 * int(w * req.crop.w / 2 + 0.01), 2 * int(h * req.crop.h / 2 + 0.01)
    if req.rotate in (90, 270):
        w, h = h, w
    if req.height and h > req.height:
        w, h = _even(w * req.height / h), req.height
    return max(2, w), max(2, h)


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


def build_command(
    ffmpeg: str,
    src: EditSource,
    req: ExportRequest,
    out: Path,
    codec: str | None = None,
    preset: str = "veryfast",
    threads: int = 0,
    captions_file: str | None = None,
) -> list[str]:
    """`codec` is a GPU H.264 encoder (see gpu.py); None encodes on the CPU with x264.

    `captions_file` is relative to the working directory FFmpeg runs in (Windows drive colons break the filter syntax).
    """
    end = min(req.end, src.duration)
    args = [ffmpeg, *FFMPEG_HEAD]
    args += ["-ss", f"{req.start:.3f}", "-i", src.path, "-t", f"{end - req.start:.3f}"]

    if req.fast:
        args += ["-map", "0:v:0?"] + ([] if req.mute else ["-map", "0:a:0?"])
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        return args + [str(out)]

    # loudnorm upsamples to 192 kHz internally, so the output rate is set explicitly.
    level = lambda rate: ["-af", LOUDNORM, "-ar", str(rate)] if req.normalize else []  # noqa: E731
    if req.format == "mp3":
        return args + ["-map", "0:a:0", "-vn", *level(44100), "-c:a", "libmp3lame", "-q:a", "2", str(out)]

    vf = _video_filters(req)
    if req.format == "gif":
        size = f"scale=-2:'min({req.height},ih)':flags=lanczos" if req.height else "scale='min(480,iw)':-2:flags=lanczos"
        vf += ["fps=12", size, "split[a][b]", "[a]palettegen=stats_mode=diff[p]", "[b][p]paletteuse=dither=bayer:bayer_scale=4"]
        return args + ["-map", "0:v:0", "-an", "-vf", ",".join(vf[:-2]) + ";" + ";".join(vf[-2:]), "-loop", "0", str(out)]

    if req.height:
        vf.append(f"scale=-2:'min({req.height},ih)'")
    if captions_file:
        vf.append(f"subtitles={captions_file}")
    args += ["-map", "0:v:0"] + ([] if req.mute or not src.has_audio else ["-map", "0:a:0"])
    if vf:
        args += ["-vf", ",".join(vf)]
    args += [*gpu.video_args(req.quality, codec, preset), "-movflags", "+faststart"]
    if codec is None and threads:
        args += ["-threads", str(threads)]
    args += ["-an"] if req.mute or not src.has_audio else [*level(48000), "-c:a", "aac", "-b:a", "160k"]
    return args + [str(out)]


# ------------------------------------------------------------------ merging


def display_size(src: EditSource) -> tuple[int, int]:
    w, h = src.width or 1920, src.height or 1080
    return (h, w) if src.rotation in (90, 270) else (w, h)


def merge_canvas(req: MergeRequest, first: EditSource) -> tuple[int, int]:
    """Output frame: the first video clip's shape or a fixed ratio, with `resolution` as the short side."""
    w, h = display_size(first)
    ratio = FRAME_RATIOS.get(req.frame, w / h)
    short = req.resolution or min(w, h)
    return (_even(short * ratio), _even(short)) if ratio >= 1 else (_even(short), _even(short / ratio))


def merge_fps(first: EditSource) -> float:
    return min(60.0, max(1.0, round(first.fps, 3))) if first.fps else 30.0


def stream_signature(path: Path) -> tuple[Any, Any]:
    """What must match for clips to be joined without re-encoding."""
    with av.open(str(path)) as c:
        v = c.streams.video[0] if c.streams.video else None
        a = c.streams.audio[0] if c.streams.audio else None
        sv = (v.codec_context.name, v.codec_context.width, v.codec_context.height, v.codec_context.pix_fmt, round(float(v.average_rate or 0), 2)) if v else None
        sa = (a.codec_context.name, a.codec_context.sample_rate, a.codec_context.channels) if a else None
    return sv, sa


def _sig_text(sig: tuple[Any, Any]) -> str:
    v, a = sig
    text = f"{v[1]}×{v[2]} {v[0]} {v[4]:g} fps" if v else "no video"
    return text + (f", {a[0]} {a[1]} Hz" if a else ", no audio")


def validate_merge(req: MergeRequest, items: list[tuple[MergeClip, EditSource]], signature: Callable[[Path], tuple[Any, Any]] = stream_signature) -> None:
    for n, (clip, src) in enumerate(items, 1):
        if clip.start >= src.duration:
            raise EditError(f"Clip {n} starts after the end of “{src.name}”.")
    if req.format == "mp4" and not any(s.has_video for _, s in items):
        raise EditError("None of these clips has video — merge them as MP3.")
    if req.format == "mp3" and not any(s.has_audio for _, s in items):
        raise EditError("None of these clips has audio.")
    if not req.fast:
        return
    if req.normalize:
        raise EditError("Fast merge can't change the volume. Turn off Fast merge to level the audio.")
    if req.format != "mp4" or not all(s.has_video for _, s in items):
        raise EditError("Fast merge only joins video clips. Turn it off to re-encode.")
    sigs = [(signature(Path(s.path)), s.rotation) for _, s in items]
    (v0, a0), rot0 = sigs[0]
    for n, ((v, a), rot) in enumerate(sigs[1:], 2):
        if v != v0 or rot != rot0 or (not req.mute and a != a0):
            raise EditError(
                f"Fast merge needs every clip in the same format, but clip {n} is {_sig_text((v, a))} and clip 1 is {_sig_text((v0, a0))}. "
                "Turn off Fast merge to re-encode them."
            )


def build_merge_command(
    ffmpeg: str,
    items: list[tuple[MergeClip, EditSource]],
    req: MergeRequest,
    out: Path,
    codec: str | None = None,
    preset: str = "veryfast",
    threads: int = 0,
) -> list[str]:
    video = req.format == "mp4"
    audio = req.format == "mp3" or (not req.mute and any(s.has_audio for _, s in items))
    rate = 44100 if req.format == "mp3" else 48000
    args = [ffmpeg, *FFMPEG_HEAD]
    graph: list[str] = []
    pads: list[str] = []
    if video:
        first = next(s for _, s in items if s.has_video)
        w, h = merge_canvas(req, first)
        fps = f"{merge_fps(first):g}"
        if req.fit == "pad":
            fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        else:
            fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    for i, (clip, src) in enumerate(items):
        dur = min(clip.end, src.duration) - clip.start
        args += ["-ss", f"{clip.start:.3f}", "-t", f"{dur:.3f}", "-i", src.path]
        if video:
            if src.has_video:
                graph.append(f"[{i}:v:0]{fit},setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
            else:
                graph.append(f"color=c=black:s={w}x{h}:r={fps}:d={dur:.3f},format=yuv420p,setsar=1[v{i}]")
            pads.append(f"[v{i}]")
        if audio:
            if src.has_audio:
                graph.append(f"[{i}:a:0]aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")
            else:
                graph.append(f"anullsrc=r={rate}:cl=stereo,atrim=duration={dur:.3f}[a{i}]")
            pads.append(f"[a{i}]")
    level = audio and req.normalize
    outs = ("[v]" if video else "") + (("[am]" if level else "[a]") if audio else "")
    graph.append(f"{''.join(pads)}concat=n={len(items)}:v={int(video)}:a={int(audio)}{outs}")
    if level:
        graph.append(f"[am]{LOUDNORM},aresample={rate}[a]")
    args += ["-filter_complex", ";".join(graph)]
    if video:
        args += ["-map", "[v]", *gpu.video_args(req.quality, codec, preset), "-movflags", "+faststart"]
        if codec is None and threads:
            args += ["-threads", str(threads)]
    if audio:
        args += ["-map", "[a]", *(["-c:a", "libmp3lame", "-q:a", "2"] if req.format == "mp3" else ["-c:a", "aac", "-b:a", "160k"])]
    return args + [str(out)]


def ffconcat(items: list[tuple[MergeClip, EditSource]]) -> str:
    lines = ["ffconcat version 1.0"]
    for clip, src in items:
        path = src.path.replace("'", "'\\''")
        lines += [f"file '{path}'", f"inpoint {clip.start:.3f}", f"outpoint {min(clip.end, src.duration):.3f}"]
    return "\n".join(lines) + "\n"


def build_fast_merge_command(ffmpeg: str, listing: Path, out: Path, mute: bool) -> list[str]:
    args = [ffmpeg, *FFMPEG_HEAD, "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:v:0?"]
    if not mute:
        args += ["-map", "0:a:0?"]
    return args + ["-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]


def describe_merge(req: MergeRequest, canvas: tuple[int, int] | None) -> str:
    parts = [f"Merge · {len(req.clips)} clips"]
    if req.fast:
        parts.append("Fast")
    elif req.format == "mp3":
        parts.append("MP3")
    elif canvas:
        parts.append(f"{canvas[0]}×{canvas[1]}")
    if req.mute and req.format == "mp4":
        parts.append("no audio")
    if req.normalize:
        parts.append("−14 LUFS")
    return " · ".join(parts)


def merge_output_name(names: list[str], ext: str) -> str:
    stem = _safe_stem(names[0])[:70]
    suffix = f" (merged {len(names)} parts)" if len(set(names)) == 1 else f" + {len(names) - 1} more"
    return f"{stem}{suffix}.{ext}"


# ------------------------------------------------------------------ manager

_preview_locks: dict[str, threading.Lock] = {}
_preview_guard = threading.Lock()


def make_preview_audio(src: Path, out: Path) -> Path:
    """Cached MP3 copy of a file's audio for browsers that can't decode the original codec (e.g. AAC in VS Code)."""
    with _preview_guard:
        lock = _preview_locks.setdefault(str(out), threading.Lock())
    with lock:
        if out.is_file():
            return out
        ffmpeg = ffmpeg_path()
        if ffmpeg is None:
            raise EditError("FFmpeg is not available on this server.")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.mp3")
        # Constant bitrate keeps browser seeking accurate, which the A/V sync relies on.
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
               "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", str(tmp)]
        done = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise EditError("Could not prepare preview audio: " + (done.stderr.strip().splitlines() or ["unknown error"])[-1])
        tmp.replace(out)
        return out


def _ttl_hours() -> float:
    try:
        return float(os.environ.get("CLIPAWESOME_DOWNLOAD_TTL_HOURS", "0"))
    except ValueError:
        return 0.0


_caption_checks: dict[str, str | None] = {}


def caption_problem(ffmpeg: str, refresh: bool = False) -> str | None:
    """Why this FFmpeg can't burn in captions (no libass, no fonts), or None when a test render works. Cached."""
    if not refresh and ffmpeg in _caption_checks:
        return _caption_checks[ffmpeg]
    problem: str | None = None
    with tempfile.TemporaryDirectory(prefix="ca_caption_check_") as work:
        Path(work, CAPTIONS_FILE).write_text(cap.ass([(0.0, 1.0, "Test")], 320, 180, "classic"), encoding="utf-8")
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2",
               "-vf", f"subtitles={CAPTIONS_FILE}", "-frames:v", "1", "-f", "null", "-"]
        try:
            done = subprocess.run(cmd, cwd=work, capture_output=True, text=True, errors="replace", timeout=60,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            err = done.stderr
            if "No such filter" in err:
                problem = "This server's FFmpeg can't draw captions (it was built without libass). Turn captions off, or set IMAGEIO_FFMPEG_EXE to an FFmpeg with libass."
            elif "failed to find any fallback" in err or "no usable fontconfig" in err.lower():
                problem = "No fonts are installed on this server, so captions can't be drawn. Install some (e.g. apt install fontconfig fonts-dejavu-core) and restart."
            elif done.returncode != 0:
                problem = "FFmpeg couldn't draw a test caption: " + (err.strip().splitlines() or ["unknown error"])[-1]
        except (OSError, subprocess.SubprocessError) as exc:
            problem = f"FFmpeg couldn't draw a test caption ({type(exc).__name__})."
    _caption_checks[ffmpeg] = problem
    return problem


def _rotation(path: Path) -> int:
    """Display rotation (0/90/180/270): phones often store portrait video sideways plus a rotation flag."""
    try:
        with av.open(str(path)) as c:
            frame = next(c.decode(video=0), None)
            return int(round(frame.rotation)) % 360 if frame is not None else 0
    except Exception:
        return 0


def _encoder_label(encodes: bool, enc: gpu.Encoder | None) -> str | None:
    if not encodes:
        return None
    return f"GPU · {enc.name}" if enc else "CPU · x264"


def _uses(task: ExportTask, source_id: str) -> bool:
    return source_id in (task.source_ids or [task.source_id])


def _space_needed(src: EditSource, seconds: float, fmt: str) -> int:
    """Rough output size: the source's own bitrate for that stretch (re-encodes rarely exceed it), plus headroom."""
    if fmt == "mp3":
        return int(seconds * 24_000) + 5 * system.MB
    share = src.size * min(1.0, seconds / src.duration) if src.duration else src.size
    return int(share * 1.5) + 20 * system.MB


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
        busy = {sid for t in self._tasks.values() if t.status in ACTIVE for sid in (t.source_ids or [t.source_id])}
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
            audio_codec=info.audio_codec,
            width=info.width,
            height=info.height,
            rotation=_rotation(path) if info.has_video else 0,
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

    def source_for_file(self, origin: str, path: Path, name: str) -> EditSource:
        """Editor source for a file the app already has (an analysed upload, a YouTube playback copy), reused per origin."""
        with self._lock:
            self._load()
            existing = next((s for s in self._sources.values() if s.origin == origin and Path(s.path) == path and path.is_file()), None)
        if existing:
            return existing
        src = self.add_source("s_" + uuid.uuid4().hex[:12], path, name, "analysis")
        src.origin = origin
        self._save_source(src)
        return src

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
        if src is None or not Path(src.path).is_file():
            return None
        if src.has_audio and src.audio_codec is None:
            try:
                src.audio_codec = probe(Path(src.path)).audio_codec
                self._save_source(src)
            except Exception:
                pass
        return src

    def preview_audio(self, source_id: str) -> Path | None:
        src = self.source(source_id)
        if src is None or not src.has_audio:
            return None
        return make_preview_audio(Path(src.path), self._src_dir(source_id) / "preview.mp3")

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            self._load()
            if any(_uses(t, source_id) and t.status in ACTIVE for t in self._tasks.values()):
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

    def start(
        self,
        req: ExportRequest,
        use_gpu: bool = False,
        caption_lines: list[tuple[float, float, str]] | None = None,
        whisper: dict[str, Any] | None = None,
    ) -> ExportTask:
        """`caption_lines` is the analysis transcript for captions; without it, `whisper` settings transcribe the clip."""
        src = self.source(req.source_id)
        if src is None:
            raise EditError("That video is no longer available — open it again.")
        validate(req, src)
        ffmpeg = ffmpeg_path()
        if ffmpeg is None:
            raise EditError("FFmpeg is not available on this server.")
        end = min(req.end, src.duration)
        if req.captions and caption_lines is None and (whisper is None or not transcribe.available()):
            raise EditError("Captions need a transcript: open this clip from an analysis, or install the 'transcribe' extra (faster-whisper).")
        if req.captions and (problem := caption_problem(ffmpeg)):
            raise EditError(problem)
        system.require_space(self.root, _space_needed(src, end - req.start, req.format), "this export", EditError)
        name = output_name(src.name, req, Path(src.path).suffix)
        task = ExportTask(
            id="e_" + uuid.uuid4().hex[:12],
            source_id=src.id,
            source_ids=[src.id],
            source_name=src.name,
            label=describe(req),
            format=Path(name).suffix.lstrip("."),
            created_at=now_iso(),
        )
        folder = self._exp_dir(task.id)
        out = folder / name

        def prepare() -> str | None:
            if not req.captions:
                return None
            words = cap.words_from_lines(caption_lines, req.start, end) if caption_lines else []
            # Focused transcription leaves gaps, so a clip outside the transcribed parts is transcribed now.
            if not words and whisper is not None and transcribe.available():
                self._update(task.id, stage="Transcribing the clip for captions…")
                items, _ = transcribe.transcribe(Path(src.path), duration=src.duration, windows=[(req.start, end)], **whisper)
                words = cap.clip_words(items, req.start, end)
            if not words:
                raise EditError("No speech was found in this clip, so there are no captions to add. Turn captions off and export again.")
            w, h = output_size(src, req)
            groups = cap.group(words, req.captions.style)
            (folder / CAPTIONS_FILE).write_text(cap.ass(groups, w, h, req.captions.style, req.captions.position), encoding="utf-8")
            self._update(task.id, stage=None)
            return CAPTIONS_FILE

        def build(codec: str | None, captions_file: str | None) -> list[str]:
            prof = system.active()
            return build_command(ffmpeg, src, req, out, codec, prof.x264_preset, prof.threads, captions_file)

        total = max(0.1, end - req.start)
        encodes = req.format == "mp4" and not req.fast
        return self._submit(task, ffmpeg, build, out, total, encodes, use_gpu, prepare)

    def start_merge(self, req: MergeRequest, use_gpu: bool = False) -> ExportTask:
        items: list[tuple[MergeClip, EditSource]] = []
        for n, clip in enumerate(req.clips, 1):
            src = self.source(clip.source_id)
            if src is None:
                raise EditError(f"Clip {n} is no longer available — remove it and add it again.")
            items.append((clip, src))
        validate_merge(req, items)
        ffmpeg = ffmpeg_path()
        if ffmpeg is None:
            raise EditError("FFmpeg is not available on this server.")
        first_video = next((s for _, s in items if s.has_video), None)
        canvas = merge_canvas(req, first_video) if first_video and req.format == "mp4" else None
        ext = (Path(items[0][1].path).suffix.lstrip(".").lower() or "mp4") if req.fast else req.format
        names = [s.name for _, s in items]
        task = ExportTask(
            id="e_" + uuid.uuid4().hex[:12],
            source_id=items[0][1].id,
            source_ids=list(dict.fromkeys(s.id for _, s in items)),
            source_name=f"{names[0]} + {len(names) - 1} more",
            label=describe_merge(req, canvas),
            format=ext,
            created_at=now_iso(),
        )
        folder = self._exp_dir(task.id)
        out = folder / merge_output_name(names, ext)
        total = max(0.1, sum(min(c.end, s.duration) - c.start for c, s in items))
        need = sum(_space_needed(s, min(c.end, s.duration) - c.start, req.format) for c, s in items)
        system.require_space(self.root, need, "this merge", EditError)
        if req.fast:
            folder.mkdir(parents=True, exist_ok=True)
            listing = folder / "clips.ffconcat"
            listing.write_text(ffconcat(items), encoding="utf-8")
            return self._submit(task, ffmpeg, lambda _codec, _cap: build_fast_merge_command(ffmpeg, listing, out, req.mute), out, total, False, False)

        def build(codec: str | None, _captions: str | None) -> list[str]:
            prof = system.active()
            return build_merge_command(ffmpeg, items, req, out, codec, prof.x264_preset, prof.threads)

        return self._submit(task, ffmpeg, build, out, total, req.format == "mp4", use_gpu)

    def _submit(
        self,
        task: ExportTask,
        ffmpeg: str,
        build: Callable[[str | None, str | None], list[str]],
        out: Path,
        total: float,
        encodes: bool,
        use_gpu: bool,
        prepare: Callable[[], str | None] | None = None,
    ) -> ExportTask:
        with self._lock:
            self._tasks[task.id] = task
        self._save_task(task)
        self._executor.submit(self._run, task.id, ffmpeg, build, out, total, encodes, use_gpu, prepare)
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

    def _exec(self, task_id: str, cmd: list[str], total: float, log_path: Path) -> int:
        with log_path.open("w", encoding="utf-8", errors="replace") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=log_fh,
                text=True,
                cwd=log_path.parent,
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
            return proc.wait()

    def _run(
        self,
        task_id: str,
        ffmpeg: str,
        build: Callable[[str | None, str | None], list[str]],
        out: Path,
        total: float,
        encodes: bool,
        use_gpu: bool,
        prepare: Callable[[], str | None] | None = None,
    ) -> None:
        folder = self._exp_dir(task_id)
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / "ffmpeg.log"
        enc = gpu.detect(ffmpeg).encoder if encodes and use_gpu else None
        if task_id in self._cancel:
            self._cancel.discard(task_id)
            (folder / "clips.ffconcat").unlink(missing_ok=True)
            return
        try:
            # Encoding and Whisper share one CPU budget, so a weak machine runs them one after another.
            with system.heavy.slot(lambda: self._update(task_id, stage="Waiting for another transcription or export to finish…")):
                if task_id in self._cancel:
                    raise InterruptedError
                self._update(task_id, persist=True, status="running", progress=0.0, stage=None, encoder=_encoder_label(encodes, enc))
                captions_file = prepare() if prepare else None
                if task_id in self._cancel:  # cancelled while Whisper transcribed the clip
                    raise InterruptedError
                code = self._exec(task_id, build(enc.codec if enc else None, captions_file), total, log_path)
                if code != 0 and enc is not None and task_id not in self._cancel:
                    log.warning("Export %s: %s encode failed, retrying on the CPU", task_id, enc.name)
                    self._update(task_id, persist=True, progress=0.0, speed=None, eta=None, encoder="CPU · x264 (GPU failed)")
                    out.unlink(missing_ok=True)
                    code = self._exec(task_id, build(None, captions_file), total, log_path)
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
                speed=None, eta=None, stage=None, finished_at=now_iso(),
            )
        finally:
            with self._lock:
                self._procs.pop(task_id, None)
            self._cancel.discard(task_id)
            (folder / "clips.ffconcat").unlink(missing_ok=True)
            (folder / CAPTIONS_FILE).unlink(missing_ok=True)
