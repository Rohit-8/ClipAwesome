from __future__ import annotations

from dataclasses import dataclass

PRESETS: dict[str, tuple[float, float, float]] = {
    "shorts": (15.0, 35.0, 60.0),
    "standard": (30.0, 55.0, 90.0),
    "long": (60.0, 110.0, 180.0),
}


@dataclass(frozen=True)
class LengthSpec:
    name: str
    min_len: float
    target: float
    max_len: float


def resolve_preset(name: str | None, min_len: float | None = None, max_len: float | None = None, default: str = "standard") -> LengthSpec:
    if name == "custom" and min_len and max_len:
        lo, hi = sorted((float(min_len), float(max_len)))
        if hi - lo < 5:
            hi = lo + 5
        return LengthSpec("custom", lo, (lo + hi) / 2, hi)
    key = name if name in PRESETS else default
    lo, target, hi = PRESETS[key]
    return LengthSpec(key, lo, target, hi)
