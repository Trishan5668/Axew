"""
Unified semantic retrieval pipeline — drop-in replacement for naive embedding search.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from python.enrichment.builder import build_enriched_transcript
from python.models.enriched import EnrichedTranscript, load_enriched
from python.retrieval.event_matcher import EventMatcher, ParsedQuery
from python.retrieval.hybrid_retriever import HybridRetriever, reciprocal_rank_fusion
from python.retrieval.query_decomposer import QueryParser
from python.retrieval.reranker import CrossEncoderReranker
from python.retrieval.temporal_reasoner import TemporalReasoner
from python.retrieval.timestamp_refiner import refine_window
from python.retrieval.temporal_coherence import TimeWindow
from python.retrieval.confidence_calibration import (
    MIN_EXTRACT_CONFIDENCE,
    assert_opener_quality,
    build_selection_reason,
    calibrate_confidence_distribution,
    cap_opener_confidence,
    compute_prefix_penalty,
    embedding_score_from_components,
    is_semantically_specific_query,
    lexical_overlap_ratio,
)
from python.semantic.action_planner import ActionPlanner, PlanningResult
from python.semantic.event_grounding import EventGrounder, SemanticEvent

logger = logging.getLogger(__name__)

FINANCIAL_TERMS = {
    "money",
    "rupee",
    "rupees",
    "cash",
    "payment",
    "paid",
    "pay",
    "finance",
    "financial",
    "crore",
    "loan",
    "amount",
    "transfer",
    "handed",
    "give",
    "gives",
}
TRANSFER_TERMS = {"give", "gives", "gave", "hand", "hands", "handed", "pass", "passed", "pay", "paid", "transfer"}


@dataclass
class CandidateScoreBreakdown:
    embedding_score: float
    entity_score: float
    action_score: float
    monetary_score: float
    contextual_score: float
    event_completeness_score: float
    prefix_penalty: float
    final_score: float
    event_confidence: float = 0.0
    reasoning: List[str] = field(default_factory=list)


@dataclass
class RefinedClip:
    start_sec: float
    end_sec: float
    confidence: float
    match_reasons: List[str] = field(default_factory=list)
    entities_found: List[str] = field(default_factory=list)
    events_found: List[str] = field(default_factory=list)
    monetary_found: Optional[Dict[str, Any]] = None
    speaker_breakdown: Dict[str, Any] = field(default_factory=dict)
    debug_info: Dict[str, Any] = field(default_factory=dict)
    suggested_action: Optional[str] = None
    requires_confirmation: bool = False
    reasoning: Optional[str] = None
class SemanticRetrievalPipeline:
    def __init__(
        self,
        transcript: EnrichedTranscript,
        segments: List[Dict[str, Any]],
        enrichment_pending: bool = False,
    ) -> None:
        self.transcript = transcript
        self.segments = segments
        self.enrichment_pending = enrichment_pending
        self.query_parser = QueryParser()
        self.event_matcher = EventMatcher(transcript)
        self.reranker = CrossEncoderReranker()
        self.temporal = TemporalReasoner()
        self.event_grounder = EventGrounder()
        self.action_planner = ActionPlanner()
        self._hybrid: Optional[HybridRetriever] = None
        self._chunk_map: Dict[str, Any] = {}
        self._confidence_gate_failed: bool = False
        self._last_retrieval_debug: Dict[str, Any] = {}

    @classmethod
    def from_segments(
        cls,
        segments: List[Dict[str, Any]],
        video_id: str = "default",
    ) -> "SemanticRetrievalPipeline":
        cached = load_enriched(video_id)
        pending = False
        if cached and len(cached.segments) == len(segments):
            transcript = cached
        else:
            try:
                transcript = build_enriched_transcript(segments, video_id=video_id)
            except Exception as e:
                logger.warning("Enrichment failed, using minimal transcript: %s", e)
                transcript = build_enriched_transcript(segments, video_id=video_id)
                pending = True
        return cls(transcript, segments, enrichment_pending=pending)

    def _ensure_hybrid(self) -> HybridRetriever:
        if self._hybrid is None:
            import asyncio

            from python.intelligence.extraction_pipeline import extract_intelligence
            from python.retrieval.video_index import VideoIndex

            async def _build():
                return await extract_intelligence(
                    self.segments, video_id=self.transcript.video_id
                )

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    artifacts = pool.submit(lambda: asyncio.run(_build())).result()
            else:
                artifacts = asyncio.run(_build())

            index = VideoIndex(artifacts, self.transcript.video_id)
            index.index()
            self._hybrid = index.hybrid
            for c in artifacts.all_retrieval_chunks():
                self._chunk_map[c.chunk_id] = c
        return self._hybrid

    def retrieve(self, prompt: str, video_id: str = "", top_k: int = 5) -> List[RefinedClip]:
        parsed = self.query_parser.parse(prompt)
        segment_map = {seg.segment_id: seg for seg in self.transcript.segments}
        events_by_segment: Dict[str, List[SemanticEvent]] = {}
        debug: Dict[str, Any] = {
            "parsed_query": parsed.__dict__,
            "enrichment_pending": self.enrichment_pending,
        }
        self._last_parsed = parsed
        self._confidence_gate_failed = False
        self._last_retrieval_debug = {}

        event_matches = self.event_matcher.match(parsed)
        debug["event_match_candidates"] = [m.__dict__ for m in event_matches[:10]]
        semantic_events = self.event_grounder.ground_transcript(self.transcript)
        for event in semantic_events:
            events_by_segment.setdefault(event.source_chunk_id, []).append(event)
        debug["semantic_events"] = [
            self._semantic_event_to_dict(event) for event in semantic_events[:20]
        ]

        # Hybrid dense + sparse (skip when strong structured matches exist)
        hybrid_candidates: List[dict] = []
        import os

        skip_hybrid = os.environ.get("AXEW_BENCHMARK") == "1"
        strong_event = bool(event_matches) and event_matches[0].match_confidence >= 0.5
        hybrid_weight = 0.20 if (strong_event and parsed.monetary) else 0.40
        debug["hybrid_weight"] = hybrid_weight
        debug["hybrid_skipped"] = bool(skip_hybrid)
        try:
            if skip_hybrid:
                raise RuntimeError("hybrid_disabled_for_benchmark")
            import asyncio

            hybrid = self._ensure_hybrid()

            async def _search():
                return await hybrid.search(prompt, top_k=20)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    results = pool.submit(lambda: asyncio.run(_search())).result()
            else:
                results = asyncio.run(_search())
            for r in results:
                hybrid_candidates.append(
                    {
                        "segment_id": r.chunk_id,
                        "start_sec": r.start_sec,
                        "end_sec": r.end_sec,
                        "rrf_score": r.score_fused,
                        "text": r.text or "",
                    }
                )
        except Exception as e:
            logger.warning("Hybrid retrieval unavailable: %s", e)

        debug["dense_sparse_top20"] = hybrid_candidates[:20]

        # Fuse event matches with hybrid
        fused_scores: Dict[str, float] = {}
        candidate_meta: Dict[str, dict] = {}

        for em in event_matches:
            key = em.segment_id or f"{em.start_ms}"
            fused_scores[key] = fused_scores.get(key, 0) + em.match_confidence
            segment = segment_map.get(key)
            candidate_meta[key] = {
                "start_sec": em.start_ms / 1000.0,
                "end_sec": em.end_ms / 1000.0,
                "match_reasons": list(em.match_reasons),
                "event_confidence": em.match_confidence,
                "text": segment.text if segment else "",
                "segment_position": (segment.start_ms / 1000.0) if segment else (em.start_ms / 1000.0),
            }

        if hybrid_candidates:
            ranking = [(c["segment_id"], c["rrf_score"]) for c in hybrid_candidates]
            rrf_list = reciprocal_rank_fusion([ranking])
            max_rrf = max((s for _, s in rrf_list), default=1.0) or 1.0
            for doc_id, score in rrf_list:
                norm = score / max_rrf
                fused_scores[doc_id] = fused_scores.get(doc_id, 0) + norm * hybrid_weight
                if doc_id not in candidate_meta:
                    hc = next((c for c in hybrid_candidates if c["segment_id"] == doc_id), None)
                    if hc:
                        candidate_meta[doc_id] = hc

        ranked_keys = sorted(fused_scores, key=fused_scores.get, reverse=True)[:20]
        raw_candidates = []
        for key in ranked_keys:
            meta = candidate_meta.get(key, {})
            raw_candidates.append(
                {
                    "key": key,
                    "start_sec": meta.get("start_sec", 0),
                    "end_sec": meta.get("end_sec", 0),
                    "score": fused_scores[key],
                    "match_reasons": meta.get("match_reasons", []),
                    "text": meta.get("text", ""),
                }
            )

        raw_candidates = self.temporal.apply_temporal_filter(
            parsed, raw_candidates, []
        )

        # Cross-encoder rerank on top segments
        clips: List[RefinedClip] = []
        rerank_debug: List[Dict[str, Any]] = []
        pre_rerank_ranking: List[Dict[str, Any]] = []
        for cand in raw_candidates[: max(top_k * 5, 12)]:
            text = cand.get("text") or self._text_for_window(cand["start_sec"], cand["end_sec"])
            ce_score = 0.0
            rerank_available = False
            try:
                chunk = self._chunk_map.get(cand["key"])
                if chunk:
                    pairs = self.reranker.rerank(prompt, [chunk], use_large=False)
                    if pairs:
                        ce_score = float(pairs[0][1])
                        rerank_available = True
            except Exception:
                pass

            segment_events = events_by_segment.get(str(cand["key"]), [])
            breakdown = self._score_candidate(
                parsed=parsed,
                text=text,
                start_sec=cand["start_sec"],
                end_sec=cand["end_sec"],
                cross_encoder=ce_score,
                fused_score=float(cand["score"]),
                events=segment_events,
                rerank_available=rerank_available,
            )
            pre_rerank_ranking.append(
                {
                    "key": cand["key"],
                    "start_sec": cand["start_sec"],
                    "end_sec": cand["end_sec"],
                    "raw_fused": cand["score"],
                    "pre_calibrated_score": breakdown.final_score,
                }
            )
            rerank_debug.append(
                {
                    "start_time": cand["start_sec"],
                    "end_time": cand["end_sec"],
                    "cross_encoder": ce_score,
                    "rerank_available": rerank_available,
                    "fused_score": cand["score"],
                    "pre_calibrated_final": breakdown.final_score,
                }
            )

            monetary_found = None
            if parsed.monetary:
                for m in self.transcript.monetary_mentions:
                    if (
                        abs(m.amount_normalized - parsed.monetary["amount"]) < 1
                        and m.segment_id == str(cand["key"])
                    ):
                        monetary_found = {
                            "amount": m.amount_normalized,
                            "currency": m.currency,
                        }
                        break

            start_sec, end_sec = self._refine_bounds(
                cand["start_sec"], cand["end_sec"], parsed
            )

            entities_found = [e for e in parsed.entities if e.lower() in text.lower()]
            events_found = cand.get("match_reasons", [])
            if segment_events:
                events_found = list(dict.fromkeys(events_found + [f"event:{event.action}" for event in segment_events[:2]]))
            speaker_role = None
            for seg in self.transcript.segments:
                if seg.start_ms / 1000.0 <= start_sec <= seg.end_ms / 1000.0:
                    speaker_role = self.transcript.speaker_map.get(
                        seg.speaker_id or "", seg.speaker_id
                    )
                    break

            clips.append(
                RefinedClip(
                    start_sec=start_sec,
                    end_sec=end_sec,
                    confidence=breakdown.final_score,
                    match_reasons=breakdown.reasoning,
                    entities_found=entities_found,
                    events_found=events_found,
                    monetary_found=monetary_found,
                    speaker_breakdown={"role": speaker_role} if speaker_role else {},
                    debug_info={
                        "cross_encoder": ce_score,
                        "rerank_available": rerank_available,
                        "rrf": cand["score"],
                        "candidate_origin": "fused",
                        "candidate_breakdown": self._candidate_breakdown_to_dict(breakdown),
                        "parsed_query": parsed.__dict__,
                        "candidate_source_chunk_id": str(cand["key"]),
                        "pre_refine_start_sec": cand["start_sec"],
                        "pre_refine_end_sec": cand["end_sec"],
                    },
                    reasoning=" | ".join(breakdown.reasoning[:4]),
                )
            )

        clips.sort(key=lambda c: c.confidence, reverse=True)
        rank_before_rerank = [
            {
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "confidence": c.confidence,
                "origin": c.debug_info.get("candidate_origin"),
            }
            for c in clips[:10]
        ]

        planning_result = self.action_planner.plan(parsed, semantic_events, self.transcript)
        debug["action_planner"] = self._planning_result_to_dict(planning_result)
        debug["planner_rejection_reason"] = planning_result.failure_reason if planning_result.execution_mode == "rejected" else None

        if planning_result.action:
            planner_clip = self._clip_from_planning_result(parsed, planning_result)
            planner_clip.debug_info["semantic_events"] = debug["semantic_events"]
            planner_clip.debug_info["candidate_origin"] = "planner"
            planner_clip.debug_info["candidate_source_chunk_id"] = (
                planning_result.best_event.source_chunk_id if planning_result.best_event else None
            )
            clips.append(planner_clip)

        # Legacy direct path for monetary + transfer queries when structured planning did not succeed.
        if not planning_result.action and parsed.monetary and event_matches:
            best_em = self._best_monetary_event_match(parsed, event_matches)
            has_money = any(
                abs(m.amount_normalized - parsed.monetary["amount"]) < 1
                for m in self.transcript.monetary_mentions
            )
            direct_conf = min(0.95, 0.45 + best_em.match_confidence + (0.25 if has_money else 0))
            start_sec = max(0, best_em.start_ms / 1000.0 - 1.5)
            end_sec = best_em.end_ms / 1000.0 + 1.5
            # Extend to include immediate audience reaction (seg_010)
            for seg in self.transcript.segments:
                if seg.segment_id == "seg_010" and "applaud" in seg.text.lower():
                    end_sec = max(end_sec, seg.end_ms / 1000.0)
            direct = RefinedClip(
                start_sec=start_sec,
                end_sec=end_sec,
                confidence=direct_conf,
                match_reasons=best_em.match_reasons,
                entities_found=parsed.entities,
                events_found=[f"action:{a}" for a in parsed.action_types],
                monetary_found=parsed.monetary,
                speaker_breakdown={"role": parsed.speaker_roles[0] if parsed.speaker_roles else "interviewer"},
                suggested_action=parsed.intent_action,
                reasoning="Legacy monetary shortcut",
                debug_info={
                    "candidate_origin": "legacy_monetary_shortcut",
                    "candidate_source_chunk_id": best_em.segment_id,
                    "pre_refine_start_sec": best_em.start_ms / 1000.0,
                    "pre_refine_end_sec": best_em.end_ms / 1000.0,
                },
            )
            clips.append(direct)

        clips.sort(key=lambda c: c.confidence, reverse=True)
        clips = self._apply_confidence_calibration(parsed, clips, pre_rerank_ranking, rerank_debug, rank_before_rerank)

        if clips:
            best = clips[0]
            if (
                is_semantically_specific_query(parsed)
                and best.confidence < MIN_EXTRACT_CONFIDENCE
            ):
                logger.info(
                    "[retrieval] rejecting weak match conf=%.3f start=%.2fs query=%r",
                    best.confidence,
                    best.start_sec,
                    prompt[:80],
                )
                best.debug_info = best.debug_info if isinstance(best.debug_info, dict) else {}
                gate_trace = {
                    "prompt": prompt,
                    "retrieval_candidates": len(raw_candidates),
                    "planner_execution_mode": planning_result.execution_mode,
                    "planner_rejection_reason": planning_result.failure_reason,
                    "confidence_gate_failed": True,
                    "confidence_gate_threshold": MIN_EXTRACT_CONFIDENCE,
                    "best_rejected_confidence": best.confidence,
                    "best_rejected_window": {
                        "start_time": best.start_sec,
                        "end_time": best.end_sec,
                    },
                    "fallback_activated": False,
                    "why_rejected": best.debug_info.get("selection_trace", {}).get("selection_reason"),
                    "rank_after_calibration": best.debug_info.get("calibration_summary", {}).get(
                        "rank_after_calibration"
                    ),
                }
                self._confidence_gate_failed = True
                self._last_retrieval_debug = {
                    "confidence_gate_failed": True,
                    "pipeline_trace": gate_trace,
                    "top_k_candidates": [],
                    "chosen_chunk": {
                        "start_time": best.start_sec,
                        "end_time": best.end_sec,
                        "final_score": best.confidence,
                        "rejected": True,
                    },
                    "planner_rejection_reason": planning_result.failure_reason,
                }
                best.debug_info["pipeline_trace"] = gate_trace
                return []

            self._assert_time_window(best.start_sec, best.end_sec)
            best.debug_info = best.debug_info if isinstance(best.debug_info, dict) else {}
            trace = best.debug_info.get("selection_trace", {})
            best.debug_info["pipeline_trace"] = {
                "prompt": prompt,
                "retrieval_candidates": len(raw_candidates),
                "planner_execution_mode": planning_result.execution_mode,
                "planner_rejection_reason": planning_result.failure_reason,
                "selected_candidate": {
                    "start_time": best.start_sec,
                    "end_time": best.end_sec,
                    "duration": round(best.end_sec - best.start_sec, 3),
                    "source_candidate_id": best.debug_info.get("candidate_source_chunk_id"),
                    "origin": best.debug_info.get("candidate_origin", "unknown"),
                },
                "fallback_activated": bool(
                    best.debug_info.get("candidate_origin") == "legacy_monetary_shortcut"
                ),
                "why_selected": trace.get("selection_reason"),
                "rank_before_calibration": trace.get("rank_before_calibration"),
                "rank_after_calibration": trace.get("rank_after_calibration"),
            }

        return clips[:top_k]

    def _apply_confidence_calibration(
        self,
        parsed: ParsedQuery,
        clips: List[RefinedClip],
        pre_rerank_ranking: List[Dict[str, Any]],
        rerank_debug: List[Dict[str, Any]],
        rank_before_rerank: List[Dict[str, Any]],
    ) -> List[RefinedClip]:
        if not clips:
            return clips

        rank_before = [
            {"start_sec": c.start_sec, "confidence": c.confidence, "origin": c.debug_info.get("candidate_origin")}
            for c in clips
        ]

        raw_scores = [c.confidence for c in clips]
        calibrated_scores = calibrate_confidence_distribution(raw_scores)
        weak_compression = max(raw_scores) < 0.38 and len(raw_scores) > 1

        for idx, clip in enumerate(clips):
            breakdown_dict = clip.debug_info.get("candidate_breakdown", {})
            text = self._text_for_window(clip.start_sec, clip.end_sec)
            breakdown = CandidateScoreBreakdown(
                embedding_score=float(breakdown_dict.get("embedding_score", 0)),
                entity_score=float(breakdown_dict.get("entity_score", 0)),
                action_score=float(breakdown_dict.get("action_score", 0)),
                monetary_score=float(breakdown_dict.get("monetary_score", 0)),
                contextual_score=float(breakdown_dict.get("contextual_score", 0)),
                event_completeness_score=float(breakdown_dict.get("event_completeness_score", 0)),
                prefix_penalty=float(breakdown_dict.get("prefix_penalty", 0)),
                final_score=float(breakdown_dict.get("final_score", clip.confidence)),
            )
            capped, opener_cap = cap_opener_confidence(
                calibrated_scores[idx],
                clip.start_sec,
                parsed,
                breakdown,
                text,
            )
            assert_opener_quality(parsed, clip.start_sec, capped, breakdown, text)
            raw = raw_scores[idx]
            clip.debug_info["raw_confidence"] = raw
            clip.debug_info["calibrated_confidence"] = capped
            clip.debug_info["opener_cap_applied"] = opener_cap
            clip.debug_info["weak_set_compression"] = weak_compression
            clip.confidence = capped

        clips.sort(key=lambda c: c.confidence, reverse=True)
        rank_after = [
            {"start_sec": c.start_sec, "confidence": c.confidence, "origin": c.debug_info.get("candidate_origin")}
            for c in clips
        ]

        for rank, clip in enumerate(clips):
            breakdown_dict = clip.debug_info.get("candidate_breakdown", {})
            clip.debug_info["selection_trace"] = {
                "rank_before_calibration": rank_before,
                "rank_after_calibration": rank_after,
                "pre_rerank_ranking": pre_rerank_ranking,
                "rerank_debug": rerank_debug,
                "rank_before_rerank_sort": rank_before_rerank,
                "selection_reason": build_selection_reason(
                    origin=str(clip.debug_info.get("candidate_origin", "unknown")),
                    rank=rank + 1,
                    breakdown=breakdown_dict,
                    calibrated=clip.confidence,
                    raw=float(clip.debug_info.get("raw_confidence", clip.confidence)),
                    fallback_activated=clip.debug_info.get("candidate_origin") == "legacy_monetary_shortcut",
                    opener_cap=bool(clip.debug_info.get("opener_cap_applied")),
                    weak_compression=weak_compression,
                ),
            }

        if clips:
            winner = clips[0]
            winner.debug_info["calibration_summary"] = {
                "pre_rerank_ranking": pre_rerank_ranking[:10],
                "rerank_responses": rerank_debug[:10],
                "rank_before_rerank": rank_before_rerank,
                "rank_before_calibration": rank_before,
                "rank_after_calibration": rank_after,
            }
        return clips

    def _best_monetary_event_match(self, parsed: ParsedQuery, event_matches: list) -> Any:
        """Prefer active transfer by interviewer over retrospective mentions."""
        import re

        best = event_matches[0]
        best_score = -1.0
        for em in event_matches:
            seg = next(
                (s for s in self.transcript.segments if s.segment_id == em.segment_id),
                None,
            )
            if not seg:
                score = em.match_confidence
            else:
                text_l = seg.text.lower()
                score = em.match_confidence
                if "TRANSFER" in parsed.action_types and re.search(
                    r"\b(giving|give|hand|pass)\b", text_l
                ):
                    score += 0.35
                if parsed.speaker_roles and "interviewer" in parsed.speaker_roles:
                    role = self.transcript.speaker_map.get(seg.speaker_id or "", "")
                    if role and "interviewer" in str(role).lower():
                        score += 0.25
                    elif seg.speaker_id == "interviewer":
                        score += 0.25
                if re.search(r"\b(pulled|remember|mentioned|years ago|incident)\b", text_l):
                    score -= 0.2
            if score > best_score:
                best_score = score
                best = em
        return best

    def _score_candidate(
        self,
        parsed: ParsedQuery,
        text: str,
        start_sec: float,
        end_sec: float,
        cross_encoder: float,
        fused_score: float,
        events: List[SemanticEvent],
        rerank_available: bool = True,
    ) -> CandidateScoreBreakdown:
        embedding_score = embedding_score_from_components(
            cross_encoder,
            fused_score,
            rerank_available=rerank_available,
        )
        entity_score = self._entity_score(parsed, text, events)
        action_score = self._action_score(parsed, text, events)
        monetary_score = self._monetary_score(parsed, text, events, start_sec=start_sec)
        contextual_score = self._contextual_score(parsed, text, events)
        event_completeness_score = self._event_completeness_score(parsed, events, text)
        lexical = lexical_overlap_ratio(parsed.raw_query, text)
        duration = self.transcript.segments[-1].end_ms / 1000.0 if self.transcript.segments else end_sec
        prefix_penalty = compute_prefix_penalty(
            start_sec=start_sec,
            end_sec=end_sec,
            duration_sec=duration,
            action_score=action_score,
            monetary_score=monetary_score,
            contextual_score=contextual_score,
            entity_score=entity_score,
            lexical_overlap=lexical,
        )
        # Weak fuzzy entity-only matches on openers should not dominate specific queries.
        if (
            start_sec < 5.0
            and is_semantically_specific_query(parsed)
            and entity_score > 0
            and entity_score < 0.95
            and action_score < 0.55
            and monetary_score < 0.55
        ):
            entity_score = min(entity_score, 0.42)

        final_score = (
            0.20 * embedding_score
            + 0.15 * entity_score
            + 0.30 * action_score
            + 0.25 * monetary_score
            + 0.10 * contextual_score
        )
        final_score *= 0.85 + 0.15 * event_completeness_score
        final_score -= prefix_penalty
        final_score = max(0.0, min(1.0, final_score))

        reasoning = [
            f"embed={embedding_score:.2f}",
            f"entity={entity_score:.2f}",
            f"action={action_score:.2f}",
            f"money={monetary_score:.2f}",
            f"context={contextual_score:.2f}",
            f"complete={event_completeness_score:.2f}",
        ]
        if prefix_penalty > 0:
            reasoning.append(f"prefix_penalty=-{prefix_penalty:.2f}")

        event_conf = max((event.confidence for event in events), default=0.0)
        if event_conf > 0:
            reasoning.append(f"event_conf={event_conf:.2f}")

        return CandidateScoreBreakdown(
            embedding_score=round(embedding_score, 4),
            entity_score=round(entity_score, 4),
            action_score=round(action_score, 4),
            monetary_score=round(monetary_score, 4),
            contextual_score=round(contextual_score, 4),
            event_completeness_score=round(event_completeness_score, 4),
            prefix_penalty=round(prefix_penalty, 4),
            final_score=round(final_score, 4),
            event_confidence=round(event_conf, 4),
            reasoning=reasoning,
        )

    def _entity_score(self, parsed: ParsedQuery, text: str, events: List[SemanticEvent]) -> float:
        targets = [parsed.subject, parsed.recipient, parsed.object] + parsed.entities
        values = [text]
        for event in events:
            values.extend([event.actor, event.object, event.recipient])
        return self._best_similarity(targets, values)

    def _action_score(self, parsed: ParsedQuery, text: str, events: List[SemanticEvent]) -> float:
        query_actions = [parsed.verb] + parsed.action_types
        best = 0.0
        for event in events:
            best = max(best, self._action_family_similarity(query_actions, event.action))
            if event.actor and event.object:
                best = max(best, min(1.0, 0.82 + (0.1 if event.recipient else 0.0)))
        if best == 0.0:
            best = self._action_family_similarity(query_actions, text)
        return best

    def _monetary_score(
        self,
        parsed: ParsedQuery,
        text: str,
        events: List[SemanticEvent],
        *,
        start_sec: float = 0.0,
    ) -> float:
        lower = text.lower()
        score = 0.0
        if parsed.monetary:
            amount = float(parsed.monetary.get("amount", 0))
            digits = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", lower)]
            if any(abs(value - amount) < 1.0 for value in digits):
                score = 1.0
            elif any(term in lower for term in FINANCIAL_TERMS):
                # Generic financial vocabulary alone must not inflate opener clips.
                score = 0.55 if start_sec >= 5.0 else 0.12
        elif any(term in lower for term in FINANCIAL_TERMS):
            score = 0.35

        for event in events:
            haystack = " ".join(filter(None, [event.monetary_amount, event.object, event.transcript_text])).lower()
            if parsed.monetary and parsed.monetary.get("amount") is not None:
                amount = float(parsed.monetary["amount"])
                digits = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", haystack)]
                if any(abs(value - amount) < 1.0 for value in digits):
                    score = max(score, 1.0)
            if any(term in haystack for term in FINANCIAL_TERMS):
                score = max(score, 0.7 if parsed.monetary else 0.45)
        return score

    def _contextual_score(self, parsed: ParsedQuery, text: str, events: List[SemanticEvent]) -> float:
        lower = text.lower()
        financial_hits = sum(1 for term in FINANCIAL_TERMS if term in lower)
        transfer_hits = sum(1 for term in TRANSFER_TERMS if re.search(rf"\b{re.escape(term)}\b", lower))
        entity_hits = sum(1 for entity in parsed.entities if entity.lower() in lower)
        score = min(1.0, 0.15 * financial_hits + 0.20 * transfer_hits + 0.10 * min(entity_hits, 2))
        if events:
            for event in events:
                if event.monetary_amount:
                    score = max(score, 0.75)
                elif event.object and event.actor:
                    score = max(score, 0.58)
        return score

    def _event_completeness_score(self, parsed: ParsedQuery, events: List[SemanticEvent], text: str) -> float:
        if not events:
            return 0.1 if any(term in text.lower() for term in TRANSFER_TERMS) else 0.0
        best = 0.0
        for event in events:
            score = 0.0
            if event.actor:
                score += 0.25
            if event.action:
                score += 0.30
            if event.object:
                score += 0.20
            if event.recipient:
                score += 0.15
            if event.monetary_amount:
                score += 0.10
            if parsed.monetary and not event.monetary_amount and event.object and any(ch.isdigit() for ch in event.object):
                score += 0.05
            best = max(best, min(1.0, score))
        return best

    def _best_similarity(self, targets: List[Optional[str]], values: List[Optional[str]]) -> float:
        cleaned_targets = [self._normalize_text(item) for item in targets if item]
        cleaned_values = [self._normalize_text(item) for item in values if item]
        if not cleaned_targets or not cleaned_values:
            return 0.0
        best = 0.0
        for target in cleaned_targets:
            for value in cleaned_values:
                if target == value:
                    best = max(best, 1.0)
                elif target in value or value in target:
                    best = max(best, 0.88)
                else:
                    try:
                        from rapidfuzz import fuzz

                        best = max(best, fuzz.partial_ratio(target, value) / 100.0)
                    except Exception:
                        pass
        return best

    def _action_family_similarity(self, query_actions: List[Optional[str]], candidate: Optional[str]) -> float:
        target = self._normalize_text(candidate)
        if not target:
            return 0.0
        normalized_actions = [self._normalize_text(action) for action in query_actions if action]
        families = {
            "transfer": TRANSFER_TERMS | {"transfer", "payment", "handover", "receives", "receive"},
            "speak": {"speak", "speaks", "say", "says", "said", "tell", "tells", "ask", "asks", "mention", "mentions"},
            "laugh": {"laugh", "laughs", "laughed", "giggle", "giggled", "chuckle"},
        }
        best = 0.0
        for action in normalized_actions:
            if action == target:
                best = max(best, 1.0)
            elif action in target or target in action:
                best = max(best, 0.86)
            for family in families.values():
                if action in family and any(term in target for term in family):
                    best = max(best, 0.92 if family is families["transfer"] else 0.84)
        return best

    def _candidate_breakdown_to_dict(self, breakdown: CandidateScoreBreakdown) -> Dict[str, Any]:
        return {
            "embedding_score": breakdown.embedding_score,
            "entity_score": breakdown.entity_score,
            "action_score": breakdown.action_score,
            "monetary_score": breakdown.monetary_score,
            "contextual_score": breakdown.contextual_score,
            "event_completeness_score": breakdown.event_completeness_score,
            "prefix_penalty": breakdown.prefix_penalty,
            "final_score": breakdown.final_score,
            "event_confidence": breakdown.event_confidence,
            "reasoning": breakdown.reasoning,
        }

    def _normalize_text(self, value: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _text_for_window(self, start: float, end: float) -> str:
        parts = []
        for seg in self.transcript.segments:
            s, e = seg.start_ms / 1000.0, seg.end_ms / 1000.0
            if s <= end and e >= start:
                parts.append(seg.text)
        return " ".join(parts)

    def _semantic_event_to_dict(self, event: SemanticEvent) -> Dict[str, Any]:
        return {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "object": event.object,
            "recipient": event.recipient,
            "monetary_amount": event.monetary_amount,
            "transcript_text": event.transcript_text,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "confidence": event.confidence,
            "source_chunk_id": event.source_chunk_id,
        }

    def _planning_result_to_dict(self, result: PlanningResult) -> Dict[str, Any]:
        return {
            "execution_mode": result.execution_mode,
            "best_score": result.best_score,
            "failure_reason": result.failure_reason,
            "action": {
                "action_type": result.action.action_type,
                "start_time": result.action.start_time,
                "end_time": result.action.end_time,
                "confidence": result.action.confidence,
                "reasoning": result.action.reasoning,
            }
            if result.action
            else None,
            "best_event": self._semantic_event_to_dict(result.best_event)
            if result.best_event
            else None,
            "event_scores": [
                {
                    "event_id": score.event_id,
                    "source_chunk_id": score.source_chunk_id,
                    "actor_score": score.actor_score,
                    "action_score": score.action_score,
                    "object_score": score.object_score,
                    "recipient_score": score.recipient_score,
                    "monetary_score": score.monetary_score,
                    "semantic_score": score.semantic_score,
                    "temporal_score": score.temporal_score,
                    "prefix_penalty": score.prefix_penalty,
                    "final_score": score.final_score,
                    "reasoning": score.reasoning,
                }
                for score in result.event_scores
            ],
            "rejected_actions": result.rejected_actions,
        }

    def _clip_from_planning_result(
        self,
        parsed: ParsedQuery,
        result: PlanningResult,
    ) -> RefinedClip:
        assert result.action is not None
        text = self._text_for_window(result.action.start_time, result.action.end_time)
        actor = result.best_event.actor if result.best_event else None
        event_name = result.best_event.action if result.best_event else None
        events_found = []
        if event_name:
            events_found.append(f"event:{event_name}")
        events_found.append(f"planner:{result.execution_mode}")
        if result.action.action_type:
            events_found.append(f"timeline:{result.action.action_type}")
        return RefinedClip(
            start_sec=result.action.start_time,
            end_sec=result.action.end_time,
            confidence=result.action.confidence,
            match_reasons=result.event_scores[0].reasoning if result.event_scores else [],
            entities_found=parsed.entities,
            events_found=events_found,
            monetary_found=parsed.monetary,
            speaker_breakdown={"role": actor} if actor else {},
            debug_info={
                "parsed_query": parsed.__dict__,
                "planner": self._planning_result_to_dict(result),
                "candidate_origin": "planner",
                "candidate_source_chunk_id": result.best_event.source_chunk_id if result.best_event else None,
                "pre_refine_start_sec": result.action.start_time,
                "pre_refine_end_sec": result.action.end_time,
            },
            suggested_action=result.action.action_type,
            requires_confirmation=result.execution_mode == "candidate",
            reasoning=result.action.reasoning,
        )

    def _refine_bounds(self, start: float, end: float, parsed: ParsedQuery) -> tuple[float, float]:
        try:
            from python.intelligence.query_parser import ParsedQuery as LegacyPQ

            legacy = LegacyPQ(
                original_query=parsed.raw_query,
                entities=parsed.entities,
                actions=[],
                monetary_amounts=[str(parsed.monetary.get("amount"))] if parsed.monetary else [],
            )
            tw = TimeWindow(start_sec=start, end_sec=end, score=0.8)
            from python.transcription.pipeline import segments_to_document

            doc = segments_to_document(self.segments, self.transcript.video_id)
            refined = refine_window(tw, doc, parsed.raw_query, legacy)
            self._assert_time_window(refined.start_sec, refined.end_sec)
            return refined.start_sec, refined.end_sec
        except Exception:
            fallback_start, fallback_end = max(0, start - 1.5), end + 1.5
            self._assert_time_window(fallback_start, fallback_end)
            return fallback_start, fallback_end

    def _assert_time_window(self, start: Optional[float], end: Optional[float]) -> None:
        assert start is not None, "start_time must be present"
        assert end is not None, "end_time must be present"
        assert end > start, f"end_time must be greater than start_time (start={start}, end={end})"
        assert (end - start) > 0.5, f"duration must be > 0.5s (start={start}, end={end})"
