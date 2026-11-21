import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipawesome import editor as ed
from clipawesome import gpu
from clipawesome.api.app import app
from clipawesome.config import Settings
from clipawesome.downloads import ffmpeg_path
from clipawesome.sources.local_media import probe

FFMPEG = ffmpeg_path()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")


@pytest.fixture
def no_gpu(monkeypatch):
    monkeypatch.setattr(gpu, "detect", lambda ffmpeg, refresh=False: gpu.Report(None))


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
    assert ed.merge_output_name(["a.mp4", "a.mp4"], "mp4") == "a (merged 2 parts).mp4"
    assert ed.merge_output_name(["a.mp4", "b.mov", "c.mkv"], "mp4") == "a + 2 more.mp4"


def test_gpu_encoder_arguments():
    assert gpu.video_args("balanced") == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    qsv = gpu.video_args("high", "h264_qsv")
    assert qsv[:2] == ["-c:v", "h264_qsv"] and qsv[qsv.index("-global_quality") + 1] == "19"
    nvenc = gpu.video_args("small", "h264_nvenc")
    assert nvenc[nvenc.index("-cq") + 1] == "30" and nvenc[nvenc.index("-b:v") + 1] == "0"
    cmd = ed.build_command("ffmpeg", source(), req(), Path("o.mp4"), codec="h264_amf")
    assert "h264_amf" in cmd and "libx264" not in cmd and "+faststart" in cmd


def test_gpu_detect_picks_first_working_encoder_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(gpu, "_compiled", lambda ff: {"h264_nvenc", "h264_qsv", "h264_amf"})

    def fake_test(ff, enc):
        calls.append(enc.codec)
        return None if enc.codec == "h264_qsv" else "Cannot load nvcuda.dll"

    monkeypatch.setattr(gpu, "_test", fake_test)
    report = gpu.detect("ff-test", refresh=True)
    assert report.encoder and report.encoder.codec == "h264_qsv"
    assert [(t["codec"], t["ok"]) for t in report.tried] == [("h264_nvenc", False), ("h264_qsv", True)]
    assert gpu.detect("ff-test") is report and calls == ["h264_nvenc", "h264_qsv"]

    monkeypatch.setattr(gpu, "_compiled", lambda ff: set())
    none = gpu.detect("ff-test", refresh=True)
    assert none.encoder is None and len(none.tried) == 3 and calls == ["h264_nvenc", "h264_qsv"]


def merge_req(*clips, **kw) -> ed.MergeRequest:
    return ed.MergeRequest(clips=[{"source_id": sid, "start": s, "end": e} for sid, s, e in clips], **kw)


