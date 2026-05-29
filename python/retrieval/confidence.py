"""Composite confidence scoring for retrieval results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

import numpy as np
from pydantic import BaseModel

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.chunker import Chunk

if TYPE_CHECKING:
    from python.embeddings.embedder import EmbeddingEngine


class ConfidenceBreakdown(BaseModel):
    semantic_similarity: float = 0.0
    rerank_score: float = 0.0
    entity_match_score: float = 0.0
    action_match_score: float = 0.0
    temporal_position_score: float = 0.0
    speaker_match_score: float = 0.5
    monetary_match_score: float = 0.0
    composite: float = 0.0
    grade: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"


class ConfidenceScorer:
    def __init__(self, embedder: Optional["EmbeddingEngine"] = None) -> None:
        self._embedder = embedder

    @property
    def embedder(self) -> "EmbeddingEngine":
        if self._embedder is None:
            from python.embeddings.embedder import EmbeddingEngine

            self._embedder = EmbeddingEngine()
        return self._embedder

    def score(
        self,
        chunk: Chunk,
        query: str,
        parsed: ParsedQuery,
        rerank_score: float,
        retrieval_method: str,
        video_duration: float = 0.0,
    ) -> ConfidenceBreakdown:
        q_vec = self.embedder.embed_query(query)
        c_vec = np.array(chunk.embedding or self.embedder.embed_passage(chunk.text))
        semantic = float(np.dot(q_vec, c_vec)) if len(c_vec) else 0.0

        rerank_norm = 1.0 / (1.0 + np.exp(-rerank_score / 5.0))

        entity_match = 0.0
        if parsed.entities:
            text_l = chunk.text.lower()
            hits = sum(1 for e in parsed.entities if e.lower() in text_l)
            entity_match = hits / len(parsed.entities)

        action_match = 0.0
        if parsed.actions:
            text_l = chunk.text.lower()
            hits = sum(1 for a in parsed.actions if a in text_l or f"{a}ing" in text_l)
            action_match = hits / len(parsed.actions)

        temporal_pos = 0.5
        if video_duration > 0:
            center = (chunk.start_sec + chunk.end_sec) / 2
            edge_dist = min(center, video_duration - center) / video_duration
            temporal_pos = min(1.0, edge_dist * 2)

        monetary = 0.0
        if parsed.monetary_amounts:
            for m in parsed.monetary_amounts:
                if m.lower() in chunk.text.lower():
                    monetary = 1.0
                    break

        composite = (
            semantic * 0.25
            + rerank_norm * 0.30
            + entity_match * 0.20
            + action_match * 0.10
            + monetary * 0.10
            + temporal_pos * 0.05
        )
        grade: Literal["HIGH", "MEDIUM", "LOW"] = (
            "HIGH" if composite > 0.8 else ("MEDIUM" if composite > 0.5 else "LOW")
        )

        return ConfidenceBreakdown(
            semantic_similarity=semantic,
            rerank_score=rerank_norm,
            entity_match_score=entity_match,
            action_match_score=action_match,
            temporal_position_score=temporal_pos,
            monetary_match_score=monetary,
            composite=composite,
            grade=grade,
        )
