from __future__ import annotations

import json

import httpx

from .youtube import current_proxy

API = "https://sponsor.ajay.app/api/skipSegments"
CATEGORIES = ["sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "filler", "poi_highlight"]


def fetch_segments(video_id: str, timeout: float = 8.0) -> tuple[list[tuple[float, float, str]], list[float]]:
    """Returns (segments, highlight_times). An unknown video yields empty lists."""
    resp = httpx.get(
        API,
        params={"videoID": video_id, "categories": json.dumps(CATEGORIES)},
        timeout=timeout,
        headers={"User-Agent": "ClipAwesome/0.1"},
        proxy=current_proxy(),
    )
    if resp.status_code == 404:
        return [], []
    resp.raise_for_status()
    segments: list[tuple[float, float, str]] = []
    highlights: list[float] = []
    for item in resp.json():
        cat = item.get("category")
        seg = item.get("segment") or [0, 0]
        if cat == "poi_highlight":
            highlights.append(float(seg[0]))
        elif cat:
            segments.append((float(seg[0]), float(seg[1]), cat))
    return segments, highlights
