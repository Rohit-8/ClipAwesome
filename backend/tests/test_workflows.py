import subprocess
import threading
import time
from pathlib import Path

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipawesome import clipexport as ce
from clipawesome import editor as ed
from clipawesome import gpu
from clipawesome import storage as st
from clipawesome.api import app as app_module
from clipawesome.api.app import app
from clipawesome.downloads import DownloadInfo, DownloadOption, DownloadTask, ffmpeg_path
from clipawesome.jobs import JobManager
from clipawesome.models import Analysis, ClipSuggestion, SourceVideo, TranscriptLine
from clipawesome.sources.local_media import probe
from clipawesome.store import Store, new_analysis_id

FFMPEG = ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")


@pytest.fixture(autouse=True)
def no_gpu(monkeypatch):
    monkeypatch.setattr(gpu, "detect", lambda ffmpeg, refresh=False: gpu.Report(None))


@pytest.fixture(scope="module")
def blue(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wf") / "blue talk.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=25:d=6",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=6:sample_rate=44100", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


def wait(fetch, done, tries=400):
    for _ in range(tries):
        value = fetch()
        if done(value):
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out: {value}")


def test_jobs_survive_a_restart_and_can_be_rerun(tmp_path):
    store = Store(tmp_path)
    manager = JobManager(store, root=tmp_path / "jobs")
    release = []

    def slow(progress):
        progress("Working", 0.5)
        while not release:
            time.sleep(0.01)
        raise RuntimeError("boom")

    job = manager.submit("youtube", "x", slow, {"kind": "youtube", "request": {"url": "dQw4w9WgXcQ"}})
    wait(lambda: manager.get(job.id), lambda j: j.stage == "Working")
    restarted = JobManager(store, root=tmp_path / "jobs")
    again = restarted.get(job.id)
    assert again.status == "interrupted" and again.retryable and "server stopped" in again.error
    assert restarted.spec(job.id) == {"kind": "youtube", "request": {"url": "dQw4w9WgXcQ"}}
    release.append(True)
    finished = wait(lambda: manager.get(job.id), lambda j: j.status == "error")
    assert finished.error == "boom"


def test_retry_endpoint_reruns_a_failed_job(monkeypatch):
    calls = []

    def fail(video_id, req, settings, progress):
        calls.append(video_id)
        raise RuntimeError("bot check")

    monkeypatch.setattr(app_module.pipeline, "analyze_youtube", fail)
    with TestClient(app) as client:
        job_id = client.post("/api/analyze/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ"}).json()["job_id"]
        failed = wait(lambda: client.get(f"/api/jobs/{job_id}").json(), lambda j: j["status"] == "error")
        assert failed["retryable"] and "bot check" in failed["error"]
        new_id = client.post(f"/api/jobs/{job_id}/retry").json()["job_id"]
        assert new_id != job_id
        wait(lambda: client.get(f"/api/jobs/{new_id}").json(), lambda j: j["status"] == "error")
        assert calls == ["dQw4w9WgXcQ", "dQw4w9WgXcQ"]
        assert client.post("/api/jobs/j_nope/retry").status_code == 404


def saved_analysis(path: Path) -> Analysis:
    store = app_module.store
    media_id = store.register_media(path, "path")
    clips = [
        ClipSuggestion(id="s1-c1", rank=1, source_id="s1", start=0.5, end=3.0, duration=2.5, score=80, engine_score=80, title="First moment"),
        ClipSuggestion(id="s1-c2", rank=2, source_id="s1", start=3.0, end=5.5, duration=2.5, score=70, engine_score=70, title="Second moment"),
    ]
    analysis = Analysis(
        id=new_analysis_id(), kind="local", mode="deterministic", preset="shorts", min_len=1, max_len=10,
        created_at="2026-01-01T00:00:00+00:00", title="blue talk",
        sources=[SourceVideo(id="s1", platform="local", title="blue talk.mp4", duration=6.0, media_id=media_id, media_kind="video")],
        clips=clips, transcripts={"s1": [TranscriptLine(start=0.0, end=6.0, text="this is a perfectly fine sentence for captions")]},
    )
    store.save(analysis)
    return analysis


