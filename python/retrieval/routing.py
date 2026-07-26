"""Strategy routing decisions from structured query evidence."""

from __future__ import annotations

from dataclasses import dataclass, field

from python.intelligence.event_extractor import EventIndex
from python.retrieval.types import DecomposedQuery


LOW_CONFIDENCE_INVOKE_THRESHOLD = 0.60


@dataclass
class StrategyRoutingDecision:
    strategy: str
    invoked: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "invoked": self.invoked,
            "reasons": self.reasons,
        }


def should_invoke_action_strategy(
    query: str,
    decomposed: DecomposedQuery,
) -> StrategyRoutingDecision:
    """Prefer recall: invoke action strategy unless evidence is strongly non-action."""
    reasons: list[str] = []
    event_types = set(decomposed.event_types)
    intent_signals = set(decomposed.intent_signals)

    if event_types & EventIndex.action_event_types():
        reasons.append("event_index_action_semantic_class")
    if intent_signals & {"action", "motion", "verb_event"}:
        reasons.append("decomposer_action_intent_signal")
    if decomposed.routing_confidence < LOW_CONFIDENCE_INVOKE_THRESHOLD:
        reasons.append("low_confidence_decomposition_bias")

    return StrategyRoutingDecision("action", bool(reasons), reasons)


def should_invoke_emotion_strategy(
    query: str,
    decomposed: DecomposedQuery,
) -> StrategyRoutingDecision:
    """Prefer recall: invoke emotion strategy unless evidence is strongly non-affective."""
    reasons: list[str] = []
    event_types = set(decomposed.event_types)
    intent_signals = set(decomposed.intent_signals)

    if event_types & EventIndex.affect_event_types():
        reasons.append("event_index_affect_semantic_class")
    if decomposed.affect_signals:
        reasons.append("decomposer_affect_signal")
    if intent_signals & {"emotion", "affect"}:
        reasons.append("decomposer_emotion_intent_signal")
    if "clip_moment" in intent_signals and not event_types and not decomposed.affect_signals:
        reasons.append("ambiguous_clip_moment_without_event_or_affect_class")
    if decomposed.routing_confidence < LOW_CONFIDENCE_INVOKE_THRESHOLD:
        reasons.append("low_confidence_decomposition_bias")

    return StrategyRoutingDecision("emotion", bool(reasons), reasons)


def strategy_routing_decisions(
    query: str,
    decomposed: DecomposedQuery,
) -> dict[str, StrategyRoutingDecision]:
    return {
        "action": should_invoke_action_strategy(query, decomposed),
        "emotion": should_invoke_emotion_strategy(query, decomposed),
    }
