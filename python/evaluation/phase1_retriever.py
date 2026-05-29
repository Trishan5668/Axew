"""
Phase 1 retriever — hierarchical sentence-level chunks with utterance merge.

Uses chunked transcript instead of flat Whisper segments.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from python.evaluation.benchmark import CandidateWindow, RetrievalOutput
from python.evaluation.baseline_retriever import BaselineRetriever
from python.retrieval.chunker import Chunk
from python.transcription.pipeline import process_segments


class Phase1Retriever:
    """Retrieval over hierarchical sentence chunks."""

    def __init__(
        self,
        segments: List[Dict[str, Any]],
        top_k: int = 8,
        min_score: float = 0.22,
    ) -> None:
        self.segments = segments
        self.top_k = top_k
        self.min_score = min_score
        self._chunks: List[Chunk] = []
        self._baseline: BaselineRetriever | None = None
        self._ready = False

    def _ensure_ready(self) -> None:
        if self._ready:
            return

        doc, all_chunks = asyncio.run(
            process_segments(self.segments, skip_correction=True, skip_topic_label=True)
        )
        self._chunks = all_chunks.get("sentence", [])
        if not self._chunks:
            # Fallback to utterance chunks
            self._chunks = all_chunks.get("utterance", [])

        # Convert chunks to segment-like dicts for baseline retriever
        chunk_segments = [
            {
                "id": c.chunk_id,
                "start": c.start_sec,
                "end": c.end_sec,
                "text": c.text,
                "speaker": c.speaker_id,
            }
            for c in self._chunks
        ]
        self._baseline = BaselineRetriever(
            chunk_segments,
            top_k=self.top_k,
            min_score=self.min_score,
        )
        self._ready = True

    def __call__(self, query: str) -> RetrievalOutput:
        self._ensure_ready()
        assert self._baseline is not None
        return self._baseline(query)
