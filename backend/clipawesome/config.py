from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CLIPAWESOME_DATA") or ROOT / "data")
WEB_DIST = Path(os.environ.get("CLIPAWESOME_WEB_DIST") or ROOT / "web" / "dist")
HOST = os.environ.get("CLIPAWESOME_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIPAWESOME_PORT", "8765"))

# Server deployments: HTTP Basic auth is enforced whenever a password is set.
AUTH_USER = os.environ.get("CLIPAWESOME_AUTH_USER", "admin")
AUTH_PASSWORD = os.environ.get("CLIPAWESOME_AUTH_PASSWORD", "")
# "Analyse by file path" reads the server's filesystem, so deployments turn it off.
ALLOW_LOCAL_PATH = os.environ.get("CLIPAWESOME_ALLOW_LOCAL_PATH", "true").strip().lower() in ("1", "true", "yes")

MASK = "••••"
CLEAR = "__clear__"

Provider = Literal["custom", "gemini", "groq", "nvidia"]

# All providers speak the OpenAI chat-completions protocol; (base_url, suggested model).
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "custom": ("", ""),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
}


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def ensure_dirs() -> None:
    for sub in ("analyses", "uploads", "models", "tmp", "downloads"):
        data_path(sub).mkdir(parents=True, exist_ok=True)


class AISettings(BaseModel):
    provider: Provider = "custom"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    ai_weight: float = Field(0.6, ge=0, le=1)
    temperature: float = Field(0.2, ge=0, le=2)
    max_tokens: int = Field(2500, ge=256, le=32000)
    timeout_sec: float = Field(120, ge=5, le=600)

    def resolved_base_url(self) -> str:
        return (self.base_url or PROVIDER_DEFAULTS[self.provider][0]).strip().rstrip("/")

    def resolved_model(self) -> str:
        return (self.model or PROVIDER_DEFAULTS[self.provider][1]).strip()

    def is_configured(self) -> bool:
        if not (self.resolved_base_url() and self.resolved_model()):
            return False
        # A custom gateway (e.g. a local server) may not require a key.
        return self.provider == "custom" or bool(self.api_key)


class ScoringWeights(BaseModel):
    heatmap: float = Field(0.28, ge=0, le=1)
    audio: float = Field(0.12, ge=0, le=1)
    reactions: float = Field(0.14, ge=0, le=1)
    relevance: float = Field(0.22, ge=0, le=1)
    comments: float = Field(0.08, ge=0, le=1)
    highlight: float = Field(0.06, ge=0, le=1)
    pace: float = Field(0.04, ge=0, le=1)
    visual: float = Field(0.03, ge=0, le=1)
    hook: float = Field(0.08, ge=0, le=1)
    completeness: float = Field(0.05, ge=0, le=1)


class Settings(BaseModel):
    default_mode: Literal["deterministic", "ai"] = "deterministic"
    default_preset: Literal["shorts", "standard", "long"] = "standard"
    default_max_clips: int = Field(8, ge=1, le=30)
    include_comments: bool = True
    max_comments: int = Field(300, ge=0, le=2000)
    visual_analysis: Literal["off", "fast", "full"] = "fast"
    whisper_model: str = "base"
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_compute_type: str = "int8"
    youtube_audio: Literal["never", "when_needed", "always"] = "when_needed"
    caption_languages: list[str] = Field(default_factory=lambda: ["en"])
    youtube_api_key: str = ""
    proxy: str = ""
    ai: AISettings = Field(default_factory=AISettings)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    @field_validator("proxy")
    @classmethod
    def _check_proxy(cls, value: str) -> str:
        value = value.strip()
        if value and not value.lower().startswith(("http://", "https://", "socks5://", "socks5h://")):
            raise ValueError("proxy must start with http://, https:// or socks5://")
        return value


def _mask(secret: str) -> str:
    if not secret:
        return ""
    return MASK + secret[-4:] if len(secret) > 8 else MASK


def _merge_secret(incoming: Any, current: str) -> str:
    if incoming == CLEAR:
        return ""
    if not isinstance(incoming, str) or not incoming or incoming.startswith(MASK):
        return current
    return incoming.strip()


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_path("settings.json")
        self._lock = threading.Lock()

    def load(self) -> Settings:
        with self._lock:
            if not self.path.exists():
                return Settings()
            try:
                return Settings.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError):
                return Settings()

    def save(self, settings: Settings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def update(self, incoming: dict[str, Any]) -> Settings:
        current = self.load()
        merged = current.model_dump()
        for key, value in incoming.items():
            if key in ("ai", "weights") and isinstance(value, dict):
                merged[key].update(value)
            elif key in merged:
                merged[key] = value
        merged["youtube_api_key"] = _merge_secret(incoming.get("youtube_api_key"), current.youtube_api_key)
        merged["ai"]["api_key"] = _merge_secret((incoming.get("ai") or {}).get("api_key"), current.ai.api_key)
        updated = Settings.model_validate(merged)
        self.save(updated)
        return updated


def public_settings(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump()
    data["youtube_api_key"] = _mask(settings.youtube_api_key)
    data["ai"]["api_key"] = _mask(settings.ai.api_key)
    data["has_youtube_api_key"] = bool(settings.youtube_api_key)
    data["ai"]["has_api_key"] = bool(settings.ai.api_key)
    data["ai"]["configured"] = settings.ai.is_configured()
    data["ai"]["effective_base_url"] = settings.ai.resolved_base_url()
    data["ai"]["effective_model"] = settings.ai.resolved_model()
    return data


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
