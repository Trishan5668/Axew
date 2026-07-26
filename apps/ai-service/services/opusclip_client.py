"""HTTP client for the OpusClip public API.

Responsibilities:
  * Authenticate with ``OPUSCLIP_API_KEY`` from the AI-service environment.
    The key is read lazily through ``middleware.cloud_config`` so it is
    NEVER hardcoded and NEVER read from anywhere else.
  * Map an AXEW ``ClipRange`` to an OpusClip "clip project" creation call.
  * Defensively parse OpusClip's responses — the documented schema is
    nested + camelCase + occasionally inconsistent, so every field is
    accessed with sensible fallbacks.
  * Retry transient failures (5xx, 429, network timeouts) with capped
    exponential backoff. 4xx errors except 429 are NOT retried.
  * Convert OpusClip stages into a normalized terminal/non-terminal flag.

Public endpoints used:
  POST  /api/clip-projects                              create project
  GET   /api/clip-projects/{projectId}                  fetch project status
  GET   /api/exportable-clips?q=findByProjectId&...     fetch finished clips

We deliberately do NOT use OpusClip's resumable-upload endpoints; AXEW
hosts the source media itself and sends ``videoUrl`` as a publicly
reachable HTTPS URL.

References:
  https://help.opus.pro/api-reference/overview
  https://help.opus.pro/api-reference/endpoints/create-project
  https://help.opus.pro/api-reference/playground/get-clips
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

import httpx

from middleware.cloud_config import cloud_settings
from models.opusclip import ClipRange, OpusClipRequest, OpusClipResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage normalization
# ---------------------------------------------------------------------------

# OpusClip documents these enum values; we map them into AXEW-side states.
# https://opusclip-c3e48c12.mintlify.app/api-reference/playground/create-project
_TERMINAL_OK_STAGES: frozenset[str] = frozenset({"COMPLETE"})
_TERMINAL_FAILED_STAGES: frozenset[str] = frozenset({"STALLED"})
_IN_PROGRESS_STAGES: frozenset[str] = frozenset({
    "PENDING", "QUEUED", "CURATE", "REFINE", "RENDER", "UPLOAD",
})


def stage_is_terminal_ok(stage: str | None) -> bool:
    return (stage or "").upper() in _TERMINAL_OK_STAGES


def stage_is_terminal_failed(stage: str | None) -> bool:
    return (stage or "").upper() in _TERMINAL_FAILED_STAGES


def stage_is_in_progress(stage: str | None) -> bool:
    return (stage or "").upper() in _IN_PROGRESS_STAGES


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class OpusClipError(Exception):
    """Raised when an OpusClip API call returns a non-recoverable error.

    Carries enough structured detail for the router to translate it into
    an HTTPException with a user-facing message + the upstream code.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        upstream_code: str | None = None,
        retryable: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.upstream_code = upstream_code
        self.retryable = retryable
        self.payload = payload

    def __str__(self) -> str:
        bits = [self.message]
        if self.upstream_code:
            bits.append(f"code={self.upstream_code}")
        if self.status_code:
            bits.append(f"http={self.status_code}")
        return " ".join(bits)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    initial_backoff_s: float = 1.0
    max_backoff_s: float = 30.0
    jitter_s: float = 0.5


_RETRY = RetryPolicy()
# OpusClip publishes a 30 req/min rate limit; respect Retry-After.
_RATE_LIMITED_STATUS = 429
_TRANSIENT_5XX = frozenset({500, 502, 503, 504})


async def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    if retry_after is not None and retry_after > 0:
        # honor server-provided Retry-After exactly (plus a tiny jitter so
        # parallel jobs don't pile back in on the same second)
        delay = retry_after + random.uniform(0, _RETRY.jitter_s)
    else:
        delay = min(_RETRY.initial_backoff_s * (2 ** (attempt - 1)), _RETRY.max_backoff_s)
        delay += random.uniform(0, _RETRY.jitter_s)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Defensive value extraction helpers
# ---------------------------------------------------------------------------


