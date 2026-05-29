from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class TemporalStrategy(RetrievalStrategy):
    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        search_terms = parsed.entities or [parsed.original_query]
        all_results: List[RetrievalResult] = []

        for term in search_terms:
            all_results.extend(await index.hybrid.search(term, top_k=top_k))

        all_results.sort(key=lambda r: r.start_sec)

        if "first" in parsed.temporal_qualifiers:
            return all_results[:top_k]
        if "last" in parsed.temporal_qualifiers:
            return list(reversed(all_results))[:top_k]

        return all_results[:top_k]
