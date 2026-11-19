import numpy as np
import pytest

from clipawesome.config import ScoringWeights
from clipawesome.engine.presets import resolve_preset
from clipawesome.engine.scoring import score_source
from clipawesome.engine.signals import SourceSignals
from clipawesome.text import query_weights
from clipawesome.transcript import Event, Word, make_transcript

DURATION = 600.0


def _transcript(special: dict[int, str] | None = None):
    special = special or {}
    words: list[Word] = []
    for k in range(int(DURATION // 4)):
        t0 = k * 4.0
        text = special.get(k, "we keep talking about general things here.")
        toks = text.split()
        step = 3.4 / len(toks)
        words += [Word(t0 + i * step, t0 + (i + 1) * step, tok) for i, tok in enumerate(toks)]
    events = [Event(315.0, "laughter", 1.0, "Laughter"), Event(318.0, "laughter", 1.0, "Laughter")]
    return make_transcript(words, events, "captions")


def _heatmap(peak_start: float, peak_end: float):
    return [(s, s + 6, 1.0 if peak_start <= s < peak_end else 0.2) for s in np.arange(0, DURATION, 6)]


def _overlap(a, b):
    return min(a.end, b.end) - max(a.start, b.start)


def test_top_clip_finds_peak_and_respects_preset():
    sig = SourceSignals(duration=DURATION, transcript=_transcript(), heatmap=_heatmap(300, 336))
    spec = resolve_preset("shorts")
    res = score_source(sig, spec, ScoringWeights(), limit=5)
    assert res.clips, res.warnings
    top = res.clips[0]
    assert top.start <= 318 <= top.end
    for c in res.clips:
        assert spec.min_len - 1 <= c.end - c.start <= spec.max_len + 1
    for i, a in enumerate(res.clips):
        for b in res.clips[i + 1 :]:
            assert _overlap(a, b) <= 0.2 * min(a.end - a.start, b.end - b.start) + 1.0
    texts = " ".join(r.text for r in top.reasons)
    assert "Replayed more than" in texts and "laughter" in texts.lower()
    assert sum(b.contribution for b in top.breakdown) == pytest.approx(top.score, abs=1.0)


def test_sponsor_segment_penalised():
    sig = SourceSignals(
        duration=DURATION,
        transcript=_transcript(),
        heatmap=_heatmap(300, 336),
        sponsor_segments=[(290.0, 350.0, "sponsor")],
    )
    res = score_source(sig, resolve_preset("shorts"), ScoringWeights(), limit=3)
    assert not (res.clips[0].start <= 318 <= res.clips[0].end) or any(r.signal == "excluded" for r in res.clips[0].reasons)
    assert res.clips[0].score < 80


def test_focus_query_steers_selection():
    special = {k: "the secret to saas pricing is charging more." for k in range(100, 106)}
    sig = SourceSignals(duration=DURATION, transcript=_transcript(special))
    res = score_source(sig, resolve_preset("shorts"), ScoringWeights(), query_weights("pricing"), limit=3)
    top = res.clips[0]
    assert top.start <= 410 and top.end >= 400
    assert any(r.signal == "relevance" for r in top.reasons)
    assert "pricing" in top.title.lower()


def test_audio_only_without_transcript():
    hop = 0.5
    db = np.full(int(DURATION / hop), -30.0)
    db[::40] = -60.0  # periodic pauses
    db[int(200 / hop) : int(230 / hop)] = -10.0  # loud stretch
    sig = SourceSignals(duration=DURATION, audio_db=db, audio_hop=hop, scene_cuts=[10.0, 50.0, 90.0, 205.0])
    res = score_source(sig, resolve_preset("shorts"), ScoringWeights(), limit=3)
    assert res.clips
    assert _overlap(res.clips[0], type("W", (), {"start": 200, "end": 230})()) > 10
    assert res.clips[0].title.startswith("Moment")


def test_short_video_yields_warning():
    sig = SourceSignals(duration=10.0, audio_db=np.linspace(-40, -10, 20))
    res = score_source(sig, resolve_preset("standard"), ScoringWeights(), limit=3)
    assert not res.clips and res.warnings


def test_timeline_downsampled():
    sig = SourceSignals(duration=DURATION, transcript=_transcript(), heatmap=_heatmap(300, 336))
    res = score_source(sig, resolve_preset("standard"), ScoringWeights(), limit=3)
    assert len(res.timeline.series["composite"]) <= 720
    assert "heatmap" in res.timeline.series
