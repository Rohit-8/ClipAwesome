"""Orchestrates sources → engine → (optional) AI for each kind of analysis."""

from __future__ import annotations

import math
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import text as tx
from .ai.llm import LLMClient, LLMError
from .ai.rerank import expand_topic, rate_videos, rerank_clips
from .config import Settings, data_path
from .engine.presets import LengthSpec, fit_to_duration, resolve_preset
from .engine.scoring import EngineClip, score_source
from .engine.signals import SourceSignals
from .models import (
    Analysis,
    AnalyzeOptions,
    Chapter,
    ClipSuggestion,
    DiscoverRequest,
    SourceVideo,
    Timeline,
    TranscriptLine,
)
from .sources import local_media, search, sponsorblock, transcribe, youtube
from .sources.youtube import SourceError
from .store import new_analysis_id
from .transcript import Transcript, from_timed_words, make_transcript, parse_subtitle_file

Progress = Callable[[str, float], None]


@dataclass
class Plan:
    mode: str
    spec: LengthSpec
    limit: int
    query: str | None
    include_comments: bool
    keywords: list[str] = field(default_factory=list)
    llm: LLMClient | None = None


@dataclass
class SourceResult:
    source: SourceVideo
    clips: list[ClipSuggestion]
    timeline: Timeline
    lines: list[TranscriptLine]
    spec: LengthSpec


def _scaled(progress: Progress, lo: float, hi: float) -> Progress:
    return lambda stage, f: progress(stage, lo + (hi - lo) * max(0.0, min(1.0, f)))


def make_plan(opts: AnalyzeOptions, settings: Settings, warnings: list[str]) -> Plan:
    youtube.configure_proxy(settings.proxy)
    mode = opts.mode or settings.default_mode
    llm = None
    if mode == "ai":
        try:
            llm = LLMClient(settings.ai)
        except LLMError as err:
            warnings.append(f"AI mode unavailable ({err}); using deterministic mode")
            mode = "deterministic"
    query = (opts.query or "").strip() or None
    return Plan(
        mode=mode,
        spec=resolve_preset(opts.preset or settings.default_preset, opts.min_len, opts.max_len, settings.default_preset),
        limit=opts.max_clips or settings.default_max_clips,
        query=query,
        include_comments=settings.include_comments if opts.include_comments is None else opts.include_comments,
        llm=llm,
    )


def _to_suggestion(c: EngineClip, source_id: str, idx: int) -> ClipSuggestion:
    return ClipSuggestion(
        id=f"{source_id}-c{idx}",
        source_id=source_id,
        start=c.start,
        end=c.end,
        duration=round(c.end - c.start, 2),
        score=c.score,
        engine_score=c.score,
        title=c.title,
        hook=c.hook,
        transcript=c.transcript,
        chapter=c.chapter,
        tags=c.tags,
        reasons=c.reasons,
        breakdown=c.breakdown,
    )


def run_engine(source: SourceVideo, sig: SourceSignals, plan: Plan, settings: Settings, warnings: list[str], focus: str | None = None) -> SourceResult:
    focus = focus if focus is not None else plan.query
    qweights = tx.query_weights(focus, plan.keywords)
    pool = max(plan.limit, 18) if plan.llm else plan.limit
    spec, note = fit_to_duration(plan.spec, sig.duration)
    if note:
        warnings.append(note)
    res = score_source(sig, spec, settings.weights, qweights, pool)
    warnings.extend(res.warnings)
    clips = [_to_suggestion(c, source.id, i) for i, c in enumerate(res.clips, 1)]
    if plan.llm and clips:
        try:
            clips = rerank_clips(plan.llm, source, clips, focus, plan.limit, settings.ai.ai_weight)
        except LLMError as err:
            warnings.append(f"AI re-ranking failed, showing deterministic ranking: {err}")
            clips = clips[: plan.limit]
    else:
        clips = clips[: plan.limit]
    source.signals = res.signals
    return SourceResult(source, clips, res.timeline, res.transcript_lines, spec)


