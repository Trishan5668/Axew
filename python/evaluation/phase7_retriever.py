"""
Phase 7 benchmark retriever — conversational context across turns.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from python.evaluation.benchmark import RetrievalOutput
from python.evaluation.phase56_retriever import _response_to_output
from python.intelligence.context_manager import ConversationalContext
from python.intelligence.extraction_pipeline import extract_intelligence
from python.retrieval.orchestrator import RetrievalOrchestrator
from python.retrieval.video_index import VideoIndex


class Phase7Retriever:
    """Phase 5 orchestrator + session context manager."""

    def __init__(self, segments: List[Dict[str, Any]], top_k: int = 8) -> None:
        self.segments = segments
        self.top_k = top_k
        self._orchestrator: Optional[RetrievalOrchestrator] = None
        self._context = ConversationalContext()

    def _ensure_ready(self) -> RetrievalOrchestrator:
        if self._orchestrator is None:
            artifacts = asyncio.run(extract_intelligence(self.segments, video_id="fixture"))
            index = VideoIndex(artifacts, "fixture")
            index.index()
            self._orchestrator = RetrievalOrchestrator(
                index, self.segments, enable_refinement=True, multimodal=None
            )
        return self._orchestrator

    def __call__(self, query: str) -> RetrievalOutput:
        orch = self._ensure_ready()
        response = asyncio.run(
            orch.retrieve(query, top_k=self.top_k, context=self._context)
        )
        return _response_to_output(response, self.top_k)
