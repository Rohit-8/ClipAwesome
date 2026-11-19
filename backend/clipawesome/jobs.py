"""Background job manager: runs pipelines on a thread pool and tracks stage/progress."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .models import Analysis, Job, JobStage
from .store import Store

log = logging.getLogger("clipawesome.jobs")

Progress = Callable[[str, float], None]
Runner = Callable[[Progress], Analysis]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, store: Store, max_workers: int = 2, keep: int = 100):
        self.store = store
        self.keep = keep
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="clip-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, title: str, runner: Runner) -> Job:
        job = Job(id="j_" + uuid.uuid4().hex[:12], kind=kind, title=title, created_at=now_iso())
        job.stages.append(JobStage(name="Queued", at=job.created_at))
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > self.keep:
                for old in sorted(self._jobs.values(), key=lambda j: j.created_at)[: len(self._jobs) - self.keep]:
                    if old.status in ("done", "error"):
                        self._jobs.pop(old.id, None)
        self._executor.submit(self._run, job.id, runner)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list(self) -> list[Job]:
        with self._lock:
            return sorted((j.model_copy(deep=True) for j in self._jobs.values()), key=lambda j: j.created_at, reverse=True)

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            stage = fields.pop("stage", None)
            progress = fields.pop("progress", None)
            if isinstance(stage, str) and stage != job.stage:
                job.stage = stage
                job.stages.append(JobStage(name=stage, at=now_iso()))
            if isinstance(progress, (int, float)):
                job.progress = max(job.progress, min(1.0, float(progress)))
            for key, value in fields.items():
                setattr(job, key, value)

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
