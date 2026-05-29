from __future__ import annotations

from typing import List

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class AudienceReactionStrategy(RetrievalStrategy):
    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        events = index.artifacts.event_index.lookup("audience_reaction")
        event_results: List[RetrievalResult] = []
        for ev in events:
            chunk = index.chunks_by_id.get(ev.chunk_id)
            if chunk:
                event_results.append(
                    RetrievalResult(
                        chunk_id=ev.chunk_id,
                        chunk=chunk,
                        text=chunk.text,
                        start_sec=ev.start_sec,
                        end_sec=ev.end_sec,
                        score_fused=ev.confidence,
                    )
                )

        semantic = await index.hybrid.search(
            "audience laughter applause reaction crowd",
            top_k=top_k,
        )
        bm25 = await index.hybrid.search(
            "laugh laughter applause crowd audience",
            top_k=top_k // 2,
        )

        merged = event_results + semantic + bm25
        seen: set[str] = set()
        out: List[RetrievalResult] = []
        for r in sorted(merged, key=lambda x: x.score_fused, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                out.append(r)
        return out[:top_k]
