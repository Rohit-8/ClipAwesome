from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["deterministic", "ai"]
PresetName = Literal["shorts", "standard", "long", "custom"]
Polarity = Literal["pos", "neg", "info"]


class AnalyzeOptions(BaseModel):
    mode: Mode | None = None
    preset: PresetName | None = None
    min_len: float | None = Field(None, ge=0, le=1_000_000)
    max_len: float | None = Field(None, ge=0, le=1_000_000)
    query: str | None = Field(None, max_length=300)
    max_clips: int | None = Field(None, ge=1, le=30)
    include_comments: bool | None = None


class YouTubeRequest(AnalyzeOptions):
    url: str = Field(..., min_length=5, max_length=500)


class LocalPathRequest(AnalyzeOptions):
    path: str = Field(..., min_length=3, max_length=1000)
    subtitle_path: str | None = Field(None, max_length=1000)


class DiscoverRequest(AnalyzeOptions):
    topic: str = Field(..., min_length=2, max_length=200)
    search_limit: int = Field(15, ge=3, le=50)
    analyze_top: int = Field(3, ge=1, le=8)
    min_duration: float = Field(180, ge=0)
    max_duration: float = Field(7200, ge=60)
    creative_commons: bool = False


class Reason(BaseModel):
    text: str
    signal: str
    polarity: Polarity = "pos"


class Contribution(BaseModel):
    signal: str
    label: str
    value: float
    weight: float
    contribution: float


class ClipSuggestion(BaseModel):
    id: str
    rank: int = 0
    source_id: str
    start: float
    end: float
    duration: float
    score: float
    engine_score: float
    ai_score: float | None = None
    title: str
    hook: str | None = None
    transcript: str = ""
    chapter: str | None = None
    tags: list[str] = []
    reasons: list[Reason] = []
    breakdown: list[Contribution] = []
    review: Literal["approved", "rejected"] | None = None


class Chapter(BaseModel):
    start: float
    end: float
    title: str


class SourceVideo(BaseModel):
    id: str
    platform: Literal["youtube", "local"]
    video_id: str | None = None
    url: str | None = None
    title: str
    channel: str | None = None
    duration: float
    thumbnail: str | None = None
    view_count: int | None = None
    upload_date: str | None = None
    media_id: str | None = None
    media_kind: Literal["video", "audio"] | None = None
    audio_codec: str | None = None
    transcript_source: str | None = None
    language: str | None = None
    signals: list[str] = []
    chapters: list[Chapter] = []
    relevance: float | None = None


class Timeline(BaseModel):
    bin_sec: float
    series: dict[str, list[float]] = {}
    markers: dict[str, list[dict]] = {}


class TranscriptLine(BaseModel):
    start: float
    end: float
    text: str


class SearchResult(BaseModel):
    video_id: str
    url: str
    title: str
    channel: str | None = None
    duration: float | None = None
    view_count: int | None = None
    thumbnail: str | None = None
    description: str | None = None
    relevance: float = 0.0
    analyzed: bool = False


class Analysis(BaseModel):
    id: str
    kind: Literal["youtube", "local", "discover"]
    mode: Mode
    preset: str
    min_len: float
    max_len: float
    query: str | None = None
    created_at: str
    elapsed_sec: float = 0.0
    title: str
    sources: list[SourceVideo] = []
    clips: list[ClipSuggestion] = []
    timelines: dict[str, Timeline] = {}
    transcripts: dict[str, list[TranscriptLine]] = {}
    other_results: list[SearchResult] = []
    warnings: list[str] = []


class AnalysisSummary(BaseModel):
    id: str
    kind: str
    mode: str
    title: str
    created_at: str
    thumbnail: str | None = None
    clip_count: int = 0
    top_score: float | None = None
    source_count: int = 1
    query: str | None = None


class JobStage(BaseModel):
    name: str
    at: str


class Job(BaseModel):
    id: str
    kind: str
    title: str = ""
    status: Literal["queued", "running", "done", "error", "interrupted"] = "queued"
    progress: float = 0.0
    stage: str = "Queued"
    stages: list[JobStage] = []
    error: str | None = None
    result_id: str | None = None
    created_at: str
    retryable: bool = False
