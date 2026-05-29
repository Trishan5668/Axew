"""
Retrieval debug endpoint — inspect every stage of the retrieval pipeline.

POST /debug/retrieval
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from routers.analysis import get_embed_model
from routers.execution import (
    SemanticSearchRequest,
    TranscriptSegmentInput,
    merge_matches,
    semantic_search,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class DebugSegmentInput(BaseModel):
    id: str
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class DebugRetrievalRequest(BaseModel):
    query: str
    top_k: int = 10
    segments: List[DebugSegmentInput] = Field(default_factory=list)
    video_id: Optional[str] = None
    session_id: Optional[str] = None
    min_score: float = 0.22
    use_intelligence: bool = True


class RetrievalFeedbackRequest(BaseModel):
    session_id: str
    feedback: str
    query: Optional[str] = None
    video_id: Optional[str] = None


class RetrievedChunkOut(BaseModel):
    chunk_id: str
    text: str
    score_bm25: float = 0.0
    score_semantic: float = 0.0
    score_reranked: float = 0.0
    confidence: float = 0.0
    start_sec: float
    end_sec: float
    speaker: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    events: List[str] = Field(default_factory=list)


class FinalWindowOut(BaseModel):
    start_sec: float
    end_sec: float
    confidence: float = 0.0


class DebugRetrievalResponse(BaseModel):
    query: str
    parsed_intent: Dict[str, Any]
    retrieved_chunks: List[RetrievedChunkOut]
    final_window: FinalWindowOut
    pipeline_trace: List[str]
    session_id: Optional[str] = None
    confidence_grade: Optional[str] = None
    media_duration: float = 0.0


def _classify_query_type(query: str) -> str:
    lower = query.lower()
    if any(w in lower for w in ("give", "hand", "pay", "receive", "transfer")):
        return "entity_action"
    if any(w in lower for w in ("laugh", "cry", "emotional", "angry", "tearful", "fear")):
        return "emotional"
    if any(w in lower for w in ("first time", "last time", "around", "minutes in")):
        return "temporal"
    if any(w in lower for w in ("audience", "applause", "cheering", "booing")):
        return "audience"
    if any(w in lower for w in ("interviewer", "host", "when he says", "when she says")):
        return "speaker_specific"
    if any(w in lower for w in ("viral", "hook", "short")):
        return "hook_detection"
    return "generic"


def _extract_entities_simple(text: str) -> List[str]:
    """Lightweight entity extraction for debug parsed_intent (Phase 2 will replace)."""
    import re

    entities: List[str] = []
    # Monetary amounts
    for m in re.finditer(r"\d+\s*(?:rupees?|crore|dollars?|\$|₹)", text, re.I):
        entities.append(m.group().strip())
    # Capitalized multi-word names
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        entities.append(m.group(1))
    return list(dict.fromkeys(entities))


def _extract_actions_simple(text: str) -> List[str]:
    lower = text.lower()
    action_verbs = [
        "give", "hand", "pay", "receive", "transfer", "laugh", "cry",
        "shout", "point", "stand", "sit", "announce", "deny", "applaud",
    ]
    return [v for v in action_verbs if v in lower]


@router.post("/retrieval", response_model=DebugRetrievalResponse)
async def debug_retrieval(request: DebugRetrievalRequest) -> DebugRetrievalResponse:
    """
    Debug retrieval pipeline — returns full trace with entities, events, and scores.
    Uses Phase 2 intelligence layer when use_intelligence=True and python/ is available.
    """
    trace: List[str] = []
    trace.append("stage=query_received")

    if not request.segments:
        raise HTTPException(
            status_code=400,
            detail="segments required — pass transcript segments for debug retrieval",
        )

    # Try intelligence orchestrator (Phases 4–6: hybrid, rerank, timestamp refinement)
    if request.use_intelligence:
        try:
            import sys
            from pathlib import Path

            project_root = Path(__file__).resolve().parents[3]
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from python.intelligence.context_manager import get_session
            from python.intelligence.extraction_pipeline import extract_intelligence
            from python.evaluation.quality_scorer import score_from_response
            from python.retrieval.orchestrator import RetrievalOrchestrator
            from python.retrieval.video_index import VideoIndex

            seg_dicts = [
                {
                    "id": s.id,
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "speaker": s.speaker,
                }
                for s in request.segments
            ]

            import asyncio

            video_id = request.video_id or "debug"
            ctx_mgr = get_session(request.session_id)

            artifacts = await extract_intelligence(
                seg_dicts, video_id=video_id, skip_topic_label=True
            )
            index = VideoIndex(artifacts, video_id)
            index.index()
            orch = RetrievalOrchestrator(index, seg_dicts, enable_refinement=True, multimodal=None)
            response = await orch.retrieve(
                request.query,
                top_k=request.top_k,
                context=ctx_mgr.context,
            )
            parsed = response.parsed_query

            parsed_intent: Dict[str, Any] = parsed.model_dump()
            parsed_intent["retrieval_strategy"] = parsed.retrieval_strategy
            trace.extend(response.pipeline_trace)

            segment_by_id = {s.id: s for s in request.segments}
            retrieved_chunks: List[RetrievedChunkOut] = []
            for i, cand in enumerate(response.candidates):
                chunk = cand.chunk
                matched_seg = None
                for s in request.segments:
                    if s.start <= cand.start_sec <= s.end or s.start <= cand.end_sec <= s.end:
                        matched_seg = s
                        break
                retrieved_chunks.append(
                    RetrievedChunkOut(
                        chunk_id=cand.chunk_id,
                        text=cand.text or (matched_seg.text if matched_seg else ""),
                        score_bm25=cand.score_bm25,
                        score_semantic=cand.score_dense,
                        score_reranked=cand.score_fused,
                        confidence=cand.score_fused,
                        start_sec=cand.start_sec,
                        end_sec=cand.end_sec,
                        speaker=chunk.speaker_id if chunk else (matched_seg.speaker if matched_seg else None),
                        entities=cand.entities or (chunk.entities if chunk else []),
                        events=cand.events or (chunk.events if chunk else []),
                    )
                )

            conf = response.confidence.composite if response.confidence else response.final_window.confidence
            if response.confidence:
                parsed_intent["confidence_breakdown"] = response.confidence.model_dump()

            match_text = retrieved_chunks[0].text if retrieved_chunks else ""
            score_from_response(response, video_id, segment_text=match_text)

            return DebugRetrievalResponse(
                query=request.query,
                parsed_intent=parsed_intent,
                retrieved_chunks=retrieved_chunks,
                final_window=FinalWindowOut(
                    start_sec=response.final_window.start_sec,
                    end_sec=response.final_window.end_sec,
                    confidence=conf,
                ),
                pipeline_trace=trace,
                session_id=response.session_id,
                confidence_grade=response.confidence.grade if response.confidence else None,
                media_duration=artifacts.document.duration_sec,
            )
        except Exception as e:
            logger.warning("Phase 4 orchestrator unavailable, falling back to baseline: %s", e)
            trace.append(f"stage=phase4_fallback reason={e}")

    query_type = _classify_query_type(request.query)
    entities = _extract_entities_simple(request.query)
    actions = _extract_actions_simple(request.query)

    parsed_intent: Dict[str, Any] = {
        "original_query": request.query,
        "query_type": query_type,
        "entities": entities,
        "actions": actions,
        "emotions": [],
        "temporal_qualifiers": [],
        "speaker_references": [],
        "monetary_amounts": [e for e in entities if any(c.isdigit() for c in e)],
        "retrieval_strategy": "baseline_semantic",
        "confidence": 0.5,
    }
    trace.append(f"stage=query_parsed type={query_type}")

    seg_inputs = [
        TranscriptSegmentInput(id=s.id, start=s.start, end=s.end, text=s.text)
        for s in request.segments
    ]

    search_req = SemanticSearchRequest(
        query=request.query,
        segments=seg_inputs,
        top_k=request.top_k,
        min_score=request.min_score,
    )

    try:
        result = await semantic_search(search_req)
        trace.append("stage=semantic_search_complete")
    except Exception as e:
        logger.error("Debug retrieval semantic search failed: %s", e)
        trace.append(f"stage=semantic_search_error error={e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    raw_matches = result.get("matches", [])
    trace.append(f"stage=matches_found count={len(raw_matches)}")

    segment_by_id = {s.id: s for s in request.segments}
    retrieved_chunks: List[RetrievedChunkOut] = []

    for rank, m in enumerate(raw_matches):
        seg = segment_by_id.get(m["segment_id"])
        speaker = seg.speaker if seg else None
        retrieved_chunks.append(
            RetrievedChunkOut(
                chunk_id=m["segment_id"],
                text=m["text"],
                score_bm25=0.0,
                score_semantic=m["score"],
                score_reranked=m["score"],
                confidence=m["score"],
                start_sec=m["start"],
                end_sec=m["end"],
                speaker=speaker,
                entities=[],
                events=[],
            )
        )

    if raw_matches:
        from routers.execution import SemanticMatchResult

        matches = [SemanticMatchResult(**m) for m in raw_matches]
        start, end, confidence, _ = merge_matches(matches)
        trace.append(f"stage=window_merged start={start:.2f} end={end:.2f}")
    else:
        start, end, confidence = 0.0, 0.0, 0.0
        trace.append("stage=no_matches")

    trace.append("stage=complete")

    return DebugRetrievalResponse(
        query=request.query,
        parsed_intent=parsed_intent,
        retrieved_chunks=retrieved_chunks,
        final_window=FinalWindowOut(
            start_sec=start,
            end_sec=end,
            confidence=confidence,
        ),
        pipeline_trace=trace,
    )


@router.post("/retrieval/feedback")
async def retrieval_feedback(request: RetrievalFeedbackRequest) -> Dict[str, str]:
    try:
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from python.evaluation.quality_scorer import QualityScorer
        from python.intelligence.context_manager import get_session

        QualityScorer().record_feedback(
            request.session_id,
            request.feedback,
            query=request.query or "",
            video_id=request.video_id or "",
        )
        get_session(request.session_id).record_feedback(request.feedback)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/quality-dashboard")
async def quality_dashboard(days: int = 7) -> Dict[str, Any]:
    try:
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from python.evaluation.quality_scorer import QualityScorer
        from python.retrieval.native_temporal import using_native

        dashboard = QualityScorer().rolling_dashboard(days=days)
        dashboard["native_temporal"] = using_native()
        return dashboard
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
