import logging
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from routers.analysis import get_embed_model, cosine_similarity

router = APIRouter()
logger = logging.getLogger(__name__)


class TranscriptSegmentInput(BaseModel):
    id: str
    start: float
    end: float
    text: str


class SemanticSearchRequest(BaseModel):
    query: str
    segments: List[TranscriptSegmentInput]
    top_k: int = 8
    min_score: float = 0.25


class SemanticMatchResult(BaseModel):
    segment_id: str
    text: str
    start: float
    end: float
    score: float


class PlanActionsRequest(BaseModel):
    prompt: str
    segments: List[TranscriptSegmentInput] = Field(default_factory=list)
    media_duration: float = 0.0
    padding_seconds: float = 0.4
    video_id: Optional[str] = None
    session_id: Optional[str] = None
    use_intelligence: bool = True
    use_large_reranker: bool = False


class StructuredActionOut(BaseModel):
    action: str
    start: Optional[float] = None
    end: Optional[float] = None
    clipId: Optional[str] = None
    time: Optional[float] = None
    mediaId: Optional[str] = None
    name: Optional[str] = None
    confidence: Optional[float] = None
    matchText: Optional[str] = None
    reasoning: Optional[str] = None
    requiresConfirmation: Optional[bool] = None


class PlanActionsResponse(BaseModel):
    intent: str
    actions: List[StructuredActionOut]
    matches: List[SemanticMatchResult]
    trace: List[str]


_HINDI_DIGITS = {
    "shunya": 0,
    "zero": 0,
    "ek": 1,
    "aik": 1,
    "one": 1,
    "do": 2,
    "two": 2,
    "teen": 3,
    "tin": 3,
    "three": 3,
    "char": 4,
    "chaar": 4,
    "four": 4,
    "paanch": 5,
    "panch": 5,
    "five": 5,
    "che": 6,
    "chhe": 6,
    "six": 6,
    "saat": 7,
    "seven": 7,
    "aath": 8,
    "eight": 8,
    "nau": 9,
    "nine": 9,
    "das": 10,
    "ten": 10,
    "gyarah": 11,
    "eleven": 11,
    "barah": 12,
    "twelve": 12,
    "bees": 20,
    "twenty": 20,
    "tees": 30,
    "thirty": 30,
    "chalis": 40,
    "forty": 40,
    "pachas": 50,
    "fifty": 50,
    "sath": 60,
    "sixty": 60,
    "sattar": 70,
    "seventy": 70,
    "assi": 80,
    "eighty": 80,
    "nabbe": 90,
    "ninety": 90,
}
_HUNDRED_WORDS = {"sau", "so", "hundred"}
_CURRENCY_WORDS = {
    "rupee", "rupees", "rs", "inr", "rupaye", "rupay", "rupaiye", "rupiya", "rupiye",
    "paise", "paisa",
}
_EDITORIAL_WORDS = {
    "keep", "only", "part", "where", "when", "the", "a", "an", "clip", "segment",
    "cut", "show", "extract", "isolate", "just", "scene", "moment", "and", "or",
}


def _fix_ocr_digit_confusions(text: str) -> str:
    return re.sub(
        r"(?<=\d)[oO](?=\d)|(?<=\d)[oO]\b|\b[oO](?=\d)",
        "0",
        text,
    )


def _spoken_amount_to_number(words: list[str]) -> Optional[int]:
    total = 0
    current = 0
    consumed = False
    for word in words:
        w = word.lower()
        if w in {"aur", "and"}:
            continue
        if w in _HINDI_DIGITS:
            current += _HINDI_DIGITS[w]
            consumed = True
        elif w in _HUNDRED_WORDS:
            current = max(current, 1) * 100
            consumed = True
        elif w in {"hazar", "hazaar", "thousand"}:
            total += max(current, 1) * 1000
            current = 0
            consumed = True
        elif w in {"lakh", "lac"}:
            total += max(current, 1) * 100000
            current = 0
            consumed = True
        else:
            return None
    if not consumed:
        return None
    return total + current


