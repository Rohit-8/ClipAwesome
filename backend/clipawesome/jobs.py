"""Background job manager: runs pipelines on a thread pool, tracks stage/progress and survives restarts."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_path, read_json, write_json
from .models import Analysis, Job, JobStage
from .store import Store

log = logging.getLogger("clipawesome.jobs")

Progress = Callable[[str, float], None]
Runner = Callable[[Progress], Analysis]
ACTIVE = ("queued", "running")
FINISHED = ("done", "error", "interrupted")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, store: Store, max_workers: int = 2, keep: int = 100, root: Path | None = None):
        self.store = store
        self.keep = keep
        self._root = root
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="clip-job")
        self._jobs: dict[str, Job] = {}
        self._specs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root or data_path("jobs")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for path in self.root.glob("j_*.json"):
            data = read_json(path, {})
            try:
                job = Job.model_validate(data.get("job") or {})
            except Exception:
                continue
            if job.status in ACTIVE:
                job.status, job.stage = "interrupted", "Interrupted"
                job.error = "The server stopped while this was running. Run it again to continue."
                job.stages.append(JobStage(name="Interrupted", at=now_iso()))
                write_json(path, {**data, "job": job.model_dump()})
            self._jobs[job.id] = job
            if data.get("spec"):
                self._specs[job.id] = data["spec"]

    def _save(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            write_json(self.root / f"{job_id}.json", {"job": job.model_dump(), "spec": self._specs.get(job_id)})

    def submit(self, kind: str, title: str, runner: Runner, spec: dict[str, Any] | None = None) -> Job:
        job = Job(id="j_" + uuid.uuid4().hex[:12], kind=kind, title=title, created_at=now_iso(), retryable=spec is not None)
        job.stages.append(JobStage(name="Queued", at=job.created_at))
        with self._lock:
            self._load()
            self._jobs[job.id] = job
            if spec is not None:
                self._specs[job.id] = spec
            self._save(job.id)
            if len(self._jobs) > self.keep:
                for old in sorted(self._jobs.values(), key=lambda j: j.created_at)[: len(self._jobs) - self.keep]:
                    if old.status in FINISHED:
                        self._jobs.pop(old.id, None)
                        self._specs.pop(old.id, None)
                        (self.root / f"{old.id}.json").unlink(missing_ok=True)
        self._executor.submit(self._run, job.id, runner)
        return job.model_copy(deep=True)

    def spec(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            return self._specs.get(job_id)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._load()
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list(self) -> list[Job]:
        with self._lock:
            self._load()
            return sorted((j.model_copy(deep=True) for j in self._jobs.values()), key=lambda j: j.created_at, reverse=True)

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            stage = fields.pop("stage", None)
            progress = fields.pop("progress", None)
            changed = bool(fields)
            if isinstance(stage, str) and stage != job.stage:
                job.stage = stage
                job.stages.append(JobStage(name=stage, at=now_iso()))
                changed = True
            if isinstance(progress, (int, float)):
                job.progress = max(job.progress, min(1.0, float(progress)))
            for key, value in fields.items():
                setattr(job, key, value)
            # Progress ticks stay in memory; stage/status changes are written so a restart shows where it stopped.
            if changed:
                self._save(job_id)

    def _run(self, job_id: str, runner: Runner) -> None:
        self._update(job_id, status="running", stage="Starting", progress=0.01)

        def progress(stage: str, fraction: float) -> None:
            self._update(job_id, stage=stage, progress=fraction)

        try:
            analysis = runner(progress)
            self.store.save(analysis)
            self._update(job_id, status="done", stage="Done", progress=1.0, result_id=analysis.id)
        except Exception as err:
            log.exception("Job %s failed", job_id)
            message = str(err).strip() or type(err).__name__
            self._update(job_id, status="error", stage="Failed", error=message[:500])
