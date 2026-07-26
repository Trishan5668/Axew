"""Pydantic models for the AXEW <-> OpusClip integration.

These models cover two boundaries:

  1. The AXEW HTTP API surface (what the renderer POSTs / GETs).
  2. A normalized result shape that hides OpusClip's internal field names
     (uriForExport, durationMs, etc.) and converts units (ms → s).

The actual OpusClip wire payloads are parsed defensively in
``services.opusclip_client``; this module only describes what AXEW
itself ingests and emits.

References:
  - POST  https://api.opus.pro/api/clip-projects
  - GET   https://api.opus.pro/api/clip-projects/{projectId}      (stage)
  - GET   https://api.opus.pro/api/exportable-clips?q=findByProjectId&projectId={id}
  - https://help.opus.pro/api-reference/endpoints/create-project
  - https://help.opus.pro/api-reference/playground/get-clips
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

# ---------------------------------------------------------------------------
# Request side — what AXEW sends to /opusclip/process
# ---------------------------------------------------------------------------


class ClipRange(BaseModel):
    """A time range AXEW's own retrieval pipeline has selected for export.

    Times are in seconds relative to the source video. ``label`` is a
    human-readable tag (e.g. a topic name) — purely informational.
    """

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    label: str | None = None

    @field_validator("end_seconds")
    @classmethod
    def _end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_seconds")
        if start is not None and v <= start:
            raise ValueError("end_seconds must be greater than start_seconds")
        return v

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


CurationModel = Literal["ClipBasic", "ClipAnything"]
LayoutAspectRatio = Literal["portrait", "landscape", "square"]


class OpusClipRequest(BaseModel):
    """Body of POST /opusclip/process.

    AXEW already chose the clip ranges; OpusClip is invoked as a downstream
    enhancer. We create ONE OpusClip "clip project" per range using
    ``curationPref.range.{startSec,endSec}`` so OpusClip operates within
    the AXEW-selected window.
    """

    video_url: HttpUrl
    clips: list[ClipRange] = Field(min_length=1)
    user_id: UUID

    # Optional knobs forwarded to OpusClip. Everything safe (never an API
    # key) — the backend layers in the required feature flags.
    curation_model: CurationModel = "ClipBasic"
    aspect_ratio: LayoutAspectRatio = "portrait"
    source_language: str = "auto"
    brand_template_id: str | None = None
    topic_keywords: list[str] = Field(default_factory=list)
    custom_prompt: str | None = None
    remove_fillers: bool = True
    enable_broll: bool = True
    enable_captions: bool = True


# ---------------------------------------------------------------------------
# Response side — what AXEW returns from /status and /result
# ---------------------------------------------------------------------------


JobStage = Literal[
    "queued",        # POST /process accepted, nothing dispatched yet
    "submitting",    # we're issuing /api/clip-projects calls right now
    "processing",    # at least one OpusClip project not yet COMPLETE
    "completed",     # every project COMPLETE, results fetched + normalized
    "failed",        # one or more projects STALLED, or a hard upstream error
    "expired",       # job aged past the in-memory TTL
]


class OpusClipResult(BaseModel):
    """A single AI-enhanced clip ready for preview / import into the timeline.

    Mirrors OpusClip's ``ExportableClipRepresentation`` after normalization:
      - ``duration_seconds`` derived from ``durationMs / 1000``
      - ``clip_url`` prefers ``uriForExport``, falls back to ``uriForPreview``
      - ``viral_score`` is OPTIONAL — the documented public API does not
        currently expose it. We surface it when present (under any of the
        observed field names) and ``None`` otherwise.
    """

    opusclip_id: str = Field(description="OpusClip full id ({projectId}.{curationId})")
    project_id: str
    clip_url: HttpUrl
    preview_url: HttpUrl | None = None
    duration_seconds: float = Field(ge=0.0)
    title: str | None = None
    description: str | None = None
    hashtags: str | None = None
    keywords: list[str] = Field(default_factory=list)
    transcript_text: str | None = None
    viral_score: float | None = Field(default=None, ge=0.0, le=100.0)
    source_range: ClipRange


class PerProjectStatus(BaseModel):
    """OpusClip's reported stage for one of the project IDs in this job."""

    project_id: str
    source_range: ClipRange
    stage: str
    last_error: str | None = None


class JobStatusResponse(BaseModel):
    """Body of GET /opusclip/status/{job_id}."""

    job_id: str
    stage: JobStage
    minutes_required: float
    submitted_at: float
    updated_at: float
    projects: list[PerProjectStatus]
    error_message: str | None = None


class JobResultResponse(BaseModel):
    """Body of GET /opusclip/result/{job_id} (only valid when stage=completed)."""

    job_id: str
    stage: JobStage
    minutes_processed: float
    credits_remaining: float
    results: list[OpusClipResult]


class JobAcceptedResponse(BaseModel):
    """Body of POST /opusclip/process — returned with HTTP 202."""

    job_id: str
    stage: JobStage = "queued"
    minutes_required: float
    credits_balance_before: float
    poll_status_url: str
    poll_result_url: str
