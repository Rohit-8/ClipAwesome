from pathlib import Path

import av
import numpy as np
import pytest

from clipawesome.config import Settings
from clipawesome.models import AnalyzeOptions
from clipawesome.sources import local_media, transcribe
from clipawesome import pipeline

SECONDS = 40
FPS = 10
RATE = 16000


def make_media(path: Path) -> Path:
    """Three flat-colour scenes (cuts at 13 s and 26 s) and quiet audio with a loud burst at 20–25 s."""
    with av.open(str(path), "w") as c:
        vs = c.add_stream("mpeg4", rate=FPS)
        vs.width, vs.height, vs.pix_fmt = 64, 48, "yuv420p"
        aus = c.add_stream("pcm_s16le", rate=RATE, layout="mono")
        for i in range(SECONDS * FPS):
            t = i / FPS
            level = 30 if t < 13 else 220 if t < 26 else 120
            img = np.full((48, 64, 3), level, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = i
            for packet in vs.encode(frame):
                c.mux(packet)
        step = RATE // 10
        for k in range(SECONDS * 10):
            t = k / 10
            amp = 0.0 if int(t * 10) % 37 == 0 else (0.8 if 20 <= t < 25 else 0.05)
            samples = (amp * np.sin(2 * np.pi * 220 * (np.arange(step) + k * step) / RATE) * 32767).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = RATE
            frame.pts = k * step
            for packet in aus.encode(frame):
                c.mux(packet)
        for packet in vs.encode(None):
            c.mux(packet)
        for packet in aus.encode(None):
            c.mux(packet)
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> Path:
    return make_media(tmp_path_factory.mktemp("media") / "sample.mkv")


def test_probe(media):
    info = local_media.probe(media)
    assert info.has_video and info.has_audio
    assert abs(info.duration - SECONDS) < 1.5


def test_loudness_detects_burst(media):
    db = local_media.loudness(media, hop=0.5)
    assert db is not None and abs(len(db) - SECONDS * 2) <= 2
    assert db[int(22 / 0.5)] > db[int(5 / 0.5)] + 15


def test_decode_audio_for_whisper(media):
    pcm = local_media.decode_audio(media, 16000)
    assert pcm.dtype == np.float32 and pcm.ndim == 1
    assert abs(len(pcm) / 16000 - SECONDS) < 0.5


@pytest.mark.parametrize("mode", ["full", "fast"])
def test_scene_cuts(media, mode):
    cuts = local_media.scene_cuts(media, mode)
    assert any(abs(c - 13) <= 1.6 for c in cuts), cuts
    assert any(abs(c - 26) <= 1.6 for c in cuts), cuts


def test_analyze_local_without_transcript(media, monkeypatch):
    monkeypatch.setattr(transcribe, "available", lambda: False)
    stages: list[str] = []
    analysis = pipeline.analyze_local(
        media, "sample.mkv", "m_" + "0" * 16, None, AnalyzeOptions(preset="shorts", max_clips=2), Settings(), lambda s, f: stages.append(s)
    )
    assert analysis.kind == "local" and analysis.clips
    assert analysis.sources[0].media_kind == "video"
    assert "audio" in analysis.sources[0].signals
    top = analysis.clips[0]
    assert top.start <= 22 <= top.end
    assert any("transcript" in w.lower() for w in analysis.warnings)
    assert "Detecting scene cuts" in stages
