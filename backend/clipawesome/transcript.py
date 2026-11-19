"""Transcript parsing (YouTube json3, WebVTT, SRT, Whisper words) and sentence segmentation. Pure functions only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

TERMINAL = (".", "!", "?", "…")
_TRAILING_QUOTES = "\"')]»”’"

_SQUARE_TAG_RE = re.compile(r"\[\s*([^\[\]]{1,40}?)\s*\]")
_PAREN_TAG_RE = re.compile(r"\(\s*([a-zA-Z][a-zA-Z \-]{1,30}?)\s*\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_VTT_INLINE_RE = re.compile(r"<(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})>")
_TIME_LINE_RE = re.compile(r"([\d:.,]+)\s*-->\s*([\d:.,]+)")


@dataclass(slots=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class Event:
    t: float
    kind: str
    weight: float = 1.0
    label: str = ""


@dataclass(slots=True)
class Sentence:
    start: float
    end: float
    text: str
    n_words: int
    terminal: bool


@dataclass
class Transcript:
    words: list[Word]
    sentences: list[Sentence]
    events: list[Event] = field(default_factory=list)
    source: str = "unknown"
    language: str | None = None

    @property
    def has_speech(self) -> bool:
        return bool(self.sentences)


def _reaction(label: str) -> tuple[str, float] | None:
    low = label.lower()
    if "laugh" in low or "chuckl" in low or "giggl" in low:
        return "laughter", 1.0
    if "applau" in low or "clap" in low:
        return "applause", 0.9
    if "cheer" in low or "whoop" in low:
        return "cheering", 0.9
    if "gasp" in low:
        return "gasp", 0.6
    return None


def strip_tags(text: str, t: float, events: list[Event]) -> str:
    """Remove sound tags like [Music] / (laughs); reaction tags become events at time `t`."""

    def square(m: re.Match[str]) -> str:
        found = _reaction(m.group(1))
        if found:
            events.append(Event(t, found[0], found[1], m.group(1).strip()))
        return " "

    def paren(m: re.Match[str]) -> str:
        found = _reaction(m.group(1))
        if not found:
            return m.group(0)
        events.append(Event(t, found[0], found[1], m.group(1).strip()))
        return " "

    text = _HTML_TAG_RE.sub("", text)
    text = _SQUARE_TAG_RE.sub(square, text)
    return _PAREN_TAG_RE.sub(paren, text)


def _spread(text: str, start: float, end: float) -> list[Word]:
    toks = text.split()
    if not toks:
        return []
    dur = max(end - start, 0.05)
    total = sum(len(t) + 1 for t in toks)
    out: list[Word] = []
    t = start
    for tok in toks:
        d = dur * (len(tok) + 1) / total
        out.append(Word(t, t + d, tok))
        t += d
    return out


def _parse_ts(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def finalize_words(words: list[Word]) -> list[Word]:
    words = sorted((w for w in words if w.text.strip()), key=lambda w: w.start)
    out: list[Word] = []
    for w in words:
        if out and out[-1].text == w.text and abs(out[-1].start - w.start) < 0.05:
            continue
        out.append(Word(w.start, max(w.end, w.start + 0.05), w.text.strip()))
    for i in range(len(out) - 1):
        nxt = out[i + 1].start
        if out[i].end > nxt:
            out[i].end = max(nxt, out[i].start + 0.01)
    return out


def parse_json3(data: str | dict) -> tuple[list[Word], list[Event]]:
    doc = json.loads(data) if isinstance(data, str) else data
    words: list[Word] = []
    events: list[Event] = []
    for ev in doc.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = (ev.get("tStartMs") or 0) / 1000
        end_ev = t0 + (ev.get("dDurationMs") or 0) / 1000
        items = [(t0 + (s.get("tOffsetMs") or 0) / 1000, s.get("utf8") or "") for s in segs]
        items = [(t, txt) for t, txt in items if txt.strip()]
        for k, (t, txt) in enumerate(items):
            end = items[k + 1][0] if k + 1 < len(items) else max(end_ev, t + 0.3)
            clean = strip_tags(txt, t, events)
            words.extend(_spread(clean, t, end))
    return finalize_words(words), events


def parse_vtt(text: str) -> tuple[list[Word], list[Event]]:
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("\ufeff", ""))
    cues: list[tuple[float, float, list[str]]] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            m = _TIME_LINE_RE.search(line)
            if m:
                cues.append((_parse_ts(m.group(1)), _parse_ts(m.group(2).split()[0]), lines[i + 1 :]))
                break
    auto = any(_VTT_INLINE_RE.search(ln) for _, _, lines in cues for ln in lines)
    words: list[Word] = []
    events: list[Event] = []
    last_text = ""
    for start, end, lines in cues:
        if auto:
            # YouTube rolling captions: only lines carrying inline word timings are new speech.
            for ln in lines:
                if not _VTT_INLINE_RE.search(ln):
                    continue
                parts = _VTT_INLINE_RE.split(ln)
                times = [start] + [_parse_ts(p) for p in parts[1::2]]
                chunks = parts[0::2]
                for idx, chunk in enumerate(chunks):
                    t = times[idx]
                    t_end = times[idx + 1] if idx + 1 < len(times) else end
                    clean = strip_tags(chunk, t, events)
                    words.extend(_spread(clean, t, max(t_end, t + 0.05)))
        else:
            joined = " ".join(lines).strip()
            if not joined or joined == last_text:
                continue
            last_text = joined
            words.extend(_spread(strip_tags(joined, start, events), start, end))
    return finalize_words(words), events


def parse_srt(text: str) -> tuple[list[Word], list[Event]]:
    words: list[Word] = []
    events: list[Event] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("\ufeff", "")):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            m = _TIME_LINE_RE.search(line)
            if m:
                start, end = _parse_ts(m.group(1)), _parse_ts(m.group(2))
                joined = " ".join(lines[i + 1 :])
                words.extend(_spread(strip_tags(joined, start, events), start, end))
                break
    return finalize_words(words), events


def parse_subtitle_file(text: str, ext: str) -> tuple[list[Word], list[Event]]:
    ext = ext.lower().lstrip(".")
    if ext == "json3":
        return parse_json3(text)
    if ext == "srt":
        return parse_srt(text)
    return parse_vtt(text)


def from_timed_words(items: list[tuple[float, float, str]]) -> tuple[list[Word], list[Event]]:
    words: list[Word] = []
    events: list[Event] = []
    for start, end, txt in items:
        clean = strip_tags(txt, start, events).strip()
        if clean:
            words.append(Word(start, end, clean))
    return finalize_words(words), events


def _is_terminal(token: str) -> bool:
    return token.rstrip(_TRAILING_QUOTES).endswith(TERMINAL)


def build_sentences(words: list[Word]) -> list[Sentence]:
    if not words:
        return []
    punct_ratio = sum(_is_terminal(w.text) for w in words) / len(words)
    punctuated = punct_ratio >= 0.02
    pause, max_len = (0.6, 15.0) if punctuated else (0.45, 9.0)

    sentences: list[Sentence] = []
    cur: list[Word] = []

    def flush() -> None:
        if cur:
            text = " ".join(w.text for w in cur)
            sentences.append(Sentence(cur[0].start, cur[-1].end, text, len(cur), _is_terminal(cur[-1].text)))
            cur.clear()

    for w in words:
        if cur and (w.start - cur[-1].end >= pause or w.end - cur[0].start > max_len):
            flush()
        cur.append(w)
        if punctuated and _is_terminal(w.text) and len(cur) >= 2:
            flush()
    flush()
    return sentences


def make_transcript(words: list[Word], events: list[Event], source: str, language: str | None = None) -> Transcript:
    return Transcript(words=words, sentences=build_sentences(words), events=sorted(events, key=lambda e: e.t), source=source, language=language)
