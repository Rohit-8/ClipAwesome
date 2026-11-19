import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipawesome import editor as ed
from clipawesome.api.app import app
from clipawesome.downloads import ffmpeg_path
from clipawesome.sources.local_media import probe

FFMPEG = ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")


def source(**kw) -> ed.EditSource:
    base = dict(id="s_1", name="My clip.mp4", kind="upload", path="in.mp4", duration=100.0, has_video=True, has_audio=True,
                width=1920, height=1080, size=1, created_at="2026-01-01T00:00:00+00:00")
    return ed.EditSource(**{**base, **kw})


def req(**kw) -> ed.ExportRequest:
    return ed.ExportRequest(**{"source_id": "s_1", "start": 10, "end": 20, **kw})


def test_crop_rotate_resize_mp4_command():
    r = req(crop={"x": 0.25, "y": 0, "w": 0.5, "h": 1}, rotate=90, flip_h=True, height=720, quality="high")
    cmd = ed.build_command("ffmpeg", source(), r, Path("out.mp4"))
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "crop=trunc(iw*0.500000/2+0.01)*2:trunc(ih*1.000000/2+0.01)*2:trunc(iw*0.250000):trunc(ih*0.000000),transpose=1,hflip,scale=-2:'min(720,ih)'"
    assert cmd[cmd.index("-ss") + 1] == "10.000" and cmd[cmd.index("-t") + 1] == "10.000"
    assert ["-c:v", "libx264"] == cmd[cmd.index("-c:v"):cmd.index("-c:v") + 2] and "18" in cmd and "aac" in cmd


def test_mute_fast_mp3_gif_commands():
    assert "-an" in ed.build_command("ffmpeg", source(), req(mute=True), Path("o.mp4"))
    assert "-an" in ed.build_command("ffmpeg", source(has_audio=False), req(), Path("o.mp4"))

    fast = ed.build_command("ffmpeg", source(), req(fast=True), Path("o.mp4"))
    assert fast[fast.index("-c") + 1] == "copy" and "-vf" not in fast

    mp3 = ed.build_command("ffmpeg", source(), req(format="mp3"), Path("o.mp3"))
    assert "libmp3lame" in mp3 and "-vn" in mp3

    gif = ed.build_command("ffmpeg", source(), req(format="gif", crop={"x": 0, "y": 0, "w": 0.5, "h": 0.5}), Path("o.gif"))
    graph = gif[gif.index("-vf") + 1]
    assert graph.startswith("crop=") and "split[a][b];[a]palettegen" in graph and graph.endswith("paletteuse=dither=bayer:bayer_scale=4")


def test_crop_is_clamped_and_requests_validated():
    assert ed.CropBox(x=0.8, y=0.5, w=0.5, h=0.9).w == pytest.approx(0.2)
    with pytest.raises(ValueError):
        req(start=5, end=5)
    with pytest.raises(ValueError):
        req(height=999)
    with pytest.raises(ed.EditError, match="Fast cut"):
        ed.validate(req(fast=True, rotate=90), source())
    with pytest.raises(ed.EditError, match="GIF"):
        ed.validate(req(format="gif", start=0, end=90), source())
    with pytest.raises(ed.EditError, match="no audio"):
        ed.validate(req(format="mp3"), source(has_audio=False))
    with pytest.raises(ed.EditError, match="no video"):
        ed.validate(req(), source(has_video=False))


def test_output_name_is_safe():
    name = ed.output_name('a:b*c?"<>|.mp4', req(start=65, end=3725), ".mp4")
    assert name == "a_b_c [1-05 to 1-02-05].mp4"
    assert ed.output_name("x.mkv", req(fast=True), ".mkv").endswith(".mkv")


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("edit") / "sample clip.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


def wait_done(client: TestClient, task_id: str) -> dict:
    for _ in range(300):
        task = client.get(f"/api/editor/exports/{task_id}").json()
        if task["status"] not in ("queued", "running"):
            return task
        time.sleep(0.05)
    raise AssertionError("export did not finish")


@needs_ffmpeg
def test_editor_end_to_end(sample: Path, tmp_path: Path):
    with TestClient(app) as client:
        bad = client.post("/api/editor/sources/upload", files={"file": ("notes.txt", b"hi", "text/plain")})
        assert bad.status_code == 400

        with sample.open("rb") as fh:
            src = client.post("/api/editor/sources/upload", files={"file": (sample.name, fh, "video/mp4")}).json()
        assert src["has_video"] and src["has_audio"] and src["width"] == 320 and 5.5 < src["duration"] < 6.5
        assert "path" not in src
        assert client.get(f"/api/editor/sources/{src['id']}/media").status_code == 200

        w = 240 * 9 / 16 / 320
        jobs = {
            "crop": {"crop": {"x": (1 - w) / 2, "y": 0, "w": w, "h": 1}, "start": 1, "end": 4},
            "mp3": {"format": "mp3", "start": 0, "end": 3},
            "gif": {"format": "gif", "start": 0, "end": 1, "rotate": 90},
            "fast": {"fast": True, "start": 2, "end": 5, "mute": True},
        }
        results = {}
        for key, body in jobs.items():
            resp = client.post("/api/editor/exports", json={"source_id": src["id"], **body})
            assert resp.status_code == 202, resp.text
            results[key] = wait_done(client, resp.json()["id"])
            assert results[key]["status"] == "done", results[key]

        def fetch(key: str) -> Path:
            file = client.get(f"/api/editor/exports/{results[key]['id']}/file")
            assert file.status_code == 200 and "attachment" in file.headers["content-disposition"]
            path = tmp_path / results[key]["file_name"]
            path.write_bytes(file.content)
            return path

        crop = probe(fetch("crop"))
        assert (crop.width, crop.height) == (134, 240) and crop.has_audio and 2.8 < crop.duration < 3.3

        mp3 = probe(fetch("mp3"))
        assert mp3.has_audio and not mp3.has_video and 2.8 < mp3.duration < 3.3

        gif = probe(fetch("gif"))
        assert gif.has_video and (gif.width, gif.height) == (240, 320)

        fast = probe(fetch("fast"))
        assert fast.has_video and not fast.has_audio

        assert client.post("/api/editor/exports", json={"source_id": src["id"], "format": "gif", "start": 0, "end": 6, "fast": True}).status_code == 400
        assert client.post("/api/editor/exports", json={"source_id": "s_missing", "start": 0, "end": 1}).status_code == 400

        assert any(t["id"] == results["crop"]["id"] for t in client.get("/api/editor/exports").json())
        assert client.delete(f"/api/editor/exports/{results['crop']['id']}").status_code == 204
        assert client.delete(f"/api/editor/sources/{src['id']}").status_code == 204
        assert client.get(f"/api/editor/sources/{src['id']}").status_code == 404
