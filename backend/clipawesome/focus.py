"""Focused transcription: pick the stretches of a long video most likely to hold the best clips.

Whisper is the slowest step on a CPU. Instead of transcribing everything, transcribe the parts that viewers
replayed, commented on, or where the audio gets loud, plus some context around them.
"""

from __future__ import annotations

import math

import numpy as np

MIN_BUDGET_SEC = 600.0
BUDGET_SHARE = 0.3
MERGE_GAP_SEC = 15.0


def budget_for(duration: float) -> float:
    return min(duration, max(MIN_BUDGET_SEC, BUDGET_SHARE * duration))


def pick_windows(
    duration: float,
    clip_len: float,
    audio_db: np.ndarray | None = None,
    hop: float = 0.5,
    heatmap: list[tuple[float, float, float]] | None = None,
    marks: list[tuple[float, float, str]] | None = None,
    budget: float | None = None,
) -> list[tuple[float, float]]:
    """Sorted, non-overlapping (start, end) windows covering about `budget` seconds."""
    budget = budget_for(duration) if budget is None else min(budget, duration)
    if budget >= duration * 0.85:
        return [(0.0, duration)]
    n = max(1, math.ceil(duration))
    score = np.zeros(n)
    if heatmap:
        for s, e, v in heatmap:
            score[int(s) : max(int(s) + 1, int(e))] += 2.0 * float(v)
    if audio_db is not None and len(audio_db):
        per_sec = max(1, round(1 / hop))
        k = len(audio_db) // per_sec
        if k:
            sec = audio_db[: k * per_sec].reshape(k, per_sec).mean(axis=1)
            spread = float(np.std(sec)) or 1.0
            z = np.clip((sec - float(np.median(sec))) / spread, 0, 3) / 3
            score[: min(n, k)] += z[: min(n, k)]
    for t, w, _ in marks or []:
        lo, hi = max(0, int(t) - 10), min(n, int(t) + 10)
        score[lo:hi] += min(1.0, float(w) / 5)
    if not score.any():
        # No signal at all: spread the budget evenly so every part of the video gets a chance.
        parts = max(1, int(budget // max(60.0, clip_len * 1.5)))
        size = budget / parts
        step = duration / parts
        return [(round(i * step, 2), round(min(duration, i * step + size), 2)) for i in range(parts)]

    win = max(1, int(clip_len))
    smooth = np.convolve(score, np.ones(win) / win, mode="same")
    half = max(30.0, clip_len * 0.75)
    covered = np.zeros(n, dtype=bool)
    for idx in np.argsort(-smooth, kind="stable"):
        if covered.sum() >= budget:
            break
        if covered[idx]:
            continue
        covered[max(0, int(idx - half)) : min(n, int(idx + half))] = True

    windows: list[tuple[float, float]] = []
    edges = np.flatnonzero(np.diff(np.concatenate([[0], covered.astype(np.int8), [0]])))
    for s, e in zip(edges[::2], edges[1::2]):
        start, end = float(s), float(min(e, duration))
        if windows and start - windows[-1][1] <= MERGE_GAP_SEC:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((start, end))
    return windows


def covered(windows: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in windows)
