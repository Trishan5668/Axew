"""
Knowledge layer — structured semantic representation of a video.

Contains the hierarchical index (moment → segment → scene → video) and the
NetworkX-backed event graph that the retrieval engine queries.

This package is dependency-light: NetworkX is the only required external dep.
Visual/audio signals are *optional* — every node can be constructed from
transcript alone, and visual evidence (face tracks, motion peaks, emotion
peaks) attaches as node attributes when available.
"""

from python.knowledge.event_graph import EventGraph, EventNode, EventType
from python.knowledge.hierarchical_index import (
    HierarchicalIndex,
    Moment,
    Scene,
    Segment,
    build_index_from_segments,
)

__all__ = [
    "EventGraph",
    "EventNode",
    "EventType",
    "HierarchicalIndex",
    "Moment",
    "Scene",
    "Segment",
    "build_index_from_segments",
]
