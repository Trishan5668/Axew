import asyncio
import enum
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Load apps/ai-service/.env into os.environ BEFORE anything imports
# middleware.cloud_config, so non-AXEW_-prefixed secrets like
# OPUSCLIP_API_KEY, RAZORPAY_KEY_SECRET, SUPABASE_SERVICE_ROLE_KEY are
# visible. Pydantic Settings only populates fields on the Settings
# class — it does not populate os.environ.
try:
    from dotenv import load_dotenv as _load_dotenv
    _SERVICE_DIR = Path(__file__).resolve().parent
    _load_dotenv(_SERVICE_DIR / ".env", override=False)
except Exception:  # pragma: no cover — dotenv is a transitive dep, very rare
    pass

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from routers import analysis, chat, debug, execution, models, opusclip, retrieval, semantic

# Cloud-mode routers depend on optional packages (razorpay, supabase,
# python-jose). To keep local-only deployments working without those deps
# installed, the cloud routers are imported lazily inside the `if cloud
# enabled` branch below.
from middleware.cloud_config import cloud_settings as _cloud_settings

_START_TIME = time.time()

_STARTUP_DIAG: dict = {}


# ---------------------------------------------------------------------------
# Startup lifecycle state machine
# ---------------------------------------------------------------------------

class StartupPhase(str, enum.Enum):
    SPAWNING = "SPAWNING"
    INITIALIZING = "INITIALIZING"
    MODEL_LOADING = "MODEL_LOADING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class ServiceReadiness:
    """Thread-safe singleton tracking the startup lifecycle."""

    def __init__(self) -> None:
        self.phase: StartupPhase = StartupPhase.SPAWNING
        self.is_live: bool = True          # process exists and HTTP is bound
        self.is_ready: bool = False        # models initialized, API fully usable
        self.phase_history: list[dict] = []
        self._transition(StartupPhase.SPAWNING)

    def _transition(self, new_phase: StartupPhase) -> None:
        prev = self.phase
        self.phase = new_phase
        entry = {
            "from": prev.value,
            "to": new_phase.value,
            "timestamp": time.time(),
            "uptime_sec": round(time.time() - _START_TIME, 2),
        }
        self.phase_history.append(entry)
        logger.info(
            "[Lifecycle] %s -> %s (uptime=%.2fs)",
            prev.value, new_phase.value, entry["uptime_sec"],
        )

    def set_initializing(self) -> None:
        self._transition(StartupPhase.INITIALIZING)

    def set_model_loading(self) -> None:
        self._transition(StartupPhase.MODEL_LOADING)

    def set_ready(self) -> None:
        self.is_ready = True
        self._transition(StartupPhase.READY)

    def set_degraded(self) -> None:
        self.is_ready = True  # still usable, just missing optional components
        self._transition(StartupPhase.DEGRADED)

    def set_failed(self) -> None:
        self.is_ready = False
        self._transition(StartupPhase.FAILED)


_readiness = ServiceReadiness()


