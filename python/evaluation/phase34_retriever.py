"""
Phase 3 and Phase 4 benchmark retrievers.

- Phase3Retriever: hybrid dense + BM25 (RRF) only
- Phase4Retriever: full multi-stage orchestrator
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from python.evaluation.benchmark import CandidateWindow, RetrievalOutput
from python.intelligence.extraction_pipeline import extract_intelligence
from python.retrieval.orchestrator import RetrievalOrchestrator
from python.retrieval.video_index import VideoIndex


class Phase3Retriever:
    """Hybrid retrieval (BGE + BM25 RRF) without reranking orchestration."""

    def __init__(self, segments: List[Dict[str, Any]], top_k: int = 8) -> None:
        self.segments = segments
        self.top_k = top_k
        self._index: Optional[VideoIndex] = None

    def _ensure_ready(self) -> VideoIndex:
        if self._index is None:
            artifacts = asyncio.run(extract_intelligence(self.segments, video_id="fixture"))
            self._index = VideoIndex(artifacts, "fixture")
            self._index.index()
        return self._index

    def __call__(self, query: str) -> RetrievalOutput:
        index = self._ensure_ready()

        results = asyncio.run(
            index.hybrid.search(query, top_k=self.top_k, chunk_types=["sentence", "utterance"])
        )

        if not results:
            return RetrievalOutput(0, 0, 0, [])

        candidates = [
            CandidateWindow(r.start_sec, r.end_sec, r.score_fused) for r in results
        ]
        best = results[0]
        start, end = best.start_sec, best.end_sec
        for r in results[1:4]:
            if r.start_sec <= end + 1.5:
                end = max(end, r.end_sec)

        return RetrievalOutput(
            start_sec=max(0.0, start - 0.4),
            end_sec=end + 0.4,
            confidence=best.score_fused,
            candidates=candidates,
        )


class Phase4Retriever:
    """Full orchestrator: parse, strategy, hybrid, rerank, coherence, confidence."""

    def __init__(self, segments: List[Dict[str, Any]], top_k: int = 8) -> None:
        self.segments = segments
        self.top_k = top_k
        self._orchestrator: Optional[RetrievalOrchestrator] = None

    def _ensure_ready(self) -> RetrievalOrchestrator:
        if self._orchestrator is None:
            artifacts = asyncio.run(extract_intelligence(self.segments, video_id="fixture"))
            index = VideoIndex(artifacts, "fixture")
            index.index()
            self._orchestrator = RetrievalOrchestrator(
                index, self.segments, enable_refinement=False
            )
        return self._orchestrator

    def __call__(self, query: str) -> RetrievalOutput:
        orch = self._ensure_ready()
        response = asyncio.run(orch.retrieve(query, top_k=self.top_k))

        candidates = [
            CandidateWindow(
                c.start_sec,
                c.end_sec,
                c.score_fused,
            )
            for c in response.candidates[: self.top_k]
        ]

        fw = response.final_window
        conf = response.confidence.composite if response.confidence else fw.confidence

        return RetrievalOutput(
            start_sec=fw.start_sec,
            end_sec=fw.end_sec,
            confidence=conf,
            candidates=candidates or [
                CandidateWindow(fw.start_sec, fw.end_sec, conf)
            ],
        )
