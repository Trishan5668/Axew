"""Build and hold per-video retrieval indexes from intelligence artifacts."""

from __future__ import annotations

from typing import Dict, List

from python.intelligence.extraction_pipeline import IntelligenceArtifacts
from python.retrieval.chunker import Chunk
from python.retrieval.hybrid_retriever import HybridRetriever


class VideoIndex:
    def __init__(self, artifacts: IntelligenceArtifacts, video_id: str) -> None:
        self.artifacts = artifacts
        self.video_id = video_id
        self.chunks_by_id: Dict[str, Chunk] = {}
        self._build_chunk_lookup()
        self.hybrid = HybridRetriever(video_id, self.chunks_by_id)

    def _build_chunk_lookup(self) -> None:
        for chunks in self.artifacts.chunks.values():
            for c in chunks:
                self.chunks_by_id[c.chunk_id] = c

    def index(self) -> None:
        all_chunks = list(self.chunks_by_id.values())
        self.hybrid.index(all_chunks)

    def get_parent_map(self) -> Dict[str, Chunk]:
        parents: Dict[str, Chunk] = {}
        for c in self.chunks_by_id.values():
            if c.parent_chunk_id and c.parent_chunk_id in self.chunks_by_id:
                parents[c.chunk_id] = self.chunks_by_id[c.parent_chunk_id]
        return parents