# ---------------------------------------------------------------------------
# Lifespan — staged, async, non-blocking initialization
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[Startup] AXEW AI Service starting on port %s", settings.port)
    _readiness.set_initializing()

    os.makedirs(settings.models_dir, exist_ok=True)
    os.makedirs(settings.cache_dir, exist_ok=True)

    diag: dict = {"started_at": time.time(), "errors": [], "warnings": []}

    # Stage 1 — ffmpeg / transcription deps (non-critical)
    logger.info("[Startup] Stage 1: Checking transcription dependencies")
    try:
        from transcription import ensure_ffmpeg_on_path, check_dependencies

        ffmpeg = ensure_ffmpeg_on_path()
        deps = check_dependencies()
        diag["ffmpeg"] = ffmpeg
        diag["transcription_ready"] = deps.ok
        logger.info(
            "[Startup] Transcription deps: ready=%s ffmpeg=%s whisper=%s torch=%s",
            deps.ok, ffmpeg, deps.whisper, deps.torch,
        )
        if deps.errors:
            diag["warnings"].extend(deps.errors)
            logger.warning("[Startup] Transcription issues: %s", "; ".join(deps.errors))
    except Exception as e:
        diag["errors"].append(f"transcription_init: {e}")
        logger.warning("[Startup] Could not verify transcription deps: %s", e)

    # Stage 2 — model registry (lazy, no actual loading yet)
    logger.info("[Startup] Stage 2: Initializing model registry (lazy)")
    _readiness.set_model_loading()
    try:
        from python.retrieval.model_registry import ModelRegistry

        registry = ModelRegistry()
        diag["device"] = registry.device
        logger.info(
            "[Startup] Model registry initialized (device=%s) — models load on first request",
            registry.device,
        )
    except Exception as e:
        diag["errors"].append(f"model_registry: {e}")
        logger.warning("[Startup] Model registry init skipped: %s", e)

    # Stage 3 — resource manager snapshot
    logger.info("[Startup] Stage 3: Resource manager snapshot")
    try:
        from python.resource_manager import get_memory_snapshot

        snap = get_memory_snapshot()
        diag["memory_at_start"] = {
            "total_mb": round(snap.total_mb),
            "available_mb": round(snap.available_mb),
            "used_percent": round(snap.used_percent, 1),
            "pressure": snap.pressure.value,
        }
        logger.info(
            "[Startup] Memory: %.0f MB avail, %.1f%% used, pressure=%s",
            snap.available_mb, snap.used_percent, snap.pressure.value,
        )
    except Exception as e:
        diag["warnings"].append(f"resource_manager: {e}")

    # Finalize startup
    diag["boot_time_sec"] = round(time.time() - diag["started_at"], 2)
    _STARTUP_DIAG.update(diag)

    has_critical_errors = any(
        "transcription_init" not in e for e in diag["errors"]
    ) and len(diag["errors"]) > 0
    if has_critical_errors:
        _readiness.set_degraded()
        logger.warning(
            "[Startup] AXEW AI Service DEGRADED in %.1fs (errors: %s)",
            diag["boot_time_sec"], diag["errors"],
        )
    else:
        _readiness.set_ready()
        logger.info(
            "[Startup] AXEW AI Service READY in %.1fs", diag["boot_time_sec"],
        )

    logger.info("[Startup] Server binding complete — accepting requests")

    yield

    logger.info("[Shutdown] AXEW AI Service shutting down")
    try:
        from python.resource_manager import get_model_lifecycle

        get_model_lifecycle().unload_all()
    except Exception:
        pass


