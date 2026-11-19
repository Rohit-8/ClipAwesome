"""Candidate generation, scoring, selection and explanation. Pure functions only."""

from __future__ import annotations

import bisect
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .. import text as tx
from ..config import ScoringWeights
from ..models import Chapter, Contribution, Reason, Timeline, TranscriptLine
from .presets import LengthSpec
from .signals import CATEGORY_LABELS, EXCLUDE_CATEGORIES, SERIES_KEYS, SeriesBundle, SourceSignals, build_series

FEATURE_LABELS = {
    "heatmap": "Most replayed",
    "audio": "Audio energy",
    "reactions": "Audience reactions",
    "relevance": "Topic relevance",
    "comments": "Viewer comments",
    "highlight": "Community highlight",
    "pace": "Speech pace",
    "visual": "Visual activity",
    "hook": "Opening hook",
    "completeness": "Clean boundaries",
}

HOOK_PHRASES = (
    "the secret", "secret is", "biggest mistake", "here's why", "here is why", "the truth", "nobody tells you",
    "no one tells you", "you need to", "the reason", "what if", "imagine", "the problem is", "i was wrong",
    "the best", "the worst", "how to", "why you", "stop doing", "this is why", "the key", "most people",
    "turns out", "changed my life", "i realized", "let me tell you", "the craziest", "you have to",
)
CONJ_START = {"and", "but", "so", "because", "or", "also", "then", "which", "um", "uh", "like", "yeah", "anyway", "cause"}
QUESTION_START = {"what", "why", "how", "who", "when", "where", "did", "do", "does", "is", "are", "can", "could", "would", "should", "have", "has", "ever"}
REACTION_NAMES = {"laughter": "laughter", "applause": "applause", "cheering": "cheering", "gasp": "gasps"}


@dataclass
class Unit:
    start: float
    end: float
    text: str = ""
    terminal: bool = False


@dataclass
class EngineClip:
    start: float
    end: float
    score: float
    base: float
    features: dict[str, float]
    breakdown: list[Contribution]
    reasons: list[Reason]
    title: str
    hook: str | None
    transcript: str
    tags: list[str]
    chapter: str | None


@dataclass
class EngineResult:
    clips: list[EngineClip]
    timeline: Timeline
    transcript_lines: list[TranscriptLine]
    signals: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Cand:
    i: int
    j: int
    start: float
    end: float
    score: float
    base: float
    feats: dict[str, float]
    excl: float
    silent: float


MAX_ENDS_PER_START = 48


class RangeMax:
    """Sparse table: O(1) max over arr[lo:hi] after O(n log n) setup."""

    def __init__(self, arr: np.ndarray):
        self.levels = [np.asarray(arr, dtype=float)]
        k = 1
        while (1 << k) <= len(arr):
            prev, half = self.levels[-1], 1 << (k - 1)
            self.levels.append(np.maximum(prev[:-half], prev[half:]))
            k += 1

    def query(self, lo: int, hi: int) -> float:
        k = (hi - lo).bit_length() - 1
        level = self.levels[k]
        return float(max(level[lo], level[hi - (1 << k)]))


def _sample_ends(j_lo: int, j_hi: int) -> list[int]:
    """All end units for normal ranges; evenly spaced ones when a very long range allows thousands."""
    count = j_hi - j_lo + 1
    if count <= MAX_ENDS_PER_START:
        return list(range(j_lo, j_hi + 1))
    step = (count - 1) / (MAX_ENDS_PER_START - 1)
    return sorted({j_lo + round(k * step) for k in range(MAX_ENDS_PER_START)})


def _is_question(text: str, punctuated: bool) -> bool:
    stripped = text.rstrip(" \"'")
    if stripped.endswith("?"):
        return True
    first = (tx.words(text) or [""])[0]
    return not punctuated and first in QUESTION_START


