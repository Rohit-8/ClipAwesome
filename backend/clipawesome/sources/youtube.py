"""YouTube access via yt-dlp: strict URL intake, metadata, captions, comments and temporary audio."""

from __future__ import annotations

import math
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from ..text import find_timestamps

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_PATTERNS = (
    re.compile(r"^(?:https?://)?(?:www\.|m\.|music\.)?youtube\.com/watch\?(?:[^#]*&)?v=([A-Za-z0-9_-]{11})(?:[&#].*)?$"),
    re.compile(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:[/?#].*)?$"),
    re.compile(r"^(?:https?://)?youtu\.be/([A-Za-z0-9_-]{11})(?:[/?#].*)?$"),
    re.compile(r"^(?:https?://)?(?:www\.)?youtube-nocookie\.com/embed/([A-Za-z0-9_-]{11})(?:[/?#].*)?$"),
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_proxy: str | None = None


class SourceError(RuntimeError):
    pass


def configure_proxy(url: str | None) -> None:
    global _proxy
    _proxy = (url or "").strip() or None


def current_proxy() -> str | None:
    return _proxy


def parse_video_id(value: str) -> str | None:
    value = (value or "").strip()
    if _ID_RE.match(value):
        return value
    for pat in _URL_PATTERNS:
        m = pat.match(value)
        if m:
            return m.group(1)
    return None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def js_runtime() -> str | None:
    if shutil.which("deno"):
        return "deno"
    if shutil.which("node"):
        return "node"
    return None


class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def base_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 3,
        "logger": _QuietLogger(),
    }
    if js_runtime() == "node":
        opts["js_runtimes"] = {"node": {}}
    if _proxy:
        opts["proxy"] = _proxy
    return opts


NETWORK_HINT = (
    "Could not connect to YouTube (the network may block it). "
    "If you are behind a firewall, set a proxy in Settings → Network."
)


def _clean_error(err: Exception) -> str:
    msg = _ANSI_RE.sub("", str(err)).replace("ERROR: ", "").strip()
    low = msg.lower()
    if any(k in low for k in ("handshake", "ssl", "timed out", "getaddrinfo", "connection refused", "connection reset")):
        return NETWORK_HINT
    msg = re.sub(r"^\[youtube\]\s*[A-Za-z0-9_-]{11}:\s*", "", msg)
    return msg.split("\n")[0][:300]


def check_reachable(timeout: float = 6.0) -> tuple[bool, str]:
    import httpx

    try:
        resp = httpx.get("https://www.youtube.com/generate_204", timeout=timeout, proxy=_proxy)
        return resp.status_code in (200, 204), f"YouTube reachable (HTTP {resp.status_code})"
    except httpx.HTTPError as err:
        return False, f"{NETWORK_HINT} ({type(err).__name__})"
    except (ImportError, RuntimeError, ValueError) as err:
        # Bad proxy URL or missing SOCKS support surface here, not as HTTPError.
        return False, f"Proxy error: {err}"


def fetch_info(video_id: str, include_comments: bool = False, max_comments: int = 0) -> dict[str, Any]:
    opts = base_opts()
    if include_comments and max_comments > 0:
        opts["getcomments"] = True
        opts["extractor_args"] = {"youtube": {"max_comments": [str(max_comments), "all", "0"], "comment_sort": ["top"]}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False)
            return ydl.sanitize_info(info)
    except yt_dlp.utils.DownloadError as err:
        raise SourceError(_clean_error(err)) from err


@dataclass
class CaptionTrack:
    url: str
    ext: str
    lang: str
    kind: str  # "captions" | "auto-captions"


def _best_format(formats: list[dict[str, Any]]) -> tuple[str, str] | None:
    for ext in ("json3", "vtt", "srv3"):
        for f in formats or []:
            if f.get("ext") == ext and f.get("url"):
                return f["url"], ("vtt" if ext == "srv3" else ext)
    return None


def pick_caption(info: dict[str, Any], prefer_langs: list[str]) -> CaptionTrack | None:
    subs = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    autos = info.get("automatic_captions") or {}
    orig = (info.get("language") or "").split("-")[0] or None
    langs = [lang for lang in [orig, *prefer_langs] if lang]

    for lang in langs:
        for key, formats in subs.items():
            if key == lang or key.startswith(lang + "-"):
                best = _best_format(formats)
                if best:
                    return CaptionTrack(best[0], best[1], key, "captions")
    for key, formats in subs.items():
        best = _best_format(formats)
        if best:
            return CaptionTrack(best[0], best[1], key, "captions")

    order: list[str] = []
    for lang in langs:
        order += [f"{lang}-orig", lang]
    order += [k for k in autos if k.endswith("-orig")]
    for key in order:
        if key in autos:
            best = _best_format(autos[key])
            if best:
                return CaptionTrack(best[0], best[1], key.removesuffix("-orig"), "auto-captions")
    return None


def fetch_caption(track: CaptionTrack) -> str:
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            return ydl.urlopen(track.url).read().decode("utf-8", errors="replace")
    except Exception as err:
        raise SourceError(_clean_error(err)) from err


def comment_marks(comments: list[dict[str, Any]], duration: float) -> list[tuple[float, float, str]]:
    marks: list[tuple[float, float, str]] = []
    for c in comments or []:
        text = c.get("text") or ""
        stamps = sorted(set(find_timestamps(text)))
        if not stamps:
            continue
        weight = 1 + math.log1p(max(0, int(c.get("like_count") or 0)))
        if len(stamps) > 3:
            weight *= 0.3  # timestamp lists / chapter comments are weak evidence per moment
        if c.get("author_is_uploader"):
            weight *= 0.5
        for t in stamps:
            if 0 <= t < duration:
                marks.append((float(t), weight, text))
    return marks


def heatmap_of(info: dict[str, Any]) -> list[tuple[float, float, float]] | None:
    raw = info.get("heatmap") or []
    out = [(float(h["start_time"]), float(h["end_time"]), float(h["value"])) for h in raw if "start_time" in h and "value" in h]
    return out or None


def download_audio(video_id: str, dest: Path, progress: Callable[[float], None] | None = None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)

    def hook(d: dict[str, Any]) -> None:
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, (d.get("downloaded_bytes") or 0) / total))

    opts = base_opts()
    opts.update(
        {
            "skip_download": False,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(dest / "%(id)s.%(ext)s"),
            "progress_hooks": [hook],
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=True)
            downloads = info.get("requested_downloads") or []
            path = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as err:
        raise SourceError(_clean_error(err)) from err
    if not path.exists():
        raise SourceError("Audio download finished but the file was not found")
    return path
