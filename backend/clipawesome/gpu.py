"""Hardware H.264 encoders (NVIDIA NVENC, Intel Quick Sync, AMD AMF): detection by a real test encode, and encoder arguments."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("clipawesome.gpu")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CPU_CRF = {"high": 18, "balanced": 23, "small": 28}
# Chosen so size and SSIM roughly match the x264 CRF values above (measured with Quick Sync).
GPU_QUALITY = {"high": 19, "balanced": 24, "small": 30}

_GPU_ARGS: dict[str, Callable[[str], list[str]]] = {
    "h264_nvenc": lambda q: ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", q, "-b:v", "0", "-pix_fmt", "yuv420p"],
    "h264_qsv": lambda q: ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", q, "-pix_fmt", "nv12"],
    "h264_amf": lambda q: ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", q, "-qp_p", q, "-pix_fmt", "nv12"],
}


@dataclass(frozen=True)
class Encoder:
    codec: str
    name: str


CANDIDATES = (
    Encoder("h264_nvenc", "NVIDIA NVENC"),
    Encoder("h264_qsv", "Intel Quick Sync"),
    Encoder("h264_amf", "AMD AMF"),
)


@dataclass
class Report:
    encoder: Encoder | None
    tried: list[dict[str, object]] = field(default_factory=list)


def video_args(quality: str, codec: str | None = None) -> list[str]:
    if codec is None:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(CPU_CRF[quality]), "-pix_fmt", "yuv420p"]
    return _GPU_ARGS[codec](str(GPU_QUALITY[quality]))


def _compiled(ffmpeg: str) -> set[str]:
    done = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
    return {parts[1] for line in done.stdout.splitlines() if len(parts := line.split()) > 1}


def _test(ffmpeg: str, enc: Encoder) -> str | None:
    """None when a short test encode succeeds, otherwise the reason it failed."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=1",
           "-frames:v", "15", *video_args("balanced", enc.codec), "-f", "null", "-"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as err:
        return type(err).__name__
    if done.returncode == 0:
        return None
    lines = done.stderr.strip().splitlines()
    # The first line names the cause (e.g. "Cannot load nvcuda.dll"); later ones are generic follow-ups.
    return (re.sub(r"^\[[^\]]*\]\s*", "", lines[0]) if lines else f"exit code {done.returncode}")[:200]


_cache: dict[str, Report] = {}
_lock = threading.Lock()


def detect(ffmpeg: str, refresh: bool = False) -> Report:
    """First GPU encoder that really works on this machine (cached per FFmpeg binary)."""
    with _lock:
        if not refresh and ffmpeg in _cache:
            return _cache[ffmpeg]
        try:
            compiled = _compiled(ffmpeg)
        except (OSError, subprocess.TimeoutExpired):
            compiled = set()
        report = Report(None)
        for enc in CANDIDATES:
            if enc.codec not in compiled:
                report.tried.append({"codec": enc.codec, "name": enc.name, "ok": False, "detail": "Not included in this FFmpeg build"})
                continue
            reason = _test(ffmpeg, enc)
            report.tried.append({"codec": enc.codec, "name": enc.name, "ok": reason is None, "detail": reason or "Test encode succeeded"})
            if reason is None:
                report.encoder = enc
                break
        log.info("GPU encoder: %s", report.encoder.name if report.encoder else "none usable, exports use the CPU")
        _cache[ffmpeg] = report
        return report
