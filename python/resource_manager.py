"""
Central resource manager for low-resource environments.

Tracks RAM usage, manages model lifecycle, serializes heavy AI tasks,
and provides graceful degradation when memory is constrained.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memory monitoring
# ---------------------------------------------------------------------------

_PSUTIL_AVAILABLE = False
try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    pass


class MemoryPressure(str, Enum):
    LOW = "low"  # < 60 % used — all models allowed
    MEDIUM = "medium"  # 60-80 % — prefer lightweight models
    HIGH = "high"  # 80-90 % — unload inactive models
    CRITICAL = "critical"  # > 90 % — force-unload everything, heuristic-only


@dataclass
class MemorySnapshot:
    total_mb: float = 0.0
    available_mb: float = 0.0
    used_percent: float = 0.0
    pressure: MemoryPressure = MemoryPressure.LOW
    process_rss_mb: float = 0.0


def get_memory_snapshot() -> MemorySnapshot:
    if not _PSUTIL_AVAILABLE:
        return MemorySnapshot()
    vm = psutil.virtual_memory()
    proc = psutil.Process(os.getpid())
    rss = proc.memory_info().rss / (1024 * 1024)
    pct = vm.percent
    if pct > 90:
        pressure = MemoryPressure.CRITICAL
    elif pct > 80:
        pressure = MemoryPressure.HIGH
    elif pct > 60:
        pressure = MemoryPressure.MEDIUM
    else:
        pressure = MemoryPressure.LOW
    return MemorySnapshot(
        total_mb=vm.total / (1024 * 1024),
        available_mb=vm.available / (1024 * 1024),
        used_percent=pct,
        pressure=pressure,
        process_rss_mb=rss,
    )


def should_use_lightweight() -> bool:
    snap = get_memory_snapshot()
    return snap.pressure in (MemoryPressure.MEDIUM, MemoryPressure.HIGH, MemoryPressure.CRITICAL)


def should_skip_models() -> bool:
    snap = get_memory_snapshot()
    return snap.pressure == MemoryPressure.CRITICAL


# ---------------------------------------------------------------------------
# Model lifecycle manager
# ---------------------------------------------------------------------------

@dataclass
class _ModelEntry:
    name: str
    obj: Any
    size_mb_est: float
    last_used: float = 0.0
    load_count: int = 0


class ModelLifecycle:
    """Tracks loaded models and unloads the least-recently-used when under pressure."""

    _instance: Optional["ModelLifecycle"] = None

    def __new__(cls) -> "ModelLifecycle":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._models = {}
            inst._lock = threading.Lock()
            inst._max_models = int(os.environ.get("AXEW_MAX_MODELS", "3"))
            cls._instance = inst
        return cls._instance

    def register(self, name: str, obj: Any, size_mb_est: float = 200.0) -> None:
        with self._lock:
            self._models[name] = _ModelEntry(
                name=name, obj=obj, size_mb_est=size_mb_est, last_used=time.time(), load_count=1
            )
        self._maybe_evict()

    def touch(self, name: str) -> None:
        with self._lock:
            entry = self._models.get(name)
            if entry:
                entry.last_used = time.time()

    def unload(self, name: str) -> None:
        with self._lock:
            entry = self._models.pop(name, None)
        if entry:
            logger.info("Unloading model %s (~%.0f MB)", name, entry.size_mb_est)
            del entry.obj
            gc.collect()

    def unload_all(self) -> None:
        names = list(self._models.keys())
        for n in names:
            self.unload(n)

    def _maybe_evict(self) -> None:
        snap = get_memory_snapshot()
        if snap.pressure == MemoryPressure.CRITICAL:
            self.unload_all()
            return
        with self._lock:
            while len(self._models) > self._max_models:
                lru = min(self._models.values(), key=lambda e: e.last_used)
                self._models.pop(lru.name, None)
                logger.info("Evicting LRU model %s", lru.name)
                del lru.obj
                gc.collect()

    def loaded_names(self) -> List[str]:
        return list(self._models.keys())

    def total_est_mb(self) -> float:
        return sum(e.size_mb_est for e in self._models.values())


# ---------------------------------------------------------------------------
# AI task queue — serializes expensive operations
# ---------------------------------------------------------------------------

class TaskPriority(int, Enum):
    HIGH = 0
    NORMAL = 1
    LOW = 2


@dataclass
class AITask:
    task_id: str
    priority: TaskPriority = TaskPriority.NORMAL
    created: float = field(default_factory=time.time)
    timeout_sec: float = 120.0
    cancelled: bool = False
    result: Any = None
    error: Optional[str] = None
    status: str = "pending"


class AITaskQueue:
    """
    Serializes heavy inference tasks so only one runs at a time.
    Stale tasks (older than their timeout) are auto-cancelled.
    """

    _instance: Optional["AITaskQueue"] = None

    def __new__(cls) -> "AITaskQueue":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._queue = asyncio.Queue()
            inst._current = None
            inst._tasks = {}
            inst._worker_started = False
            inst._lock = asyncio.Lock()
            cls._instance = inst
        return cls._instance

    async def submit(
        self,
        task_id: str,
        coro_factory: Callable[[], Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout_sec: float = 120.0,
    ) -> AITask:
        async with self._lock:
            # Cancel any existing task with same id
            prev = self._tasks.get(task_id)
            if prev and prev.status in ("pending", "running"):
                prev.cancelled = True
                prev.status = "cancelled"

            task = AITask(task_id=task_id, priority=priority, timeout_sec=timeout_sec)
            self._tasks[task_id] = task
            await self._queue.put((task, coro_factory))

            if not self._worker_started:
                self._worker_started = True
                asyncio.create_task(self._worker())

        # Wait for completion
        deadline = time.time() + timeout_sec
        while task.status in ("pending", "running"):
            if time.time() > deadline:
                task.cancelled = True
                task.status = "timeout"
                task.error = f"Task {task_id} timed out after {timeout_sec}s"
                break
            await asyncio.sleep(0.1)
        return task

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in ("pending", "running"):
            task.cancelled = True
            task.status = "cancelled"
            return True
        return False

    def get_status(self, task_id: str) -> Optional[AITask]:
        return self._tasks.get(task_id)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def is_busy(self) -> bool:
        return self._current is not None and self._current.status == "running"

    async def _worker(self) -> None:
        while True:
            task, coro_factory = await self._queue.get()
            if task.cancelled:
                self._queue.task_done()
                continue

            # Auto-cancel stale tasks
            if time.time() - task.created > task.timeout_sec:
                task.status = "timeout"
                task.error = "Stale task discarded"
                self._queue.task_done()
                continue

            task.status = "running"
            self._current = task
            try:
                coro = coro_factory()
                result = await asyncio.wait_for(coro, timeout=task.timeout_sec)
                if not task.cancelled:
                    task.result = result
                    task.status = "complete"
            except asyncio.TimeoutError:
                task.status = "timeout"
                task.error = f"Execution exceeded {task.timeout_sec}s"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error("AI task %s failed: %s", task.task_id, e)
            finally:
                self._current = None
                self._queue.task_done()


# ---------------------------------------------------------------------------
# Convenience singletons
# ---------------------------------------------------------------------------

def get_model_lifecycle() -> ModelLifecycle:
    return ModelLifecycle()


def get_task_queue() -> AITaskQueue:
    return AITaskQueue()


def force_gc() -> None:
    gc.collect()
    if _PSUTIL_AVAILABLE:
        snap = get_memory_snapshot()
        logger.debug(
            "GC complete — RSS=%.0f MB, system=%.1f%% used", snap.process_rss_mb, snap.used_percent
        )
