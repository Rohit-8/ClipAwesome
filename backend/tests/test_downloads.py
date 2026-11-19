import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipawesome import downloads as dl
from clipawesome.api.app import app

URL = "https://youtu.be/abcdefghijk"


def fake_info() -> dict:
    v = {"protocol": "https", "acodec": "none"}
    a = {"protocol": "https", "vcodec": "none"}
    return {
        "id": "abcdefghijk",
        "title": "Test video",
        "channel": "Chan",
        "duration": 100,
        "license": "Creative Commons Attribution license (reuse allowed)",
        "formats": [
            {"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard", "vcodec": "none", "acodec": "none"},
            {**v, "format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "width": 1920, "height": 1080, "fps": 30, "filesize": 50_000_000, "tbr": 4000},
            {**v, "format_id": "248", "ext": "webm", "vcodec": "vp9", "width": 1920, "height": 1080, "fps": 30, "filesize": 40_000_000, "tbr": 3000},
            {**v, "format_id": "337", "ext": "webm", "vcodec": "vp9.2", "width": 1920, "height": 1080, "fps": 60, "dynamic_range": "HDR10", "filesize": 90_000_000},
            {**v, "format_id": "136", "ext": "mp4", "vcodec": "avc1.4d401f", "width": 1280, "height": 720, "fps": 30, "filesize": 20_000_000},
            {"format_id": "18", "protocol": "https", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "width": 640, "height": 360, "fps": 30, "tbr": 500},
            {**a, "format_id": "140", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 129, "audio_channels": 2, "filesize": 1_600_000},
            {**a, "format_id": "140-drc", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 129, "audio_channels": 2, "filesize": 1_600_000},
            {**a, "format_id": "258", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 384, "audio_channels": 6, "filesize": 4_800_000},
            {**a, "format_id": "251", "ext": "webm", "acodec": "opus", "abr": 130, "audio_channels": 2, "filesize": 1_500_000},
            {**a, "format_id": "773", "ext": "mp4", "acodec": "iamf.001.001.Opus", "abr": 200},
        ],
    }


def test_build_options_prefers_compatible_sdr_and_stereo():
    opts = {o.id: o for o in dl.build_options(fake_info(), has_ffmpeg=True)}
    assert list(opts) == ["v1080", "v720", "v360", "a-m4a", "a-webm"]

    hd = opts["v1080"]
    assert hd.format_spec.startswith("137+140/") and hd.ext == "mp4" and hd.codec == "H.264"
    assert hd.size == 51_600_000 and not hd.approx and not hd.hdr and hd.quality == "Full HD"

    sd = opts["v360"]
    assert sd.format_spec.startswith("18/") and sd.approx and sd.size == 500 * 125 * 100

    assert opts["a-m4a"].format_spec.startswith("140/")
    assert opts["a-webm"].format_spec.startswith("251/")


def test_build_options_without_ffmpeg_only_offers_muxed_video():
    opts = {o.id: o for o in dl.build_options(fake_info(), has_ffmpeg=False)}
    assert not opts["v1080"].available and "FFmpeg" in (opts["v1080"].reason or "")
    assert opts["v360"].available and opts["a-m4a"].available


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        out = Path(self.opts["outtmpl"].replace("%(title).120B [%(id)s].%(ext)s", "Test video [abcdefghijk].mp4"))
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading", "filename": f"{out}.part", "downloaded_bytes": 50, "total_bytes": 100, "info_dict": {"vcodec": "avc1"}})
        out.write_bytes(b"x" * 100)
        return {"requested_downloads": [{"filepath": str(out)}]}


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(dl.youtube, "fetch_info", lambda video_id, **_: fake_info())
    monkeypatch.setattr(dl.yt_dlp, "YoutubeDL", FakeYDL)
    dl._info_cache.clear()


def test_download_api_flow(offline):
    with TestClient(app) as client:
        assert client.post("/api/download/formats", json={"url": "https://example.com/x"}).status_code == 400

        info = client.post("/api/download/formats", json={"url": URL}).json()
        assert info["creative_commons"] and info["options"][0]["id"] == "v1080"
        assert "format_spec" not in info["options"][0]

        assert client.post("/api/downloads", json={"url": URL, "option_id": "v9999"}).status_code == 400
        task = client.post("/api/downloads", json={"url": URL, "option_id": "v1080"}).json()
        assert task["status"] in ("queued", "downloading", "done") and task["label"] == "1080p · MP4"

        for _ in range(50):
            task = client.get(f"/api/downloads/{task['id']}").json()
            if task["status"] == "done":
                break
            time.sleep(0.05)
        assert task["status"] == "done" and task["file_size"] == 100

        file = client.get(f"/api/downloads/{task['id']}/file")
        assert file.status_code == 200 and file.content == b"x" * 100
        assert "attachment" in file.headers["content-disposition"]

        assert any(t["id"] == task["id"] for t in client.get("/api/downloads").json())
        assert client.delete(f"/api/downloads/{task['id']}").status_code == 204
        assert client.get(f"/api/downloads/{task['id']}").status_code == 404


def test_expired_downloads_are_purged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPAWESOME_DOWNLOAD_TTL_HOURS", "1")
    mgr = dl.DownloadManager(root=tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    task = dl.DownloadTask(id="d_000000000001", video_id="abcdefghijk", title="t", option_id="v1080", label="1080p", ext="mp4",
                           status="done", created_at=old, finished_at=old)
    mgr._save(task)
    assert mgr.list() == []
    assert not (tmp_path / task.id).exists()
