from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class HookDetectionStrategy(RetrievalStrategy):
    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        topic_chunks = index.artifacts.chunks.get("topic", [])
        utterance_chunks = index.artifacts.chunks.get("utterance", [])
        candidates = topic_chunks or utterance_chunks

        scored: List[RetrievalResult] = []
        affect = index.artifacts.affect_index

        for chunk in candidates:
            entity_density = len(chunk.entities)
            aff = affect.by_chunk.get(chunk.chunk_id)
            emotion_score = aff.emotion.dominant_score if aff else 0.0
            action_density = len(chunk.events)
            composite = emotion_score * 0.4 + min(entity_density * 0.1, 0.3) + min(action_density * 0.1, 0.3)
            scored.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    chunk=chunk,
                    text=chunk.text,
                    start_sec=chunk.start_sec,
                    end_sec=chunk.end_sec,
                    score_fused=composite,
                )
            )

        scored.sort(key=lambda x: x.score_fused, reverse=True)
        return scored[:top_k]
