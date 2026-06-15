"""Cross-encoder reranking with optional parent context.

Falls back to bi-encoder cosine similarity when the cross-encoder is
unavailable (critical memory pressure) so retrieval never hard-fails.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np

from python.embeddings.embedder import EmbeddingEngine
from python.intelligence.query_parser import ParsedQuery
from python.retrieval.timestamp_contract import RetrievalIntegrityError
from python.retrieval.topic_segmenter import cosine
from python.retrieval.types import DecomposedQuery, RetrievalCandidate
from python.retrieval.chunker import Chunk

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self) -> None:
        self.embedder = EmbeddingEngine()

    def rerank(
        self,
        query: str,
        candidates: List[Chunk],
        use_large: bool = False,
    ) -> List[Tuple[Chunk, float]]:
        if not candidates:
            return []

        model = self.embedder.registry.get_cross_encoder(use_large=use_large)
        if model is None:
            return self._fallback_cosine_rank(query, candidates)

        return self.embedder.rerank(query, candidates, use_large=use_large)

    def rerank_with_context(
        self,
        query: str,
        candidates: List[Chunk],
        context_chunks: Dict[str, Chunk],
        use_large: bool = False,
    ) -> List[Tuple[Chunk, float]]:
        model = self.embedder.registry.get_cross_encoder(use_large=use_large)
        if model is None:
            return self._fallback_cosine_rank(query, candidates)

        return self.embedder.rerank_with_context(
            query, candidates, context_chunks, use_large=use_large
        )

    def should_use_large(self, parsed: ParsedQuery) -> bool:
        try:
            from python.resource_manager import should_use_lightweight

            if should_use_lightweight():
                return False
        except ImportError:
            pass
        return parsed.query_type in ("entity_action", "temporal")

    def _fallback_cosine_rank(
        self, query: str, candidates: List[Chunk]
    ) -> List[Tuple[Chunk, float]]:
        """Rank by bi-encoder cosine similarity when cross-encoder is unavailable."""
        import numpy as np

        logger.debug("Cross-encoder unavailable — falling back to cosine ranking")
        q_vec = self.embedder.embed_query(query)
        scored: List[Tuple[Chunk, float]] = []
        for c in candidates:
            if c.embedding:
                c_vec = np.array(c.embedding, dtype=np.float32)
                score = float(np.dot(q_vec, c_vec))
            else:
                c_vec = self.embedder.embed_passage(c.text)
                score = float(np.dot(q_vec, c_vec))
            scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


class ConversationalReranker:
    """Cross-encoder reranker with entity, context, topic, and calibration bonuses."""

    _cross_encoder = None

    def __init__(self) -> None:
        self.embedder = EmbeddingEngine()
        self.trace_events: Dict[str, List[dict]] = {"opener_demotions": []}

    def rerank(
        self,
        query: DecomposedQuery,
        candidates: List[RetrievalCandidate],
        session_context: List[str] | None = None,
    ) -> List[RetrievalCandidate]:
        if not candidates:
            return []

        ce_scores = [self._cross_score(query, c) for c in candidates]
        ce_norm = self._normalize(ce_scores)
        context_vec = self._session_context_embedding(session_context)

        try:
            from thefuzz import fuzz
        except Exception:
            try:
                from rapidfuzz import fuzz
            except Exception:
                from difflib import SequenceMatcher

                class _Fuzz:
                    @staticmethod
                    def partial_ratio(a: str, b: str) -> int:
                        a = (a or "").lower()
                        b = (b or "").lower()
                        if not a or not b:
                            return 0
                        if a in b or b in a:
                            return 100
                        short, long = (a, b) if len(a) <= len(b) else (b, a)
                        best = 0.0
                        for i in range(0, max(1, len(long) - len(short) + 1)):
                            best = max(best, SequenceMatcher(None, short, long[i:i + len(short)]).ratio())
                        return int(best * 100)

                fuzz = _Fuzz()

        for cand, ce_raw, ce_n in zip(candidates, ce_scores, ce_norm):
            cand.score_cross_encoder = float(ce_raw)
            text = cand.chunk.text.lower()
            entity_hits = sum(
                1 for ent in query.entities
                if ent.lower() in text or fuzz.partial_ratio(ent.lower(), text) >= 80
            )
            entity_bonus = min(entity_hits * 0.08, 0.20)
            context_bonus = 0.0
            if context_vec is not None:
                context_bonus = min(0.10, 0.05 * max(0.0, cosine(context_vec, self._chunk_embedding(cand.chunk))))
            topic_bonus = 0.0
            if cand.segment is not None:
                for concept in query.semantic_concepts:
                    if fuzz.partial_ratio(concept.lower(), cand.segment.topic_label.lower()) >= 60:
                        topic_bonus = 0.06
                        break
            cand.score_final = 0.45 * ce_n + 0.30 * cand.score_fused + entity_bonus + context_bonus + topic_bonus
            if cand.expanded_start is None or cand.expanded_end is None or cand.expanded_end <= cand.expanded_start:
                raise RetrievalIntegrityError(f"Rerank timestamp integrity failed | candidate={cand}")
            if cand.score_final is None:
                raise RetrievalIntegrityError(f"Rerank score_final missing | candidate={cand}")

        ranked = sorted(candidates, key=lambda c: c.score_final or 0.0, reverse=True)
        intro_terms = {"intro", "opening", "beginning", "start"}
        if ranked and ranked[0].is_opener and not (set(query.semantic_concepts) & intro_terms):
            if len(ranked) > 1:
                opener = ranked.pop(0)
                insert_at = min(2, len(ranked))
                ranked.insert(insert_at, opener)
                self.trace_events["opener_demotions"].append({
                    "chunk_id": opener.chunk.id,
                    "start": opener.chunk.start_time,
                    "reason": "top opener without intro intent",
                })

        self._calibrate(ranked)
        for rank, cand in enumerate(ranked, start=1):
            cand.rank = rank
            cand.match_explanation = (
                f"Dense:{cand.score_dense:.2f} BM25:{cand.score_bm25:.2f} Entity:{cand.score_entity:.2f} "
                f"Fuzzy:{cand.score_fuzzy:.2f} Strategy:{cand.score_strategy:.2f}"
                f"{'/' + ','.join(cand.strategy_origins) if cand.strategy_origins else ''} "
                f"-> Fused:{cand.score_fused:.2f} | "
                f"CE:{cand.score_cross_encoder:.2f} -> Final:{(cand.score_final or 0.0):.2f} "
                f"Calibrated:{cand.score_calibrated:.2f} [{cand.match_quality}] | "
                f"Opener:{cand.is_opener} | Segment:{cand.segment.topic_label if cand.segment else 'none'}"
            )
        return ranked

    def _cross_score(self, query: DecomposedQuery, cand: RetrievalCandidate) -> float:
        model = self._get_cross_encoder()
        prompts = [query.original] + query.paraphrases[:2]
        if model is not None:
            try:
                scores = model.predict([(p, cand.chunk.text) for p in prompts], show_progress_bar=False)
                return float(max(scores))
            except Exception as e:
                logger.warning("Cross-encoder scoring failed; using cosine fallback: %s", e)
        chunk_emb = self._chunk_embedding(cand.chunk)
        return float(max(cosine(self.embedder.embed_query(p), chunk_emb) for p in prompts))

    def _get_cross_encoder(self):
        if ConversationalReranker._cross_encoder is not None:
            return ConversationalReranker._cross_encoder
        try:
            from pathlib import Path
            from sentence_transformers import CrossEncoder

            cache_dir = Path(__file__).resolve().parents[2] / "models" / "cross_encoder"
            cache_dir.mkdir(parents=True, exist_ok=True)
            ConversationalReranker._cross_encoder = CrossEncoder(
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
                cache_folder=str(cache_dir),
            )
        except Exception as e:
            logger.warning("Cross-encoder unavailable; retrieval will use cosine fallback: %s", e)
            ConversationalReranker._cross_encoder = False
        return ConversationalReranker._cross_encoder if ConversationalReranker._cross_encoder is not False else None

    def _session_context_embedding(self, session_context: List[str] | None) -> np.ndarray | None:
        if not session_context:
            return None
        embeddings = [self.embedder.embed_query(q) for q in session_context if q.strip()]
        if not embeddings:
            return None
        return np.mean(embeddings, axis=0)

    def _chunk_embedding(self, chunk) -> np.ndarray:
        emb = getattr(chunk, "embedding", None)
        if emb is not None:
            return np.asarray(emb, dtype=np.float32)
        return self.embedder.embed_passage(chunk.text or "")

    # Intrinsic logit range of the ms-marco cross-encoders (a property of the
    # model, not of any video/benchmark): irrelevant pairs score around -10,
    # clearly-relevant pairs around +5 and above.
    _CE_LOGIT_FLOOR = -10.0
    _CE_LOGIT_CEIL = 5.0

    def _normalize(self, scores: List[float]) -> List[float]:
        # Absolute, fixed-range normalization of cross-encoder logits instead of
        # per-query min-max scaling. Min-max always maps the best candidate to
        # 1.0 -- even when EVERY candidate is irrelevant (all logits strongly
        # negative) -- which fabricates a full-strength relevance signal out of
        # noise and lets the cross-encoder override the topically-correct fused
        # retrieval score (a single "attractor" segment then wins unrelated
        # queries). Anchoring to the model's intrinsic logit range instead means
        # a query whose best match is still poor (e.g. max logit -8) yields a
        # uniformly low CE contribution so the fused score governs, while a
        # genuine match (logit > 0) still dominates. This stays monotonic in the
        # logit, so the cross-encoder's relative ordering is preserved.
        lo, hi = self._CE_LOGIT_FLOOR, self._CE_LOGIT_CEIL
        span = hi - lo
        return [float(np.clip((s - lo) / span, 0.0, 1.0)) for s in scores]

    def _calibrate(self, candidates: List[RetrievalCandidate]) -> None:
        scores = np.asarray([c.score_final or 0.0 for c in candidates], dtype=np.float32)
        p10, p90 = np.percentile(scores, [10, 90])
        for cand in candidates:
            cand.score_calibrated = float(np.clip(((cand.score_final or 0.0) - p10) / max(p90 - p10, 1e-6), 0.0, 1.0))
            if cand.score_calibrated >= 0.75:
                cand.match_quality = "strong_match"
            elif cand.score_calibrated >= 0.45:
                cand.match_quality = "moderate_match"
            elif cand.score_calibrated >= 0.20:
                cand.match_quality = "weak_match"
            else:
                cand.match_quality = "poor_match"
