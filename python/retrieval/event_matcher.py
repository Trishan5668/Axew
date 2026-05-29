"""Structured event graph matching for parsed queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from python.enrichment.entity_graph import EntityTimelineGraph
from python.enrichment.monetary_parser import MonetaryParser
from python.intelligence.ner import normalize_entity
from python.models.enriched import EnrichedTranscript, ExtractedEvent


@dataclass
class ParsedQuery:
    intent_action: str = "keep_segment"
    subject: Optional[str] = None
    verb: Optional[str] = None
    object: Optional[str] = None
    recipient: Optional[str] = None
    entities: List[str] = field(default_factory=list)
    action_types: List[str] = field(default_factory=list)
    monetary: Optional[dict] = None
    speaker_roles: List[str] = field(default_factory=list)
    temporal_modifiers: List[str] = field(default_factory=list)
    raw_query: str = ""


@dataclass
class EventMatch:
    start_ms: int
    end_ms: int
    match_confidence: float
    match_reasons: List[str] = field(default_factory=list)
    segment_id: str = ""


class EventMatcher:
    WEIGHT_MONETARY = 0.35
    WEIGHT_ENTITY = 0.25
    WEIGHT_ACTION = 0.20
    WEIGHT_SPEAKER = 0.15

    def __init__(self, transcript: EnrichedTranscript) -> None:
        self.transcript = transcript
        graph_path = Path(__file__).resolve().parents[2] / "data" / transcript.video_id / "entity_graph.db"
        self.graph = EntityTimelineGraph(graph_path) if graph_path.is_file() else None
        self.monetary_parser = MonetaryParser()

    def match(self, query: ParsedQuery) -> List[EventMatch]:
        candidates: List[EventMatch] = []

        # Monetary mentions
        if query.monetary:
            amount = float(query.monetary.get("amount", 0))
            currency = str(query.monetary.get("currency", "INR"))
            mentions = self.transcript.monetary_mentions
            hits = self.monetary_parser.query_amount(mentions, amount, currency)
            for m in hits:
                if isinstance(m, dict):
                    from python.models.enriched import MonetaryMention

                    m = MonetaryMention(**m)
                seg = self._segment(m.segment_id)
                conf = self.WEIGHT_MONETARY
                reasons = [f"monetary_match:{m.amount_normalized} {m.currency}"]
                candidates.append(
                    EventMatch(
                        start_ms=m.start_ms,
                        end_ms=m.end_ms,
                        match_confidence=conf,
                        match_reasons=reasons,
                        segment_id=m.segment_id,
                    )
                )

        # Action types
        if query.action_types:
            for ev in self.transcript.events:
                if ev.action_type in query.action_types:
                    candidates.append(
                        EventMatch(
                            start_ms=ev.start_ms,
                            end_ms=ev.end_ms,
                            match_confidence=self.WEIGHT_ACTION,
                            match_reasons=[f"action_match:{ev.action_type}"],
                            segment_id=ev.segment_id,
                        )
                    )

        # Structured event field matching
        if query.subject or query.object or query.recipient or query.verb or query.monetary:
            for ev in self.transcript.events:
                conf = 0.0
                reasons: List[str] = []
                if query.subject and self._matches(query.subject, ev.subject):
                    conf += 0.28
                    reasons.append(f"subject_match:{query.subject}")
                if query.verb and self._matches(query.verb, ev.verb):
                    conf += 0.24
                    reasons.append(f"verb_match:{query.verb}")
                if query.object and self._matches(query.object, ev.object_):
                    conf += 0.16
                    reasons.append(f"object_match:{query.object}")
                if query.recipient and self._matches(query.recipient, ev.indirect_object or ev.object_):
                    conf += 0.22
                    reasons.append(f"recipient_match:{query.recipient}")
                if query.monetary and ev.monetary_ref and self._money_matches(query.monetary, ev.monetary_ref):
                    conf += 0.30
                    reasons.append("monetary_ref_match")
                if conf > 0:
                    candidates.append(
                        EventMatch(
                            start_ms=ev.start_ms,
                            end_ms=ev.end_ms,
                            match_confidence=min(1.0, conf),
                            match_reasons=reasons,
                            segment_id=ev.segment_id,
                        )
                    )

        # Entity windows
        for ent in query.entities:
            if self.graph:
                for start_ms, end_ms in self.graph.query_entity_windows(ent):
                    candidates.append(
                        EventMatch(
                            start_ms=start_ms,
                            end_ms=end_ms,
                            match_confidence=self.WEIGHT_ENTITY,
                            match_reasons=[f"entity_match:{ent}"],
                        )
                    )
            else:
                for e in self.transcript.entities:
                    if ent.lower() in e.text.lower() or ent.lower() in e.normalized.lower():
                        candidates.append(
                            EventMatch(
                                start_ms=e.start_ms,
                                end_ms=e.end_ms,
                                match_confidence=self.WEIGHT_ENTITY,
                                match_reasons=[f"entity_match:{ent}"],
                                segment_id=e.segment_id,
                            )
                        )

        # Speaker role filter boost
        if query.speaker_roles:
            for seg in self.transcript.segments:
                role = self.transcript.speaker_map.get(seg.speaker_id or "", seg.speaker_id or "")
                if role and any(r.lower() in str(role).lower() for r in query.speaker_roles):
                    candidates.append(
                        EventMatch(
                            start_ms=seg.start_ms,
                            end_ms=seg.end_ms,
                            match_confidence=self.WEIGHT_SPEAKER,
                            match_reasons=[f"speaker_match:{role}"],
                            segment_id=seg.segment_id,
                        )
                    )

        return self._merge_candidates(candidates)

    def _segment(self, segment_id: str):
        for s in self.transcript.segments:
            if s.segment_id == segment_id:
                return s
        return None

    def _merge_candidates(self, candidates: List[EventMatch]) -> List[EventMatch]:
        if not candidates:
            return []
        merged: dict[str, EventMatch] = {}
        for c in candidates:
            key = c.segment_id or f"{c.start_ms}-{c.end_ms}"
            if key in merged:
                m = merged[key]
                m.match_confidence = min(1.0, m.match_confidence + c.match_confidence)
                m.match_reasons.extend(c.match_reasons)
                m.start_ms = min(m.start_ms, c.start_ms)
                m.end_ms = max(m.end_ms, c.end_ms)
            else:
                merged[key] = c
        return sorted(merged.values(), key=lambda x: x.match_confidence, reverse=True)

    def _matches(self, left: str, right: str) -> bool:
        a = normalize_entity(left)
        b = normalize_entity(right)
        if not a or not b:
            return False
        if a == b or a in b or b in a:
            return True
        try:
            from rapidfuzz import fuzz

            return fuzz.partial_ratio(a, b) >= 85
        except Exception:
            return False

    def _money_matches(self, query_money: dict, value: str) -> bool:
        amount = float(query_money.get("amount", 0))
        digits = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
        return any(abs(item - amount) < 1.0 for item in digits)
