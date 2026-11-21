import pytest

from clipawesome.sources import youtube
from clipawesome.sources.youtube import BOT_CHECK_HINT, _clean_error, comment_marks, parse_video_id, pick_caption, retry_blocked

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        VID,
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?feature=share&v={VID}&t=42s",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}?feature=share",
        f"https://www.youtube.com/embed/{VID}",
        f"youtube.com/watch?v={VID}",
    ],
)
def test_parse_video_id_accepts(url):
    assert parse_video_id(url) == VID


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PL123",
        "file:///etc/passwd",
        "not a url",
        "",
    ],
)
def test_parse_video_id_rejects(url):
    assert parse_video_id(url) is None


def test_comment_marks_weights_and_bounds():
    comments = [
        {"text": "3:15 had me dying", "like_count": 120},
        {"text": "0:10 1:00 2:00 3:00 4:00 chapters", "like_count": 5},
        {"text": "99:00 out of range"},
        {"text": "no timestamps"},
    ]
    marks = comment_marks(comments, duration=300)
    times = [t for t, _, _ in marks]
    assert 195 in times and 5940 not in times
    strong = next(w for t, w, _ in marks if t == 195)
    weak = next(w for t, w, _ in marks if t == 10)
    assert strong > weak


def test_pick_caption_prefers_manual_then_original_auto():
    track = lambda ext: [{"ext": ext, "url": f"https://x/{ext}"}]  # noqa: E731
    info = {"language": "en", "subtitles": {"live_chat": track("json"), "en": track("vtt")}, "automatic_captions": {"en-orig": track("json3")}}
    assert pick_caption(info, ["en"]).kind == "captions"
    info["subtitles"] = {}
    picked = pick_caption(info, ["en"])
    assert picked.kind == "auto-captions" and picked.ext == "json3" and picked.lang == "en"
    info["automatic_captions"] = {}
    assert pick_caption(info, ["en"]) is None


def _flaky(errors):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return "ok"

    return fn, calls


def test_retry_blocked_retries_bot_check_only_with_proxy(monkeypatch):
    bot = RuntimeError("Sign in to confirm you’re not a bot")
    monkeypatch.setattr(youtube, "_proxy", "socks5://p:1")
    fn, calls = _flaky([bot, RuntimeError("HTTP Error 429: Too Many Requests")])
    assert retry_blocked(fn) == "ok" and len(calls) == 3

    fn, calls = _flaky([RuntimeError("Video unavailable")])
    with pytest.raises(RuntimeError, match="unavailable"):
        retry_blocked(fn)
    assert len(calls) == 1

    monkeypatch.setattr(youtube, "_proxy", None)
    fn, calls = _flaky([bot])
    with pytest.raises(RuntimeError):
        retry_blocked(fn)
    assert len(calls) == 1


def test_clean_error_explains_bot_check():
    err = RuntimeError("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser")
    assert _clean_error(err) == BOT_CHECK_HINT
