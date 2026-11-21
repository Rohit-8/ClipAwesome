"""Burned-in captions: group transcript words into short on-screen phrases and write them as an ASS subtitle file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Style = Literal["bold", "classic", "boxed"]
Position = Literal["bottom", "center"]

Word = tuple[float, float, str]


@dataclass(frozen=True)
class Look:
    max_words: int
    max_chars: int
    max_sec: float
    size: float  # font size as a share of the frame's short side
    upper: bool
    box: bool


LOOKS: dict[str, Look] = {
    # Short, punchy phrases in big type: the usual Shorts / Reels look.
    "bold": Look(max_words=3, max_chars=18, max_sec=1.4, size=0.085, upper=True, box=False),
    "classic": Look(max_words=12, max_chars=42, max_sec=4.0, size=0.055, upper=False, box=False),
    "boxed": Look(max_words=12, max_chars=42, max_sec=4.0, size=0.055, upper=False, box=True),
}


def words_from_lines(lines: list[tuple[float, float, str]], start: float, end: float) -> list[Word]:
    """Spreads each transcript line's time across its words (captions from YouTube only carry line timings)."""
    words: list[Word] = []
    for ls, le, text in lines:
        if le <= start or ls >= end:
            continue
        tokens = text.split()
        if not tokens:
            continue
        weights = [len(t) + 2 for t in tokens]
        total, t = sum(weights), ls
        for token, w in zip(tokens, weights):
            dur = (le - ls) * w / total
            if t + dur > start and t < end:
                words.append((max(t, start) - start, min(t + dur, end) - start, token))
            t += dur
    return words


def clip_words(items: list[Word], start: float, end: float) -> list[Word]:
    return [(max(s, start) - start, min(e, end) - start, w.strip()) for s, e, w in items if e > start and s < end and w.strip()]


def group(words: list[Word], style: Style) -> list[Word]:
    look = LOOKS[style]
    groups: list[Word] = []
    cur: list[Word] = []

    def push() -> None:
        if cur:
            groups.append((cur[0][0], cur[-1][1], " ".join(w for _, _, w in cur)))
            cur.clear()

    for word in words:
        if cur:
            text = " ".join(w for _, _, w in cur) + " " + word[2]
            gap = word[0] - cur[-1][1]
            if len(cur) >= look.max_words or len(text) > look.max_chars or word[1] - cur[0][0] > look.max_sec or gap > 0.8:
                push()
        cur.append(word)
        if word[2].endswith((".", "?", "!")):
            push()
    push()
    # Hold each caption until the next one starts (short gaps) so the text doesn't flicker.
    out = []
    for i, (s, e, t) in enumerate(groups):
        nxt = groups[i + 1][0] if i + 1 < len(groups) else e + 0.6
        out.append((s, max(e, min(nxt, e + 0.6)), t))
    return out


def _ts(sec: float) -> str:
    cs = max(0, round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    return re.sub(r"[{}\\]", "", text).replace("\n", " ")


def ass(groups: list[Word], width: int, height: int, style: Style = "bold", position: Position = "bottom") -> str:
    look = LOOKS[style]
    short = min(width, height)
    size = max(12, round(short * look.size))
    outline = max(1, round(size * (0.06 if not look.box else 0.25)))
    # Portrait frames keep captions above the app buttons that Shorts/Reels/TikTok draw at the bottom.
    margin_v = round(height * (0.2 if height > width else 0.08))
    align = 5 if position == "center" else 2
    border_style = 3 if look.box else 1
    back = "&H80000000" if look.box else "&H64000000"
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,{back},-1,0,0,0,100,100,0,0,{border_style},{outline},"
        f"{0 if look.box else 2},{align},{round(width * 0.06)},{round(width * 0.06)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = [
        f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{_escape(t.upper() if look.upper else t)}"
        for s, e, t in groups
        if e > s
    ]
    return header + "\n".join(events) + "\n"
