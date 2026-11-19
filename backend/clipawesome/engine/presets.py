from __future__ import annotations

from dataclasses import dataclass, replace

from ..text import fmt_time

PRESETS: dict[str, tuple[float, float, float]] = {
    "shorts": (15.0, 35.0, 60.0),
    "standard": (30.0, 55.0, 90.0),
    "long": (60.0, 110.0, 180.0),
}

MIN_GAP = 5.0


@dataclass(frozen=True)
class LengthSpec:
    name: str
    min_len: float
    target: float
    max_len: float


def resolve_preset(name: str | None, min_len: float | None = None, max_len: float | None = None, default: str = "standard") -> LengthSpec:
    if name == "custom" and min_len is not None and max_len is not None:
        # Invalid ranges are snapped to the nearest valid one instead of being rejected.
        lo, hi = sorted((max(0.0, float(min_len)), max(0.0, float(max_len))))
        if hi - lo < MIN_GAP:
            hi = lo + MIN_GAP
        return LengthSpec("custom", lo, (lo + hi) / 2, hi)
    key = name if name in PRESETS else default
    lo, target, hi = PRESETS[key]
    return LengthSpec(key, lo, target, hi)


def fit_to_duration(spec: LengthSpec, duration: float) -> tuple[LengthSpec, str | None]:
    """Clamp a length range to the video so a too-long request falls back to the nearest feasible range."""
    if duration <= 0 or spec.max_len <= duration:
        return spec, None
    hi = duration
    lo = min(spec.min_len, max(0.0, hi - MIN_GAP))
    target = min(max(spec.target, lo), hi) if spec.name != "custom" else (lo + hi) / 2
    note = (
        f"Clip length {fmt_time(spec.min_len)}–{fmt_time(spec.max_len)} is longer than this "
        f"{fmt_time(duration)} video; used the nearest range {fmt_time(lo)}–{fmt_time(hi)}"
    )
    return replace(spec, min_len=lo, target=target, max_len=hi), note
