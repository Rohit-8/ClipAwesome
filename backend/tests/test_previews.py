import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipawesome import previews as pv
from clipawesome.api.app import app
from clipawesome.downloads import DownloadManager, DownloadTask, ffmpeg_path

FFMPEG = ffmpeg_path()
VID = "AIvSTjArIZo"
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("pv") / "sample.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


def fake_ydl(sample: Path, fail: bool = False):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            assert url.endswith(VID) and download and self.opts["format"].startswith("18/")
            if fail:
                raise RuntimeError("Video unavailable")
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            shutil.copy(sample, self.opts["outtmpl"].replace("%(ext)s", "mp4"))
            return {}

    return FakeYDL


def wait(manager: pv.PreviewManager, video_id: str) -> pv.PreviewStatus:
    for _ in range(200):
        status = manager.status(video_id)
        if status.status != "downloading":
            return status
        time.sleep(0.02)
    raise AssertionError("preview did not finish")


def test_preview_downloads_once_then_serves_cached_copy(sample, tmp_path, monkeypatch):
    monkeypatch.setattr(pv.yt_dlp, "YoutubeDL", fake_ydl(sample))
    manager = pv.PreviewManager(DownloadManager(root=tmp_path / "dl"), root=tmp_path / "pv")
    assert manager.status(VID).status == "none"
    assert manager.start(VID).status == "downloading"
    done = wait(manager, VID)
    assert done.status == "ready" and done.audio_codec == "aac" and done.size and not done.reused_download
    assert manager.file(VID) == tmp_path / "pv" / VID / "preview.mp4"
    assert manager.start(VID).status == "ready"
    audio = manager.audio(VID)
    assert audio is not None and audio.suffix == ".mp3" and audio.stat().st_size > 0

    with pytest.raises(ValueError):
        manager.status("../../etc")


def test_preview_reuses_a_finished_download_and_reports_errors(sample, tmp_path, monkeypatch):
    dl = DownloadManager(root=tmp_path / "dl")
    dl._load()
    task = DownloadTask(id="d_x", video_id=VID, title="t", option_id="v360", label="360p", ext="mp4", status="done", file_name="v.mp4", created_at="2026-01-01T00:00:00+00:00")
    dl._tasks[task.id] = task
    dl._dir(task.id).mkdir(parents=True)
    shutil.copy(sample, dl._dir(task.id) / "v.mp4")
    manager = pv.PreviewManager(dl, root=tmp_path / "pv")
    status = manager.start(VID)
    assert status.status == "ready" and status.reused_download and manager.file(VID) == dl._dir(task.id) / "v.mp4"

    monkeypatch.setattr(pv.yt_dlp, "YoutubeDL", fake_ydl(sample, fail=True))
    other = pv.PreviewManager(DownloadManager(root=tmp_path / "dl2"), root=tmp_path / "pv2")
    other.start(VID)
    failed = wait(other, VID)
    assert failed.status == "error" and "Video unavailable" in failed.error and other.file(VID) is None


def test_preview_api_rejects_bad_ids():
    with TestClient(app) as client:
        assert client.get("/api/youtube/not-an-id!/preview").status_code == 400
        assert client.get(f"/api/youtube/{VID}x/preview/media").status_code == 400
        assert client.get("/api/youtube/zzzzzzzzzzz/preview/media").status_code == 404