def hook_score(text: str, punctuated: bool) -> tuple[float, str | None]:
    low = text.lower()
    ws = tx.words(low)
    score = 0.5
    phrase = next((p for p in HOOK_PHRASES if p in low), None)
    if _is_question(text, punctuated):
        score += 0.25
    if phrase:
        score += 0.25
    if ws and ws[0] in CONJ_START:
        score -= 0.35
    if len(ws) < 3:
        score -= 0.1
    return float(min(1.0, max(0.0, score))), phrase


def _completeness(units: list[Unit], i: int, j: int, punctuated: bool) -> float:
    prev_gap = units[i].start - units[i - 1].end if i > 0 else 9.0
    clean_start = 1.0 if (i == 0 or (punctuated and units[i - 1].terminal) or prev_gap >= 0.6) else 0.6
    next_gap = units[j + 1].start - units[j].end if j + 1 < len(units) else 9.0
    if punctuated and units[j].terminal:
        clean_end = 1.0
    elif next_gap >= 0.8:
        clean_end = 0.8
    else:
        clean_end = 0.45
    return 0.5 * clean_start + 0.5 * clean_end


def build_units(sig: SourceSignals) -> tuple[list[Unit], bool]:
    """Sentences when a transcript exists; otherwise pause-delimited audio chunks or a 5 s grid."""
    tr = sig.transcript
    if tr and tr.sentences:
        punctuated = sum(s.terminal for s in tr.sentences) / len(tr.sentences) >= 0.3
        return [Unit(s.start, s.end, s.text, s.terminal) for s in tr.sentences], punctuated

    duration = sig.duration
    cuts: list[float] = []
    if sig.audio_db is not None and len(sig.audio_db) > 8:
        db = np.asarray(sig.audio_db, dtype=float)
        low = db < (np.median(db) - 10)
        hop = sig.audio_hop
        run_start = None
        for k, is_low in enumerate(np.append(low, False)):
            if is_low and run_start is None:
                run_start = k
            elif not is_low and run_start is not None:
                if (k - run_start) * hop >= 0.4:
                    cuts.append((run_start + k) / 2 * hop)
                run_start = None
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    units: list[Unit] = []
    for a, b in zip(bounds, bounds[1:]):
        if units and (b - a < 2.0 or units[-1].end - units[-1].start < 2.0):
            units[-1].end = b
            continue
        pieces = max(1, int(round((b - a) / 5.0))) if b - a > 10 else 1
        step = (b - a) / pieces
        units.extend(Unit(a + k * step, a + (k + 1) * step) for k in range(pieces))
    return units, False


def _chapter_at(chapters: list[Chapter], t: float) -> str | None:
    for ch in chapters:
        if ch.start <= t < ch.end:
            return ch.title
    return None


def _downsample(x: np.ndarray, bin_sec: int) -> list[float]:
    if bin_sec <= 1:
        return [round(float(v), 4) for v in x]
    pad = (-len(x)) % bin_sec
    if pad:
        x = np.concatenate([x, np.full(pad, x[-1])])
    return [round(float(v), 4) for v in x.reshape(-1, bin_sec).mean(axis=1)]


def _timeline(sig: SourceSignals, bundle: SeriesBundle, composite: np.ndarray) -> Timeline:
    bin_sec = max(1, math.ceil(bundle.n / 720))
    series = {"composite": _downsample(composite, bin_sec)}
    for k, arr in bundle.series.items():
        series[k] = _downsample(arr, bin_sec)
    markers: dict[str, list[dict]] = {
        "excluded": [
            {"start": s, "end": e, "label": CATEGORY_LABELS.get(c, c)}
            for s, e, c in sig.sponsor_segments if c in EXCLUDE_CATEGORIES
        ],
        "highlights": [{"t": t, "label": "Community highlight"} for t in sig.highlights],
        "reactions": [{"t": round(t, 2), "label": k} for t, k in bundle.reaction_events[:300]],
        "scene_cuts": [{"t": round(t, 2)} for t in (sig.scene_cuts or [])[:800]],
        "comments": [{"t": t, "label": tx.shorten(txt, 90)} for t, _, txt in sig.comment_marks[:150]],
    }
    return Timeline(bin_sec=bin_sec, series=series, markers=markers)


