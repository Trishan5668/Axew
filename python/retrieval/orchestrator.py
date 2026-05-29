"""
Multi-stage retrieval orchestrator — Phases 3 + 4 combined pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from python.intelligence.context_manager import ContextManager, ConversationalContext
from python.intelligence.extraction_pipeline import IntelligenceArtifacts
from python.intelligence.query_parser import ParsedQuery, QueryParser
from python.intelligence.ner import normalize_entity
from python.retrieval.chunker import Chunk
from python.retrieval.confidence import ConfidenceBreakdown, ConfidenceScorer
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.reranker import CrossEncoderReranker
from python.retrieval.strategies import get_strategy
from python.retrieval.temporal_coherence import TimeWindow, apply_temporal_coherence, merge_overlapping_windows
from python.retrieval.timestamp_refiner import (
    extract_entity_action_timestamp,
    refine_window,
)
from python.retrieval.video_index import VideoIndex

logger = logging.getLogger(__name__)


class TimeWindowOut(BaseModel):
    start_sec: float
    end_sec: float
    confidence: float = 0.0


class RetrievalResponse(BaseModel):
    query: str
    parsed_query: ParsedQuery
    candidates: List[RetrievalResult] = Field(default_factory=list)
    final_window: TimeWindowOut
    pipeline_trace: List[str] = Field(default_factory=list)
    confidence: Optional[ConfidenceBreakdown] = None
    session_id: Optional[str] = None


class RetrievalOrchestrator:
    def __init__(
        self,
        index: VideoIndex,
        segments: Optional[List[Dict[str, Any]]] = None,
        enable_refinement: bool = True,
        multimodal: Optional[Any] = None,
    ) -> None:
        self.index = index
        self.segments = segments or []
        self.enable_refinement = enable_refinement
        self.multimodal = multimodal
        self.query_parser = QueryParser()
        self.reranker = CrossEncoderReranker()
        self.confidence_scorer = ConfidenceScorer()
        self.trace: List[str] = []

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        context: Optional[ConversationalContext] = None,
    ) -> RetrievalResponse:
        self.trace = []
        self.trace.append("stage=query_received")

        ctx_mgr = ContextManager(context) if context is not None else ContextManager()
        expanded_query, temporal_hint, ctx_trace = ctx_mgr.prepare_query(query)
        self.trace.extend(ctx_trace)

        video_id = self.index.video_id
        from python.cache.query_cache import get_cached, set_cached

        cached = get_cached(video_id, expanded_query, top_k)
        if cached:
            self.trace.append("stage=query_cache_hit")
            return RetrievalResponse.model_validate(cached)

        parsed = await self.query_parser.parse_query(expanded_query)
        self.trace.append(f"stage=query_parsed type={parsed.query_type} strategy={parsed.retrieval_strategy}")

        response = await self._retrieve_parsed(
            query, expanded_query, parsed, top_k, temporal_hint
        )
        response.session_id = ctx_mgr.session_id

        fw = response.final_window
        ctx_mgr.record_turn(
            query,
            parsed,
            TimeWindow(fw.start_sec, fw.end_sec, fw.confidence),
            response.confidence.composite if response.confidence else fw.confidence,
        )
        set_cached(video_id, expanded_query, top_k, response.model_dump(mode="json"))
        return response

    async def _retrieve_parsed(
        self,
        original_query: str,
        query: str,
        parsed: ParsedQuery,
        top_k: int,
        temporal_hint: Optional[TimeWindow] = None,
    ) -> RetrievalResponse:
        if temporal_hint and temporal_hint.end_sec > temporal_hint.start_sec:
            hint_resp = await self._retrieve_in_window(query, parsed, top_k, temporal_hint)
            if hint_resp and hint_resp.final_window.confidence > 0.2:
                hint_resp.pipeline_trace = self.trace + hint_resp.pipeline_trace
                return hint_resp

        # Fast path: direct monetary + entity + action (most precise for amount queries)
        direct = self._direct_monetary_match(parsed)
        if direct:
            start, end, score = direct
            self.trace.append(f"stage=direct_monetary_match start={start:.1f} end={end:.1f}")
            fw = TimeWindowOut(start_sec=max(0.0, start - 0.4), end_sec=end + 0.4, confidence=score)
            if self.enable_refinement:
                fw = self._apply_refinement(fw, query, parsed, light=True)
            conf = ConfidenceBreakdown(composite=min(score, 1.0), grade="HIGH" if score > 0.8 else "MEDIUM")
            return RetrievalResponse(
                query=original_query,
                parsed_query=parsed,
                final_window=fw,
                pipeline_trace=self.trace,
                confidence=conf,
            )

        # Entity-action timestamp candidates (Phase 5.2)
        if parsed.query_type == "entity_action" and parsed.entities and parsed.actions:
            ea_candidates = extract_entity_action_timestamp(
                parsed.entities,
                parsed.actions,
                parsed.monetary_amounts,
                self.index.artifacts.entity_index,
                self.index.artifacts.event_index,
            )
            if ea_candidates:
                best_ea = ea_candidates[0]
                self.trace.append(f"stage=entity_action_ts score={best_ea.score:.3f}")
                fw = TimeWindowOut(
                    start_sec=best_ea.start_sec,
                    end_sec=best_ea.end_sec,
                    confidence=best_ea.score,
                )
                if self.enable_refinement:
                    fw = self._apply_refinement(fw, query, parsed, light=False)
                return RetrievalResponse(
                    query=original_query,
                    parsed_query=parsed,
                    final_window=fw,
                    pipeline_trace=self.trace,
                    confidence=ConfidenceBreakdown(composite=min(best_ea.score, 1.0), grade="HIGH" if best_ea.score > 0.7 else "MEDIUM"),
                )

        # Multimodal-augmented retrieval when index available (Phase 6)
        if self.multimodal and getattr(self.multimodal, "ready", False):
            if parsed.query_type == "entity_action" or parsed.monetary_amounts:
                mm_response = await self.retrieve_multimodal(query, parsed, top_k)
                if mm_response:
                    mm_response.query = original_query
                    return mm_response

        strategy = get_strategy(parsed.query_type)
        candidates = await strategy.retrieve_candidates(parsed, self.index, top_k=50)
        self.trace.append(f"stage=candidates count={len(candidates)}")

        chunks = [c.chunk for c in candidates if c.chunk]
        if not chunks:
            return RetrievalResponse(
                query=original_query,
                parsed_query=parsed,
                final_window=TimeWindowOut(start_sec=0, end_sec=0, confidence=0),
                pipeline_trace=self.trace + ["stage=no_candidates"],
            )

        expanded = self.expand_with_context(chunks)
        self.trace.append(f"stage=context_expanded count={len(expanded)}")

        use_large = self.reranker.should_use_large(parsed)
        reranked = self.reranker.rerank_with_context(
            query, expanded[:30], self.index.get_parent_map(), use_large=use_large
        )
        self.trace.append(f"stage=reranked top={reranked[0][1]:.3f}" if reranked else "stage=reranked empty")

        coherent = apply_temporal_coherence(reranked)
        self.trace.append("stage=temporal_coherence")

        scored_pairs = coherent[:top_k]
        duration = self.index.artifacts.document.duration_sec
        best_chunk, best_rerank = scored_pairs[0]
        conf = self.confidence_scorer.score(
            best_chunk, query, parsed, best_rerank, parsed.retrieval_strategy, duration
        )
        self.trace.append(f"stage=confidence grade={conf.grade} composite={conf.composite:.3f}")

        final = self.select_final_window(scored_pairs, parsed)
        if self.enable_refinement:
            final = self._apply_refinement(final, query, parsed, light=False)
        self.trace.append(f"stage=final_window start={final.start_sec:.1f} end={final.end_sec:.1f}")

        return RetrievalResponse(
            query=original_query,
            parsed_query=parsed,
            candidates=candidates[:top_k],
            final_window=final,
            pipeline_trace=self.trace,
            confidence=conf,
        )

    async def _retrieve_in_window(
        self,
        query: str,
        parsed: ParsedQuery,
        top_k: int,
        hint: TimeWindow,
    ) -> Optional[RetrievalResponse]:
        """Search within a conversational temporal hint window."""
        self.trace.append(
            f"stage=context_window_search start={hint.start_sec:.1f} end={hint.end_sec:.1f}"
        )
        in_range: List[Chunk] = []
        for chunk in self.index.chunks_by_id.values():
            if chunk.chunk_type == "entity_context":
                continue
            if chunk.end_sec >= hint.start_sec and chunk.start_sec <= hint.end_sec:
                in_range.append(chunk)

        if not in_range:
            return None

        reranked = self.reranker.rerank(query, in_range[:40], use_large=self.reranker.should_use_large(parsed))
        if not reranked:
            return None

        coherent = apply_temporal_coherence(reranked)
        final = self.select_final_window(coherent, parsed)
        if self.enable_refinement:
            final = self._apply_refinement(final, query, parsed, light=False)

        best_chunk, best_score = coherent[0]
        duration = self.index.artifacts.document.duration_sec
        conf = self.confidence_scorer.score(
            best_chunk, query, parsed, best_score, "context_refinement", duration
        )
        return RetrievalResponse(
            query=query,
            parsed_query=parsed,
            final_window=final,
            pipeline_trace=["stage=context_window_hit"],
            confidence=conf,
        )

    def expand_with_context(self, candidates: List[Chunk]) -> List[Chunk]:
        expanded: List[Chunk] = []
        seen: set[str] = set()
        for c in candidates:
            if c.chunk_id in seen:
                continue
            seen.add(c.chunk_id)
            expanded.append(c)
            if c.parent_chunk_id:
                parent = self.index.chunks_by_id.get(c.parent_chunk_id)
                if parent and parent.chunk_id not in seen:
                    seen.add(parent.chunk_id)
                    expanded.append(parent)
        return expanded

    def select_final_window(
        self,
        ranked: List[Tuple[Chunk, float]],
        parsed: ParsedQuery,
    ) -> TimeWindowOut:
        if not ranked:
            return TimeWindowOut(start_sec=0, end_sec=0, confidence=0)

        windows = [
            TimeWindow(start_sec=c.start_sec, end_sec=c.end_sec, score=s)
            for c, s in ranked[:5]
        ]
        merged = merge_overlapping_windows(windows)
        if not merged:
            best, score = ranked[0]
            start, end = self._expand_to_segment(best.start_sec, best.end_sec)
            return TimeWindowOut(start_sec=max(0.0, start - 0.4), end_sec=end + 0.4, confidence=float(score))

        best_w = max(merged, key=lambda w: w.score)
        start, end = self._expand_to_segment(best_w.start_sec, best_w.end_sec)
        return TimeWindowOut(
            start_sec=max(0.0, start - 0.4),
            end_sec=end + 0.4,
            confidence=best_w.score,
        )

    def _expand_to_segment(self, start: float, end: float) -> Tuple[float, float]:
        center = (start + end) / 2
        best_seg = None
        best_overlap = 0.0
        for seg in self.segments:
            s, e = float(seg["start"]), float(seg["end"])
            overlap = max(0.0, min(end, e) - max(start, s))
            if overlap > best_overlap or (s <= center <= e):
                best_overlap = max(best_overlap, overlap)
                best_seg = seg
        if best_seg:
            return float(best_seg["start"]), float(best_seg["end"])
        return start, end

    def _query_action_in_text(self, text_lower: str, actions: List[str]) -> bool:
        if not actions:
            return True
        for action in actions:
            stem = action.rstrip("e")
            if re.search(rf"\b{re.escape(action)}|{re.escape(stem)}ing|{re.escape(stem)}es\b", text_lower):
                return True
        return False

    def _direct_monetary_match(self, parsed: ParsedQuery) -> Optional[Tuple[float, float, float]]:
        if not parsed.monetary_amounts or not parsed.entities:
            return None

        candidates: List[Tuple[float, float, float]] = []
        for chunk in self.index.chunks_by_id.values():
            if chunk.chunk_type == "entity_context":
                continue
            text_lower = chunk.text.lower()
            has_money = any(
                m.lower() in text_lower or (re.search(r"\d+", m) and re.search(r"\d+", m).group() in text_lower)
                for m in parsed.monetary_amounts
            )
            has_entity = any(normalize_entity(e) in text_lower for e in parsed.entities)
            has_action = self._query_action_in_text(text_lower, parsed.actions)
            if has_money and has_entity and has_action:
                precision = 1.0 / max(chunk.end_sec - chunk.start_sec, 1.0)
                candidates.append((chunk.start_sec, chunk.end_sec, precision))

        if not candidates:
            return None
        best = max(candidates, key=lambda x: x[2])
        start, end, score = best
        start, end = self._expand_to_segment(start, end)
        return start, end, score

    def _apply_refinement(
        self,
        window: TimeWindowOut,
        query: str,
        parsed: ParsedQuery,
        light: bool = False,
    ) -> TimeWindowOut:
        tw = TimeWindow(start_sec=window.start_sec, end_sec=window.end_sec, score=window.confidence)
        refined = refine_window(
            tw,
            self.index.artifacts.document,
            query,
            parsed,
        )
        if light:
            # Preserve segment-aligned start; only extend end for natural lead-out
            start = window.start_sec
            end = max(window.end_sec, refined.end_sec)
        else:
            start = refined.start_sec
            end = refined.end_sec
            # Don't drift start more than 5s earlier than coarse window
            start = max(start, window.start_sec - 5.0)

        self.trace.append(
            f"stage=timestamp_refined anchor={refined.anchor_word!r} conf={refined.confidence:.3f}"
        )
        return TimeWindowOut(
            start_sec=start,
            end_sec=end,
            confidence=max(window.confidence, refined.confidence),
        )

    async def retrieve_multimodal(
        self,
        query: str,
        parsed: ParsedQuery,
        top_k: int = 5,
    ) -> Optional[RetrievalResponse]:
        """Fuse transcript hybrid retrieval with CLIP frame search (Phase 6)."""
        from python.multimodal.multimodal_index import frames_to_windows, merge_transcript_visual

        self.trace.append("stage=multimodal_retrieval")
        transcript_results = await self.index.hybrid.search(
            query, top_k=30, chunk_types=["sentence", "utterance", "entity_context"]
        )

        visual_windows: List[Tuple[float, float, float]] = []
        if self.multimodal and self.multimodal.clip:
            frame_hits = self.multimodal.clip.search_frames_by_text(query, top_k=10)
            visual_windows = frames_to_windows(frame_hits)

        if self.multimodal and self.multimodal.scene_chunks:
            import numpy as np
            from python.embeddings.embedder import EmbeddingEngine

            eng = EmbeddingEngine()
            qv = eng.embed_query(query)
            for sc in self.multimodal.scene_chunks:
                if sc.embedding:
                    sim = float(np.dot(qv, np.array(sc.embedding)))
                    visual_windows.append((sc.start_sec, sc.end_sec, sim))

        merged = merge_transcript_visual(transcript_results, visual_windows)
        if not merged:
            return None

        chunks = [m.chunk for m in merged[:20] if m.chunk]
        if not chunks:
            return None

        reranked = self.reranker.rerank(query, chunks, use_large=self.reranker.should_use_large(parsed))
        coherent = apply_temporal_coherence(reranked)
        final = self.select_final_window(coherent, parsed)
        if self.enable_refinement:
            final = self._apply_refinement(final, query, parsed, light=False)

        conf = self.confidence_scorer.score(
            coherent[0][0], query, parsed, coherent[0][1], "multimodal", self.index.artifacts.document.duration_sec
        )
        self.trace.append("stage=multimodal_complete")

        return RetrievalResponse(
            query=query,
            parsed_query=parsed,
            candidates=merged[:top_k],
            final_window=final,
            pipeline_trace=self.trace,
            confidence=conf,
        )
