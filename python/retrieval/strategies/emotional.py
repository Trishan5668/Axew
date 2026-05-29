from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class EmotionalStrategy(RetrievalStrategy):
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

        semantic = await index.hybrid.search(
            "emotional intense moment powerful",
            top_k=top_k,
            chunk_types=["sentence", "utterance"],
        )

        merged = emotional_chunks + semantic
        seen: set[str] = set()
        out: List[RetrievalResult] = []
        for r in sorted(merged, key=lambda x: x.score_fused, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                out.append(r)
        return out[:top_k]
