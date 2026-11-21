"""Local persistence: analyses, history index and the media registry."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from .config import DATA_DIR, read_json, write_json
from .models import Analysis, AnalysisSummary

_ANALYSIS_ID = re.compile(r"^a_[0-9a-f]{12}$")
_MEDIA_ID = re.compile(r"^m_[0-9a-f]{16}$")


def new_analysis_id() -> str:
    return "a_" + uuid.uuid4().hex[:12]


def new_media_id() -> str:
    return "m_" + uuid.uuid4().hex[:16]


def summarize(a: Analysis) -> AnalysisSummary:
    return AnalysisSummary(
        id=a.id,
        kind=a.kind,
        mode=a.mode,
        title=a.title,
        created_at=a.created_at,
        thumbnail=next((s.thumbnail for s in a.sources if s.thumbnail), None),
        clip_count=len(a.clips),
        top_score=max((c.score for c in a.clips), default=None),
        source_count=len(a.sources),
        query=a.query,
    )


class Store:
    def __init__(self, root: Path = DATA_DIR):
        self.root = root
        self.analyses = root / "analyses"
        self.uploads = root / "uploads"
        self.index_path = self.analyses / "index.json"
        self.media_path = root / "media.json"
        self._lock = threading.Lock()

    def save(self, analysis: Analysis) -> None:
        with self._lock:
            self.analyses.mkdir(parents=True, exist_ok=True)
            (self.analyses / f"{analysis.id}.json").write_text(analysis.model_dump_json(), encoding="utf-8")
            index = [e for e in read_json(self.index_path, []) if e.get("id") != analysis.id]
            index.append(summarize(analysis).model_dump())
            write_json(self.index_path, index)

    def get(self, analysis_id: str) -> Analysis | None:
        if not _ANALYSIS_ID.match(analysis_id):
            return None
        path = self.analyses / f"{analysis_id}.json"
        if not path.exists():
            return None
        return Analysis.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[AnalysisSummary]:
        items = [AnalysisSummary.model_validate(e) for e in read_json(self.index_path, [])]
        return sorted(items, key=lambda s: s.created_at, reverse=True)

    def set_review(self, analysis_id: str, clip_id: str, review: str | None) -> Analysis | None:
        with self._lock:
            analysis = self.get(analysis_id)
            clip = next((c for c in analysis.clips if c.id == clip_id), None) if analysis else None
            if analysis is None or clip is None:
                return None
            clip.review = review  # type: ignore[assignment]
            (self.analyses / f"{analysis.id}.json").write_text(analysis.model_dump_json(), encoding="utf-8")
            return analysis

    def delete(self, analysis_id: str) -> bool:
        analysis = self.get(analysis_id)
        if analysis is None:
            return False
        with self._lock:
            (self.analyses / f"{analysis_id}.json").unlink(missing_ok=True)
            index = [e for e in read_json(self.index_path, []) if e.get("id") != analysis_id]
            write_json(self.index_path, index)
        for src in analysis.sources:
            if src.media_id:
                self.release_media(src.media_id)
        return True

    def register_media(self, path: Path, kind: str, media_id: str | None = None) -> str:
        media_id = media_id or new_media_id()
        with self._lock:
            registry = read_json(self.media_path, {})
            registry[media_id] = {"path": str(path), "kind": kind}
            write_json(self.media_path, registry)
        return media_id

    def media_file(self, media_id: str) -> Path | None:
        if not _MEDIA_ID.match(media_id):
            return None
        entry = read_json(self.media_path, {}).get(media_id)
        if not entry:
            return None
        path = Path(entry["path"])
        return path if path.is_file() else None

    def release_media(self, media_id: str) -> None:
        with self._lock:
            registry = read_json(self.media_path, {})
            entry = registry.pop(media_id, None)
            write_json(self.media_path, registry)
        if entry and entry.get("kind") == "upload":
            for f in self.uploads.glob(f"{media_id}*"):
                f.unlink(missing_ok=True)
        (self.root / "previews" / f"{media_id}.mp3").unlink(missing_ok=True)
