"""Local media analysis with PyAV (bundled FFmpeg libraries): probe, loudness and scene cuts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
SUBTITLE_EXTS = {".srt", ".vtt"}

Progress = Callable[[float], None]


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    title: str | None = None
    audio_codec: str | None = None


def probe(path: Path) -> MediaInfo:
    with av.open(str(path)) as c:
        vs = c.streams.video[0] if c.streams.video else None
        as_ = c.streams.audio[0] if c.streams.audio else None
        duration = (c.duration / av.time_base) if c.duration else 0.0
        if not duration:
            for s in (vs, as_):
                if s is not None and s.duration and s.time_base:
                    duration = max(duration, float(s.duration * s.time_base))
        fps = float(vs.average_rate) if vs is not None and vs.average_rate else None
        title = (c.metadata or {}).get("title")
        return MediaInfo(
            duration=float(duration),
            has_video=vs is not None,
            has_audio=as_ is not None,
            width=vs.codec_context.width if vs is not None else None,
            height=vs.codec_context.height if vs is not None else None,
            fps=fps,
            title=title,
            audio_codec=as_.codec_context.codec.canonical_name if as_ is not None else None,
        )


def loudness(path: Path, hop: float = 0.5, duration: float | None = None, progress: Progress | None = None) -> np.ndarray | None:
    """RMS loudness in dB for consecutive `hop`-second windows of mono 16 kHz audio."""
    rate = 16000
    hop_n = int(rate * hop)
    blocks: list[np.ndarray] = []
    leftover = np.zeros(0, dtype=np.float32)

    def consume(frames: list) -> None:
        nonlocal leftover
        for f in frames:
            buf = np.concatenate([leftover, f.to_ndarray().reshape(-1).astype(np.float32)])
            k = len(buf) // hop_n
            if k:
                chunk = buf[: k * hop_n].reshape(k, hop_n)
                blocks.append(np.sqrt(np.mean(chunk * chunk, axis=1)))
            leftover = buf[k * hop_n :]

    with av.open(str(path)) as c:
        if not c.streams.audio:
            return None
        stream = c.streams.audio[0]
        stream.thread_type = "AUTO"
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for idx, frame in enumerate(c.decode(stream)):
            consume(resampler.resample(frame))
            if progress and duration and idx % 400 == 0 and frame.time is not None:
                progress(min(1.0, frame.time / duration))
        consume(resampler.resample(None))
    if not blocks:
        return None
    rms = np.concatenate(blocks)
    return 20 * np.log10(rms + 1e-5)


def decode_audio(path: Path, rate: int = 16000) -> np.ndarray:
    """Whole audio track as mono float32 PCM at `rate` Hz (the input format Whisper expects)."""
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as c:
        if not c.streams.audio:
            return np.zeros(0, dtype=np.float32)
        stream = c.streams.audio[0]
        stream.thread_type = "AUTO"
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in c.decode(stream):
            chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
        chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, dtype=np.float32)


def scene_cuts(path: Path, mode: str = "fast", duration: float | None = None, progress: Progress | None = None) -> list[float]:
    """Detects hard visual changes. `fast` inspects key-frames only; `full` samples ~5 frames per second."""
    cuts: list[float] = []
    with av.open(str(path)) as c:
        if not c.streams.video:
            return cuts
        vs = c.streams.video[0]
        vs.thread_type = "AUTO"
        keyframes_only = False
        if mode == "fast":
            try:
                vs.codec_context.skip_frame = "NONKEY"
                keyframes_only = True
            except Exception:
                keyframes_only = False
        prev: np.ndarray | None = None
        prev_hist: np.ndarray | None = None
        last_t = -1.0
        last_cut = -10.0
        for idx, frame in enumerate(c.decode(vs)):
            t = frame.time
            if t is None:
                continue
            if keyframes_only and not frame.key_frame:
                continue
            if not keyframes_only and t - last_t < 0.2:
                continue
            last_t = t
            img = frame.reformat(width=64, height=36, format="gray").to_ndarray().astype(np.float32)
            hist = np.histogram(img, bins=16, range=(0, 255))[0].astype(np.float32)
            hist /= max(1.0, hist.sum())
            if prev is not None and prev_hist is not None:
                diff = float(np.abs(img - prev).mean())
                hdist = float(np.abs(hist - prev_hist).sum()) / 2
                if (diff > 30 or (diff > 18 and hdist > 0.45)) and t - last_cut >= 1.0:
                    cuts.append(round(float(t), 2))
                    last_cut = t
            prev, prev_hist = img, hist
            if progress and duration and idx % 50 == 0:
                progress(min(1.0, t / duration))
    return cuts