def _reasons(
    c: _Cand, sig: SourceSignals, bundle: SeriesBundle, units: list[Unit], query: dict[str, float], punctuated: bool, clip_text: str
) -> list[Reason]:
    out: list[Reason] = []
    b0, b1 = max(0, int(c.start)), min(bundle.n, max(int(c.start) + 1, math.ceil(c.end)))

    if bundle.raw_heatmap is not None and "heatmap" in c.feats:
        peak = float(bundle.raw_heatmap[b0:b1].max())
        pct = float((bundle.raw_heatmap < peak).mean() * 100)
        if pct >= 70:
            out.append(Reason(text=f"Replayed more than {pct:.0f}% of the video", signal="heatmap"))

    hits = [(t, w, txt) for t, w, txt in sig.comment_marks if c.start - 3 <= t <= c.end + 3]
    if hits:
        sample = max(hits, key=lambda h: h[1])[2]
        n = len(hits)
        out.append(Reason(text=f"{n} viewer comment{'s' if n > 1 else ''} point here — “{tx.shorten(sample, 80)}”", signal="comments"))

    kinds = Counter(k for t, k in bundle.reaction_events if c.start <= t <= c.end)
    if kinds:
        parts = [f"{REACTION_NAMES.get(k, k)} ×{v}" if v > 1 else REACTION_NAMES.get(k, k) for k, v in kinds.most_common()]
        out.append(Reason(text="Audience reaction: " + ", ".join(parts), signal="reactions"))

    if any(c.start - 2 <= t <= c.end for t in sig.highlights):
        out.append(Reason(text="Community-marked highlight (SponsorBlock)", signal="highlight"))

    if query and "relevance" in c.feats:
        found = tx.matched_terms(clip_text, query)
        if found:
            parts = [f"“{w}” ×{k}" if k > 1 else f"“{w}”" for w, k in found.most_common(3)]
            out.append(Reason(text="Mentions " + ", ".join(parts), signal="relevance"))

    if bundle.audio_z is not None and bundle.audio_db_sec is not None:
        zpk = float(bundle.audio_z[b0:b1].max())
        if zpk >= 1.5:
            above = float(bundle.audio_db_sec[b0:b1].max() - np.median(bundle.audio_db_sec))
            out.append(Reason(text=f"Energy spike: +{above:.0f} dB above typical", signal="audio"))

    if units[c.i].text:
        hs, phrase = hook_score(units[c.i].text, punctuated)
        if _is_question(units[c.i].text, punctuated):
            out.append(Reason(text="Opens with a question", signal="hook"))
        if phrase:
            out.append(Reason(text=f"Hook phrase: “{phrase}”", signal="hook"))
        first = (tx.words(units[c.i].text) or [""])[0]
        if first in CONJ_START:
            out.append(Reason(text=f"Starts mid-thought (“{first} …”)", signal="hook", polarity="neg"))

    if sig.scene_cuts:
        cuts = sum(1 for t in sig.scene_cuts if c.start <= t <= c.end)
        if cuts >= 4 and cuts / max(1.0, c.end - c.start) > 0.08:
            out.append(Reason(text=f"Fast visual pacing ({cuts} cuts)", signal="visual", polarity="info"))

    if c.excl > 0.03:
        cats = Counter(
            cat for s, e, cat in sig.sponsor_segments
            if cat in EXCLUDE_CATEGORIES and min(e, c.end) - max(s, c.start) > 0
        )
        label = CATEGORY_LABELS.get(cats.most_common(1)[0][0], "excluded") if cats else "excluded"
        out.append(Reason(text=f"Overlaps a {label} segment ({c.excl * 100:.0f}%)", signal="excluded", polarity="neg"))

    if bundle.speech is not None and c.silent > 0.35:
        out.append(Reason(text=f"{c.silent * 100:.0f}% without speech", signal="speech", polarity="neg"))
    return out


