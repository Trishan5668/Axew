from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class GenericStrategy(RetrievalStrategy):
    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        results: List[RetrievalResult] = []
        for subq in parsed.decomposed_subqueries[:3]:
            batch = await index.hybrid.search(
                subq,
                top_k=top_k // max(len(parsed.decomposed_subqueries), 1) + 5,
                chunk_types=["sentence", "utterance"],
            )
            results.extend(batch)

        seen = set()
        unique: List[RetrievalResult] = []
        for r in sorted(results, key=lambda x: x.score_fused, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                unique.append(r)
        return unique[:top_k]
