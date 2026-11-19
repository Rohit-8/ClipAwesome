from __future__ import annotations

import base64
import binascii
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .. import __version__, pipeline
from .. import config as cfg
from .. import downloads as dl
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    youtube.configure_proxy(settings_store.load().proxy)
    yield


app = FastAPI(title="ClipAwesome", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
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
    return public_settings(updated)


@app.post("/api/network/youtube")
def network_youtube(body: dict[str, Any] | None = None) -> dict[str, Any]:
    # POST + JSON forces a CORS preflight, so other websites can't make this server dial arbitrary proxies.
    configured = settings_store.load().proxy
    proxy = (body or {}).get("proxy")
    if proxy is not None:
        try:
            proxy = Settings(proxy=str(proxy)).proxy
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


@app.post("/api/analyze/youtube", status_code=202)
def analyze_youtube(req: YouTubeRequest) -> dict[str, str]:
    settings = settings_store.load()
    _require_mode(req, settings)
    video_id = youtube.parse_video_id(req.url)
    if not video_id:
        raise HTTPException(400, "Enter a YouTube video link (youtube.com/watch?v=…, youtu.be/…, /shorts/…) or an 11-character video ID.")
    job = jobs.submit("youtube", req.url, lambda p: pipeline.analyze_youtube(video_id, req, settings, p))
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
    job = jobs.submit(
        "local", name, lambda p: pipeline.analyze_local(media_path, name, media_id, sub_path, opts, settings, p)
    )
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
    job = jobs.submit(
        "local", path.name, lambda p: pipeline.analyze_local(path, path.name, media_id, sub_path, req, settings, p)
    )
    return {"job_id": job.id}


@app.post("/api/discover", status_code=202)
def discover(req: DiscoverRequest) -> dict[str, str]:
    settings = settings_store.load()
    _require_mode(req, settings)
    if req.min_duration >= req.max_duration:
        raise HTTPException(400, "Minimum duration must be below maximum duration")
    job = jobs.submit("discover", req.topic, lambda p: pipeline.discover(req, settings, p))
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


if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
