"""Turns raw per-source evidence into normalised per-second series. Pure functions only."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .. import text as tx
from ..models import Chapter
from ..transcript import Transcript

EXCLUDE_CATEGORIES = {"sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "filler"}
CATEGORY_LABELS = {
    "sponsor": "sponsor",
    "selfpromo": "self-promotion",
    "interaction": "subscribe reminder",
    "intro": "intro",
    "outro": "outro",
    "preview": "preview/recap",
    "filler": "filler",
}
EMPHATIC_WORDS = {
    "wow", "whoa", "insane", "crazy", "unbelievable", "incredible", "amazing", "holy", "omg",
    "hilarious", "shocking", "ridiculous", "massive", "huge", "literally", "absolutely", "seriously",
}
EMPHATIC_PHRASES = ("no way", "oh my god", "oh my gosh", "what the", "are you kidding", "you won't believe")

SERIES_KEYS = ("heatmap", "audio", "reactions", "relevance", "comments", "highlight", "pace", "visual")


@dataclass
class SourceSignals:
    duration: float
    transcript: Transcript | None = None
    heatmap: list[tuple[float, float, float]] | None = None
    audio_hop: float = 0.5
    audio_db: np.ndarray | None = None
    scene_cuts: list[float] | None = None
    comment_marks: list[tuple[float, float, str]] = field(default_factory=list)
    comments_scanned: int = 0
    sponsor_segments: list[tuple[float, float, str]] = field(default_factory=list)
    highlights: list[float] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class SeriesBundle:
    n: int
    series: dict[str, np.ndarray]
    speech: np.ndarray | None
    excluded: np.ndarray
    raw_heatmap: np.ndarray | None = None
    audio_db_sec: np.ndarray | None = None
    audio_z: np.ndarray | None = None
    reaction_events: list[tuple[float, str]] = field(default_factory=list)
    sentence_relevance: list[float] | None = None
    warnings: list[str] = field(default_factory=list)


def conv_same(x: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Centred convolution that always returns len(x), even when the kernel is longer."""
    full = np.convolve(x, kernel, mode="full")
    r = (len(kernel) - 1) // 2
    return full[r : r + len(x)]


def _gauss_kernel(sigma: float) -> np.ndarray:
    radius = int(3 * sigma) + 1
    offsets = np.arange(-radius, radius + 1)
    return np.exp(-0.5 * (offsets / sigma) ** 2)


def gaussian(n: int, events: list[tuple[float, float]], sigma: float) -> np.ndarray:
    """Sum of peak-1 Gaussians centred on each event, weighted."""
    impulses = np.zeros(n)
    for t, w in events:
        idx = int(t)
        if 0 <= idx < n:
            impulses[idx] += w
    if not impulses.any():
        return impulses
    return conv_same(impulses, _gauss_kernel(sigma))


def smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    kernel = _gauss_kernel(sigma)
    return conv_same(x, kernel / kernel.sum())


def robust_z(x: np.ndarray) -> np.ndarray:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826
    if mad < 1e-6:
        std = float(x.std())
        mad = std if std > 1e-6 else 1.0
    return (x - med) / mad


def _span(arr: np.ndarray, start: float, end: float, value: float, mode: str = "max") -> None:
    lo = max(0, int(start))
    hi = min(len(arr), max(lo + 1, int(math.ceil(end))))
    if mode == "max":
        np.maximum(arr[lo:hi], value, out=arr[lo:hi])
    else:
        arr[lo:hi] = value


def per_second(values: np.ndarray, hop: float, n: int) -> np.ndarray:
    idx = np.minimum((np.arange(len(values)) * hop).astype(int), n - 1)
    sums = np.bincount(idx, weights=values, minlength=n)[:n]
    counts = np.bincount(idx, minlength=n)[:n]
    out = np.full(n, float(values.min()) if len(values) else 0.0)
    mask = counts > 0
    out[mask] = sums[mask] / counts[mask]
    return out


def reaction_events(transcript: Transcript) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = [(e.t, e.weight, e.kind) for e in transcript.events if e.kind in ("laughter", "applause", "cheering", "gasp")]
    for s in transcript.sentences:
        mid = (s.start + s.end) / 2
        low = s.text.lower()
        if s.text.rstrip().endswith("!"):
            events.append((mid, 0.3, "exclamation"))
        hits = sum(1 for w in tx.words(low) if w in EMPHATIC_WORDS) + sum(1 for p in EMPHATIC_PHRASES if p in low)
        if hits:
            events.append((mid, min(0.75, 0.25 * hits), "emphasis"))
    return events


