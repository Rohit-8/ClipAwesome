from __future__ import annotations

import base64
import binascii
import logging
import secrets
import subprocess
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from yt_dlp import version as yt_dlp_version

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .. import __version__, gpu, pipeline, system
from .. import clipexport as ce
from .. import config as cfg
from .. import downloads as dl
from .. import editor as ed
from .. import previews as pv
from .. import storage as st
from ..ai.llm import LLMClient, LLMError
from ..config import PROVIDER_DEFAULTS, WEB_DIST, AISettings, Settings, SettingsStore, _merge_secret, ensure_dirs, public_settings
from ..jobs import JobManager
from ..models import Analysis, AnalysisSummary, AnalyzeOptions, DiscoverRequest, Job, LocalPathRequest, YouTubeRequest
from ..sources import transcribe, youtube
from ..sources.local_media import MEDIA_EXTS, SUBTITLE_EXTS
from ..store import Store, new_media_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MAX_UPLOAD_BYTES = 20 * 1024**3
CHUNK = 1024 * 1024

settings_store = SettingsStore()
store = Store()
jobs = JobManager(store)
downloads = dl.DownloadManager()
editor = ed.EditorManager()
yt_previews = pv.PreviewManager(downloads)
storage = st.Storage(settings_store, editor, yt_previews)
clip_exports = ce.ClipExporter(store, downloads, editor)


