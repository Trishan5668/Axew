"""In-memory tracking of long-running OpusClip jobs.

Why in-memory? AXEW is a desktop product where the AI service runs as a
child process of Electron and is restarted with the app. Persisting jobs
across restarts is not a requirement for v1; on restart the user just
re-submits the queue. For a future cloud deployment, swap the
``JobStore`` implementation for a Redis or Postgres backend — the
interface is small.

Threading model: FastAPI runs handlers on an asyncio loop AND on a thread
pool for sync endpoints. We protect mutating operations with a
``threading.Lock`` so both worlds can safely touch the store.

TTL: completed/failed jobs are evicted ~24h after their last update so
the dict can't grow unbounded. Active jobs are NEVER evicted.

Concurrency: at most ``MAX_ACTIVE_JOBS_PER_USER`` jobs may be in flight
per user. Beyond that the router returns 429 and the user must wait.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Final

from models.opusclip import ClipRange, JobStage, OpusClipResult

logger = logging.getLogger(__name__)


JOB_TTL_SECONDS: Final[int] = 24 * 60 * 60
MAX_ACTIVE_JOBS_PER_USER: Final[int] = 5


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------


@dataclass
class ProjectTracking:
    """One OpusClip project (one per AXEW ClipRange)."""

    source_range: ClipRange
    project_id: str | None = None
    stage: str | None = None
    last_error: str | None = None
    results: list[OpusClipResult] = field(default_factory=list)


@dataclass
class Job:
    """An AXEW job; wraps N OpusClip projects."""

    job_id: str
    user_id: str
    minutes_required: float
    submitted_at: float
    updated_at: float
    stage: JobStage = "queued"
    projects: list[ProjectTracking] = field(default_factory=list)
    error_message: str | None = None
    credits_deducted: bool = False
    credits_remaining_at_completion: float | None = None
    # asyncio.Task running in the background that drives this job. Held so
    # tests can await it deterministically; production code never awaits.
    background_task: asyncio.Task[None] | None = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # -------- writes --------

    def create(self, user_id: str, ranges: list[ClipRange], minutes_required: float) -> Job:
        self._evict_expired_locked_outside()
        now = time.time()
        with self._lock:
            active = self._count_active_for_user_locked(user_id)
            if active >= MAX_ACTIVE_JOBS_PER_USER:
                raise JobLimitExceededError(
                    f"You already have {active} OpusClip job(s) running. "
                    "Wait for one to finish before starting another.",
                )
            job = Job(
                job_id=uuid.uuid4().hex,
                user_id=user_id,
                minutes_required=minutes_required,
                submitted_at=now,
                updated_at=now,
                stage="queued",
                projects=[ProjectTracking(source_range=r) for r in ranges],
            )
            self._jobs[job.job_id] = job
        logger.info(
            "OpusClip job created: %s user=%s ranges=%d minutes=%.2f",
            job.job_id, user_id, len(ranges), minutes_required,
        )
        return job

    def update(self, job_id: str, **fields) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = time.time()
            return job

    def set_project(
        self,
        job_id: str,
        project_index: int,
        *,
        project_id: str | None = None,
        stage: str | None = None,
        last_error: str | None = None,
        results: list[OpusClipResult] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or project_index < 0 or project_index >= len(job.projects):
                return
            project = job.projects[project_index]
            if project_id is not None:
                project.project_id = project_id
            if stage is not None:
                project.stage = stage
            if last_error is not None:
                project.last_error = last_error
            if results is not None:
                project.results = list(results)
            job.updated_at = time.time()

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    # -------- reads --------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_for_user(self, job_id: str, user_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user_id != user_id:
                return None
            return job

    # -------- maintenance --------

    def _count_active_for_user_locked(self, user_id: str) -> int:
        return sum(
            1
            for j in self._jobs.values()
            if j.user_id == user_id and j.stage in ("queued", "submitting", "processing")
        )

    def _evict_expired_locked_outside(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        with self._lock:
            stale = [
                jid for jid, j in self._jobs.items()
                if j.updated_at < cutoff and j.stage in ("completed", "failed", "expired")
            ]
            for jid in stale:
                self._jobs.pop(jid, None)
        if stale:
            logger.info("Evicted %d expired OpusClip jobs", len(stale))

    def reset(self) -> None:
        """Test-only helper — drop all in-memory jobs."""
        with self._lock:
            self._jobs.clear()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JobLimitExceededError(Exception):
    """Raised by JobStore.create() when a user has too many active jobs."""


# ---------------------------------------------------------------------------
# Module-level singleton + accessor
# ---------------------------------------------------------------------------


_store: JobStore | None = None


def get_job_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore()
    return _store


def reset_job_store_for_tests() -> None:
    """Replace the singleton with a fresh instance — used by pytest fixtures."""
    global _store
    _store = JobStore()