def normalize_retrieval_text(text: str) -> str:
    """Normalize transcript/query text for Hinglish money and typo-tolerant matching."""
    lowered = _fix_ocr_digit_confusions(text.lower())
    lowered = re.sub(r"[^\w\s.]", " ", lowered)
    lowered = re.sub(r"\brs\.\b", " rs ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()

    tokens = [token.strip(".") for token in lowered.split()]
    appended: list[str] = []
    for i, tok in enumerate(tokens):
        if tok not in _CURRENCY_WORDS:
            continue
        for window in range(min(6, i), 0, -1):
            phrase = tokens[i - window:i]
            amount = _spoken_amount_to_number(phrase)
            if amount is not None and amount > 0:
                appended.extend([str(amount), f"{amount} rupees", f"{amount} rupaye"])
                break

    normalized = lowered
    if appended:
        normalized = f"{normalized} {' '.join(appended)}"
    return normalized


def lexical_match_score(query: str, text: str) -> float:
    qn = normalize_retrieval_text(query)
    tn = normalize_retrieval_text(text)
    if not qn or not tn:
        return 0.0

    q_amounts = set(re.findall(r"\b\d+(?:\.\d+)?\b", qn))
    t_amounts = set(re.findall(r"\b\d+(?:\.\d+)?\b", tn))
    amount_score = 0.0
    if q_amounts:
        amount_score = 1.0 if q_amounts & t_amounts else 0.0

    q_terms = [
        t for t in re.findall(r"[a-z0-9]+", qn)
        if len(t) > 2 and t not in _EDITORIAL_WORDS and t not in _CURRENCY_WORDS
    ]
    if not q_terms:
        return amount_score

    hits = sum(1 for term in q_terms if term in tn)
    token_score = hits / len(q_terms)

    action_bonus = 0.0
    transfer_terms = ("give", "gives", "gave", "hand", "hands", "handed", "pay", "paid")
    hinglish_transfer = ("lo", "rakhiye", "rakh", "diya", "deta", "dete", "dijiye")
    if any(t in qn for t in transfer_terms) and any(t in tn for t in transfer_terms + hinglish_transfer):
        action_bonus = 0.2

    if q_amounts:
        return min(1.0, (0.65 * amount_score) + (0.35 * token_score) + action_bonus)
    return min(1.0, token_score + action_bonus)


def lexical_search_matches(
    query: str,
    segments: List[TranscriptSegmentInput],
    top_k: int = 8,
    min_score: float = 0.34,
) -> List[SemanticMatchResult]:
    matches: list[SemanticMatchResult] = []
    for seg in segments:
        score = lexical_match_score(query, seg.text)
        if score >= min_score:
            matches.append(
                SemanticMatchResult(
                    segment_id=seg.id,
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    score=score,
                )
            )
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:top_k]


class IntelligentPlanResponse(PlanActionsResponse):
    confidence_grade: Optional[str] = None
    session_id: Optional[str] = None
    debug: Optional[dict] = None


def classify_intent(prompt: str) -> str:
    lower = prompt.lower()
    if re.search(r"keep\s+only|only\s+the\s+part|isolate|extract|show\s+only|just\s+the", lower):
        return "keep_segment"
    if re.search(r"cut\s+silence|remove\s+silence|dead\s+air", lower):
        return "cut_silence"
    if re.search(r"detect\s+scene|scene\s+change|shot\s+boundary", lower):
        return "detect_scenes"
    if re.search(r"transcribe|subtitle|caption", lower):
        return "transcribe"
    if re.search(r"split\s+at|split\s+clip", lower):
        return "split_clip"
    if re.search(r"delete\s+clip|remove\s+clip", lower):
        return "delete_clip"
    return "semantic_extract"


