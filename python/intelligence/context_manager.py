"""
Conversational context manager — pronoun resolution and multi-turn refinement.

Phase 7: session memory for NLE prompt sequences.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from python.intelligence.query_parser import ParsedQuery
from python.retrieval.temporal_coherence import TimeWindow

logger = logging.getLogger(__name__)

PRONOUNS = ("he", "she", "they", "him", "her", "them", "his", "their", "it")

REFINEMENT_EARLIER = re.compile(
    r"\b(earlier|before\s+that|previous|prior|a\s+bit\s+before|go\s+back)\b",
    re.I,
)
REFINEMENT_LATER = re.compile(
    r"\b(later|after\s+that|next\s+one|a\s+bit\s+after|go\s+forward)\b",
    re.I,
)
REFINEMENT_REJECT = re.compile(
    r"\b(no,?\s+the|not\s+that|wrong|incorrect|try\s+again)\b",
    re.I,
)


class TimeWindowModel(BaseModel):
    start_sec: float
    end_sec: float
    score: float = 0.0


class ContextTurn(BaseModel):
    turn_id: int
    query: str
    parsed_query: Optional[ParsedQuery] = None
    retrieved_window: Optional[TimeWindowModel] = None
    confidence: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_feedback: Optional[str] = None


class TimelineState(BaseModel):
    """Lightweight snapshot of NLE timeline for context."""

    clip_count: int = 0
    duration_sec: float = 0.0
    entity_labels: Dict[str, List[Tuple[float, float]]] = Field(default_factory=dict)


class ConversationalContext(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    turn_history: List[ContextTurn] = Field(default_factory=list)
    active_entities: Dict[str, float] = Field(default_factory=dict)
    active_topics: List[str] = Field(default_factory=list)
    timeline_state: Optional[TimelineState] = None
    resolved_pronouns: Dict[str, str] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


class ContextManager:
    """Prepares queries using session history and records retrieval turns."""

    def __init__(self, context: Optional[ConversationalContext] = None) -> None:
        self.context = context or ConversationalContext()

    @property
    def session_id(self) -> str:
        return self.context.session_id

    def prepare_query(self, query: str) -> Tuple[str, Optional[TimeWindow], List[str]]:
        """
        Resolve pronouns and detect refinement intent.

        Returns (expanded_query, temporal_hint_window, trace_lines).
        """
        trace: List[str] = []
        expanded = query
        temporal_hint: Optional[TimeWindow] = None

        expanded, pronoun_trace = self._resolve_pronouns(expanded)
        trace.extend(pronoun_trace)

        last = self._last_turn_with_window()
        if last and last.retrieved_window:
            if REFINEMENT_EARLIER.search(query):
                w = last.retrieved_window
                span = w.end_sec - w.start_sec
                shift = max(span * 0.5, 15.0)
                temporal_hint = TimeWindow(
                    start_sec=max(0.0, w.start_sec - shift - span),
                    end_sec=max(0.0, w.start_sec - 2.0),
                    score=1.0,
                )
                trace.append(f"stage=context_refinement direction=earlier hint={temporal_hint.start_sec:.1f}-{temporal_hint.end_sec:.1f}")
            elif REFINEMENT_LATER.search(query):
                w = last.retrieved_window
                span = w.end_sec - w.start_sec
                shift = max(span * 0.5, 15.0)
                temporal_hint = TimeWindow(
                    start_sec=w.end_sec + 2.0,
                    end_sec=w.end_sec + shift + span,
                    score=1.0,
                )
                trace.append(f"stage=context_refinement direction=later hint={temporal_hint.start_sec:.1f}-{temporal_hint.end_sec:.1f}")
            elif REFINEMENT_REJECT.search(query):
                w = last.retrieved_window
                temporal_hint = TimeWindow(
                    start_sec=0.0,
                    end_sec=max(w.start_sec - 5.0, 0.0),
                    score=0.5,
                )
                trace.append("stage=context_refinement direction=reject_prior")

        if self.context.active_entities and not pronoun_trace:
            top_entity = max(self.context.active_entities, key=self.context.active_entities.get)
            if top_entity.lower() not in expanded.lower():
                trace.append(f"stage=context_active_entity={top_entity}")

        return expanded, temporal_hint, trace

    def record_turn(
        self,
        query: str,
        parsed: ParsedQuery,
        window: TimeWindow,
        confidence: float,
        segment_texts: Optional[List[str]] = None,
    ) -> ContextTurn:
        turn_id = len(self.context.turn_history) + 1
        turn = ContextTurn(
            turn_id=turn_id,
            query=query,
            parsed_query=parsed,
            retrieved_window=TimeWindowModel(
                start_sec=window.start_sec,
                end_sec=window.end_sec,
                score=window.score,
            ),
            confidence=confidence,
        )
        self.context.turn_history.append(turn)

        for entity in parsed.entities:
            self.context.active_entities[entity] = window.start_sec
            self.context.resolved_pronouns["he"] = entity
            self.context.resolved_pronouns["she"] = entity
            self.context.resolved_pronouns["they"] = entity

        if parsed.query_type not in self.context.active_topics:
            self.context.active_topics.append(parsed.query_type)
        self.context.active_topics = self.context.active_topics[-5:]

        if segment_texts:
            for text in segment_texts:
                for ent in parsed.entities:
                    if ent.lower() in text.lower():
                        self.context.active_entities[ent] = window.start_sec

        return turn

    def record_feedback(self, feedback: str) -> None:
        if self.context.turn_history:
            self.context.turn_history[-1].user_feedback = feedback

    def update_timeline_state(
        self,
        clip_count: int,
        duration_sec: float,
        entity_coverage: Optional[Dict[str, List[Tuple[float, float]]]] = None,
    ) -> None:
        self.context.timeline_state = TimelineState(
            clip_count=clip_count,
            duration_sec=duration_sec,
            entity_labels=entity_coverage or {},
        )

    def _last_turn_with_window(self) -> Optional[ContextTurn]:
        for turn in reversed(self.context.turn_history):
            if turn.retrieved_window:
                return turn
        return None

    def _resolve_pronouns(self, query: str) -> Tuple[str, List[str]]:
        trace: List[str] = []
        if not self.context.active_entities:
            return query, trace

        primary = max(self.context.active_entities, key=self.context.active_entities.get)
        words = query.split()
        replaced = False
        out: List[str] = []
        for w in words:
            bare = re.sub(r"[^\w']", "", w.lower())
            if bare in PRONOUNS and primary:
                out.append(primary if w[0].islower() else primary.title())
                replaced = True
            else:
                out.append(w)

        if replaced:
            expanded = " ".join(out)
            trace.append(f"stage=pronoun_resolved entity={primary}")
            return expanded, trace
        return query, trace


# Session store for API (in-memory; keyed by session_id)
_SESSIONS: Dict[str, ContextManager] = {}


def get_session(session_id: Optional[str] = None) -> ContextManager:
    if session_id and session_id in _SESSIONS:
        return _SESSIONS[session_id]
    mgr = ContextManager()
    _SESSIONS[mgr.session_id] = mgr
    return mgr