app = FastAPI(
    title="AXEW AI Service",
    description="Local AI runtime for AXEW video editor",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def resource_guard_middleware(request: Request, call_next):
    """
    Lightweight middleware that:
    1. Logs every request with timing
    2. Applies a per-request timeout (default 120s, overridable via header)
    3. Returns 503 when memory is critically low before starting heavy work
    4. Returns 503 when service is not yet ready (except for health endpoints)
    5. Catches OOM and returns a structured error instead of crashing

    Registered BEFORE CORSMiddleware so CORS wraps this layer and still adds
    Access-Control-* headers on early 503/504 responses.
    """
    start = time.time()

    # Preflight must reach CORSMiddleware (outer layer) — never short-circuit OPTIONS here.
    if request.method == "OPTIONS":
        return await call_next(request)

    # Health-style probes must always be reachable, even during startup, so the
    # frontend polling system can render status badges immediately.
    if request.url.path.startswith("/health") or request.url.path == "/opusclip/health":
        response = await call_next(request)
        return response

    if not _readiness.is_ready and not request.url.path.startswith("/debug"):
        return Response(
            content=(
                '{"detail":"AI service is still starting up",'
                f'"phase":"{_readiness.phase.value}"'
                '}'
            ),
            status_code=503,
            media_type="application/json",
        )

    heavy_paths = ("/api/execution/plan", "/api/analysis/transcribe", "/api/execution/semantic-search", "/api/semantic/extract")
    if request.url.path in heavy_paths:
        try:
            from python.resource_manager import get_memory_snapshot, MemoryPressure

            snap = get_memory_snapshot()
            if snap.pressure == MemoryPressure.CRITICAL:
                logger.warning(
                    "Rejecting %s — memory CRITICAL (%.1f%% used, %.0f MB avail)",
                    request.url.path,
                    snap.used_percent,
                    snap.available_mb,
                )
                return Response(
                    content='{"detail":"AI service under extreme memory pressure. Try again shortly."}',
                    status_code=503,
                    media_type="application/json",
                )
        except ImportError:
            pass

    default_timeouts = {
        "/api/analysis/transcribe": 900,
        "/api/execution/plan": 300,
        "/api/execution/semantic-search": 180,
        "/api/semantic/extract": 300,
    }
    timeout_sec = float(
        request.headers.get(
            "x-axew-timeout",
            str(default_timeouts.get(request.url.path, 120)),
        )
    )
    try:
        response = await asyncio.wait_for(call_next(request), timeout=timeout_sec)
        elapsed = time.time() - start
        if elapsed > 5.0:
            logger.info(
                "SLOW %s %s — %.1fs", request.method, request.url.path, elapsed,
            )
        return response
    except asyncio.TimeoutError:
        logger.error("Request to %s timed out after %.0fs", request.url.path, timeout_sec)
        return Response(
            content='{"detail":"Request timed out"}',
            status_code=504,
            media_type="application/json",
        )
    except MemoryError:
        logger.critical("OOM during request to %s — forcing GC", request.url.path)
        try:
            from python.resource_manager import force_gc, get_model_lifecycle

            get_model_lifecycle().unload_all()
            force_gc()
        except Exception:
            pass
        return Response(
            content='{"detail":"Out of memory — models unloaded. Please retry."}',
            status_code=503,
            media_type="application/json",
        )


# Added after resource_guard so CORSMiddleware is outermost and applies headers to every response.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS middleware initialized (outermost layer)")


app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(execution.router, prefix="/api/execution", tags=["execution"])
app.include_router(semantic.router, prefix="/api/semantic", tags=["semantic"])
app.include_router(retrieval.router, prefix="/api/retrieval", tags=["retrieval"])
app.include_router(debug.router, prefix="/debug", tags=["debug"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(opusclip.router, prefix="/opusclip", tags=["opusclip"])

# ---------------------------------------------------------------------------
# Cloud-mode routers (opt-in). Imports are deferred so local-only installs
# do not require razorpay / supabase / python-jose to start the service.
# ---------------------------------------------------------------------------
_cloud = _cloud_settings()
if _cloud.enabled:
    try:
        from routers import opusclip as _opusclip_router  # noqa: WPS433
        from routers import payments as _payments_router  # noqa: WPS433

        app.include_router(_opusclip_router.router)
        app.include_router(_payments_router.router)
        logger.info("Cloud features ENABLED — mounted /opusclip and /payments routers")
    except RuntimeError as exc:
        # Raised by the routers when an optional dep is missing. Surface the
        # exact dep that's missing; do NOT fall through silently.
        logger.error("Cloud features enabled but a dependency is missing: %s", exc)
        raise
else:
    logger.info(
        "Cloud features DISABLED (AXEW_CLOUD_ENABLED unset) — "
        "auth/payments/OpusClip routes are not mounted"
    )


@app.get("/cloud/status", tags=["cloud"])
def cloud_status() -> dict:
    """Public endpoint the desktop app uses to discover whether cloud
    features are available on this AI service instance.

    Returns flags ONLY — never the secret values themselves.
    """
    s = _cloud_settings()
    return {
        "enabled": s.enabled,
        "supabase_configured": bool(s.supabase_url and s.supabase_service_role_key),
        "razorpay_configured": bool(
            s.razorpay_key_id and s.razorpay_key_secret and s.razorpay_webhook_secret
        ),
        "opusclip_configured": bool(s.opusclip_api_key),
    }


# ---------------------------------------------------------------------------
# Health endpoints — liveness vs. readiness
# ---------------------------------------------------------------------------

@app.get("/health/live")
async def liveness_check():
    """Liveness probe: returns 200 as soon as the HTTP server is bound.
    This must NEVER depend on models, Ollama, embeddings, or any external service.
    The supervisor uses this to determine if the PROCESS is alive."""
    return {
        "status": "live",
        "service": "axew-ai",
        "pid": os.getpid(),
        "phase": _readiness.phase.value,
        "uptime_sec": round(time.time() - _START_TIME),
    }


@app.get("/health/ready")
async def readiness_check():
    """Readiness probe: returns 200 only when models are initialized and the
    API is fully ready to serve requests. Returns 503 during startup."""
    if not _readiness.is_ready:
        return Response(
            content=(
                f'{{"status":"not_ready","phase":"{_readiness.phase.value}",'
                f'"uptime_sec":{round(time.time() - _START_TIME)}}}'
            ),
            status_code=503,
            media_type="application/json",
        )
    return {
        "status": "ready",
        "service": "axew-ai",
        "phase": _readiness.phase.value,
        "uptime_sec": round(time.time() - _START_TIME),
    }


@app.get("/health")
async def health_check():
    """Full health check with dependency and resource details.
    Always responds (even during startup) so callers can inspect state.
    This endpoint MUST NOT raise exceptions or hang — it wraps all checks
    in try/except with timeouts to guarantee a response."""
    deps_info: dict = {}
    transcription_ready = False
    try:
        from transcription import check_dependencies

        deps = check_dependencies()
        deps_info = {
            "ffmpeg": deps.ffmpeg,
            "whisper": deps.whisper,
            "torch": deps.torch,
        }
        transcription_ready = deps.ok
    except Exception as e:
        deps_info["error"] = str(e)

    memory_info: dict = {}
    task_info: dict = {}
    try:
        from python.resource_manager import (
            get_memory_snapshot,
            get_model_lifecycle,
            get_task_queue,
        )

        snap = get_memory_snapshot()
        memory_info = {
            "total_mb": round(snap.total_mb),
            "available_mb": round(snap.available_mb),
            "used_percent": round(snap.used_percent, 1),
            "pressure": snap.pressure.value,
            "process_rss_mb": round(snap.process_rss_mb),
        }
        lifecycle = get_model_lifecycle()
        tq = get_task_queue()
        task_info = {
            "loaded_models": lifecycle.loaded_names(),
            "models_est_mb": round(lifecycle.total_est_mb()),
            "queue_depth": tq.queue_depth,
            "is_busy": tq.is_busy,
        }
    except Exception as e:
        memory_info["error"] = str(e)

    # Ollama connectivity check (non-blocking, short timeout)
    ollama_status = "unknown"
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            ollama_status = "connected" if resp.status == 200 else "error"
    except Exception:
        ollama_status = "disconnected"

    if _readiness.is_ready:
        status = "ok" if transcription_ready else "degraded"
    else:
        status = "starting"

    return {
        "status": status,
        "service": "axew-ai",
        "version": "0.1.0",
        "pid": os.getpid(),
        "phase": _readiness.phase.value,
        "is_live": _readiness.is_live,
        "is_ready": _readiness.is_ready,
        "uptime_sec": round(time.time() - _START_TIME),
        "transcription_ready": transcription_ready,
        "ollama": ollama_status,
        "dependencies": deps_info,
        "memory": memory_info,
        "tasks": task_info,
    }


@app.post("/health/gc")
async def force_gc():
    """Force garbage collection and model eviction when under memory pressure."""
    try:
        from python.resource_manager import force_gc as do_gc, get_memory_snapshot

        before = get_memory_snapshot()
        do_gc()
        after = get_memory_snapshot()
        return {
            "status": "ok",
            "before_rss_mb": round(before.process_rss_mb),
            "after_rss_mb": round(after.process_rss_mb),
            "freed_mb": round(before.process_rss_mb - after.process_rss_mb),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/health/unload-models")
async def unload_models():
    """Emergency model unload to reclaim RAM."""
    try:
        from python.retrieval.model_registry import ModelRegistry

        ModelRegistry().unload_all()
        from python.resource_manager import force_gc

        force_gc()
        return {"status": "ok", "message": "All models unloaded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/health/diagnostics")
async def startup_diagnostics():
    """Full startup diagnostic report for debugging."""
    return {
        "startup": _STARTUP_DIAG,
        "lifecycle": {
            "phase": _readiness.phase.value,
            "is_live": _readiness.is_live,
            "is_ready": _readiness.is_ready,
            "phase_history": _readiness.phase_history,
        },
        "config": {
            "port": settings.port,
            "device": settings.device,
            "embed_model": settings.embed_model,
            "cross_model": settings.cross_model,
            "max_models": settings.max_models,
            "whisper_model": settings.default_whisper_model,
            "skip_multimodal": settings.skip_multimodal,
            "skip_sentiment": settings.skip_sentiment_models,
        },
    }