def _whisper(path: Path, settings: Settings, duration: float, progress: Progress) -> Transcript:
    items, lang = transcribe.transcribe(
        path,
        model_size=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        duration=duration,
        progress=lambda f: progress("Transcribing speech (Whisper)", f),
    )
    words, events = from_timed_words(items)
    return make_transcript(words, events, "whisper", lang)


def youtube_source(video_id: str, sid: str, plan: Plan, settings: Settings, progress: Progress, warnings: list[str]) -> tuple[SourceVideo, SourceSignals]:
    progress("Reading video metadata", 0.02)
    want_comments = plan.include_comments
    try:
        info = youtube.fetch_info(video_id, want_comments, settings.max_comments)
    except SourceError as err:
        if not want_comments:
            raise
        # Comment paging makes many requests; one blocked page fails the whole extraction.
        info = youtube.fetch_info(video_id)
        want_comments = False
        warnings.append(f"Comments skipped: {err}")
    duration = float(info.get("duration") or 0)
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise SourceError("Live or upcoming streams can't be analysed until the broadcast has ended")
    if duration <= 0:
        raise SourceError("Could not determine the video duration")

    title = info.get("title") or video_id
    chapters = [
        Chapter(start=float(c.get("start_time") or 0), end=float(c.get("end_time") or duration), title=c.get("title") or "")
        for c in info.get("chapters") or []
    ]
    heatmap = youtube.heatmap_of(info)
    if not heatmap:
        warnings.append("No 'Most replayed' data for this video (new or low-view videos don't have it)")

    progress("Fetching captions", 0.25)
    transcript: Transcript | None = None
    track = youtube.pick_caption(info, settings.caption_languages)
    if track:
        try:
            words, events = parse_subtitle_file(youtube.fetch_caption(track), track.ext)
            if words:
                transcript = make_transcript(words, events, track.kind, track.lang)
        except SourceError as err:
            warnings.append(f"Captions could not be downloaded: {err}")
    else:
        warnings.append("This video has no captions")

    progress("Checking SponsorBlock", 0.35)
    segments: list[tuple[float, float, str]] = []
    highlights: list[float] = []
    try:
        segments, highlights = sponsorblock.fetch_segments(video_id)
    except Exception as err:
        warnings.append(f"SponsorBlock unavailable ({type(err).__name__})")

    comments = info.get("comments") or []
    marks = youtube.comment_marks(comments, duration)
    if want_comments and not comments:
        warnings.append("No comments were available to mine for timestamps")

    audio_db = None
    need_audio = settings.youtube_audio == "always" or (settings.youtube_audio == "when_needed" and transcript is None)
    if need_audio:
        tmp = data_path("tmp", uuid.uuid4().hex)
        try:
            progress("Downloading audio for analysis", 0.4)
            path = youtube.download_audio(video_id, tmp, lambda f: progress("Downloading audio for analysis", 0.4 + 0.15 * f))
            progress("Measuring audio energy", 0.56)
            audio_db = local_media.loudness(path, duration=duration, progress=lambda f: progress("Measuring audio energy", 0.56 + 0.1 * f))
            if transcript is None:
                if transcribe.available():
                    transcript = _whisper(path, settings, duration, _scaled(progress, 0.66, 0.9))
                else:
                    warnings.append("Install the 'transcribe' extra (faster-whisper) to transcribe videos without captions")
        except Exception as err:
            warnings.append(f"Audio analysis skipped: {err}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    source = SourceVideo(
        id=sid,
        platform="youtube",
        video_id=video_id,
        url=youtube.watch_url(video_id),
        title=title,
        channel=info.get("channel") or info.get("uploader"),
        duration=duration,
        thumbnail=youtube.thumbnail_url(video_id),
        view_count=info.get("view_count"),
        upload_date=info.get("upload_date"),
        transcript_source=transcript.source if transcript else None,
        language=(transcript.language if transcript else None) or info.get("language"),
        chapters=chapters,
    )
    sig = SourceSignals(
        duration=duration,
        transcript=transcript,
        heatmap=heatmap,
        audio_db=audio_db,
        comment_marks=marks,
        comments_scanned=len(comments),
        sponsor_segments=segments,
        highlights=highlights,
        chapters=chapters,
    )
    return source, sig