def _title(units: list[Unit], c: _Cand, bundle: SeriesBundle, punctuated: bool, chapter: str | None) -> tuple[str, str | None]:
    texts = [u.text for u in units[c.i : c.j + 1] if u.text]
    if not texts:
        base = chapter or "Moment"
        return f"{base} · {tx.fmt_time(c.start)}", None
    hook = tx.shorten(texts[0], 160)
    chosen = texts[0]
    if not _is_question(texts[0], punctuated):
        if bundle.sentence_relevance is not None:
            rel = bundle.sentence_relevance[c.i : c.j + 1]
            best = int(np.argmax(rel))
            if rel[best] > 0:
                chosen = units[c.i + best].text
        if len(tx.words(chosen)) < 5:
            chosen = next((t for t in texts if len(tx.words(t)) >= 5), chosen)
    title = tx.shorten(chosen.strip(" -–—,"), 80)
    return (title[:1].upper() + title[1:]) if title else f"Moment at {tx.fmt_time(c.start)}", hook


def score_source(
    sig: SourceSignals,
    spec: LengthSpec,
    weights: ScoringWeights,
    query: dict[str, float] | None = None,
    limit: int = 8,
) -> EngineResult:
    query = query or {}
    bundle = build_series(sig, query)
    units, punctuated = build_units(sig)
    w_all = weights.model_dump()
    n = bundle.n
    warnings = list(bundle.warnings)

    series_feats = [k for k in SERIES_KEYS if k in bundle.series and w_all.get(k, 0) > 0]
    has_text = bool(sig.transcript and sig.transcript.sentences)
    window_feats = [k for k in ("hook", "completeness") if has_text and w_all.get(k, 0) > 0]
    feats_used = series_feats + window_feats
    w_sum = sum(w_all[k] for k in feats_used) or 1.0

    composite = np.zeros(n)
    s_sum = sum(w_all[k] for k in series_feats) or 1.0
    for k in series_feats:
        composite += w_all[k] * bundle.series[k]
    composite /= s_sum

    lines = [TranscriptLine(start=round(u.start, 2), end=round(u.end, 2), text=u.text) for u in units if u.text]
    if not units or not feats_used:
        if not feats_used:
            warnings.append("No usable signals were found for this video")
        return EngineResult([], _timeline(sig, bundle, composite), lines, [], warnings)

    csum = {k: np.concatenate([[0.0], np.cumsum(bundle.series[k])]) for k in series_feats}
    peaks = {k: RangeMax(bundle.series[k]) for k in series_feats}
    ex_cs = np.concatenate([[0.0], np.cumsum(bundle.excluded)])
    sp_cs = np.concatenate([[0.0], np.cumsum(bundle.speech.astype(float))]) if bundle.speech is not None else None
    hooks = [hook_score(u.text, punctuated)[0] if u.text else 0.5 for u in units] if "hook" in window_feats else []
    spread = 0.5 * max(1.0, spec.max_len - spec.min_len)
    ends = [u.end for u in units]

    cands: list[_Cand] = []

    def make(i: int, j: int) -> _Cand:
        d = units[j].end - units[i].start
        b0 = min(n - 1, max(0, int(units[i].start)))
        b1 = min(n, max(b0 + 1, math.ceil(units[j].end)))
        width = b1 - b0
        feats: dict[str, float] = {}
        for k in series_feats:
            feats[k] = 0.6 * (csum[k][b1] - csum[k][b0]) / width + 0.4 * peaks[k].query(b0, b1)
        if "hook" in window_feats:
            feats["hook"] = hooks[i]
        if "completeness" in window_feats:
            feats["completeness"] = _completeness(units, i, j, punctuated)
        base = sum(w_all[k] * v for k, v in feats.items()) / w_sum
        excl = (ex_cs[b1] - ex_cs[b0]) / width
        silent = 1 - (sp_cs[b1] - sp_cs[b0]) / width if sp_cs is not None else 0.0
        fit = math.exp(-(((d - spec.target) / spread) ** 2))
        score = 100 * base * (1 - 0.9 * excl) * (1 - 0.5 * max(0.0, silent - 0.25)) * (0.92 + 0.08 * fit)
        return _Cand(i, j, units[i].start, units[j].end, score, base, feats, excl, silent)

    for i in range(len(units)):
        start = units[i].start
        j_lo = max(i, bisect.bisect_left(ends, start + spec.min_len))
        j_hi = bisect.bisect_right(ends, start + spec.max_len) - 1
        if j_hi >= j_lo:
            cands.extend(make(i, j) for j in _sample_ends(j_lo, j_hi))

    if not cands:
        # Nothing fits exactly: per start, take the window whose length is nearest the requested range.
        def gap(i: int, j: int) -> float:
            d = units[j].end - units[i].start
            return max(0.0, spec.min_len - d, d - spec.max_len)

        nearest: list[tuple[float, int, int]] = []
        last = len(units) - 1
        for i in range(len(units)):
            start = units[i].start
            j_lo = bisect.bisect_left(ends, start + spec.min_len)
            j_hi = bisect.bisect_right(ends, start + spec.max_len) - 1
            options = {min(last, max(i, j)) for j in (j_lo - 1, j_lo, j_hi, j_hi + 1)}
            best = min(options, key=lambda j: gap(i, j))
            nearest.append((gap(i, best), i, best))
        best_gap = min(g for g, _, _ in nearest)
        cands = [make(i, j) for g, i, j in nearest if g <= best_gap + 2.0]
        lengths = sorted(units[j].end - units[i].start for g, i, j in nearest if g <= best_gap + 2.0)
        warnings.append(
            f"No sentence-aligned clip fits {tx.fmt_time(spec.min_len)}–{tx.fmt_time(spec.max_len)}; "
            f"showing the nearest lengths ({tx.fmt_time(lengths[0])}–{tx.fmt_time(lengths[-1])})"
        )

    cands.sort(key=lambda c: c.score, reverse=True)
    picked: list[_Cand] = []
    for c in cands:
        dur = c.end - c.start
        if all(min(c.end, p.end) - max(c.start, p.start) <= 0.2 * min(dur, p.end - p.start) for p in picked):
            picked.append(c)
            if len(picked) >= limit:
                break

    doc_freq: dict[str, int] = {}
    if has_text:
        bm = tx.BM25([tx.terms(u.text) for u in units])
        doc_freq = dict(bm.df)

    clips: list[EngineClip] = []
    for c in picked:
        prev_end = units[c.i - 1].end if c.i > 0 else 0.0
        next_start = units[c.j + 1].start if c.j + 1 < len(units) else sig.duration
        start = max(0.0, c.start - min(0.3, max(0.0, (c.start - prev_end) / 2)))
        end = min(sig.duration, c.end + min(0.5, max(0.0, (next_start - c.end) / 2)))
        clip_text = " ".join(u.text for u in units[c.i : c.j + 1] if u.text)
        chapter = _chapter_at(sig.chapters, (start + end) / 2)
        title, hook = _title(units, c, bundle, punctuated, chapter)
        breakdown = [
            Contribution(
                signal=k,
                label=FEATURE_LABELS[k],
                value=round(v, 3),
                weight=round(w_all[k] / w_sum, 3),
                contribution=round(100 * w_all[k] * v / w_sum, 1),
            )
            for k, v in sorted(c.feats.items(), key=lambda kv: -w_all[kv[0]] * kv[1])
        ]
        penalty = c.score - 100 * c.base
        if penalty < -0.5:
            breakdown.append(Contribution(signal="penalties", label="Penalties", value=0, weight=0, contribution=round(penalty, 1)))
        clips.append(
            EngineClip(
                start=round(start, 2),
                end=round(end, 2),
                score=round(c.score, 1),
                base=c.base,
                features=c.feats,
                breakdown=breakdown,
                reasons=_reasons(c, sig, bundle, units, query, punctuated, clip_text),
                title=title,
                hook=hook,
                transcript=clip_text,
                tags=tx.top_keywords(clip_text, doc_freq, len(units), 4) if clip_text else [],
                chapter=chapter,
            )
        )
    return EngineResult(clips, _timeline(sig, bundle, composite), lines, feats_used, warnings)
