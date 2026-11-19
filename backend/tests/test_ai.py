from types import SimpleNamespace

import pytest

from clipawesome.ai.llm import LLMError, parse_json_reply
from clipawesome.ai.rerank import rerank_clips
from clipawesome.config import AISettings
from clipawesome.models import ClipSuggestion, SourceVideo


def test_parse_json_reply_handles_think_and_fences():
    assert parse_json_reply('<think>hmm {"no": 1}</think>\n```json\n{"ok": true}\n```') == {"ok": True}
    assert parse_json_reply('Sure! Here it is: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        parse_json_reply("no json here")


def test_provider_configuration_rules():
    assert AISettings(provider="custom", base_url="https://llm.maqsoftware.net/v1", model="qwen-3.8-27b").is_configured()
    assert not AISettings(provider="custom", model="m").is_configured()
    assert not AISettings(provider="groq").is_configured()
    groq = AISettings(provider="groq", api_key="k")
    assert groq.is_configured() and groq.resolved_base_url() == "https://api.groq.com/openai/v1"
    assert AISettings(provider="nvidia", api_key="k").resolved_base_url().startswith("https://integrate.api.nvidia.com")
    assert AISettings(provider="gemini", api_key="k", base_url="https://custom/v1/").resolved_base_url() == "https://custom/v1"


def _clip(i: int, score: float) -> ClipSuggestion:
    return ClipSuggestion(
        id=f"s1-c{i}", source_id="s1", start=i * 100, end=i * 100 + 40, duration=40,
        score=score, engine_score=score, title=f"Clip {i}", transcript=f"text {i}",
    )


def test_rerank_is_grounded_and_blends_scores():
    fake = SimpleNamespace(
        chat_json=lambda system, user, max_tokens=None: {
            "clips": [
                {"id": "c99", "score": 100, "title": "invented"},
                {"id": "c2", "score": 90, "title": "Best one", "hook": "Wait for it", "reason": "Great payoff", "tags": ["#fun"]},
                {"id": "c2", "score": 10},
                {"id": "c1", "score": 40},
            ]
        }
    )
    source = SourceVideo(id="s1", platform="youtube", title="T", duration=600)
    out = rerank_clips(fake, source, [_clip(1, 70), _clip(2, 50), _clip(3, 30)], None, 5, 0.6)
    assert [c.id for c in out] == ["s1-c2", "s1-c1"]
    assert out[0].score == pytest.approx(0.6 * 90 + 0.4 * 50)
    assert out[0].title == "Best one" and out[0].hook == "Wait for it" and out[0].tags[0] == "fun"
    assert out[0].reasons[0].signal == "ai"


def test_rerank_rejects_empty_selection():
    fake = SimpleNamespace(chat_json=lambda *a, **k: {"clips": [{"id": "nope", "score": 50}]})
    source = SourceVideo(id="s1", platform="youtube", title="T", duration=600)
    with pytest.raises(LLMError):
        rerank_clips(fake, source, [_clip(1, 70)], None, 5, 0.6)
