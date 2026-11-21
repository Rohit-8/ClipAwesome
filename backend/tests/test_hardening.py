import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from clipawesome import captions as cap
from clipawesome import focus, system
from clipawesome.config import MASK, Settings, SettingsStore, mask_proxy, merge_proxy, public_settings
from clipawesome.sources.transcribe import RATE, Transcriber

GB = system.GB


def test_profile_recommendation_and_values():
    assert system.recommended(cpus=4, ram=16 * GB) == "low"
    assert system.recommended(cpus=8, ram=6 * GB) == "low"
    assert system.recommended(cpus=8, ram=32 * GB) == "balanced"
    assert system.recommended(cpus=16, ram=32 * GB) == "high"
    low, bal, high = (system.profile(n, cpus=8) for n in ("low", "balanced", "high"))
    assert (low.whisper_model, low.visual_analysis, low.heavy_slots, low.threads, low.focused_over_sec) == ("tiny", "off", 1, 4, 0)
    assert (bal.whisper_model, bal.x264_preset, bal.threads, bal.focused_over_sec) == (None, "veryfast", 7, 1800)
    assert (high.heavy_slots, high.x264_preset, high.focused_over_sec) == (2, "faster", None)
    assert system.configure("low").name == "low" and system.active().name == "low"
    system.configure("balanced")


def test_heavy_gate_runs_one_task_at_a_time_and_reports_waiting():
    gate = system.HeavyGate(1)
    order, waited = [], []

    def work(name):
        with gate.slot(lambda: waited.append(name)):
            order.append(f"{name}+")
            time.sleep(0.05)
            order.append(f"{name}-")

    first = threading.Thread(target=work, args=("a",))
    first.start()
    time.sleep(0.01)
    second = threading.Thread(target=work, args=("b",))
    second.start()
    first.join()
    second.join()
    assert order == ["a+", "a-", "b+", "b-"] and waited == ["b"]


def test_require_space_explains_the_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "free_bytes", lambda p: 600_000_000)
    system.require_space(tmp_path, 50_000_000, "this")
    with pytest.raises(ValueError, match=r"needs about 1\.0 GB but only 600\.0 MB is free"):
        system.require_space(tmp_path, 1_000_000_000, "this export", ValueError)


def test_focus_windows_follow_the_signals_and_budget():
    duration = 3600.0
    heat = [(i * 36.0, (i + 1) * 36.0, 1.0 if i == 50 else 0.05) for i in range(100)]
    windows = focus.pick_windows(duration, 60, heatmap=heat)
    assert focus.covered(windows) == pytest.approx(focus.budget_for(duration), abs=120)
    assert any(s <= 1810 and e >= 1830 for s, e in windows), windows
    assert all(b[0] > a[1] for a, b in zip(windows, windows[1:]))

    db = np.full(int(duration * 2), -40.0)
    db[2 * 600 : 2 * 640] = -5.0
    loud = focus.pick_windows(duration, 60, audio_db=db, budget=300)
    assert any(s <= 610 and e >= 630 for s, e in loud) and focus.covered(loud) <= 360

    assert focus.pick_windows(700, 60) == [(0.0, 700)]
    spread = focus.pick_windows(7200, 60)
    assert len(spread) > 3 and spread[0][0] == 0 and spread[-1][0] > 6000


def test_captions_grouping_and_ass_file():
    words = cap.words_from_lines([(10.0, 12.0, "hello there my friend"), (12.0, 13.0, "how are you?")], 10.5, 20)
    assert words[0][0] == 0 and all(e <= 9.5 for _, e, _ in words)
    groups = cap.group(words, "bold")
    assert all(len(t.split()) <= 3 for _, _, t in groups) and groups[-1][2].endswith("you?")
    assert all(groups[i][1] <= groups[i + 1][0] + 1e-6 for i in range(len(groups) - 1))
    doc = cap.ass(groups, 1080, 1920, "bold")
    assert "PlayResX: 1080" in doc and "PlayResY: 1920" in doc and "HELLO" in doc and doc.count("Dialogue:") == len(groups)
    assert "{" not in cap.ass([(0, 1, "a {\\b1} b")], 640, 360, "classic").split("[Events]")[1].split("Text\n")[1]
    assert cap.clip_words([(5.0, 5.5, " hi"), (9.0, 9.4, "bye")], 4.0, 9.0) == [(1.0, 1.5, "hi")]


def test_proxy_password_is_masked_and_kept(tmp_path):
    url = "socks5h://user:s3cr3t@p.example.com:80"
    assert mask_proxy(url) == f"socks5h://user:{MASK}@p.example.com:80"
    assert mask_proxy("http://proxy:8080") == "http://proxy:8080"
    assert merge_proxy(mask_proxy(url), url) == url
    assert merge_proxy("socks5h://user:new@p.example.com:80", url) == "socks5h://user:new@p.example.com:80"
    assert merge_proxy(f"socks5h://other:{MASK}@p.example.com:80", url) == "socks5h://other@p.example.com:80"

    store = SettingsStore(tmp_path / "s.json")
    store.update({"proxy": url})
    public = public_settings(store.load())
    assert "s3cr3t" not in str(public) and public["proxy"].endswith("@p.example.com:80")
    assert store.update({"proxy": public["proxy"], "performance": "low"}).proxy == url
    assert Settings().performance == "auto" and Settings().focused_transcription == "auto"


class FakeModel:
    def __init__(self):
        self.lengths = []

    def transcribe(self, audio, **kw):
        self.lengths.append(len(audio) / RATE)
        dur = len(audio) / RATE
        word = SimpleNamespace(start=0.2, end=0.6, word="w")
        return [SimpleNamespace(start=0.2, end=dur - 0.1, text="w", words=[word])], SimpleNamespace(language="en")


def test_transcriber_cuts_chunks_at_quiet_points():
    model = FakeModel()
    tr = Transcriber(model, chunk_sec=20)
    tone = (0.3 * np.sin(np.arange(RATE) * 0.1)).astype(np.float32)
    for second in range(50):
        quiet = second in (17, 38)
        tr.feed(np.zeros(RATE, dtype=np.float32) if quiet else tone)
    tr.flush()
    assert len(model.lengths) == 3
    assert 17 <= model.lengths[0] <= 18.1 and abs(sum(model.lengths) - 50) < 0.01
    starts = [s for s, _, _ in tr.items]
    assert starts[0] == pytest.approx(0.2) and starts[1] == pytest.approx(model.lengths[0] + 0.2)
    assert tr.language == "en"