def _whisper_opts(settings: Settings) -> dict[str, Any]:
    prof = system.configure(settings.performance)
    return {
        "model_size": prof.whisper_model or settings.whisper_model,
        "device": settings.whisper_device,
        "compute_type": settings.whisper_compute_type,
        "threads": prof.threads,
        "workers": prof.heavy_slots,
        "chunk_sec": prof.chunk_sec,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    settings = settings_store.load()
    youtube.configure_proxy(settings.proxy)
    system.configure(settings.performance)
    storage.startup_cleanup()
    yield


app = FastAPI(title="ClipAwesome", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

PUBLIC_PATHS = {"/api/healthz"}


def _authorized(header: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:], validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return secrets.compare_digest(user.encode(), cfg.AUTH_USER.encode()) & secrets.compare_digest(
        password.encode(), cfg.AUTH_PASSWORD.encode()
    )


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not cfg.AUTH_PASSWORD or request.url.path in PUBLIC_PATHS or _authorized(request.headers.get("authorization", "")):
        return await call_next(request)
    return Response("Authentication required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="ClipAwesome", charset="UTF-8"'})


def _require_mode(opts: AnalyzeOptions, settings: Settings) -> None:
    if (opts.mode or settings.default_mode) == "ai" and not settings.ai.is_configured():
        raise HTTPException(400, "AI mode needs a configured provider. Open Settings → AI provider.")


def _ai_settings(overrides: dict[str, Any] | None) -> AISettings:
    """Stored AI settings with unsaved form values applied (secret masks keep the stored key)."""
    current = settings_store.load().ai
    if not overrides:
        return current
    merged = current.model_dump()
    merged.update({k: v for k, v in overrides.items() if k in merged and k != "api_key"})
    merged["api_key"] = _merge_secret(overrides.get("api_key"), current.api_key)
    try:
        return AISettings.model_validate(merged)
    except ValidationError as err:
        raise HTTPException(422, f"Invalid AI settings: {err.errors()[0]['msg']}") from err


# ---- system -------------------------------------------------------------------------------------


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = settings_store.load()
    return {
        "status": "ok",
        "version": __version__,
        "capabilities": {
            "pyav": True,
            "whisper": transcribe.available(),
            "js_runtime": youtube.js_runtime(),
            "ai_configured": settings.ai.is_configured(),
            "ai_provider": settings.ai.provider,
            "ai_model": settings.ai.resolved_model() or None,
            "youtube_api_key": bool(settings.youtube_api_key),
            "local_path": cfg.ALLOW_LOCAL_PATH,
            "performance": system.configure(settings.performance).name,
            "performance_auto": settings.performance == "auto",
        },
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return public_settings(settings_store.load())


@app.get("/api/settings/defaults")
def get_default_settings() -> dict[str, Any]:
    return public_settings(Settings())


@app.put("/api/settings")
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = settings_store.update(body)
    except ValidationError as err:
        first = err.errors()[0]
        raise HTTPException(422, f"Invalid setting {'.'.join(map(str, first['loc']))}: {first['msg']}") from err
    youtube.configure_proxy(updated.proxy)
    system.configure(updated.performance)
    return public_settings(updated)


@app.post("/api/network/youtube")
def network_youtube(body: dict[str, Any] | None = None) -> dict[str, Any]:
    # POST + JSON forces a CORS preflight, so other websites can't make this server dial arbitrary proxies.
    configured = settings_store.load().proxy
    proxy = (body or {}).get("proxy")
    if proxy is not None:
        try:
            proxy = Settings(proxy=cfg.merge_proxy(str(proxy).strip(), configured)).proxy
        except ValidationError as err:
            raise HTTPException(422, err.errors()[0]["msg"]) from err
    youtube.configure_proxy(proxy if proxy is not None else configured)
    try:
        ok, message = youtube.check_reachable()
    finally:
        youtube.configure_proxy(configured)
    return {"ok": ok, "message": message}


@app.get("/api/ai/providers")
def ai_providers() -> dict[str, Any]:
    return {name: {"base_url": url, "model": model} for name, (url, model) in PROVIDER_DEFAULTS.items()}


@app.get("/api/system")
def system_info() -> dict[str, Any]:
    system.configure(settings_store.load().performance)
    return {**system.describe(), "profiles": {name: asdict(system.profile(name)) for name in ("low", "balanced", "high")}}


@app.get("/api/storage")
def storage_usage() -> dict[str, Any]:
    return storage.usage()


@app.post("/api/storage/cleanup")
def storage_cleanup() -> dict[str, Any]:
    result = storage.cleanup(everything=True)
    return {**result, "usage": storage.usage()}


def _check(checks: list[dict[str, Any]], key: str, label: str, status: str, detail: str, hint: str | None = None) -> None:
    checks.append({"key": key, "label": label, "status": status, "detail": detail, "hint": hint})


@app.get("/api/diagnostics")
def diagnostics() -> dict[str, Any]:
    """One-click self-test of everything the app depends on, with a fix hint for each problem."""
    s = settings_store.load()
    prof = system.configure(s.performance)
    checks: list[dict[str, Any]] = []

    ffmpeg = dl.ffmpeg_path()
    if ffmpeg:
        version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=20, creationflags=gpu.NO_WINDOW).stdout.split("\n")[0]
        _check(checks, "ffmpeg", "FFmpeg", "ok", version[:120])
    else:
        _check(checks, "ffmpeg", "FFmpeg", "fail", "Not found: downloads, exports and merges won't work.", 'Reinstall the backend: pip install -e ".[transcribe]"')

    if not s.gpu_acceleration:
        _check(checks, "gpu", "GPU encoding", "info", "Turned off in Settings, so exports use the CPU.")
    elif ffmpeg:
        enc = gpu.detect(ffmpeg).encoder
        if enc:
            _check(checks, "gpu", "GPU encoding", "ok", f"{enc.name} ({enc.codec}) works.")
        else:
            _check(checks, "gpu", "GPU encoding", "info", "No usable GPU encoder, so exports use the CPU (x264).")

    model = prof.whisper_model or s.whisper_model
    if transcribe.available():
        cached = any(cfg.data_path("models").glob(f"models--*whisper-{model}"))
        if cached:
            _check(checks, "whisper", "Speech-to-text", "ok", f"faster-whisper ready with the '{model}' model.")
        else:
            _check(checks, "whisper", "Speech-to-text", "warn", f"The '{model}' model isn't downloaded yet; it downloads on first use (needs internet).")
    else:
        _check(checks, "whisper", "Speech-to-text", "warn", "Not installed: videos without captions can't be transcribed.", 'pip install -e ".[transcribe]"')

    yv = yt_dlp_version.__version__
    try:
        age = (datetime.now() - datetime.strptime(".".join(yv.split(".")[:3]), "%Y.%m.%d")).days
    except ValueError:
        age = 0
    if age > 60:
        _check(checks, "ytdlp", "yt-dlp", "warn", f"Version {yv} is {age} days old. YouTube changes often, so old versions break.", "pip install -U yt-dlp, then restart the server")
    else:
        _check(checks, "ytdlp", "yt-dlp", "ok", f"Version {yv}.")
    js = youtube.js_runtime()
    _check(checks, "js", "JavaScript runtime", "ok" if js else "warn", f"{js} found." if js else "None found: some YouTube videos may fail to load.", None if js else "Install Node.js or Deno")

    ok, message = youtube.check_reachable()
    _check(checks, "youtube", "YouTube access", "ok" if ok else "fail", message, None if ok else "Set a proxy in Settings → YouTube & network")

    if s.ai.is_configured():
        _check(checks, "ai", "AI provider", "info", f"Configured: {s.ai.provider} · {s.ai.resolved_model()} (use Test connection to check it).")
    else:
        _check(checks, "ai", "AI provider", "info", "Not configured (optional; Deterministic mode works without it).")

    free = system.free_bytes(cfg.DATA_DIR)
    disk_status = "fail" if free < system.GB else "warn" if free < 5 * system.GB else "ok"
    _check(checks, "disk", "Free disk space", disk_status, f"{system.fmt_bytes(free)} free where data is stored.", None if disk_status == "ok" else "Use Settings → Storage → Clean up, or free space on that drive")

    info = system.describe()
    ram = f"{info['ram_gb']} GB RAM" if info["ram_gb"] else "RAM unknown"
    low_ram = info["available_ram_gb"] is not None and info["available_ram_gb"] < 1.5
    _check(
        checks, "machine", "Machine", "warn" if low_ram else "ok",
        f"{info['cpus']} CPU threads · {ram} ({info['available_ram_gb']} GB free) · performance profile: {prof.name}" + (" (auto)" if s.performance == "auto" else ""),
        "Close other apps, or switch Settings → Performance to Low" if low_ram else None,
    )

    try:
        probe_file = cfg.data_path("tmp", f"write-test-{secrets.token_hex(4)}")
        probe_file.parent.mkdir(parents=True, exist_ok=True)
        probe_file.write_text("ok")
        probe_file.unlink()
        _check(checks, "data", "Data folder", "ok", f"Writable: {cfg.DATA_DIR}")
    except OSError as err:
        _check(checks, "data", "Data folder", "fail", f"Can't write to {cfg.DATA_DIR}: {err}", "Fix the folder permissions or set CLIPAWESOME_DATA")
    return {"ok": all(c["status"] != "fail" for c in checks), "checks": checks}


@app.post("/api/ai/test")
def ai_test(body: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _ai_settings(body)
    try:
        return LLMClient(cfg).test()
    except LLMError as err:
        return {"ok": False, "message": str(err), "model": cfg.resolved_model()}


@app.post("/api/ai/models")
def ai_models(body: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _ai_settings(body)
    try:
        return {"ok": True, "models": LLMClient(cfg).list_models()}
    except LLMError as err:
        return {"ok": False, "message": str(err), "models": []}


# ---- analysis jobs -------------------------------------------------------------------------------


def _job_runner(spec: dict[str, Any]):
    """Builds the pipeline call for a saved job spec, so jobs can be re-run after a failure or restart."""
    settings = settings_store.load()
    kind = spec["kind"]
    if kind == "youtube":
        req = YouTubeRequest.model_validate(spec["request"])
        _require_mode(req, settings)
        video_id = youtube.parse_video_id(req.url) or req.url
        return lambda p: pipeline.analyze_youtube(video_id, req, settings, p)
    if kind == "discover":
        disc = DiscoverRequest.model_validate(spec["request"])
        _require_mode(disc, settings)
        return lambda p: pipeline.discover(disc, settings, p)
    opts = AnalyzeOptions.model_validate(spec["request"])
    _require_mode(opts, settings)
    path = Path(spec["path"])
    sub = Path(spec["subtitle"]) if spec.get("subtitle") else None
    if not path.is_file():
        raise HTTPException(410, "The original file is no longer available. Upload it again.")
    return lambda p: pipeline.analyze_local(path, spec["name"], spec["media_id"], sub, opts, settings, p)


def _start_job(kind: str, title: str, spec: dict[str, Any]) -> Job:
    return jobs.submit(kind, title, _job_runner(spec), spec)


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str) -> dict[str, str]:
    job, spec = jobs.get(job_id), jobs.spec(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in ("queued", "running"):
        raise HTTPException(409, "This job is still running")
    if spec is None:
        raise HTTPException(409, "This job can't be run again; start a new analysis instead")
    return {"job_id": _start_job(job.kind, job.title, spec).id}


@app.post("/api/analyze/youtube", status_code=202)
def analyze_youtube(req: YouTubeRequest) -> dict[str, str]:
    settings = settings_store.load()
    _require_mode(req, settings)
    video_id = youtube.parse_video_id(req.url)
    if not video_id:
        raise HTTPException(400, "Enter a YouTube video link (youtube.com/watch?v=…, youtu.be/…, /shorts/…) or an 11-character video ID.")
    job = _start_job("youtube", req.url, {"kind": "youtube", "request": req.model_dump()})
    return {"job_id": job.id}


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File is larger than 20 GB")
            fh.write(chunk)


@app.post("/api/analyze/local", status_code=202)
async def analyze_local_upload(
    file: UploadFile = File(...),
    subtitle: UploadFile | None = File(None),
    options: str = Form("{}"),
) -> dict[str, str]:
    settings = settings_store.load()
    try:
        opts = AnalyzeOptions.model_validate_json(options or "{}")
    except ValidationError as err:
        raise HTTPException(422, f"Invalid options: {err.errors()[0]['msg']}") from err
    _require_mode(opts, settings)

    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in MEDIA_EXTS:
        raise HTTPException(400, f"Unsupported media type '{ext or 'unknown'}'. Supported: {', '.join(sorted(MEDIA_EXTS))}")
    sub_ext = Path(subtitle.filename or "").suffix.lower() if subtitle and subtitle.filename else ""
    if subtitle and subtitle.filename and sub_ext not in SUBTITLE_EXTS:
        raise HTTPException(400, "Subtitle must be .srt or .vtt")

    ensure_dirs()
    media_id = new_media_id()
    media_path = store.uploads / f"{media_id}{ext}"
    await _save_upload(file, media_path)
    sub_path = None
    if subtitle and subtitle.filename:
        sub_path = store.uploads / f"{media_id}.sub{sub_ext}"
        await _save_upload(subtitle, sub_path)
    store.register_media(media_path, "upload", media_id)
    spec = {"kind": "local", "request": opts.model_dump(), "path": str(media_path), "name": name, "media_id": media_id, "subtitle": str(sub_path) if sub_path else None}
    job = _start_job("local", name, spec)
    return {"job_id": job.id}


@app.post("/api/analyze/local-path", status_code=202)
def analyze_local_path(req: LocalPathRequest) -> dict[str, str]:
    if not cfg.ALLOW_LOCAL_PATH:
        raise HTTPException(403, "Analysing by server file path is disabled on this deployment. Upload the file instead.")
    settings = settings_store.load()
    _require_mode(req, settings)
    path = Path(req.path.strip().strip('"')).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(400, "Enter the absolute path of an existing media file")
    if path.suffix.lower() not in MEDIA_EXTS:
        raise HTTPException(400, f"Unsupported media type '{path.suffix}'")
    sub_path = None
    if req.subtitle_path:
        sub_path = Path(req.subtitle_path.strip().strip('"')).expanduser()
        if not sub_path.is_file() or sub_path.suffix.lower() not in SUBTITLE_EXTS:
            raise HTTPException(400, "Subtitle path must be an existing .srt or .vtt file")
    media_id = store.register_media(path.resolve(), "path")
    opts = AnalyzeOptions.model_validate(req.model_dump(include=set(AnalyzeOptions.model_fields)))
    spec = {"kind": "local", "request": opts.model_dump(), "path": str(path), "name": path.name, "media_id": media_id, "subtitle": str(sub_path) if sub_path else None}
    job = _start_job("local", path.name, spec)
    return {"job_id": job.id}


@app.post("/api/discover", status_code=202)
def discover(req: DiscoverRequest) -> dict[str, str]:
    settings = settings_store.load()
    _require_mode(req, settings)
    if req.min_duration >= req.max_duration:
        raise HTTPException(400, "Minimum duration must be below maximum duration")
    job = _start_job("discover", req.topic, {"kind": "discover", "request": req.model_dump()})
    return {"job_id": job.id}


@app.get("/api/jobs")
def list_jobs() -> list[Job]:
    return jobs.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found (the server may have restarted)")
    return job


# ---- results ------------------------------------------------------------------------------------


@app.get("/api/analyses")
def list_analyses() -> list[AnalysisSummary]:
    return store.list()


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> Analysis:
    analysis = store.get(analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analysis not found")
    return analysis


@app.patch("/api/analyses/{analysis_id}/clips/{clip_id}")
def review_clip(analysis_id: str, clip_id: str, body: dict[str, Any]) -> dict[str, Any]:
    review = body.get("review")
    if review not in ("approved", "rejected", None):
        raise HTTPException(422, "review must be 'approved', 'rejected' or null")
    analysis = store.set_review(analysis_id, clip_id, review)
    if analysis is None:
        raise HTTPException(404, "Clip not found")
    return {"id": clip_id, "review": review}


def _analysis_or_404(analysis_id: str) -> Analysis:
    analysis = store.get(analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analysis not found")
    return analysis


@app.post("/api/analyses/{analysis_id}/sources/{source_id}/edit-source")
def analysis_edit_source(analysis_id: str, source_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Editable copy of an analysed video: ready now, or a download to wait for (poll /api/downloads/{id})."""
    quality = int((body or {}).get("quality") or 720)
    if quality not in ce.QUALITIES:
        raise HTTPException(422, f"quality must be one of {ce.QUALITIES}")
    try:
        return clip_exports.ensure_source(_analysis_or_404(analysis_id), source_id, quality)
    except (ed.EditError, youtube.SourceError, OSError) as err:
        raise HTTPException(400, str(err)) from err


@app.post("/api/analyses/{analysis_id}/export", status_code=202)
def analysis_export(analysis_id: str, opts: ce.BatchOptions) -> ce.Batch:
    if opts.download_quality not in ce.QUALITIES:
        raise HTTPException(422, f"download_quality must be one of {ce.QUALITIES}")
    settings = settings_store.load()
    try:
        return clip_exports.start_batch(_analysis_or_404(analysis_id), opts, settings.gpu_acceleration, _whisper_opts(settings) if transcribe.available() else None)
    except ed.EditError as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/export-batches/{batch_id}")
def export_batch(batch_id: str) -> ce.Batch:
    batch = clip_exports.batch(batch_id)
    if batch is None:
        raise HTTPException(404, "Batch not found (the server may have restarted)")
    return batch


@app.delete("/api/analyses/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str) -> Response:
    if not store.delete(analysis_id):
        raise HTTPException(404, "Analysis not found")
    return Response(status_code=204)


@app.get("/api/media/{media_id}")
def media(media_id: str) -> FileResponse:
    path = store.media_file(media_id)
    if path is None:
        raise HTTPException(404, "Media not found")
    return FileResponse(path)


@app.get("/api/media/{media_id}/preview-audio")
def media_preview_audio(media_id: str) -> FileResponse:
    path = store.media_file(media_id)
    if path is None:
        raise HTTPException(404, "Media not found")
    try:
        preview = ed.make_preview_audio(path, cfg.data_path("previews", f"{media_id}.mp3"))
    except ed.EditError as err:
        raise HTTPException(500, str(err)) from err
    return FileResponse(preview, media_type="audio/mpeg")


# ---- YouTube playback copies (when the browser can't show YouTube's own player) ------------------


def _preview_call(fn, video_id: str):
    try:
        return fn(video_id)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/youtube/{video_id}/preview")
def youtube_preview_status(video_id: str) -> pv.PreviewStatus:
    return _preview_call(yt_previews.status, video_id)


@app.post("/api/youtube/{video_id}/preview", status_code=202)
def youtube_preview_start(video_id: str) -> pv.PreviewStatus:
    return _preview_call(yt_previews.start, video_id)


@app.get("/api/youtube/{video_id}/preview/media")
def youtube_preview_media(video_id: str) -> FileResponse:
    path = _preview_call(yt_previews.file, video_id)
    if path is None:
        raise HTTPException(404, "No playable copy yet")
    return FileResponse(path)


@app.get("/api/youtube/{video_id}/preview/audio")
def youtube_preview_audio(video_id: str) -> FileResponse:
    try:
        path = _preview_call(yt_previews.audio, video_id)
    except ed.EditError as err:
        raise HTTPException(500, str(err)) from err
    if path is None:
        raise HTTPException(404, "No playable copy yet")
    return FileResponse(path, media_type="audio/mpeg")


# ---- YouTube downloads --------------------------------------------------------------------------


def _video_id_or_400(url: str) -> str:
    video_id = youtube.parse_video_id(url)
    if not video_id:
        raise HTTPException(400, "Enter a YouTube video link (youtube.com/watch?v=…, youtu.be/…, /shorts/…) or an 11-character video ID.")
    return video_id


@app.post("/api/download/formats")
def download_formats(req: dl.DownloadRequest) -> dl.DownloadInfo:
    try:
        info, _ = dl.get_formats(_video_id_or_400(req.url), fresh=True)
    except youtube.SourceError as err:
        raise HTTPException(502, str(err)) from err
    return info


@app.post("/api/downloads", status_code=202)
def start_download(req: dl.StartDownloadRequest) -> dl.DownloadTask:
    video_id = _video_id_or_400(req.url)
    try:
        info, options = dl.get_formats(video_id)
        option = options.get(req.option_id)
        if option is None:
            raise HTTPException(400, "That format is no longer offered for this video. Fetch the formats again.")
        return downloads.start(info, option)
    except youtube.SourceError as err:
        raise HTTPException(502, str(err)) from err


@app.get("/api/downloads")
def list_downloads() -> list[dl.DownloadTask]:
    return downloads.list()


@app.get("/api/downloads/{task_id}")
def get_download(task_id: str) -> dl.DownloadTask:
    task = downloads.get(task_id)
    if task is None:
        raise HTTPException(404, "Download not found")
    return task


@app.post("/api/downloads/{task_id}/cancel")
def cancel_download(task_id: str) -> dl.DownloadTask:
    task = downloads.cancel(task_id)
    if task is None:
        raise HTTPException(404, "Download not found")
    return task


@app.delete("/api/downloads/{task_id}", status_code=204)
def delete_download(task_id: str) -> Response:
    if downloads.get(task_id) is None:
        raise HTTPException(404, "Download not found")
    if not downloads.delete(task_id):
        raise HTTPException(409, "Cancel the download before deleting it")
    return Response(status_code=204)


@app.get("/api/downloads/{task_id}/file")
def download_file(task_id: str) -> FileResponse:
    path = downloads.file_path(task_id)
    if path is None:
        raise HTTPException(404, "File not ready")
    return FileResponse(path, filename=path.name)


# ---- editor -------------------------------------------------------------------------------------


@app.post("/api/editor/sources/upload")
async def editor_upload(file: UploadFile = File(...)) -> ed.EditSource:
    name = Path(file.filename or "video").name
    if Path(name).suffix.lower() not in MEDIA_EXTS:
        raise HTTPException(400, f"Unsupported media type '{Path(name).suffix or 'unknown'}'. Supported: {', '.join(sorted(MEDIA_EXTS))}")
    source_id, path = editor.new_upload_path(name)
    await _save_upload(file, path)
    try:
        return editor.add_source(source_id, path, name, "upload")
    except ed.EditError as err:
        editor.delete_source(source_id)
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(err)) from err


@app.post("/api/editor/sources/from-download")
def editor_from_download(body: dict[str, str]) -> ed.EditSource:
    task_id = str(body.get("download_id", ""))
    task = downloads.get(task_id)
    path = downloads.file_path(task_id)
    if task is None or path is None:
        raise HTTPException(404, "That download is not available (it may have expired)")
    try:
        return editor.source_for_download(task_id, path, path.name)
    except ed.EditError as err:
        raise HTTPException(400, str(err)) from err


@app.get("/api/editor/sources")
def editor_sources() -> list[ed.EditSource]:
    return editor.sources()


@app.get("/api/editor/sources/{source_id}")
def editor_source(source_id: str) -> ed.EditSource:
    src = editor.source(source_id)
    if src is None:
        raise HTTPException(404, "Video not found (it may have expired)")
    return src


@app.get("/api/editor/sources/{source_id}/media")
def editor_source_media(source_id: str) -> FileResponse:
    src = editor.source(source_id)
    if src is None:
        raise HTTPException(404, "Video not found")
    return FileResponse(src.path)


@app.get("/api/editor/sources/{source_id}/preview-audio")
def editor_preview_audio(source_id: str) -> FileResponse:
    try:
        path = editor.preview_audio(source_id)
    except ed.EditError as err:
        raise HTTPException(500, str(err)) from err
    if path is None:
        raise HTTPException(404, "No audio for this video")
    return FileResponse(path, media_type="audio/mpeg")


@app.delete("/api/editor/sources/{source_id}", status_code=204)
def editor_delete_source(source_id: str) -> Response:
    if not editor.delete_source(source_id):
        raise HTTPException(409, "Video not found, or an export from it is still running")
    return Response(status_code=204)


@app.post("/api/editor/exports", status_code=202)
def editor_start_export(req: ed.ExportRequest) -> ed.ExportTask:
    settings = settings_store.load()
    lines = None
    if req.captions and req.captions.analysis_id:
        analysis = store.get(req.captions.analysis_id)
        if analysis is None:
            raise HTTPException(400, "The analysis used for captions no longer exists")
        sid = req.captions.analysis_source or (analysis.sources[0].id if analysis.sources else "")
        lines = [(t.start, t.end, t.text) for t in analysis.transcripts.get(sid, [])]
    try:
        return editor.start(req, settings.gpu_acceleration, caption_lines=lines, whisper=_whisper_opts(settings) if transcribe.available() else None)
    except ed.EditError as err:
        raise HTTPException(400, str(err)) from err


@app.post("/api/editor/merges", status_code=202)
def editor_start_merge(req: ed.MergeRequest) -> ed.ExportTask:
    try:
        return editor.start_merge(req, use_gpu=settings_store.load().gpu_acceleration)
    except ed.EditError as err:
        raise HTTPException(400, str(err)) from err


def _gpu_status(force: bool) -> dict[str, Any]:
    enabled = settings_store.load().gpu_acceleration
    ffmpeg = dl.ffmpeg_path()
    report = gpu.detect(ffmpeg, refresh=force) if ffmpeg and (enabled or force) else None
    encoder = report.encoder if report else None
    return {
        "enabled": enabled,
        "ffmpeg": ffmpeg is not None,
        "encoder": {"codec": encoder.codec, "name": encoder.name} if encoder else None,
        "tried": report.tried if report else [],
    }


@app.get("/api/editor/gpu")
def editor_gpu() -> dict[str, Any]:
    return _gpu_status(force=False)


@app.post("/api/editor/gpu/detect")
def editor_gpu_detect() -> dict[str, Any]:
    # POST: re-running test encodes is an explicit action, not something a page load should trigger.
    return _gpu_status(force=True)


@app.get("/api/editor/exports")
def editor_exports() -> list[ed.ExportTask]:
    return editor.exports()


@app.get("/api/editor/exports/{task_id}")
def editor_export(task_id: str) -> ed.ExportTask:
    task = editor.export(task_id)
    if task is None:
        raise HTTPException(404, "Export not found")
    return task


@app.post("/api/editor/exports/{task_id}/cancel")
def editor_cancel_export(task_id: str) -> ed.ExportTask:
    task = editor.cancel(task_id)
    if task is None:
        raise HTTPException(404, "Export not found")
    return task


@app.delete("/api/editor/exports/{task_id}", status_code=204)
def editor_delete_export(task_id: str) -> Response:
    if editor.export(task_id) is None:
        raise HTTPException(404, "Export not found")
    if not editor.delete(task_id):
        raise HTTPException(409, "Cancel the export before deleting it")
    return Response(status_code=204)


@app.get("/api/editor/exports/{task_id}/file")
def editor_export_file(task_id: str) -> FileResponse:
    path = editor.file_path(task_id)
    if path is None:
        raise HTTPException(404, "File not ready")
    return FileResponse(path, filename=path.name)


if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