def bright_share(path: Path, at: float) -> float:
    with av.open(str(path)) as c:
        for frame in c.decode(video=0):
            if frame.time is not None and frame.time >= at:
                img = frame.to_ndarray(format="rgb24")
                return float((img.min(axis=2) > 200).mean())
    return 0.0


@needs_ffmpeg
def test_review_batch_export_with_captions_and_levelled_audio(blue, tmp_path):
    with TestClient(app) as client:
        a = saved_analysis(blue)
        assert client.patch(f"/api/analyses/{a.id}/clips/s1-c1", json={"review": "approved"}).json()["review"] == "approved"
        assert client.patch(f"/api/analyses/{a.id}/clips/s1-c1", json={"review": "maybe"}).status_code == 422
        assert client.get(f"/api/analyses/{a.id}").json()["clips"][0]["review"] == "approved"

        ready = client.post(f"/api/analyses/{a.id}/sources/s1/edit-source", json={"quality": 720}).json()
        assert ready["status"] == "ready" and ready["source"]["kind"] == "analysis"
        assert client.post(f"/api/analyses/{a.id}/sources/s1/edit-source", json={}).json()["source"]["id"] == ready["source"]["id"]

        batch = client.post(f"/api/analyses/{a.id}/export", json={"clip_ids": ["s1-c1", "s1-c2"], "frame": "9:16", "captions": "bold", "normalize": True}).json()
        batch = wait(lambda: client.get(f"/api/export-batches/{batch['id']}").json(), lambda b: b["status"] != "preparing")
        assert batch["status"] == "done" and len(batch["export_ids"]) == 2 and not batch["errors"], batch
        tasks = [wait(lambda i=i: client.get(f"/api/editor/exports/{i}").json(), lambda t: t["status"] not in ("queued", "running")) for i in batch["export_ids"]]
        assert all(t["status"] == "done" for t in tasks), tasks
        assert tasks[0]["file_name"].startswith("01 First moment") and "captions" in tasks[0]["label"] and "LUFS" in tasks[0]["label"]
        out = tmp_path / tasks[0]["file_name"]
        out.write_bytes(client.get(f"/api/editor/exports/{tasks[0]['id']}/file").content)
        info = probe(out)
        assert (info.width, info.height) == (202, 360) and info.has_audio and 2.3 < info.duration < 2.8
        with av.open(str(out)) as c:
            assert c.streams.audio[0].codec_context.sample_rate == 48000
        assert bright_share(out, 1.0) > 0.003  # white caption text on a pure-blue frame

        plain = client.post("/api/editor/exports", json={"source_id": ready["source"]["id"], "start": 0.5, "end": 2.5}).json()
        plain = wait(lambda: client.get(f"/api/editor/exports/{plain['id']}").json(), lambda t: t["status"] not in ("queued", "running"))
        plain_file = tmp_path / "plain.mp4"
        plain_file.write_bytes(client.get(f"/api/editor/exports/{plain['id']}/file").content)
        assert bright_share(plain_file, 1.0) == 0.0

        bad = client.post("/api/editor/exports", json={"source_id": ready["source"]["id"], "start": 0, "end": 2, "fast": True, "normalize": True})
        assert bad.status_code == 400 and "Fast cut" in bad.json()["detail"]


def test_storage_system_and_diagnostics_endpoints():
    with TestClient(app) as client:
        usage = client.get("/api/storage").json()
        assert {c["key"] for c in usage["categories"]} >= {"downloads", "exports", "youtube_copies", "temp"}
        assert usage["disk_free_bytes"] > 0 and usage["cleanup_days"] == 14
        tmp_junk = app_module.cfg.data_path("tmp", "leftover")
        tmp_junk.mkdir(parents=True, exist_ok=True)
        (tmp_junk / "x.bin").write_bytes(b"0" * 2048)
        with st.temp_dir() as in_use:
            in_use.mkdir(parents=True)
            (in_use / "audio.m4a").write_bytes(b"0" * 1024)
            cleaned = client.post("/api/storage/cleanup").json()
            assert cleaned["freed"]["temp"] >= 2048 and not tmp_junk.exists()
            assert (in_use / "audio.m4a").exists(), "a running analysis' audio must survive cleanup"
        assert not in_use.exists()

        info = client.get("/api/system").json()
        assert info["cpus"] >= 1 and set(info["profiles"]) == {"low", "balanced", "high"} and info["active"]["name"] in info["profiles"]
        assert client.get("/api/health").json()["capabilities"]["performance"] in ("low", "balanced", "high")

        diag = client.get("/api/diagnostics").json()
        keys = {c["key"] for c in diag["checks"]}
        assert {"ffmpeg", "captions", "whisper", "ytdlp", "youtube", "disk", "machine", "data"} <= keys
        assert all(c["status"] in ("ok", "warn", "fail", "info") for c in diag["checks"])
        assert app_module.cfg.DATA_DIR.is_absolute()


