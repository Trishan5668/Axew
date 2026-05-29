"""
Background processing queue — Phase 9.3.

Runs intelligence extraction + indexing after transcription completes.
Single-worker executor to prevent RAM exhaustion on low-resource machines.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Single worker prevents concurrent heavy inference from blowing RAM
_EXECUTOR = ThreadPoolExecutor(max_workers=1)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ProcessingJob:
    video_id: str
    segments: List[Dict[str, Any]]
    media_path: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    error: Optional[str] = None
    artifacts: Any = None
    index: Any = None


class ProcessingQueue:
    """Async queue for post-transcription intelligence indexing."""

    def __init__(self) -> None:
        self._jobs: Dict[str, ProcessingJob] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        video_id: str,
        segments: List[Dict[str, Any]],
        media_path: Optional[str] = None,
    ) -> ProcessingJob:
        async with self._lock:
            job = ProcessingJob(video_id=video_id, segments=segments, media_path=media_path)
            self._jobs[video_id] = job
        asyncio.create_task(self._process(job))
        return job

    def get_status(self, video_id: str) -> Optional[ProcessingJob]:
        return self._jobs.get(video_id)

    async def _process(self, job: ProcessingJob) -> None:
        job.status = JobStatus.RUNNING
        try:
            loop = asyncio.get_running_loop()

            from python.intelligence.extraction_pipeline import extract_intelligence
            from python.retrieval.video_index import VideoIndex

            # Memory check before heavy processing
            try:
                from python.resource_manager import get_memory_snapshot, MemoryPressure, force_gc

                snap = get_memory_snapshot()
                if snap.pressure in (MemoryPressure.HIGH, MemoryPressure.CRITICAL):
                    logger.warning("Memory pressure %s before processing %s — running GC first", snap.pressure.value, job.video_id)
                    force_gc()
            except ImportError:
                pass

            artifacts = await loop.run_in_executor(
                _EXECUTOR,
                lambda: asyncio.run(extract_intelligence(job.segments, video_id=job.video_id)),
            )
            job.artifacts = artifacts

            index = VideoIndex(artifacts, job.video_id)
            await loop.run_in_executor(_EXECUTOR, index.index)

            # Skip multimodal on low-resource — it loads CLIP + OCR models
            skip_multimodal = True
            try:
                from python.resource_manager import should_use_lightweight

                skip_multimodal = should_use_lightweight()
            except ImportError:
                pass

            if job.media_path and not skip_multimodal:
                try:
                    from python.multimodal.multimodal_index import build_multimodal_index

                    duration = artifacts.document.duration_sec
                    await build_multimodal_index(
                        job.media_path,
                        job.video_id,
                        duration,
                        skip_ollama_scenes=True,
                    )
                except Exception as e:
                    logger.warning("Multimodal indexing skipped for %s: %s", job.video_id, e)

            job.index = index
            job.status = JobStatus.COMPLETE
            logger.info("Processing complete for video_id=%s", job.video_id)
        except MemoryError:
            job.status = JobStatus.FAILED
            job.error = "Out of memory during processing"
            logger.critical("OOM during processing for %s", job.video_id)
            try:
                from python.resource_manager import force_gc, get_model_lifecycle

                get_model_lifecycle().unload_all()
                force_gc()
            except Exception:
                pass
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            logger.error("Processing failed for %s: %s", job.video_id, e)


_QUEUE = ProcessingQueue()


def get_processing_queue() -> ProcessingQueue:
    return _QUEUE