@router.post("/semantic-search")
async def semantic_search(request: SemanticSearchRequest):
    if not request.segments:
        return {"matches": [], "query_embedding_dims": 0}

    try:
        model = get_embed_model()
        query_vec = model.encode(request.query, normalize_embeddings=True)
        texts = [s.text for s in request.segments]
        segment_vecs = model.encode(texts, normalize_embeddings=True)

        scored = []
        for seg, vec in zip(request.segments, segment_vecs):
            semantic_score = float(cosine_similarity(query_vec, vec))
            lexical_score = lexical_match_score(request.query, seg.text)
            score = max(semantic_score, lexical_score)
            if score >= request.min_score:
                scored.append(
                    SemanticMatchResult(
                        segment_id=seg.id,
                        text=seg.text,
                        start=seg.start,
                        end=seg.end,
                        score=score,
                    )
                )

        scored.sort(key=lambda m: m.score, reverse=True)
        matches = scored[: request.top_k]
        logger.info(
            "Semantic search: query=%r matches=%d top_score=%.3f",
            request.query[:80],
            len(matches),
            matches[0].score if matches else 0.0,
        )
        return {
            "matches": [m.model_dump() for m in matches],
            "query_embedding_dims": len(query_vec),
        }
    except Exception as e:
        logger.warning("Semantic model search failed, using lexical fallback: %s", e)
        matches = lexical_search_matches(
            request.query,
            request.segments,
            top_k=request.top_k,
            min_score=request.min_score,
        )
        return {
            "matches": [m.model_dump() for m in matches],
            "query_embedding_dims": 0,
            "fallback": "lexical",
        }


def merge_matches(matches: List[SemanticMatchResult], gap: float = 1.5) -> tuple[float, float, float, str]:
    if not matches:
        return 0.0, 0.0, 0.0, ""
    sorted_m = sorted(matches, key=lambda m: m.start)
    start = sorted_m[0].start
    end = sorted_m[0].end
    best = sorted_m[0]
    texts = [best.text]
    for m in sorted_m[1:]:
        if m.start <= end + gap:
            end = max(end, m.end)
            texts.append(m.text)
            if m.score > best.score:
                best = m
        else:
            break
    confidence = max(m.score for m in sorted_m if m.start <= end and m.end >= start)
    return start, end, confidence, " … ".join(texts[:3])


def _assert_window(start: float, end: float) -> None:
    assert start is not None, "start_time must not be None"
    assert end is not None, "end_time must not be None"
    assert end > start, f"end_time must be greater than start_time ({start} -> {end})"
    assert (end - start) > 0.5, f"duration must exceed 0.5s ({start} -> {end})"


def _timestamp_boundary_trace(
    *,
    anchor_start: float,
    anchor_end: float,
    expanded_start: float,
    expanded_end: float,
    action_start: float,
    action_end: float,
    ffmpeg_start: Optional[float] = None,
    ffmpeg_end: Optional[float] = None,
) -> dict:
    ffmpeg_start = action_start if ffmpeg_start is None else ffmpeg_start
    ffmpeg_end = action_end if ffmpeg_end is None else ffmpeg_end
    stages = [
        ("anchor", anchor_start, anchor_end),
        ("context_expansion", expanded_start, expanded_end),
        ("timeline_action", action_start, action_end),
        ("execution_plan", action_start, action_end),
        ("ffmpeg_request", ffmpeg_start, ffmpeg_end),
    ]
    first_end_divergence = None
    for stage, _start, end in stages[1:]:
        if abs(float(end) - float(anchor_end)) > 1e-3:
            first_end_divergence = stage
            break

    return {
        "anchor_start": anchor_start,
        "anchor_end": anchor_end,
        "expanded_start": expanded_start,
        "expanded_end": expanded_end,
        "action_start": action_start,
        "action_end": action_end,
        "ffmpeg_start": ffmpeg_start,
        "ffmpeg_end": ffmpeg_end,
        "first_end_divergence_from_anchor": first_end_divergence,
        "end_matches_anchor_at_action": abs(float(action_end) - float(anchor_end)) <= 1e-3,
        "end_matches_anchor_at_ffmpeg": abs(float(ffmpeg_end) - float(anchor_end)) <= 1e-3,
    }


