"""Topic search (yt-dlp or YouTube Data API) and deterministic video ranking."""

from __future__ import annotations

import math
import re
from typing import Any

import httpx
import yt_dlp

from .. import text as tx
from ..models import SearchResult
from .youtube import SourceError, _clean_error, base_opts, current_proxy, parse_video_id, thumbnail_url, watch_url

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_ISO_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _iso_duration(value: str | None) -> float | None:
    m = _ISO_DUR.fullmatch(value or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def search_ytdlp(query: str, limit: int) -> list[dict[str, Any]]:
    opts = base_opts()
    opts["extract_flat"] = "in_playlist"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{int(limit)}:{query}", download=False)
    except yt_dlp.utils.DownloadError as err:
        raise SourceError(_clean_error(err)) from err
    out: list[dict[str, Any]] = []
    for e in info.get("entries") or []:
        vid = parse_video_id(e.get("id") or "")
        if not vid:
            continue
        out.append(
            {
                "video_id": vid,
                "title": e.get("title") or "",
                "channel": e.get("channel") or e.get("uploader"),
                "duration": e.get("duration"),
                "view_count": e.get("view_count"),
                "description": e.get("description"),
                "live_status": e.get("live_status"),
            }
        )
    return out


def _api_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = httpx.get(url, params=params, timeout=15, proxy=current_proxy())
    except httpx.HTTPError as err:
        raise SourceError(f"YouTube Data API unreachable: {type(err).__name__}") from err
    if resp.status_code != 200:
        # Never echo the request URL: it carries the API key.
        try:
            reason = resp.json()["error"]["message"]
        except Exception:
            reason = resp.reason_phrase
        raise SourceError(f"YouTube Data API error {resp.status_code}: {reason}")
    return resp.json()


def search_data_api(query: str, limit: int, api_key: str, creative_commons: bool = False) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max(1, min(50, int(limit))),
        "key": api_key,
    }
    if creative_commons:
        params["videoLicense"] = "creativeCommon"
    found = _api_get(SEARCH_URL, params)
    ids = [it["id"]["videoId"] for it in found.get("items", []) if it.get("id", {}).get("videoId")]
    if not ids:
        return []
    details = _api_get(VIDEOS_URL, {"part": "snippet,contentDetails,statistics", "id": ",".join(ids), "key": api_key})
    out: list[dict[str, Any]] = []
    for it in details.get("items", []):
        sn = it.get("snippet", {})
        out.append(
            {
                "video_id": it["id"],
                "title": sn.get("title") or "",
                "channel": sn.get("channelTitle"),
                "duration": _iso_duration(it.get("contentDetails", {}).get("duration")),
                "view_count": int(it.get("statistics", {}).get("viewCount") or 0),
                "description": sn.get("description"),
                "live_status": "is_live" if sn.get("liveBroadcastContent") in ("live", "upcoming") else None,
            }
        )
    order = {vid: i for i, vid in enumerate(ids)}
    return sorted(out, key=lambda r: order.get(r["video_id"], 999))


def rank_results(
    raw: list[dict[str, Any]], query: dict[str, float], min_duration: float, max_duration: float
) -> list[SearchResult]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for r in raw:
        if r["video_id"] in seen or r.get("live_status") in ("is_live", "is_upcoming"):
            continue
        dur = r.get("duration")
        if dur is not None and not (min_duration <= dur <= max_duration):
            continue
        seen.add(r["video_id"])
        kept.append(r)
    if not kept:
        return []
    docs = [tx.terms(f"{r['title']} {r['title']} {(r.get('description') or '')[:500]}") for r in kept]
    text_scores = tx.BM25(docs).score(query)
    top = max(text_scores) or 1.0
    results: list[SearchResult] = []
    for r, ts in zip(kept, text_scores):
        views = r.get("view_count") or 0
        pop = min(1.0, math.log10(views + 1) / 7)
        dur = r.get("duration")
        fit = 1.0 if dur and 300 <= dur <= 3600 else 0.7
        relevance = 0.6 * (ts / top) + 0.25 * pop + 0.15 * fit
        results.append(
            SearchResult(
                video_id=r["video_id"],
                url=watch_url(r["video_id"]),
                title=r["title"],
                channel=r.get("channel"),
                duration=dur,
                view_count=views or None,
                thumbnail=thumbnail_url(r["video_id"]),
                description=tx.shorten(r.get("description") or "", 240) or None,
                relevance=round(relevance, 3),
            )
        )
    results.sort(key=lambda s: s.relevance, reverse=True)
    return results