def build_series(sig: SourceSignals, query: dict[str, float]) -> SeriesBundle:
    n = max(1, int(math.ceil(sig.duration)))
    series: dict[str, np.ndarray] = {}
    warnings: list[str] = []
    tr = sig.transcript if sig.transcript and sig.transcript.has_speech else None

    raw_heat = None
    if sig.heatmap:
        raw_heat = np.zeros(n)
        for s, e, v in sig.heatmap:
            _span(raw_heat, s, e, float(v))
        if raw_heat.max() > 0:
            med = float(np.median(raw_heat))
            series["heatmap"] = np.clip((raw_heat - med) / max(1e-6, raw_heat.max() - med), 0, 1)
        else:
            raw_heat = None

    audio_sec = audio_z = None
    if sig.audio_db is not None and len(sig.audio_db) > 4:
        audio_sec = per_second(np.asarray(sig.audio_db, dtype=float), sig.audio_hop, n)
        if float(audio_sec.std()) > 0.5:
            audio_z = robust_z(audio_sec)
            series["audio"] = np.clip((audio_z + 0.5) / 3.5, 0, 1)

    reactions: list[tuple[float, str]] = []
    if tr:
        evs = reaction_events(tr)
        reactions = [(t, kind) for t, _, kind in evs if kind in ("laughter", "applause", "cheering", "gasp")]
        r = 1 - np.exp(-gaussian(n, [(t, w) for t, w, _ in evs], 3.0))
        if r.max() > 0.05:
            series["reactions"] = r

    sentence_rel = None
    if query:
        if tr:
            bm = tx.BM25([tx.terms(s.text) for s in tr.sentences])
            scores = bm.score(query)
            top = max(scores) if scores else 0.0
            if top > 0:
                sentence_rel = [s / top for s in scores]
                rel = np.zeros(n)
                for s, v in zip(tr.sentences, sentence_rel):
                    if v > 0:
                        _span(rel, s.start, s.end, v)
                rel = smooth(rel, 2.0)
                series["relevance"] = rel / rel.max()
            else:
                warnings.append("Focus terms were not found in the transcript; relevance was not used")
        else:
            warnings.append("Focus query needs a transcript; relevance was not used")

    if sig.comment_marks:
        c = gaussian(n, [(t, w) for t, w, _ in sig.comment_marks], 6.0)
        if c.max() > 0:
            series["comments"] = (c / c.max()) * min(1.0, len(sig.comment_marks) / 5)

    if sig.highlights:
        series["highlight"] = np.clip(gaussian(n, [(t, 1.0) for t in sig.highlights], 8.0), 0, 1)

    speech = None
    if tr:
        speech = np.zeros(n, dtype=bool)
        for s in tr.sentences:
            lo, hi = max(0, int(s.start)), min(n, max(int(s.start) + 1, int(math.ceil(s.end))))
            speech[lo:hi] = True
        mids = np.array([(w.start + w.end) / 2 for w in tr.words])
        wps = np.bincount(np.clip(mids.astype(int), 0, n - 1), minlength=n)[:n].astype(float)
        wps = conv_same(wps, np.ones(5) / 5)
        if speech.sum() > 10:
            z = robust_z(wps[speech])
            pace = np.zeros(n)
            pace[speech] = np.clip((z + 1) / 3, 0, 1)
            series["pace"] = pace

    if sig.scene_cuts and len(sig.scene_cuts) >= 3:
        series["visual"] = 1 - np.exp(-gaussian(n, [(t, 1.0) for t in sig.scene_cuts], 2.0))

    excluded = np.zeros(n)
    for s, e, cat in sig.sponsor_segments:
        if cat in EXCLUDE_CATEGORIES:
            _span(excluded, s, e, 1.0, mode="set")

    return SeriesBundle(
        n=n,
        series=series,
        speech=speech,
        excluded=excluded,
        raw_heatmap=raw_heat,
        audio_db_sec=audio_sec,
        audio_z=audio_z,
        reaction_events=reactions,
        sentence_relevance=sentence_rel,
        warnings=warnings,
    )
