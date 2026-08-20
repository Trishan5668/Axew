"""AXEW <-> OpusClip integration.

Endpoints:
    GET /opusclip/health
        Fast, never-throwing upstream health probe for UI status badges.

    POST /opusclip/process
        Validate credits, register an AXEW job, kick off background processing,
        return 202 Accepted with ``{job_id, ...}``.

    GET /opusclip/status/{job_id}
        Return the current aggregated stage of the job.

    GET /opusclip/result/{job_id}
        Return normalized enhanced clips after ``stage == "completed"``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from config import settings
from middleware.auth import CurrentUser
from middleware.cloud_config import CloudConfigError, cloud_settings
from middleware.supabase_client import rpc, supabase_admin
from models.opusclip import (
    ClipRange,
    JobAcceptedResponse,
    JobResultResponse,
    JobStatusResponse,
    OpusClipRequest,
    OpusClipResult,
    PerProjectStatus,
)
from services.opusclip_client import (
    OpusClipClient,
    OpusClipError,
    stage_is_terminal_failed,
    stage_is_terminal_ok,
)
from services.opusclip_jobs import (
    Job,
    JobLimitExceededError,
    get_job_store,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class OpusClipHealth(BaseModel):
    status: str
    service: str = "opusclip"
    api_key_present: bool = False
    reason: Optional[str] = None


async def check_opusclip_reachable(
    api_key: str,
    base_url: str,
    timeout: float,
) -> Tuple[bool, Optional[str]]:
    """Probe the upstream OpusClip API.

    Returns ``(reachable, reason)``. ``reason`` is ``None`` when reachable,
    otherwise a machine-readable code used by the frontend.
    """
    try:
        import httpx
    except Exception:  # pragma: no cover - httpx is a hard dependency
        return False, "backend_unreachable"

    url = f"{base_url.rstrip('/')}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code in (401, 403):
            return False, "authentication_failed"
        if resp.status_code >= 400:
            return False, "service_unavailable"
        return True, None
    except Exception as exc:
        logger.debug("OpusClip reachability probe failed: %s", exc)
        return False, "backend_unreachable"


@router.get("/health", response_model=OpusClipHealth)
async def opusclip_health() -> OpusClipHealth:
    """Return OpusClip integration status without exposing the API key."""
    api_key = settings.opusclip_api_key or ""
    api_key_present = bool(api_key.strip())

    if not api_key_present:
        return OpusClipHealth(
            status="offline",
            api_key_present=False,
            reason="missing_api_key",
        )

    timeout = float(settings.opusclip_health_timeout_sec or 0.8)
    try:
        reachable, reason = await asyncio.wait_for(
            check_opusclip_reachable(api_key, settings.opusclip_base_url, timeout),
            timeout=timeout + 0.2,
        )
    except asyncio.TimeoutError:
        reachable, reason = False, "backend_unreachable"
    except Exception as exc:
        logger.warning("OpusClip health check error: %s", exc)
        reachable, reason = False, "service_unavailable"

    if reachable:
        return OpusClipHealth(status="online", api_key_present=True, reason=None)

    return OpusClipHealth(
        status="offline",
        api_key_present=True,
        reason=reason or "service_unavailable",
    )


# How often the worker polls EACH OpusClip project's status. The OpusClip
# rate limit is 30 req/min; with 5 projects we send at most 5 req per tick.
_WORKER_POLL_INTERVAL_S = 15.0
_WORKER_MAX_RUNTIME_S = 30 * 60.0


async def _run_job(job_id: str, request: OpusClipRequest) -> None:
    """Drive a job from queued to completed/failed."""
    store = get_job_store()
    job = store.get(job_id)
    if job is None:
        logger.error("_run_job: job %s vanished before worker started", job_id)
        return

    try:
        store.update(job_id, stage="submitting")

        async with OpusClipClient() as client:
            for idx, project in enumerate(job.projects):
                try:
                    project_id = await client.create_clip_project(request, project.source_range)
                except OpusClipError as exc:
                    logger.error("Job %s project %d submission failed: %s", job_id, idx, exc)
                    store.set_project(job_id, idx, stage="STALLED", last_error=str(exc))
                    store.update(job_id, stage="failed", error_message=str(exc))
                    return
                store.set_project(job_id, idx, project_id=project_id, stage="QUEUED")

            store.update(job_id, stage="processing")

            deadline = asyncio.get_event_loop().time() + _WORKER_MAX_RUNTIME_S
            while True:
                if asyncio.get_event_loop().time() > deadline:
                    store.update(
                        job_id,
                        stage="failed",
                        error_message=(
                            "OpusClip did not finish in time. "
                            "Please retry; you have not been charged."
                        ),
                    )
                    return

                still_running = False
                refreshed = store.get(job_id)
                if refreshed is None:
                    return
                for idx, project in enumerate(refreshed.projects):
                    if not project.project_id:
                        continue
                    if stage_is_terminal_ok(project.stage) or stage_is_terminal_failed(project.stage):
                        continue

                    try:
                        stage = await client.get_project_stage(project.project_id)
                    except OpusClipError as exc:
                        logger.warning(
                            "Job %s project %s status check failed: %s",
                            job_id,
                            project.project_id,
                            exc,
                        )
                        if exc.retryable:
                            still_running = True
                            continue
                        store.set_project(job_id, idx, stage="STALLED", last_error=str(exc))
                        store.update(job_id, stage="failed", error_message=str(exc))
                        return

                    store.set_project(job_id, idx, stage=stage)

                    if stage_is_terminal_failed(stage):
                        msg = f"OpusClip stalled on clip {idx + 1} of {len(refreshed.projects)}."
                        store.update(job_id, stage="failed", error_message=msg)
                        return
                    if not stage_is_terminal_ok(stage):
                        still_running = True

                if not still_running:
                    break

                await asyncio.sleep(_WORKER_POLL_INTERVAL_S)

            refreshed = store.get(job_id)
            if refreshed is None:
                return
            for idx, project in enumerate(refreshed.projects):
                if not project.project_id:
                    continue
                try:
                    results = await client.get_exportable_clips(
                        project.project_id,
                        project.source_range,
                    )
                except OpusClipError as exc:
                    logger.error(
                        "Job %s project %s fetch results failed: %s",
                        job_id,
                        project.project_id,
                        exc,
                    )
                    store.update(job_id, stage="failed", error_message=str(exc))
                    return
                store.set_project(job_id, idx, results=results)

        try:
            new_balance = _deduct_credits(job.user_id, job.minutes_required)
        except HTTPException as exc:
            logger.error("Job %s credit deduction failed: %s", job_id, exc.detail)
            store.update(job_id, stage="failed", error_message=str(exc.detail))
            return

        store.update(
            job_id,
            stage="completed",
            credits_deducted=True,
            credits_remaining_at_completion=new_balance,
        )
        logger.info(
            "Job %s completed: deducted %.2f minutes, balance now %.2f",
            job_id,
            job.minutes_required,
            new_balance,
        )

    except Exception as exc:  # pragma: no cover - last-resort safety
        logger.exception("Job %s worker crashed: %s", job_id, exc)
        store.update(
            job_id,
            stage="failed",
            error_message="Internal error processing your clips. Please retry.",
        )


def _read_credit_balance(user_id: str) -> float:
    resp = rpc("get_credit_summary", {"p_user_id": user_id})
    data = resp.data or []
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AXEW profile found for this account. Please sign in again.",
        )
    return float(data[0]["credit_balance"])


def _deduct_credits(user_id: str, minutes: float) -> float:
    resp = rpc("deduct_credits", {"p_user_id": user_id, "p_minutes": minutes})
    try:
        return float(resp.data) if resp.data is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _total_minutes(ranges: list[ClipRange]) -> float:
    return round(sum(r.duration_seconds for r in ranges) / 60.0, 4)


def _projects_view(job: Job) -> list[PerProjectStatus]:
    return [
        PerProjectStatus(
            project_id=p.project_id or "",
            source_range=p.source_range,
            stage=p.stage or "PENDING",
            last_error=p.last_error,
        )
        for p in job.projects
    ]


@router.post(
    "/process",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_clip_job(
    body: OpusClipRequest,
    request: Request,
    current_user: CurrentUser,
) -> JobAcceptedResponse:
    """Register an OpusClip job and start background processing."""
    if str(current_user.user_id) != str(body.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only process clips for your own account.",
        )

    try:
        cloud_settings().require_opusclip()
        supabase_admin()
    except CloudConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    minutes_required = _total_minutes(body.clips)
    balance = _read_credit_balance(str(body.user_id))
    if balance < minutes_required:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Insufficient credits ({balance:.2f} left, "
                f"{minutes_required:.2f} required). Buy more in Billing."
            ),
        )

    store = get_job_store()
    try:
        job = store.create(
            user_id=str(body.user_id),
            ranges=list(body.clips),
            minutes_required=minutes_required,
        )
    except JobLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

    task = asyncio.create_task(_run_job(job.job_id, body), name=f"opusclip:{job.job_id}")
    store.update(job.job_id, background_task=task)

    base = str(request.base_url).rstrip("/")
    return JobAcceptedResponse(
        job_id=job.job_id,
        stage="queued",
        minutes_required=minutes_required,
        credits_balance_before=balance,
        poll_status_url=f"{base}/opusclip/status/{job.job_id}",
        poll_result_url=f"{base}/opusclip/result/{job.job_id}",
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, current_user: CurrentUser) -> JobStatusResponse:
    job = _require_job(job_id, current_user)
    return JobStatusResponse(
        job_id=job.job_id,
        stage=job.stage,
        minutes_required=job.minutes_required,
        submitted_at=job.submitted_at,
        updated_at=job.updated_at,
        projects=_projects_view(job),
        error_message=job.error_message,
    )


@router.get("/result/{job_id}", response_model=JobResultResponse)
async def get_job_result(job_id: str, current_user: CurrentUser) -> JobResultResponse:
    job = _require_job(job_id, current_user)

    if job.stage == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or "OpusClip job failed.",
        )
    if job.stage != "completed":
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=(
                f"Job is still {job.stage}. Poll /opusclip/status/{job.job_id} "
                "until stage is 'completed'."
            ),
        )

    all_results: list[OpusClipResult] = []
    for project in job.projects:
        all_results.extend(project.results)

    return JobResultResponse(
        job_id=job.job_id,
        stage=job.stage,
        minutes_processed=job.minutes_required,
        credits_remaining=job.credits_remaining_at_completion or 0.0,
        results=all_results,
    )


def _require_job(job_id: str, current_user: Any) -> Job:
    """Fetch a job, enforcing ownership without leaking cross-user existence."""
    job = get_job_store().get_for_user(job_id, str(current_user.user_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OpusClip job not found.",
        )
    return job
