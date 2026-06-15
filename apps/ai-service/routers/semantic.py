"""
Semantic extraction endpoint — multi-stage retrieval pipeline.

POST /api/semantic/extract
GET  /api/semantic/last_debug
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)
router = APIRouter()


class SemanticExtractRequest(BaseModel):
    prompt: str
    media_id: str
    transcript_id: Optional[str] = None
    segments: List[Dict[str, Any]] = Field(default_factory=list)


class SemanticExtractResponse(BaseModel):
    status: str
    time_range: Optional[Dict[str, float]] = None
    confidence: Optional[float] = None
    message: Optional[str] = None
    best_score: Optional[float] = None
    threshold: Optional[float] = None
    debug: Optional[Dict[str, Any]] = None


@router.post("/extract", response_model=SemanticExtractResponse)
async def semantic_extract(request: SemanticExtractRequest) -> SemanticExtractResponse:
    """
    Multi-stage semantic extraction with confidence gating.

    Returns structured JSON for all outcomes — never HTTP 500 for semantic failures.
    """
    from python.models.transcript import TranscriptChunk
    from python.retrieval.pipeline import RetrievalPipeline
    from python.retrieval.timestamp_contract import (
        RetrievalIntegrityError,
        RetrievalLowConfidenceError,
        StrategyExecutionError,
    )

    if not request.segments:
        return SemanticExtractResponse(
            status="error",
            message="No transcript segments provided",
        )

    chunks: List[TranscriptChunk] = []
    for i, seg in enumerate(request.segments):
        chunk = TranscriptChunk.from_segment_dict(seg, index=i)
        if not chunk.words:
            chunk.interpolate_word_timestamps()
        chunks.append(chunk)

    pipeline = RetrievalPipeline()

    try:
        result = pipeline.retrieve(request.prompt, chunks)
        top = result.top_candidate

        return SemanticExtractResponse(
            status="success",
            time_range={
                "start": float(top.expanded_start),
                "end": float(top.expanded_end),
            },
            confidence=float(top.score_final or 0.0),
            debug=result.trace.to_dict(),
        )

    except (RetrievalIntegrityError, RetrievalLowConfidenceError, StrategyExecutionError) as e:
        logger.warning("Semantic retrieval failed explicitly: %s", e)
        return SemanticExtractResponse(
            status="error",
            message=str(e),
        )

    except Exception as e:
        logger.exception("Unexpected semantic extraction error")
        return SemanticExtractResponse(
            status="error",
            message=f"Unexpected error: {str(e)}",
        )


@router.get("/last_debug")
async def get_last_debug() -> Dict[str, Any]:
    """Return full debug payload from the most recent retrieval pipeline run."""
    from python.retrieval.trace import get_traces

    traces = get_traces(1)
    if not traces:
        return {"status": "no_data", "message": "No retrieval has been executed yet"}
    return {"status": "ok", "data": traces[-1].to_dict()}