async def _intelligent_retrieve(
    request: PlanActionsRequest,
) -> Optional[IntelligentPlanResponse]:
    if not request.use_intelligence or not request.segments:
        return None
    try:
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from python.intelligence.context_manager import get_session
        from python.models.transcript import TranscriptChunk
        from python.retrieval.pipeline import RetrievalPipeline
        from python.retrieval.timestamp_contract import TimestampContract

        video_id = request.video_id or "default"
        seg_dicts = [
            {
                "id": s.id,
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "speaker": getattr(s, "speaker", None),
            }
            for s in request.segments
        ]

        chunks = [TranscriptChunk.from_segment_dict(seg, i) for i, seg in enumerate(seg_dicts)]
        pipeline = RetrievalPipeline()
        result = pipeline.retrieve(request.prompt, chunks)
        best = result.top_candidate
        context_start = float(best.expanded_start)
        context_end = float(best.expanded_end)
        retrieval_start = float(best.anchor_start)
        retrieval_end = float(best.anchor_end)
        _assert_window(context_start, context_end)
        _assert_window(retrieval_start, retrieval_end)

        start = retrieval_start
        end = retrieval_end
        TimestampContract.validate_extraction_matches_retrieval(
            retrieval_start=start,
            retrieval_end=end,
            extraction_start=start,
            extraction_end=end,
        )
        _assert_window(start, end)
        boundary_trace = _timestamp_boundary_trace(
            anchor_start=retrieval_start,
            anchor_end=retrieval_end,
            expanded_start=context_start,
            expanded_end=context_end,
            action_start=start,
            action_end=end,
        )

        match_text = ""
        for seg in request.segments:
            if seg.start <= retrieval_end and seg.end >= retrieval_start:
                match_text = seg.text[:200]
                break

        conf = float(
            best.score_final
            if getattr(best, "score_final", None) is not None
            else best.score_calibrated
        )
        grade = "HIGH" if conf > 0.75 else "MEDIUM" if conf > 0.4 else "LOW"
        ctx_mgr = get_session(request.session_id)
        matches = [
            SemanticMatchResult(
                segment_id=c.chunk.id,
                text=c.chunk.text[:160],
                start=float(c.expanded_start),
                end=float(c.expanded_end),
                score=float(
                    c.score_final
                    if getattr(c, "score_final", None) is not None
                    else c.score_calibrated
                ),
            )
            for c in result.all_candidates[:8]
        ]
        return IntelligentPlanResponse(
            intent="keep_segment",
            actions=[
                StructuredActionOut(
                    action="keep_segment",
                    start=start,
                    end=end,
                    confidence=conf,
                    matchText=match_text[:200] or best.chunk.text[:200],
                    name="AI Extract",
                    reasoning=best.match_explanation,
                    requiresConfirmation=best.match_quality in {"weak_match", "poor_match"},
                )
            ],
            matches=matches,
            trace=[best.match_explanation],
            confidence_grade=grade,
            session_id=ctx_mgr.session_id,
            debug={
                **result.trace.to_dict(),
                "timestamp_boundary_trace": boundary_trace,
                "timestamp_propagation": {
                    "candidate_start_sec": retrieval_start,
                    "candidate_end_sec": retrieval_end,
                    "expanded_start_sec": context_start,
                    "expanded_end_sec": context_end,
                    "action_start_sec": start,
                    "action_end_sec": end,
                    "ffmpeg_start_sec": boundary_trace["ffmpeg_start"],
                    "ffmpeg_end_sec": boundary_trace["ffmpeg_end"],
                    "first_end_divergence_from_anchor": boundary_trace["first_end_divergence_from_anchor"],
                    "changed_during_pipeline": not boundary_trace["end_matches_anchor_at_action"],
                },
            },
        )

        pipeline = SemanticRetrievalPipeline.from_segments(seg_dicts, video_id=video_id)
        clips = pipeline.retrieve(request.prompt, video_id=video_id, top_k=10)

        if not clips:
            if getattr(pipeline, "_confidence_gate_failed", False):
                gate_debug = getattr(pipeline, "_last_retrieval_debug", {}) or {}
                return IntelligentPlanResponse(
                    intent="semantic_extract",
                    actions=[],
                    matches=[],
                    trace=["confidence_gate_failed_no_silent_fallback"],
                    confidence_grade="LOW",
                    session_id=request.session_id,
                    debug={
                        **gate_debug,
                        "confidence_gated": True,
                        "failure_reason": (
                            "Best candidate scored below minimum confidence after calibration; "
                            "no clip selected."
                        ),
                        "planner_rejection_reason": gate_debug.get("planner_rejection_reason"),
                        "fallback_activated": False,
                    },
                )
            return None

        best = clips[0]
        _assert_window(best.start_sec, best.end_sec)
        conf = best.confidence
        grade = "HIGH" if conf > 0.75 else "MEDIUM" if conf > 0.4 else "LOW"
        planner_mode = "candidate" if best.requires_confirmation else "auto"
        if isinstance(best.debug_info, dict):
            planner_mode = str(best.debug_info.get("planner", {}).get("execution_mode", planner_mode))
        is_candidate = planner_mode == "candidate"

        match_text = ""
        for seg in request.segments:
            if seg.start <= best.end_sec and seg.end >= best.start_sec:
                match_text = seg.text[:200]
                break

        pad = request.padding_seconds
        start = max(0.0, best.start_sec - pad)
        end = best.end_sec + pad
        if request.media_duration > 0:
            end = min(request.media_duration, end)
        _assert_window(start, end)

        matches = [
            SemanticMatchResult(
                segment_id=f"clip_{i}",
                text=match_text[:160] if i == 0 else "",
                start=c.start_sec,
                end=c.end_sec,
                score=c.confidence,
            )
            for i, c in enumerate(clips[:8])
        ]

        def clip_text(start_sec: float, end_sec: float) -> str:
            parts = [
                seg.text
                for seg in request.segments
                if seg.start <= end_sec and seg.end >= start_sec
            ]
            return " ".join(parts)[:220]

        ranked_clips = sorted(clips[:5], key=lambda clip: clip.confidence, reverse=True)

        calibration_summary = (
            best.debug_info.get("calibration_summary", {})
            if isinstance(best.debug_info, dict)
            else {}
        )
        selection_trace = (
            best.debug_info.get("selection_trace", {})
            if isinstance(best.debug_info, dict)
            else {}
        )

        debug_payload = {
            "intent_graph": best.debug_info.get("parsed_query"),
            "top_k_candidates": [
                {
                    "chunk_id": f"clip_{i}",
                    "text": clip_text(c.start_sec, c.end_sec),
                    "start_time": c.start_sec,
                    "end_time": c.end_sec,
                    "bm25_score": c.debug_info.get("rrf", 0) if isinstance(c.debug_info, dict) else 0,
                    "embedding_score": c.debug_info.get("cross_encoder", 0) if isinstance(c.debug_info, dict) else 0,
                    "entity_match_score": c.debug_info.get("candidate_breakdown", {}).get("entity_score", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "action_score": c.debug_info.get("candidate_breakdown", {}).get("action_score", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "monetary_score": c.debug_info.get("candidate_breakdown", {}).get("monetary_score", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "contextual_score": c.debug_info.get("candidate_breakdown", {}).get("contextual_score", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "event_completeness_score": c.debug_info.get("candidate_breakdown", {}).get("event_completeness_score", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "prefix_penalty": c.debug_info.get("candidate_breakdown", {}).get("prefix_penalty", 0)
                    if isinstance(c.debug_info, dict)
                    else 0,
                    "rerank_score": c.debug_info.get("cross_encoder", 0) if isinstance(c.debug_info, dict) else 0,
                    "final_score": c.confidence,
                    "explanation": c.reasoning or "",
                }
                for i, c in enumerate(ranked_clips)
            ],
            "reranker_responses": calibration_summary.get("rerank_responses", []),
            "rank_before_rerank": calibration_summary.get("rank_before_rerank", []),
            "rank_before_calibration": calibration_summary.get("rank_before_calibration", []),
            "rank_after_calibration": calibration_summary.get("rank_after_calibration", []),
            "selection_reason": selection_trace.get("selection_reason"),
            "why_selected": selection_trace.get("selection_reason"),
            "chosen_chunk": {
                "start_time": best.start_sec,
                "end_time": best.end_sec,
                "final_score": conf,
                "raw_score": best.debug_info.get("raw_confidence") if isinstance(best.debug_info, dict) else None,
                "text": match_text[:200],
                "origin": best.debug_info.get("candidate_origin") if isinstance(best.debug_info, dict) else None,
                "source_candidate_id": best.debug_info.get("candidate_source_chunk_id")
                if isinstance(best.debug_info, dict)
                else None,
                "opener_cap_applied": best.debug_info.get("opener_cap_applied")
                if isinstance(best.debug_info, dict)
                else False,
            },
            "time_range": {
                "start": best.start_sec,
                "end": best.end_sec,
                "confidence": conf,
                "method": "action_planner" if planner_mode == "auto" else "candidate_extraction",
            },
            "threshold_decision": best.debug_info.get("planner", {})
            if isinstance(best.debug_info, dict)
            else {},
            "confidence_gated": False,
            "total_pipeline_ms": 0,
            "parsed_query": best.debug_info.get("parsed_query"),
            "pipeline_trace": best.debug_info.get("pipeline_trace", best.match_reasons),
            "confidence_breakdown": best.debug_info,
            "semantic_events": best.debug_info.get("semantic_events"),
            "action_plan": best.debug_info.get("planner"),
            "event_scores": best.debug_info.get("planner", {}).get("event_scores")
            if isinstance(best.debug_info.get("planner"), dict)
            else [],
            "rejected_actions": best.debug_info.get("planner", {}).get("rejected_actions")
            if isinstance(best.debug_info.get("planner"), dict)
            else [],
            "failure_reason": best.debug_info.get("planner", {}).get("failure_reason")
            if isinstance(best.debug_info.get("planner"), dict)
            else None,
            "clips": [
                {
                    "start_sec": c.start_sec,
                    "end_sec": c.end_sec,
                    "confidence": c.confidence,
                    "match_reasons": c.match_reasons,
                    "entities_found": c.entities_found,
                    "events_found": c.events_found,
                    "monetary_found": c.monetary_found,
                    "suggested_action": c.suggested_action,
                    "requires_confirmation": c.requires_confirmation,
                    "reasoning": c.reasoning,
                }
                for c in clips[:5]
            ],
            "final_window": {
                "start_sec": best.start_sec,
                "end_sec": best.end_sec,
                "confidence": conf,
            },
            "timestamp_propagation": {
                "candidate_start_sec": best.debug_info.get("pre_refine_start_sec")
                if isinstance(best.debug_info, dict)
                else None,
                "candidate_end_sec": best.debug_info.get("pre_refine_end_sec")
                if isinstance(best.debug_info, dict)
                else None,
                "selected_start_sec": best.start_sec,
                "selected_end_sec": best.end_sec,
                "action_start_sec": start,
                "action_end_sec": end,
                "changed_during_pipeline": bool(
                    isinstance(best.debug_info, dict)
                    and (
                        abs(float(best.debug_info.get("pre_refine_start_sec", best.start_sec)) - best.start_sec) > 1e-3
                        or abs(float(best.debug_info.get("pre_refine_end_sec", best.end_sec)) - best.end_sec) > 1e-3
                    )
                ),
            },
            "fallback_activated": bool(
                isinstance(best.debug_info, dict)
                and best.debug_info.get("candidate_origin") == "legacy_monetary_shortcut"
            ),
            "execution_mode": planner_mode,
            "enrichment_status": "pending" if pipeline.enrichment_pending else "complete",
            "enrichment_pending": pipeline.enrichment_pending,
            "confidence_degraded": pipeline.enrichment_pending,
        }

        ctx_mgr = get_session(request.session_id)
        action_name = best.suggested_action or "keep_segment"
        action_label = "Candidate extraction" if is_candidate else "AI Extract"

        return IntelligentPlanResponse(
            intent=action_name,
            actions=[
                StructuredActionOut(
                    action=action_name,
                    start=start,
                    end=end,
                    confidence=conf,
                    matchText=match_text[:200],
                    name=action_label,
                    reasoning=best.reasoning,
                    requiresConfirmation=is_candidate,
                )
            ],
            matches=matches,
            trace=best.match_reasons,
            confidence_grade=grade,
            session_id=ctx_mgr.session_id,
            debug=debug_payload,
        )
    except Exception as e:
        logger.warning("Intelligent retrieval failed without fallback: %s", e)
        return IntelligentPlanResponse(
            intent="semantic_extract",
            actions=[],
            matches=[],
            trace=["planner_error_no_silent_first_clip_fallback"],
            confidence_grade="LOW",
            session_id=request.session_id,
            debug={
                "planner_error": "No valid retrieval result. Cannot extract clip.",
                "detail": str(e),
                "fallback_activated": False,
            },
        )


@router.post("/plan")
async def plan_actions(request: PlanActionsRequest):
    intelligent_failure: Optional[str] = None
    if request.use_intelligence:
        import asyncio

        try:
            intelligent = await asyncio.wait_for(
                _intelligent_retrieve(request), timeout=90.0
            )
        except asyncio.TimeoutError:
            logger.warning("Intelligent retrieval timed out after 90s, falling back")
            intelligent = None
            intelligent_failure = "intelligent_retrieval_timeout"
        except Exception as e:
            logger.warning("Intelligent retrieval error: %s, falling back", e)
            intelligent = None
            intelligent_failure = f"intelligent_retrieval_error:{e}"

        if intelligent and intelligent.actions:
            return intelligent.model_dump()
        if intelligent and not intelligent.actions:
            debug_payload = intelligent.debug or {}
            if debug_payload.get("confidence_gate_failed") or debug_payload.get("confidence_gated"):
                trace_msg = "confidence_gate_failed_no_silent_fallback"
            else:
                trace_msg = "intelligent_retrieval_no_actions"
            return IntelligentPlanResponse(
                intent="semantic_extract",
                actions=[],
                matches=[],
                trace=[trace_msg],
                confidence_grade="LOW",
                session_id=request.session_id,
                debug={
                    **debug_payload,
                    "planner_error": debug_payload.get("failure_reason")
                    or "Planner returned no executable action; no fallback clip inserted.",
                },
            ).model_dump()

    trace: List[str] = []
    actions: List[StructuredActionOut] = []
    matches: List[SemanticMatchResult] = []

    intent = classify_intent(request.prompt)
    trace.append(f"intent={intent}")

    if intent in ("keep_segment", "semantic_extract") and request.segments:
        lexical_matches = lexical_search_matches(
            request.prompt,
            request.segments,
            top_k=8,
            min_score=0.34,
        )
        if lexical_matches:
            matches = lexical_matches
            trace.append(f"lexical_matches={len(matches)}")
        else:
            if intelligent_failure:
                trace.append(intelligent_failure)
        search = SemanticSearchRequest(
            query=request.prompt,
            segments=request.segments,
            top_k=8,
            min_score=0.22,
        )
        if not matches:
            result = await semantic_search(search)
            raw = result.get("matches", [])
            matches = [SemanticMatchResult(**m) for m in raw]
            trace.append(f"semantic_matches={len(matches)}")

        if matches:
            pad = request.padding_seconds
            start, end, confidence, match_text = merge_matches(matches)
            start = max(0.0, start - pad)
            if request.media_duration > 0:
                end = min(request.media_duration, end + pad)
            else:
                end = end + pad

            actions.append(
                StructuredActionOut(
                    action="keep_segment",
                    start=start,
                    end=end,
                    confidence=confidence,
                    matchText=match_text[:200],
                    name="AI Extract",
                )
            )
            trace.append(f"range={start:.2f}-{end:.2f} confidence={confidence:.3f}")
        else:
            trace.append("no_semantic_matches")

    elif intent == "cut_silence":
        actions.append(StructuredActionOut(action="cut_silence", confidence=0.9))
    elif intent == "detect_scenes":
        actions.append(StructuredActionOut(action="detect_scenes", confidence=0.85))
    elif intent == "transcribe":
        actions.append(StructuredActionOut(action="add_subtitle", confidence=0.85))

    return PlanActionsResponse(
        intent=intent,
        actions=actions,
        matches=matches,
        trace=trace,
    ).model_dump()
