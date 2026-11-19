"""Local speech-to-text with faster-whisper (optional dependency)."""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import data_path

_models: dict[tuple[str, str, str], Any] = {}
_load_lock = threading.Lock()
_run_lock = threading.Lock()


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _model(size: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    key = (size, device, compute_type)
    with _load_lock:
        if key not in _models:
            _models[key] = WhisperModel(size, device=device, compute_type=compute_type, download_root=str(data_path("models")))
        return _models[key]


def transcribe(
    path: Path,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> tuple[list[tuple[float, float, str]], str | None]:
    """Returns word-level items (start, end, text) and the detected language."""
    model = _model(model_size, device, compute_type)
    items: list[tuple[float, float, str]] = []
    # One transcription at a time keeps memory bounded on CPU machines.
    with _run_lock:
        segments, info = model.transcribe(
            str(path),
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
            language=language or None,
        )
        total = info.duration or duration or 0
        for seg in segments:
            if seg.words:
                items.extend((float(w.start), float(w.end), w.word) for w in seg.words)
            else:
                items.append((float(seg.start), float(seg.end), seg.text))
            if progress and total:
                progress(min(1.0, seg.end / total))
    return items, getattr(info, "language", None)
