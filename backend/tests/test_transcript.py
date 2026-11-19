import json

from clipawesome.transcript import build_sentences, from_timed_words, make_transcript, parse_json3, parse_srt, parse_vtt

JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 4000, "segs": [{"utf8": "hello"}, {"utf8": " everyone", "tOffsetMs": 500}]},
        {"tStartMs": 2000, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 4000, "dDurationMs": 3000, "segs": [{"utf8": "[Laughter]"}]},
        {"tStartMs": 7000, "dDurationMs": 3000, "segs": [{"utf8": "this"}, {"utf8": " is", "tOffsetMs": 300}, {"utf8": " great", "tOffsetMs": 600}]},
    ]
}

AUTO_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
hello<00:00:00.500><c> world</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hello world

00:00:02.010 --> 00:00:04.000 align:start position:0%
hello world
again<00:00:02.800><c> friends</c>
"""

MANUAL_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
<i>First line.</i>

00:00:03.000 --> 00:00:05.000
(laughs) Second line!
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
What is going on?

2
00:00:02,500 --> 00:00:05,000
[Applause] Thank you all.
"""


def test_json3_words_and_reactions():
    words, events = parse_json3(json.dumps(JSON3))
    assert [w.text for w in words] == ["hello", "everyone", "this", "is", "great"]
    assert words[1].start == 0.5
    assert events and events[0].kind == "laughter" and events[0].t == 4.0


def test_auto_vtt_dedupes_rolling_lines():
    words, _ = parse_vtt(AUTO_VTT)
    assert [w.text for w in words] == ["hello", "world", "again", "friends"]
    assert abs(words[1].start - 0.5) < 1e-6


def test_manual_vtt_and_paren_reaction():
    words, events = parse_vtt(MANUAL_VTT)
    assert " ".join(w.text for w in words) == "First line. Second line!"
    assert events[0].kind == "laughter"


def test_srt_and_sentences():
    words, events = parse_srt(SRT)
    tr = make_transcript(words, events, "subtitles")
    assert [s.text for s in tr.sentences] == ["What is going on?", "Thank you all."]
    assert all(s.terminal for s in tr.sentences)
    assert events[0].kind == "applause"


def test_unpunctuated_splits_on_pauses():
    items = [(i * 0.3, i * 0.3 + 0.25, "word") for i in range(10)] + [(5.0 + i * 0.3, 5.25 + i * 0.3, "next") for i in range(5)]
    words, _ = from_timed_words(items)
    sents = build_sentences(words)
    assert len(sents) == 2
    assert sents[1].text.startswith("next")
