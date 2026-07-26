"""Shared types for the production semantic retrieval engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np

from python.models.transcript import TranscriptChunk


@dataclass
class DecomposedQuery:
    original: str
    entities: list[str] = field(default_factory=list)
    entity_types: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    event_verbs: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    affect_signals: list[str] = field(default_factory=list)
    intent_signals: list[str] = field(default_factory=list)
    routing_confidence: float = 0.5
    semantic_concepts: list[str] = field(default_factory=list)
    monetary_refs: list[str] = field(default_factory=list)
    paraphrases: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    lang_hint: str = "en"
    entity_anchored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TopicSegment:
    segment_id: str
    chunks: list[TranscriptChunk]
    start: float
    end: float
    topic_label: str
    embedding: np.ndarray
    boundary_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start": self.start,
            "end": self.end,
            "topic_label": self.topic_label,
            "boundary_confidence": self.boundary_confidence,
            "chunk_ids": [c.id for c in self.chunks],
        }


@dataclass
class RetrievalCandidate:
    chunk: TranscriptChunk
    segment: Optional[TopicSegment] = None
    score_dense: float = 0.0
    score_bm25: float = 0.0
    score_entity: float = 0.0
    score_fuzzy: float = 0.0
    score_strategy: float = 0.0
    score_fused: float = 0.0
    match_explanation: str = ""
    is_opener: bool = False
    rank: int = 0
    score_entity_bonus: bool = False
    strategy_origins: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    expanded_start: Optional[float] = None
    expanded_end: Optional[float] = None
    anchor_start: Optional[float] = None
    anchor_end: Optional[float] = None
    score_cross_encoder: float = 0.0
    score_final: Optional[float] = None
    score_calibrated: float = 0.0
    match_quality: str = "poor_match"

    def __post_init__(self) -> None:
        self.is_opener = self.chunk.start_time < 5.0
        self.anchor_start = self.chunk.start_time if self.anchor_start is None else self.anchor_start
        self.anchor_end = self.chunk.end_time if self.anchor_end is None else self.anchor_end
        self.expanded_start = self.chunk.start_time if self.expanded_start is None else self.expanded_start
        self.expanded_end = self.chunk.end_time if self.expanded_end is None else self.expanded_end

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.id,
            "text": self.chunk.text,
            "start": self.chunk.start_time,
            "end": self.chunk.end_time,
            "anchor_start": self.anchor_start,
            "anchor_end": self.anchor_end,
            "expanded_start": self.expanded_start,
            "expanded_end": self.expanded_end,
            "segment": self.segment.to_dict() if self.segment else None,
            "score_dense": self.score_dense,
            "score_bm25": self.score_bm25,
            "score_entity": self.score_entity,
            "score_fuzzy": self.score_fuzzy,
            "score_strategy": self.score_strategy,
            "score_fused": self.score_fused,
            "score_cross_encoder": self.score_cross_encoder,
            "score_final": self.score_final,
            "score_calibrated": self.score_calibrated,
            "match_quality": self.match_quality,
            "match_explanation": self.match_explanation,
            "is_opener": self.is_opener,
            "rank": self.rank,
            "strategy_origins": self.strategy_origins,
            "tags": self.tags,
        }
