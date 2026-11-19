"""Text utilities: tokenising, light stemming, BM25 and keyword extraction. Pure functions only."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping

_TOKEN_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?![\d:])")

STOPWORDS = frozenset(
    """a about above after again against all am an and any are aren't as at be because been before being
    below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
    during each few for from further gonna gotta got had hadn't has hasn't have haven't having he he'd he'll
    he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it
    it's its itself just let's like me more most mustn't my myself no nor not now of off on once only or
    other ought our ours ourselves out over own really right same shan't she she'd she'll she's should
    shouldn't so some such than that that's the their theirs them themselves then there there's these they
    they'd they'll they're they've this those through to too um uh under until up very was wasn't we we'd
    we'll we're we've were weren't what what's when when's where where's which while who who's whom why
    why's will with won't would wouldn't yeah yes you you'd you'll you're you've your yours yourself
    yourselves okay ok oh also actually going get know think thing things want say said lot kind sort mean
    well gonna wanna one two even still much many way something anything everything stuff guys guy""".split()
)

_SUFFIXES = ("ingly", "edly", "ings", "ing", "ies", "ied", "ers", "ed", "es", "ly", "er", "s")


def normalize(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def stem(word: str) -> str:
    w = word
    if len(w) > 4:
        for suf in _SUFFIXES:
            if suf == "s" and w.endswith("ss"):
                continue
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
                break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    if len(w) > 3 and w[-1] == w[-2] and w[-1].isalpha() and w[-1] not in "aeioulsz":
        w = w[:-1]
    return w


def words(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(normalize(text))]


def is_content_word(w: str) -> bool:
    return w not in STOPWORDS and (len(w) > 1 or w.isdigit())


def terms(text: str) -> list[str]:
    return [stem(w) for w in words(text) if is_content_word(w)]


def query_weights(query: str | None, extra_keywords: Iterable[str] = ()) -> dict[str, float]:
    """Query terms weigh 1.0; AI-provided synonyms weigh 0.6."""
    weights: dict[str, float] = {}
    for kw in extra_keywords:
        for t in terms(kw):
            weights[t] = max(weights.get(t, 0.0), 0.6)
    for t in terms(query or ""):
        weights[t] = 1.0
    return weights


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        n = len(docs)
        self.avgdl = (sum(self.lens) / n) if n else 0.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        self.df = df
        self.n = n
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query: Mapping[str, float]) -> list[float]:
        if not query or not self.n:
            return [0.0] * self.n
        out: list[float] = []
        avgdl = self.avgdl or 1.0
        for tf, dl in zip(self.tfs, self.lens):
            s = 0.0
            for t, qw in query.items():
                f = tf.get(t)
                if f:
                    s += qw * self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avgdl))
            out.append(s)
        return out


def top_keywords(text: str, doc_freq: Mapping[str, int], n_docs: int, limit: int = 3) -> list[str]:
    """Most distinctive surface words of `text` relative to a document collection (TF-IDF)."""
    surface: dict[str, Counter[str]] = {}
    tf: Counter[str] = Counter()
    for w in words(text):
        if not is_content_word(w) or len(w) < 3 or w.isdigit():
            continue
        s = stem(w)
        tf[s] += 1
        surface.setdefault(s, Counter())[w] += 1
    scored = sorted(
        tf.items(),
        key=lambda kv: kv[1] * math.log(1 + n_docs / (1 + doc_freq.get(kv[0], 0))),
        reverse=True,
    )
    return [surface[s].most_common(1)[0][0] for s, _ in scored[:limit]]


def matched_terms(text: str, query: Mapping[str, float]) -> Counter[str]:
    """Surface words in `text` whose stem is a query term, with counts."""
    found: Counter[str] = Counter()
    for w in words(text):
        if stem(w) in query and is_content_word(w):
            found[w] += 1
    return found


def find_timestamps(text: str) -> list[float]:
    out: list[float] = []
    for m in _TS_RE.finditer(text):
        h = int(m.group(1)) if m.group(1) else 0
        out.append(h * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    return out


def fmt_time(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-") + "…"
