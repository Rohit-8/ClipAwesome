"""Prompts that let an LLM re-rank engine candidates, expand topics and rate search results."""

from __future__ import annotations

import json
from typing import Any

from ..models import ClipSuggestion, Reason, SearchResult, SourceVideo
from ..text import fmt_time, shorten
from .llm import LLMClient, LLMError

MAX_CANDIDATES = 18

SYSTEM_CLIPS = (
    "You are a senior short-form video editor for YouTube Shorts, TikTok and Reels. "
    "You choose moments that work as standalone clips: a hook in the first seconds, a complete thought or story, "
    "a surprising, funny, emotional or highly useful payoff, and no dependency on context outside the clip. "
    "You only choose from the candidates you are given and never invent timestamps. "
    "Respond with a single JSON object and nothing else."
)

SYSTEM_SEARCH = (
    "You help a video editor find YouTube videos and moments about a topic. "
    "Respond with a single JSON object and nothing else."
)


def _clean(value: Any, limit: int) -> str:
    return shorten(str(value or "").replace("\n", " ").strip().strip('"'), limit)


def rerank_clips(
    llm: LLMClient,
    source: SourceVideo,
    clips: list[ClipSuggestion],
    focus: str | None,
    limit: int,
    ai_weight: float,
) -> list[ClipSuggestion]:
    cands = clips[:MAX_CANDIDATES]
    if not cands:
        return []
    by_id = {f"c{i}": c for i, c in enumerate(cands, 1)}
    payload = [
        {
            "id": cid,
            "range": f"{fmt_time(c.start)}-{fmt_time(c.end)}",
            "duration_sec": round(c.duration),
            "engine_score": round(c.engine_score),
            "signals": [r.text for r in c.reasons if r.polarity != "neg"][:4],
            "transcript": shorten(c.transcript, 1200) or "(no transcript available)",
        }
        for cid, c in by_id.items()
    ]
    user = (
        f'Video: "{source.title}" by {source.channel or "unknown"} ({fmt_time(source.duration)}).\n'
        f"User focus: {focus or 'none - pick the most engaging, shareable moments'}.\n"
        f"Select up to {limit} of the best candidates for short clips and score each 0-100 "
        "(90+ = would likely go viral, 70 = solid, below 50 = weak).\n\n"
        f"Candidates:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        'Return: {"clips": [{"id": "c3", "score": 87, "title": "catchy title under 70 characters", '
        '"hook": "one-line on-screen hook", "reason": "one sentence on why it works as a clip", '
        '"tags": ["tag", "tag"]}]}\n'
        "Order best first. Use only ids from the list."
    )
    data = llm.chat_json(SYSTEM_CLIPS, user, max_tokens=max(1500, 260 * limit))
    picks = data.get("clips") if isinstance(data, dict) else data
    if not isinstance(picks, list):
        raise LLMError("AI response did not contain a clip list")

    out: list[ClipSuggestion] = []
    seen: set[str] = set()
    for p in picks:
        if not isinstance(p, dict):
            continue
        cid = str(p.get("id", "")).strip()
        base = by_id.get(cid)
        if base is None or cid in seen:
            continue
        seen.add(cid)
        try:
            ai_score = max(0.0, min(100.0, float(p.get("score", 0))))
        except (TypeError, ValueError):
            ai_score = 0.0
        clip = base.model_copy(deep=True)
        clip.ai_score = round(ai_score, 1)
        clip.score = round(ai_weight * ai_score + (1 - ai_weight) * base.engine_score, 1)
        if title := _clean(p.get("title"), 90):
            clip.title = title
        if hook := _clean(p.get("hook"), 160):
            clip.hook = hook
        if reason := _clean(p.get("reason"), 240):
            clip.reasons.insert(0, Reason(text=reason, signal="ai", polarity="pos"))
        tags = [_clean(t, 30).lstrip("#") for t in (p.get("tags") or []) if isinstance(t, str)]
        clip.tags = list(dict.fromkeys([t for t in tags if t] + clip.tags))[:6]
        out.append(clip)
        if len(out) >= limit:
            break
    if not out:
        raise LLMError("AI returned no usable clip selections")
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def expand_topic(llm: LLMClient, topic: str, want_queries: bool = True) -> tuple[list[str], list[str]]:
    ask = '"queries": ["up to 3 distinct YouTube search queries"], ' if want_queries else ""
    user = (
        f'Topic: "{topic}"\n'
        "Return JSON: {" + ask + '"keywords": ["10-15 single words or short phrases a speaker would say in a relevant moment, '
        'including synonyms and related terms"]}'
    )
    data = llm.chat_json(SYSTEM_SEARCH, user, max_tokens=800)
    if not isinstance(data, dict):
        return [], []
    queries = [_clean(q, 100) for q in data.get("queries") or [] if isinstance(q, str)][:3]
    keywords = [_clean(k, 40) for k in data.get("keywords") or [] if isinstance(k, str)][:20]
    return [q for q in queries if q], [k for k in keywords if k]


def rate_videos(llm: LLMClient, topic: str, results: list[SearchResult]) -> dict[str, float]:
    items = [
        {
            "id": r.video_id,
            "title": r.title,
            "channel": r.channel,
            "duration": fmt_time(r.duration or 0),
            "description": shorten(r.description or "", 200),
        }
        for r in results[:25]
    ]
    user = (
        f'Topic: "{topic}"\n'
        "Rate how likely each video contains strong, clippable moments specifically about this topic (0-10).\n"
        f"Videos: {json.dumps(items, ensure_ascii=False)}\n"
        'Return: {"ratings": [{"id": "...", "fit": 7}]}'
    )
    data = llm.chat_json(SYSTEM_SEARCH, user, max_tokens=1200)
    ratings = data.get("ratings") if isinstance(data, dict) else None
    out: dict[str, float] = {}
    for r in ratings or []:
        try:
            out[str(r["id"])] = max(0.0, min(10.0, float(r["fit"]))) / 10
        except (KeyError, TypeError, ValueError):
            continue
    return out
