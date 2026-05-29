"""
Phase 5 and Phase 6 benchmark retrievers.

Phase 5: Phase 4 orchestrator + word-level timestamp refinement.
Phase 6: Phase 5 + multimodal (CLIP/OCR) when media_path is provided.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from python.evaluation.benchmark import CandidateWindow, RetrievalOutput
from python.intelligence.extraction_pipeline import extract_intelligence
from python.multimodal.multimodal_index import build_multimodal_index
from python.retrieval.orchestrator import RetrievalOrchestrator
from python.retrieval.video_index import VideoIndex


class Phase5Retriever:
    """Full orchestrator with timestamp refinement enabled."""

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
                index, self.segments, enable_refinement=True, multimodal=None
            )
        return self._orchestrator

    def __call__(self, query: str) -> RetrievalOutput:
        orch = self._ensure_ready()
        response = asyncio.run(orch.retrieve(query, top_k=self.top_k))
        return _response_to_output(response, self.top_k)


class Phase6Retriever:
    """Phase 5 + multimodal fusion when AXEW_BENCHMARK_MEDIA or media_path is set."""

    def __init__(
        self,
        segments: List[Dict[str, Any]],
        top_k: int = 8,
        media_path: Optional[str] = None,
    ) -> None:
        self.segments = segments
        self.top_k = top_k
        self.media_path = media_path or os.environ.get("AXEW_BENCHMARK_MEDIA")
        self._orchestrator: Optional[RetrievalOrchestrator] = None

    def _ensure_ready(self) -> RetrievalOrchestrator:
        if self._orchestrator is None:
            artifacts = asyncio.run(extract_intelligence(self.segments, video_id="fixture"))
            index = VideoIndex(artifacts, "fixture")
            index.index()

            multimodal = None
            if self.media_path and os.path.isfile(self.media_path):
                duration = artifacts.document.duration_sec
                speaker_times = [
                    float(s["start"])
                    for i, s in enumerate(self.segments)
                    if i > 0 and s.get("speaker") != self.segments[i - 1].get("speaker")
                ]
                multimodal = asyncio.run(
                    build_multimodal_index(
                        self.media_path,
                        "fixture",
                        duration,
                        speaker_change_times=speaker_times,
                        skip_ollama_scenes=True,
                    )
                )

            self._orchestrator = RetrievalOrchestrator(
                index,
                self.segments,
                enable_refinement=True,
                multimodal=multimodal,
            )
        return self._orchestrator

    def __call__(self, query: str) -> RetrievalOutput:
        orch = self._ensure_ready()
        response = asyncio.run(orch.retrieve(query, top_k=self.top_k))
        return _response_to_output(response, self.top_k)


def _response_to_output(response, top_k: int) -> RetrievalOutput:
    candidates = [
        CandidateWindow(c.start_sec, c.end_sec, c.score_fused)
        for c in response.candidates[:top_k]
    ]
    fw = response.final_window
    conf = response.confidence.composite if response.confidence else fw.confidence
    return RetrievalOutput(
        start_sec=fw.start_sec,
        end_sec=fw.end_sec,
        confidence=conf,
        candidates=candidates or [CandidateWindow(fw.start_sec, fw.end_sec, conf)],
    )
