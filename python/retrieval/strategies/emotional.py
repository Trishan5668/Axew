from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class EmotionalStrategy(RetrievalStrategy):
    MIN_FALLBACK_CANDIDATES = 3

    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        affect = index.artifacts.affect_index
        emotional_chunks = []

        for cid in affect.high_emotion_chunks:
            chunk = index.chunks_by_id.get(cid)
            if chunk:
                aff = affect.by_chunk.get(cid)
                score = 0.8
                if aff:
                    score = max(aff.sentiment.intensity, aff.emotion.dominant_score)
                emotional_chunks.append(
                    RetrievalResult(
                        chunk_id=cid,
                        chunk=chunk,
                        text=chunk.text,
                        start_sec=chunk.start_sec,
                        end_sec=chunk.end_sec,
                        score_fused=score,
                    )
                )

        semantic: List[RetrievalResult] = []
        subqueries = list(dict.fromkeys(
            [parsed.original_query] + list(parsed.decomposed_subqueries or [])
        ))
        for subq in subqueries[:4]:
            semantic.extend(
                await index.hybrid.search(
                    subq,
                    top_k=max(self.MIN_FALLBACK_CANDIDATES, top_k // 2),
                    chunk_types=["sentence", "utterance"],
                )
            )

        merged = emotional_chunks + semantic
        if len(merged) < self.MIN_FALLBACK_CANDIDATES:
            merged.extend(self._event_affect_fallback(parsed, index))
        seen: set[str] = set()
        out: List[RetrievalResult] = []
        for r in sorted(merged, key=lambda x: x.score_fused, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                out.append(r)
        return out[:top_k]

    def _event_affect_fallback(self, parsed: ParsedQuery, index: VideoIndex) -> List[RetrievalResult]:
        results: List[RetrievalResult] = []
        mentions = []
        mentions.extend(index.artifacts.event_index.lookup("emotional"))
        mentions.extend(index.artifacts.event_index.lookup("audience_reaction"))
        for mention in sorted(mentions, key=lambda m: m.confidence, reverse=True):
            chunk = index.chunks_by_id.get(mention.chunk_id)
            if not chunk:
                continue
            results.append(
                RetrievalResult(
                    chunk_id=mention.chunk_id,
                    chunk=chunk,
                    text=chunk.text,
                    start_sec=mention.start_sec,
                    end_sec=mention.end_sec,
                    score_fused=max(0.55, float(mention.confidence)),
                    events=[mention.verb, mention.event_type],
                )
            )
        return results