def _first_str(obj: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        v = obj.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _first_number(obj: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        v = obj.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _user_facing(message: str, payload: dict[str, Any] | None, status_code: int | None) -> str:
    code = (payload or {}).get("code") or (payload or {}).get("errorCode") or (payload or {}).get("error")
    msg = (payload or {}).get("message") or (payload or {}).get("detail")
    parts = [message]
    if msg:
        parts.append(f"({msg})")
    if code:
        parts.append(f"[code={code}]")
    if status_code:
        parts.append(f"[http={status_code}]")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Request payload builders (AXEW -> OpusClip)
# ---------------------------------------------------------------------------


def build_create_project_payload(request: OpusClipRequest, clip: ClipRange) -> dict[str, Any]:
    """Build the body of POST /api/clip-projects for a single AXEW ClipRange.

    Notes on the mapping:
      * ``curationPref.range.startSec/endSec`` constrain OpusClip to the
        AXEW-selected window. We DO NOT pass ``skipCurate=true``: that
        bypasses OpusClip's viral curation entirely, which is the whole
        reason we forward the request. Within the range OpusClip is free
        to pick its own sub-clips.
      * ``clipDurations`` caps each generated short to <=90s.
      * ``renderPref.quickstartConfig.enableRemoveFillerWords`` is the
        documented filler-removal toggle.
      * ``renderPref.layoutAspectRatio`` defaults to ``portrait`` for
        short-form social.
      * ``topicKeywords`` is ClipBasic-only; ``customPrompt`` is
        ClipAnything-only — we include exactly one based on model.
      * ``uploadedVideoAttr.title`` carries the AXEW clip label so the
        OpusClip dashboard is searchable.
    """
    curation: dict[str, Any] = {
        "model": request.curation_model,
        "clipDurations": [[0, 90]],
        "range": {
            "startSec": float(clip.start_seconds),
            "endSec": float(clip.end_seconds),
        },
        "genre": "Auto",
        "skipCurate": False,
    }
    if request.curation_model == "ClipBasic":
        if request.topic_keywords:
            curation["topicKeywords"] = list(request.topic_keywords)
    else:  # ClipAnything
        if request.custom_prompt:
            curation["customPrompt"] = request.custom_prompt

    render: dict[str, Any] = {
        "layoutAspectRatio": request.aspect_ratio,
        "enableCaption": request.enable_captions,
        "enableBroll": request.enable_broll,
    }
    if request.remove_fillers:
        render["quickstartConfig"] = {"enableRemoveFillerWords": True}

    payload: dict[str, Any] = {
        "videoUrl": str(request.video_url),
        "curationPref": curation,
        "renderPref": render,
        "importPref": {"sourceLang": request.source_language},
        "uploadedVideoAttr": {
            "title": clip.label or f"AXEW clip {clip.start_seconds:.1f}-{clip.end_seconds:.1f}s",
        },
    }
    if request.brand_template_id:
        payload["brandTemplateId"] = request.brand_template_id
    return payload


# ---------------------------------------------------------------------------
# Response parsers (OpusClip -> AXEW models). DEFENSIVE.
# ---------------------------------------------------------------------------


def parse_project_id(payload: dict[str, Any] | None) -> str | None:
    """Extract the project id from POST /api/clip-projects response.

    Documented field is ``projectId``; ``id`` is the same value but kept
    around because some OpusClip endpoints expose ``id`` only. Some
    error / wrapped responses nest the project under ``data``.
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("data"), dict):
        nested = parse_project_id(payload["data"])
        if nested:
            return nested
    return _first_str(payload, "projectId", "id", "project_id")


def parse_project_stage(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("data"), dict):
        nested = parse_project_stage(payload["data"])
        if nested:
            return nested
    return _first_str(payload, "stage", "status", "state")


def parse_exportable_clips(raw: Any, source: ClipRange) -> list[OpusClipResult]:
    """Normalize the GET /api/exportable-clips response.

    The endpoint returns an array directly (per the OpenAPI spec) but some
    intermediaries wrap it in ``{data: [...]}`` — handle both.
    """
    items: list[dict[str, Any]]
    if isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    elif isinstance(raw, dict):
        nested = raw.get("data") or raw.get("clips") or raw.get("items")
        if isinstance(nested, list):
            items = [x for x in nested if isinstance(x, dict)]
        else:
            items = []
    else:
        items = []

    results: list[OpusClipResult] = []
    for clip in items:
        try:
            results.append(_parse_one_clip(clip, source))
        except Exception as exc:
            # Skip individual malformed clips rather than failing the whole
            # batch — we still want to surface the good ones.
            logger.warning("Skipping malformed OpusClip clip: %s", exc, extra={"clip": clip})
    return results


def _parse_one_clip(clip: dict[str, Any], source: ClipRange) -> OpusClipResult:
    """Single ExportableClipRepresentation -> normalized OpusClipResult.

    Field mapping (defensive — try the documented name first, then the
    most-commonly-observed alternates):

      clip_url       <- uriForExport | downloadUrl | output.url | uriForPreview
      preview_url    <- uriForPreview | previewUrl
      duration_sec   <- durationMs/1000 | durationSeconds | duration
      title          <- title | name
      description    <- description | summary
      hashtags       <- hashtags
      keywords       <- keywords (list of str)
      transcript     <- text | transcript
      viral_score    <- viralityScore | viralScore | score | scores.viral
                       (OPTIONAL — public docs don't expose this; we
                       surface it when the API does and clamp 0..100)
    """
    export_url = _first_str(clip, "uriForExport", "downloadUrl", "exportUrl")
    if not export_url:
        output = clip.get("output")
        if isinstance(output, dict):
            export_url = _first_str(output, "url", "downloadUrl")
    preview_url = _first_str(clip, "uriForPreview", "previewUrl")
    chosen_url = export_url or preview_url
    if not chosen_url:
        raise ValueError("clip missing both uriForExport and uriForPreview")

    duration_ms = _first_number(clip, "durationMs")
    duration_s = (
        duration_ms / 1000.0 if duration_ms is not None
        else _first_number(clip, "durationSeconds", "duration") or 0.0
    )

    raw_keywords = clip.get("keywords")
    keywords: list[str] = []
    if isinstance(raw_keywords, list):
        keywords = [k for k in raw_keywords if isinstance(k, str)]

    viral_score: float | None = _first_number(clip, "viralityScore", "viralScore", "score")
    if viral_score is None:
        scores = clip.get("scores")
        if isinstance(scores, dict):
            viral_score = _first_number(scores, "viral", "virality", "overall")
    # The public API documents virality on a 0..99 scale; clamp defensively.
    if viral_score is not None:
        viral_score = max(0.0, min(100.0, float(viral_score)))

    return OpusClipResult(
        opusclip_id=str(clip.get("id") or clip.get("clipId") or ""),
        project_id=str(clip.get("projectId") or ""),
        clip_url=chosen_url,  # type: ignore[arg-type] — pydantic validates HttpUrl
        preview_url=preview_url,  # type: ignore[arg-type]
        duration_seconds=float(duration_s),
        title=_first_str(clip, "title", "name"),
        description=_first_str(clip, "description", "summary"),
        hashtags=_first_str(clip, "hashtags"),
        keywords=keywords,
        transcript_text=_first_str(clip, "text", "transcript"),
        viral_score=viral_score,
        source_range=source,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OpusClipClient:
    """Async client around the OpusClip API.

    One instance is meant to live for the duration of a single AXEW job —
    construct via ``async with OpusClipClient() as client:``. The
    underlying ``httpx.AsyncClient`` is created lazily so importing this
    module never opens a connection.

    All credentials are read fresh from ``cloud_settings()`` so a key
    rotation in the running process is picked up on the next request.
    """

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OpusClipClient:
        settings = cloud_settings()
        settings.require_opusclip()
        self._http = httpx.AsyncClient(
            base_url=settings.opusclip_base_url,
            timeout=self._timeout_s,
        )
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        # Read key from settings on every call so rotation is observed.
        settings = cloud_settings()
        return {
            "Authorization": f"Bearer {settings.opusclip_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AXEW/1.0 (+https://axew.app)",
        }

    # -------- low-level request with retry --------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        assert self._http is not None, "OpusClipClient must be used as async-context-manager"

        last_exc: Exception | None = None
        for attempt in range(1, _RETRY.max_attempts + 1):
            try:
                resp = await self._http.request(
                    method,
                    path,
                    headers=self._headers(),
                    json=json,
                    params=params,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                logger.warning("OpusClip transport error (attempt %d): %s", attempt, exc)
                last_exc = exc
                if attempt == _RETRY.max_attempts:
                    raise OpusClipError(
                        "OpusClip is unreachable. Please retry in a minute.",
                        retryable=True,
                    ) from exc
                await _sleep_backoff(attempt)
                continue

            if resp.status_code == _RATE_LIMITED_STATUS:
                retry_after = _parse_retry_after(resp)
                logger.warning(
                    "OpusClip rate-limited (attempt %d). retry_after=%s", attempt, retry_after,
                )
                if attempt == _RETRY.max_attempts:
                    raise OpusClipError(
                        "OpusClip rate-limited; please retry in a moment.",
                        status_code=429,
                        retryable=True,
                    )
                await _sleep_backoff(attempt, retry_after=retry_after)
                continue

            if resp.status_code in _TRANSIENT_5XX:
                payload = _safe_json(resp)
                logger.warning(
                    "OpusClip transient error %s (attempt %d): %s",
                    resp.status_code, attempt, payload,
                )
                if attempt == _RETRY.max_attempts:
                    raise OpusClipError(
                        _user_facing("OpusClip service temporarily unavailable.", payload, resp.status_code),
                        status_code=resp.status_code,
                        retryable=True,
                        payload=payload if isinstance(payload, dict) else None,
                    )
                await _sleep_backoff(attempt)
                continue

            if resp.status_code >= 400:
                payload = _safe_json(resp)
                # Non-retryable client error (auth, validation, billing, etc.)
                raise OpusClipError(
                    _user_facing("OpusClip rejected the request.", payload, resp.status_code),
                    status_code=resp.status_code,
                    upstream_code=(payload or {}).get("code") if isinstance(payload, dict) else None,
                    retryable=False,
                    payload=payload if isinstance(payload, dict) else None,
                )

            body = _safe_json(resp)
            if body is None:
                raise OpusClipError(
                    f"OpusClip returned non-JSON response (HTTP {resp.status_code}).",
                    status_code=resp.status_code,
                )
            return body

        # exhaustion path — should always go through one of the raises above
        raise OpusClipError(
            "OpusClip request failed after retries.",
            retryable=True,
        ) from last_exc

    # -------- high-level operations --------

    async def create_clip_project(
        self, request: OpusClipRequest, clip: ClipRange,
    ) -> str:
        """Create one OpusClip project for the given clip range.

        Returns the OpusClip ``projectId``. Raises ``OpusClipError`` on
        failure with a user-facing message.
        """
        payload = build_create_project_payload(request, clip)
        logger.info(
            "OpusClip create-project label=%r range=%.2f-%.2fs",
            clip.label, clip.start_seconds, clip.end_seconds,
        )
        body = await self._request("POST", "/api/clip-projects", json=payload)
        if isinstance(body, list):
            body = body[0] if body else {}
        project_id = parse_project_id(body if isinstance(body, dict) else None)
        if not project_id:
            raise OpusClipError(
                "OpusClip did not return a project id. Please retry.",
                payload=body if isinstance(body, dict) else None,
            )
        logger.info("OpusClip project created: %s", project_id)
        return project_id

    async def get_project_stage(self, project_id: str) -> str:
        """Poll the project status. Returns the raw OpusClip stage string."""
        body = await self._request("GET", f"/api/clip-projects/{project_id}")
        stage = parse_project_stage(body if isinstance(body, dict) else None)
        if stage is None:
            raise OpusClipError(
                "OpusClip project status response did not include a stage.",
                payload=body if isinstance(body, dict) else None,
            )
        return stage

    async def get_exportable_clips(
        self, project_id: str, source: ClipRange,
    ) -> list[OpusClipResult]:
        """Fetch and normalize the finished clips for a completed project."""
        body = await self._request(
            "GET",
            "/api/exportable-clips",
            params={"q": "findByProjectId", "projectId": project_id, "pageSize": 50},
        )
        return parse_exportable_clips(body, source)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(resp: httpx.Response) -> Any:
    """Return parsed JSON or None for non-JSON bodies. Never raises."""
    try:
        return resp.json()
    except Exception:
        return None


def _parse_retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