def _analysis(
    kind: str,
    plan: Plan,
    title: str,
    started: float,
    results: list[SourceResult],
    clips: list[ClipSuggestion],
    warnings: list[str],
    query: str | None,
    spec: LengthSpec | None = None,
) -> Analysis:
    spec = spec or plan.spec
    for rank, c in enumerate(clips, 1):
        c.rank = rank
    return Analysis(
        id=new_analysis_id(),
        kind=kind,  # type: ignore[arg-type]
        mode=plan.mode,  # type: ignore[arg-type]
        preset=spec.name,
        min_len=round(spec.min_len, 2),
        max_len=round(spec.max_len, 2),
        query=query,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        elapsed_sec=round(time.perf_counter() - started, 1),
        title=title,
        sources=[r.source for r in results],
        clips=clips,
        timelines={r.source.id: r.timeline for r in results},
        transcripts={r.source.id: r.lines for r in results},
        warnings=list(dict.fromkeys(warnings)),
    )


def _expand_focus(plan: Plan, warnings: list[str]) -> None:
    if plan.llm and plan.query:
        try:
            _, plan.keywords = expand_topic(plan.llm, plan.query, want_queries=False)
        except LLMError as err:
            warnings.append(f"AI keyword expansion skipped: {err}")


def analyze_youtube(url: str, opts: AnalyzeOptions, settings: Settings, progress: Progress) -> Analysis:
    started = time.perf_counter()
    warnings: list[str] = []
    video_id = youtube.parse_video_id(url)
    if not video_id:
        raise ValueError("Not a valid YouTube video URL")
    plan = make_plan(opts, settings, warnings)
    _expand_focus(plan, warnings)
    source, sig = youtube_source(video_id, "s1", plan, settings, progress, warnings)
    progress("Scoring candidate clips", 0.9)
    result = run_engine(source, sig, plan, settings, warnings)
    return _analysis("youtube", plan, source.title, started, [result], result.clips, warnings, plan.query, result.spec)


def analyze_local(
    path: Path,
    display_name: str,
    media_id: str,
    subtitle: Path | None,
    opts: AnalyzeOptions,
    settings: Settings,
    progress: Progress,
) -> Analysis:
    started = time.perf_counter()
    warnings: list[str] = []
    plan = make_plan(opts, settings, warnings)
    _expand_focus(plan, warnings)

    progress("Reading media file", 0.02)
    info = local_media.probe(path)
    if info.duration <= 0:
        raise SourceError("Could not determine the media duration")
    if not info.has_audio and not info.has_video:
        raise SourceError("The file has no audio or video streams")

    transcript: Transcript | None = None
    if subtitle is not None:
        try:
            words, events = parse_subtitle_file(subtitle.read_text(encoding="utf-8", errors="replace"), subtitle.suffix)
            if words:
                transcript = make_transcript(words, events, "subtitles")
        except Exception as err:
            warnings.append(f"Subtitle file could not be parsed: {err}")

    audio_db = None
    if info.has_audio:
        progress("Measuring audio energy", 0.05)
        audio_db = local_media.loudness(path, duration=info.duration, progress=lambda f: progress("Measuring audio energy", 0.05 + 0.15 * f))
    else:
        warnings.append("No audio track: speech and energy signals are unavailable")

    cuts: list[float] | None = None
    if info.has_video and settings.visual_analysis != "off":
        progress("Detecting scene cuts", 0.2)
        try:
            cuts = local_media.scene_cuts(
                path, settings.visual_analysis, info.duration, lambda f: progress("Detecting scene cuts", 0.2 + 0.15 * f)
            )
        except Exception as err:
            warnings.append(f"Scene detection skipped: {err}")

    if transcript is None and info.has_audio:
        if transcribe.available():
            progress("Transcribing speech (Whisper)", 0.35)
            try:
                transcript = _whisper(path, settings, info.duration, _scaled(progress, 0.35, 0.9))
            except Exception as err:
                warnings.append(f"Transcription failed: {err}")
        else:
            warnings.append("No transcript: add a subtitle file or install the 'transcribe' extra (faster-whisper)")

    source = SourceVideo(
        id="s1",
        platform="local",
        title=display_name,
        duration=info.duration,
        media_id=media_id,
        media_kind="video" if info.has_video else "audio",
        audio_codec=info.audio_codec,
        transcript_source=transcript.source if transcript else None,
        language=transcript.language if transcript else None,
    )
    sig = SourceSignals(duration=info.duration, transcript=transcript, audio_db=audio_db, scene_cuts=cuts)
    progress("Scoring candidate clips", 0.92)
    result = run_engine(source, sig, plan, settings, warnings)
    return _analysis("local", plan, display_name, started, [result], result.clips, warnings, plan.query, result.spec)