def test_merge_command_normalises_every_clip():
    land = source(id="s_a", path="a.mp4", fps=29.97)
    rotated = source(id="s_b", path="b.mp4", rotation=90, has_audio=False)
    audio = source(id="s_c", path="c.mp3", has_video=False, width=None, height=None)
    items = list(zip(merge_req(("s_a", 0, 5), ("s_b", 2, 4), ("s_c", 0, 3)).clips, [land, rotated, audio]))

    r = merge_req(("s_a", 0, 5), ("s_b", 2, 4), ("s_c", 0, 3))
    cmd = ed.build_merge_command("ffmpeg", items, r, Path("o.mp4"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert ed.merge_canvas(r, land) == (1920, 1080)
    assert "[0:v:0]scale=1920:1080:force_original_aspect_ratio=decrease" in graph and "pad=1920:1080" in graph and "fps=29.97" in graph
    assert "anullsrc=r=48000:cl=stereo,atrim=duration=2.000[a1]" in graph
    assert "color=c=black:s=1920x1080:r=29.97:d=3.000" in graph
    assert graph.endswith("[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]")
    assert cmd.count("-i") == 3 and cmd[cmd.index("-ss") + 1] == "0.000" and "libx264" in cmd and "aac" in cmd

    portrait = merge_req(("s_b", 0, 1), ("s_a", 0, 1), frame="first")
    assert ed.merge_canvas(portrait, rotated) == (1080, 1920)
    assert ed.merge_canvas(merge_req(("s_a", 0, 1), ("s_b", 0, 1), frame="9:16", resolution=720), land) == (720, 1280)
    assert ed.merge_canvas(merge_req(("s_a", 0, 1), ("s_b", 0, 1), frame="1:1"), land) == (1080, 1080)

    crop = ed.build_merge_command("ffmpeg", items, merge_req(("s_a", 0, 5), ("s_b", 2, 4), ("s_c", 0, 3), fit="crop", mute=True), Path("o.mp4"), "h264_qsv")
    graph = crop[crop.index("-filter_complex") + 1]
    assert "force_original_aspect_ratio=increase,crop=1920:1080" in graph and graph.endswith("concat=n=3:v=1:a=0[v]")
    assert "[a]" not in crop and "h264_qsv" in crop

    mp3 = ed.build_merge_command("ffmpeg", items, merge_req(("s_a", 0, 5), ("s_b", 2, 4), ("s_c", 0, 3), format="mp3"), Path("o.mp3"))
    graph = mp3[mp3.index("-filter_complex") + 1]
    assert graph.endswith("[a0][a1][a2]concat=n=3:v=0:a=1[a]") and "[v]" not in mp3 and "libmp3lame" in mp3 and "aresample=44100" in graph


def test_merge_validation_and_fast_merge_listing():
    with pytest.raises(ValueError):
        merge_req(("s_a", 0, 5))
    with pytest.raises(ValueError):
        merge_req(("s_a", 0, 5), ("s_b", 3, 3))
    with pytest.raises(ValueError):
        merge_req(("s_a", 0, 5), ("s_b", 0, 3), resolution=999)

    a, b = source(id="s_a", path="a.mp4"), source(id="s_b", path="b.mp4")
    sound = source(id="s_s", path="s.mp3", has_video=False)
    r = merge_req(("s_a", 0, 5), ("s_b", 0, 5))
    with pytest.raises(ed.EditError, match="has video"):
        ed.validate_merge(r, [(r.clips[0], sound), (r.clips[1], sound)])
    mp3 = merge_req(("s_a", 0, 5), ("s_b", 0, 5), format="mp3")
    with pytest.raises(ed.EditError, match="has audio"):
        ed.validate_merge(mp3, [(mp3.clips[0], source(has_audio=False)), (mp3.clips[1], source(has_audio=False))])
    late = merge_req(("s_a", 0, 5), ("s_b", 150, 160))
    with pytest.raises(ed.EditError, match="Clip 2 starts after"):
        ed.validate_merge(late, [(late.clips[0], a), (late.clips[1], b)])

    fast = merge_req(("s_a", 0, 5), ("s_b", 0, 5), fast=True)
    same = lambda p: (("h264", 1920, 1080, "yuv420p", 30.0), ("aac", 44100, 2))  # noqa: E731
    ed.validate_merge(fast, [(fast.clips[0], a), (fast.clips[1], b)], signature=same)
    differ = lambda p: (("h264", 1280 if p.name == "b.mp4" else 1920, 720, "yuv420p", 30.0), ("aac", 44100, 2))  # noqa: E731
    with pytest.raises(ed.EditError, match="clip 2 is 1280×720 h264 30 fps"):
        ed.validate_merge(fast, [(fast.clips[0], a), (fast.clips[1], b)], signature=differ)

    quoted = source(path="C:\\v\\it's.mp4", duration=8.0)
    listing = ed.ffconcat([(fast.clips[0], quoted), (merge_req(("s_x", 2, 20), ("s_x", 0, 1)).clips[0], quoted)])
    assert listing.splitlines() == [
        "ffconcat version 1.0",
        "file 'C:\\v\\it'\\''s.mp4'", "inpoint 0.000", "outpoint 5.000",
        "file 'C:\\v\\it'\\''s.mp4'", "inpoint 2.000", "outpoint 8.000",
    ]
    assert Settings().gpu_acceleration is True


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("edit") / "sample clip.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


@pytest.fixture(scope="module")
def rotated(tmp_path_factory) -> Path:
    """Landscape pixels with a 90° display rotation and no audio, like a portrait phone clip."""
    folder = tmp_path_factory.mktemp("rot")
    plain, out = folder / "plain.mp4", folder / "phone clip.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plain)],
        check=True,
    )
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", str(plain), "-c", "copy", str(out)], check=True)
    return out


def wait_done(client: TestClient, task_id: str) -> dict:
    for _ in range(300):
        task = client.get(f"/api/editor/exports/{task_id}").json()
        if task["status"] not in ("queued", "running"):
            return task
        time.sleep(0.05)
    raise AssertionError("export did not finish")


@needs_ffmpeg
def test_editor_end_to_end(sample: Path, tmp_path: Path, no_gpu):
    with TestClient(app) as client:
        bad = client.post("/api/editor/sources/upload", files={"file": ("notes.txt", b"hi", "text/plain")})
        assert bad.status_code == 400

        with sample.open("rb") as fh:
            src = client.post("/api/editor/sources/upload", files={"file": (sample.name, fh, "video/mp4")}).json()
        assert src["has_video"] and src["has_audio"] and src["width"] == 320 and 5.5 < src["duration"] < 6.5
        assert src["audio_codec"] == "aac"
        assert "path" not in src
        assert client.get(f"/api/editor/sources/{src['id']}/media").status_code == 200

        preview = client.get(f"/api/editor/sources/{src['id']}/preview-audio")
        assert preview.status_code == 200 and preview.headers["content-type"] == "audio/mpeg"
        preview_file = tmp_path / "preview.mp3"
        preview_file.write_bytes(preview.content)
        info = probe(preview_file)
        assert info.audio_codec == "mp3" and not info.has_video and 5.5 < info.duration < 6.5

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


def upload(client: TestClient, path: Path) -> dict:
    with path.open("rb") as fh:
        resp = client.post("/api/editor/sources/upload", files={"file": (path.name, fh, "video/mp4")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def fetch_export(client: TestClient, task: dict, tmp_path: Path) -> Path:
    path = tmp_path / task["file_name"]
    path.write_bytes(client.get(f"/api/editor/exports/{task['id']}/file").content)
    return path


@needs_ffmpeg
def test_merge_end_to_end(sample: Path, rotated: Path, tmp_path: Path, no_gpu):
    with TestClient(app) as client:
        land, phone = upload(client, sample), upload(client, rotated)
        assert land["rotation"] == 0 and phone["rotation"] in (90, 270) and not phone["has_audio"]

        def merge(body: dict) -> dict:
            resp = client.post("/api/editor/merges", json=body)
            assert resp.status_code == 202, resp.text
            task = wait_done(client, resp.json()["id"])
            assert task["status"] == "done", task
            return task

        # Landscape first: the portrait clip is letterboxed and gets silent audio so the soundtrack stays continuous.
        task = merge({"clips": [{"source_id": land["id"], "start": 1, "end": 4}, {"source_id": phone["id"], "start": 0, "end": 2}]})
        assert task["encoder"] == "CPU · x264" and task["source_ids"] == [land["id"], phone["id"]] and task["label"].startswith("Merge · 2 clips")
        info = probe(fetch_export(client, task, tmp_path))
        assert (info.width, info.height) == (320, 240) and info.has_audio and 4.7 < info.duration < 5.4

        # Portrait first: the frame follows the first clip's displayed shape.
        task = merge({"clips": [{"source_id": phone["id"], "start": 0, "end": 1}, {"source_id": land["id"], "start": 0, "end": 1}], "mute": True})
        info = probe(fetch_export(client, task, tmp_path))
        assert (info.width, info.height) == (240, 320) and not info.has_audio

        task = merge({"clips": [{"source_id": land["id"], "start": 0, "end": 2}, {"source_id": phone["id"], "start": 0, "end": 2}], "format": "mp3"})
        info = probe(fetch_export(client, task, tmp_path))
        assert task["encoder"] is None and not info.has_video and info.has_audio and 3.7 < info.duration < 4.4

        task = merge({"clips": [{"source_id": land["id"], "start": 0, "end": 3}, {"source_id": land["id"], "start": 3, "end": 6}], "fast": True})
        info = probe(fetch_export(client, task, tmp_path))
        assert task["file_name"].endswith("(merged 2 parts).mp4") and info.has_video and info.has_audio and 5.5 < info.duration < 6.6

        mismatch = client.post("/api/editor/merges", json={"clips": [{"source_id": land["id"], "start": 0, "end": 1}, {"source_id": phone["id"], "start": 0, "end": 1}], "fast": True})
        assert mismatch.status_code == 400 and "Fast merge" in mismatch.json()["detail"]
        assert client.post("/api/editor/merges", json={"clips": [{"source_id": land["id"], "start": 0, "end": 1}]}).status_code == 422
        missing = client.post("/api/editor/merges", json={"clips": [{"source_id": land["id"], "start": 0, "end": 1}, {"source_id": "s_gone", "start": 0, "end": 1}]})
        assert missing.status_code == 400 and "Clip 2" in missing.json()["detail"]


@needs_ffmpeg
def test_gpu_failure_falls_back_to_cpu_and_setting_disables_gpu(sample: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setitem(gpu._GPU_ARGS, "h264_broken", lambda q: ["-c:v", "no_such_encoder"])
    monkeypatch.setattr(gpu, "detect", lambda ffmpeg, refresh=False: gpu.Report(gpu.Encoder("h264_broken", "Broken GPU"), [{"codec": "h264_broken", "ok": True}]))
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"gpu_acceleration": True}).json()["gpu_acceleration"] is True
        status = client.get("/api/editor/gpu").json()
        assert status["enabled"] and status["encoder"] == {"codec": "h264_broken", "name": "Broken GPU"}

        src = upload(client, sample)
        resp = client.post("/api/editor/exports", json={"source_id": src["id"], "start": 0, "end": 2})
        task = wait_done(client, resp.json()["id"])
        assert task["status"] == "done" and task["encoder"] == "CPU · x264 (GPU failed)"
        assert probe(fetch_export(client, task, tmp_path)).has_video

        try:
            assert client.put("/api/settings", json={"gpu_acceleration": False}).json()["gpu_acceleration"] is False
            assert client.get("/api/editor/gpu").json() == {"enabled": False, "ffmpeg": True, "encoder": None, "tried": []}
            resp = client.post("/api/editor/exports", json={"source_id": src["id"], "start": 0, "end": 1})
            assert wait_done(client, resp.json()["id"])["encoder"] == "CPU · x264"
        finally:
            client.put("/api/settings", json={"gpu_acceleration": True})
