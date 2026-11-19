"""OpenAI-compatible chat client used for every provider (custom gateway, Gemini, Groq, NVIDIA NIM)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from ..config import AISettings

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


class LLMError(RuntimeError):
    pass


def _error_text(err: APIStatusError) -> str:
    try:
        body = err.response.json()
        if isinstance(body, list) and body:
            body = body[0]
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
        return str(msg or body.get("message") or err.message)
    except Exception:
        return str(err.message)


def parse_json_reply(text: str) -> Any:
    text = _THINK_RE.sub("", text or "")
    if "</think>" in text.lower():
        text = text[text.lower().rfind("</think>") + len("</think>"):]
    text = _FENCE_RE.sub("", text.strip()).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise LLMError("The model did not return valid JSON")


class LLMClient:
    def __init__(self, settings: AISettings):
        if not settings.is_configured():
            raise LLMError("AI provider is not configured. Set base URL, model and API key in Settings.")
        self.settings = settings
        self.base_url = settings.resolved_base_url()
        self.model = settings.resolved_model()
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=settings.api_key or "not-needed",
            timeout=settings.timeout_sec,
            max_retries=2,
        )
        self._json_mode = True
        self._temperature = True
        self._token_param = "max_tokens"

    def _create(self, messages: list[dict[str, str]], json_mode: bool, max_tokens: int | None) -> str:
        for _ in range(4):
            kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
            kwargs[self._token_param] = max_tokens or self.settings.max_tokens
            if self._temperature:
                kwargs["temperature"] = self.settings.temperature
            if json_mode and self._json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except APIStatusError as err:
                msg = _error_text(err)
                low = msg.lower()
                # Providers differ in supported params; relax and retry instead of failing.
                if err.status_code in (400, 422):
                    if "response_format" in kwargs:
                        self._json_mode = False
                        continue
                    if "temperature" in kwargs and "temperature" in low:
                        self._temperature = False
                        continue
                    if self._token_param == "max_tokens" and "max_tokens" in low:
                        self._token_param = "max_completion_tokens"
                        continue
                raise LLMError(f"{self.model} @ {self.base_url} → HTTP {err.status_code}: {msg}") from err
            except APITimeoutError as err:
                raise LLMError(f"Timed out after {self.settings.timeout_sec:.0f}s waiting for {self.model}") from err
            except APIConnectionError as err:
                raise LLMError(f"Cannot reach {self.base_url}: {err}") from err
            if not resp.choices:
                raise LLMError("The provider returned no choices")
            return resp.choices[0].message.content or ""
        raise LLMError("The provider rejected the request parameters")

    def chat(self, system: str, user: str, max_tokens: int | None = None) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self._create(messages, json_mode=False, max_tokens=max_tokens)

    def chat_json(self, system: str, user: str, max_tokens: int | None = None) -> Any:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        reply = self._create(messages, json_mode=True, max_tokens=max_tokens)
        try:
            return parse_json_reply(reply)
        except LLMError:
            messages += [
                {"role": "assistant", "content": reply[:4000]},
                {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON object, no prose."},
            ]
            return parse_json_reply(self._create(messages, json_mode=True, max_tokens=max_tokens))

    def test(self) -> dict[str, Any]:
        started = time.perf_counter()
        data = self.chat_json(
            "You are a connectivity check. Reply with a JSON object only.",
            'Return exactly: {"ok": true, "message": "<a five word greeting>"}',
            max_tokens=300,
        )
        latency = time.perf_counter() - started
        message = data.get("message") if isinstance(data, dict) else None
        return {
            "ok": True,
            "message": f"{message or 'Connected'} ({latency:.1f}s)",
            "model": self.model,
            "json_mode": self._json_mode,
        }

    def list_models(self) -> list[str]:
        try:
            return sorted({m.id for m in self.client.models.list()})
        except APIStatusError as err:
            raise LLMError(f"Model list not available (HTTP {err.status_code}): {_error_text(err)}") from err
        except (APIConnectionError, APITimeoutError) as err:
            raise LLMError(f"Cannot reach {self.base_url}: {err}") from err