def discover(req: DiscoverRequest, settings: Settings, progress: Progress) -> Analysis:
    started = time.perf_counter()
    warnings: list[str] = []
    plan = make_plan(req, settings, warnings)
    topic = req.topic.strip()

    queries = [topic]
    if plan.llm:
        progress("Expanding topic with AI", 0.02)
        try:
            extra, plan.keywords = expand_topic(plan.llm, topic)
            queries += [q for q in extra if q.lower() != topic.lower()]
        except LLMError as err:
            warnings.append(f"AI topic expansion skipped: {err}")

    progress("Searching YouTube", 0.05)
    raw: list[dict] = []
    per_query = max(5, math.ceil(req.search_limit / len(queries)))
    for q in queries:
        try:
            if settings.youtube_api_key:
                raw += search.search_data_api(q, per_query, settings.youtube_api_key, req.creative_commons)
            else:
                raw += search.search_ytdlp(q, per_query)
        except SourceError as err:
            warnings.append(f"Search for '{q}' failed: {err}")
    if req.creative_commons and not settings.youtube_api_key:
        warnings.append("Creative-Commons filter needs a YouTube Data API key; it was not applied")

    ranked = search.rank_results(raw, tx.query_weights(topic, plan.keywords), req.min_duration, req.max_duration)
    if not ranked:
        raise SourceError("No suitable videos found. Try a broader topic or widen the duration range.")

    if plan.llm:
        progress("Rating videos with AI", 0.1)
        try:
            fits = rate_videos(plan.llm, topic, ranked)
            for r in ranked:
                if r.video_id in fits:
                    r.relevance = round(0.5 * r.relevance + 0.5 * fits[r.video_id], 3)
            ranked.sort(key=lambda r: r.relevance, reverse=True)
        except LLMError as err:
            warnings.append(f"AI video rating skipped: {err}")

    targets = ranked[: req.analyze_top]
    results: list[SourceResult] = []
    errors: list[str] = []
    span = 0.85 / len(targets)
    for idx, cand in enumerate(targets):
        lo = 0.12 + idx * span
        sub = _scaled(progress, lo, lo + span)
        label = tx.shorten(cand.title, 48)
        local_warnings: list[str] = []
        try:
            source, sig = youtube_source(
                cand.video_id, f"s{idx + 1}", plan, settings, lambda stage, f: sub(f"[{idx + 1}/{len(targets)}] {label} · {stage}", f), local_warnings
            )
            source.relevance = cand.relevance
            result = run_engine(source, sig, plan, settings, local_warnings, focus=topic)
            results.append(result)
            cand.analyzed = True
        except Exception as err:
            local_warnings.append(f"skipped: {err}")
            errors.append(str(err))
        warnings.extend(f"{label} — {w}" for w in local_warnings)
    if not results:
        # Warnings are lost when the job fails, so surface the reason directly.
        raise SourceError(f"None of the top videos could be analysed. {errors[-1] if errors else ''}".strip())

    merged: list[ClipSuggestion] = []
    for r in results:
        rel = r.source.relevance or 0.5
        for c in r.clips:
            c.score = round(c.score * (0.75 + 0.25 * rel), 1)
            merged.append(c)
    merged.sort(key=lambda c: c.score, reverse=True)
    merged = merged[: min(30, plan.limit * 2)]

    analysis = _analysis("discover", plan, f"Topic: {topic}", started, results, merged, warnings, topic)
    analysis.other_results = [r for r in ranked if not r.analyzed][:20]
    return analysis
