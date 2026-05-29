"""Retrieval strategies routed by query type."""

from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.strategies.entity_action import EntityActionStrategy
from python.retrieval.strategies.emotional import EmotionalStrategy
from python.retrieval.strategies.audience import AudienceReactionStrategy
from python.retrieval.strategies.temporal import TemporalStrategy
from python.retrieval.strategies.hook import HookDetectionStrategy
from python.retrieval.strategies.generic import GenericStrategy

STRATEGY_MAP = {
    "entity_action": EntityActionStrategy,
    "emotional": EmotionalStrategy,
    "audience": AudienceReactionStrategy,
    "temporal": TemporalStrategy,
    "hook_detection": HookDetectionStrategy,
    "speaker_specific": GenericStrategy,
    "topical": GenericStrategy,
    "generic": GenericStrategy,
}


def get_strategy(query_type: str) -> RetrievalStrategy:
    cls = STRATEGY_MAP.get(query_type, GenericStrategy)
    return cls()
