"""
OpusClip integration health endpoint.

GET /opusclip/health

Exposes a fast (<1s), never-throwing health probe the desktop frontend polls
to render an online/offline status badge. The actual OpusClip API key is NEVER
included in the response — only a boolean indicating whether one is configured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class OpusClipHealth(BaseModel):
    status: str  # "online" | "offline"
    service: str = "opusclip"
    api_key_present: bool = False
    reason: Optional[str] = None


async def check_opusclip_reachable(
    api_key: str,
    base_url: str,
    timeout: float,
) -> Tuple[bool, Optional[str]]:
    """Probe the upstream OpusClip API.

    Returns (reachable, reason). `reason` is None when reachable, otherwise a
    machine-readable code: ``authentication_failed``, ``service_unavailable``
    or ``backend_unreachable``.

    This isolates network I/O so it can be monkeypatched in tests and wrapped
    in a hard timeout by the caller.
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
        if resp.status_code >= 500:
            return False, "service_unavailable"
        if resp.status_code >= 400:
            return False, "service_unavailable"
        return True, None
    except Exception as exc:  # network error, DNS failure, timeout, etc.
        logger.debug("OpusClip reachability probe failed: %s", exc)
        return False, "backend_unreachable"


@router.get("/health", response_model=OpusClipHealth)
async def opusclip_health() -> OpusClipHealth:
    """Return OpusClip integration status.

    Rules:
      * Never exposes the API key — only ``api_key_present``.
      * Always returns quickly (hard-capped by ``opusclip_health_timeout_sec``).
      * Never raises — failures are reported as ``offline`` with a reason.
    """
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
        # Hard cap so the endpoint always responds well under a second even if
        # the underlying probe misbehaves.
        reachable, reason = await asyncio.wait_for(
            check_opusclip_reachable(api_key, settings.opusclip_base_url, timeout),
            timeout=timeout + 0.2,
        )
    except asyncio.TimeoutError:
        reachable, reason = False, "backend_unreachable"
    except Exception as exc:  # absolute safety net
        logger.warning("OpusClip health check error: %s", exc)
        reachable, reason = False, "service_unavailable"

    if reachable:
        return OpusClipHealth(
            status="online",
            api_key_present=True,
            reason=None,
        )

    return OpusClipHealth(
        status="offline",
        api_key_present=True,
        reason=reason or "service_unavailable",
    )