class FakeDownloads:
    def __init__(self, tasks: list[DownloadTask], files: dict[str, Path]):
        self.tasks, self.files, self.started = tasks, files, []

    def list(self):
        return self.tasks

    def file_path(self, task_id):
        return self.files.get(task_id)

    def start(self, info, option):
        self.started.append(option.id)
        return DownloadTask(id="d_new", video_id=info.video_id, title=info.title, option_id=option.id, label=option.label, ext="mp4", created_at="2026-01-01T00:00:00+00:00")


class FakeEditor:
    def source_for_download(self, download_id, path, name):
        return {"download": download_id}


def test_edit_source_reuses_the_best_download_when_the_video_tops_out_lower(tmp_path, monkeypatch):
    vid = "aqz-KE-bpKQ"
    file = tmp_path / "v.mp4"
    file.write_bytes(b"x")
    done = lambda i, h: DownloadTask(id=i, video_id=vid, title="t", option_id=f"v{h}", label=f"{h}p", ext="mp4", status="done", created_at="2026-01-01T00:00:00+00:00")  # noqa: E731
    # d_gone's file was deleted; d_480 is the best this video offers.
    downloads = FakeDownloads([done("d_gone", 1080), done("d_480", 480)], {"d_480": file})
    opts = {f"v{h}": DownloadOption(id=f"v{h}", kind="video", label=f"{h}p", quality=f"{h}p", height=h, ext="mp4", codec="h264") for h in (360, 480)}
    info = DownloadInfo(video_id=vid, url="u", title="t", duration=600, ffmpeg=True, options=list(opts.values()))
    monkeypatch.setattr(ce, "get_formats", lambda video_id: (info, opts))
    analysis = Analysis(
        id=new_analysis_id(), kind="youtube", mode="deterministic", preset="standard", min_len=30, max_len=90, created_at="2026-01-01T00:00:00+00:00", title="t",
        sources=[SourceVideo(id="s1", platform="youtube", video_id=vid, title="t", duration=600)],
    )
    exporter = ce.ClipExporter(app_module.store, downloads, FakeEditor())  # type: ignore[arg-type]
    assert exporter.ensure_source(analysis, "s1", 720) == {"status": "ready", "source": {"download": "d_480"}}
    assert downloads.started == []


@needs_ffmpeg
def test_cancel_while_transcribing_for_captions_skips_the_encode(blue, tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_transcribe(path, **kwargs):
        started.set()
        release.wait(10)
        return [(0.6, 1.0, "hello")], "en"

    monkeypatch.setattr(ed.transcribe, "transcribe", slow_transcribe)
    monkeypatch.setattr(ed.transcribe, "available", lambda: True)
    manager = ed.EditorManager(tmp_path / "editor")
    src = manager.add_source("s_000000000001", blue, "blue.mp4", "upload")
    req = ed.ExportRequest(source_id=src.id, start=0.5, end=2.5, captions=ed.CaptionOptions(style="bold"))
    task = manager.start(req, whisper={"model_size": "tiny"})
    assert started.wait(10)
    assert manager.cancel(task.id).status == "running"
    release.set()
    finished = wait(lambda: manager.export(task.id), lambda t: t.status not in ("queued", "running"))
    assert finished.status == "cancelled"
    assert not (tmp_path / "editor" / "exports" / task.id / "ffmpeg.log").exists(), "FFmpeg should not have run"
