"""Local speech-to-text with faster-whisper (optional dependency)."""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..config import data_path
from .local_media import audio_scan, iter_pcm

RATE = 16000
SEARCH_SEC = 30  # look this far around each chunk boundary for a quiet moment to cut at

_models: dict[tuple[str, str, str, int, int], Any] = {}
_load_lock = threading.Lock()


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _model(size: str, device: str, compute_type: str, threads: int = 0, workers: int = 1) -> Any:
    from faster_whisper import WhisperModel

    key = (size, device, compute_type, threads, workers)
    with _load_lock:
        if key not in _models:
            _models.clear()  # one loaded model at a time; each can take hundreds of MB
            _models[key] = WhisperModel(
                size, device=device, compute_type=compute_type, cpu_threads=threads, num_workers=workers, download_root=str(data_path("models"))
            )
        return _models[key]


def _quiet_cut(audio: np.ndarray, target: int) -> int:
    """Sample index near `target` where the audio is quietest, so no word is split between chunks."""
    # Never search the first half: a chunk that starts in silence would otherwise be cut again right away.
    lo, hi = max(target // 2, target - SEARCH_SEC * RATE), min(len(audio), target + SEARCH_SEC * RATE // 3)
    frame = RATE // 10
    region = audio[lo:hi]
    n = len(region) // frame
    if n < 2:
        return target
    energy = np.square(region[: n * frame].reshape(n, frame)).mean(axis=1)
    return lo + int(np.argmin(energy)) * frame + frame // 2


class Transcriber:
    """Takes PCM blocks as they're decoded and transcribes each chunk as soon as it's complete.

    Memory stays at about one chunk of audio instead of the whole track (a 2-hour track is ~460 MB as float32).
    """

    def __init__(self, model: Any, chunk_sec: int = 600, language: str | None = None, on_progress: Callable[[float], None] | None = None):
        self.model = model
        self.chunk = chunk_sec * RATE
        self.language = language
        self.on_progress = on_progress
        self.items: list[tuple[float, float, str]] = []
        self._buf: list[np.ndarray] = []
        self._n = 0
        self._offset = 0.0

    def start_span(self, offset: float) -> None:
        self.flush()
        self._offset = offset

    def feed(self, pcm: np.ndarray) -> None:
        self._buf.append(pcm)
        self._n += len(pcm)
        if self._n >= self.chunk + SEARCH_SEC * RATE // 3:
            data = np.concatenate(self._buf)
            cut = _quiet_cut(data, self.chunk)
            self._run(data[:cut])
            rest = data[cut:]
            self._buf, self._n = ([rest] if len(rest) else []), len(rest)

    def flush(self) -> None:
        if self._n:
            self._run(np.concatenate(self._buf))
        self._buf, self._n = [], 0

    def _run(self, audio: np.ndarray) -> None:
        offset = self._offset
        self._offset += len(audio) / RATE
        if len(audio) < RATE // 2:
            return
        segments, info = self.model.transcribe(
            audio,
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
            language=self.language,
        )
        for seg in segments:
            if seg.words:
                self.items.extend((offset + float(w.start), offset + float(w.end), w.word) for w in seg.words)
            else:
                self.items.append((offset + float(seg.start), offset + float(seg.end), seg.text))
            if self.on_progress:
                self.on_progress(offset + float(seg.end))
        # Keep one language for the whole video: later chunks skip detection and can't flip mid-video.
        self.language = self.language or getattr(info, "language", None)


def transcribe(
    path: Path,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
    windows: list[tuple[float, float]] | None = None,
    threads: int = 0,
    workers: int = 1,
    chunk_sec: int = 600,
) -> tuple[list[tuple[float, float, str]], str | None]:
    """Word-level items (start, end, text) and the detected language, for the whole file or only `windows`."""
    model = _model(model_size, device, compute_type, threads, workers)
    spans = windows or [(0.0, duration or float("inf"))]
    total = sum(min(e, duration or e) - s for s, e in spans) if duration or windows else 0.0
    done = 0.0

    def report(t: float) -> None:
        if progress and total:
            progress(min(1.0, (done + max(0.0, t - span_start)) / total))

    tr = Transcriber(model, chunk_sec, language, report)
    for span_start, span_end in spans:
        tr.start_span(span_start)
        for pcm in iter_pcm(path, RATE, span_start, None if span_end == float("inf") else span_end):
            tr.feed(pcm)
        tr.flush()
        done += min(span_end, duration or span_end) - span_start
    return tr.items, tr.language


def scan_and_transcribe(
    path: Path,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
    threads: int = 0,
    workers: int = 1,
    chunk_sec: int = 600,
) -> tuple[np.ndarray | None, list[tuple[float, float, str]], str | None]:
    """Loudness (dB per 0.5 s) and a full transcript from a single decode of the audio."""
    model = _model(model_size, device, compute_type, threads, workers)
    tr = Transcriber(model, chunk_sec, language, (lambda t: progress(min(1.0, t / duration))) if progress and duration else None)
    audio_db = audio_scan(path, sink=tr.feed)
    tr.flush()
    return audio_db, tr.items, tr.language
