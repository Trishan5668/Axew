"""
EventGraph — NetworkX-backed structured event index for a video.

This is a faithful, transcript-grounded implementation of the spec's
``backend/knowledge/event_graph.py``. It is dependency-light (NetworkX only)
and works equally well when visual signals are present or absent:

- When only the transcript is available, events are derived from action
  verbs, vocatives, monetary mentions, and speaker turns.
- When perception modules are available, they attach visual / audio
  modalities to existing nodes (handover gesture confidence, emotion peaks,
  face appearance windows) by calling :meth:`EventGraph.attach_modality`.

The graph is the bridge between perception output and retrieval scoring:
:class:`python.retrieval.entity_grounded_retriever.EntityGroundedRetriever`
queries it for candidate windows that match a parsed query, and the fusion
scorer uses node confidences as multimodal evidence.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

import networkx as nx

logger = logging.getLogger(__name__)

EventType = Literal[
    "speech_act",
    "gesture",
    "object_transfer",
    "monetary_transfer",
    "emotional_peak",
    "scene_change",
    "face_appearance",
    "action_peak",
    "interruption",
    "vocative_address",
    "laughter_burst",
    "applause",
]

VALID_EVENT_TYPES = frozenset(
    [
        "speech_act",
        "gesture",
        "object_transfer",
        "monetary_transfer",
        "emotional_peak",
        "scene_change",
        "face_appearance",
        "action_peak",
        "interruption",
        "vocative_address",
        "laughter_burst",
        "applause",
    ]
)


@dataclass
class EventNode:
    """One structured event in the graph.

    Fields mirror the spec's ``EventNode`` but extend it with transcript-side
    grounding (``segment_id``, ``tense``) needed for action/role reasoning when
    visual signals are unavailable.
    """

    event_id: str
    event_type: EventType
    start_ts: float
    end_ts: float
    participants: List[str] = field(default_factory=list)
    description: str = ""
    confidence: float = 0.0
    modalities: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    # Transcript-side anchors (extension over the spec)
    segment_id: Optional[str] = None
    speaker: Optional[str] = None
    tense: Optional[Literal["past", "present", "future", "unknown"]] = None

    def overlaps(self, start: float, end: float) -> bool:
        return self.start_ts < end and self.end_ts > start

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventGraph:
    """NetworkX DiGraph of structured events plus temporal adjacency edges.

    Edges represent **temporal adjacency** (``temporal_gap`` < 5s by default).
    The graph is intentionally simple — heavier reasoning (causality,
    coreference, role binding) happens in retrieval-side scorers that consume
    this graph plus the hierarchical index.
    """

    TEMPORAL_LINK_GAP_SEC = 5.0

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()

    # -- Mutation ----------------------------------------------------------

    def add_event(self, node: EventNode) -> str:
        """Insert an event and link it to temporally adjacent neighbors."""
        if node.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Unknown event_type: {node.event_type}")

        if not node.event_id:
            node.event_id = f"evt_{uuid.uuid4().hex[:10]}"

        self.G.add_node(node.event_id, **node.to_dict())

        for existing_id, existing_data in list(self.G.nodes(data=True)):
            if existing_id == node.event_id:
                continue
            gap = min(
                abs(node.start_ts - float(existing_data.get("end_ts", 0.0))),
                abs(float(existing_data.get("start_ts", 0.0)) - node.end_ts),
            )
            if gap < self.TEMPORAL_LINK_GAP_SEC:
                # Direction: earlier -> later
                if float(existing_data.get("start_ts", 0.0)) <= node.start_ts:
                    self.G.add_edge(existing_id, node.event_id, temporal_gap=gap)
                else:
                    self.G.add_edge(node.event_id, existing_id, temporal_gap=gap)

        return node.event_id

    def add_events(self, nodes: Iterable[EventNode]) -> List[str]:
        return [self.add_event(n) for n in nodes]

    def attach_modality(
        self,
        event_id: str,
        modality: str,
        evidence: Dict[str, Any],
        confidence_boost: float = 0.0,
    ) -> None:
        """Attach visual / audio evidence to an existing transcript-derived event.

        Called by perception modules when (later) a face track, motion peak, or
        emotion spike is detected within an event's time window. The transcript
        backbone graph stays usable when perception is offline.
        """
        if event_id not in self.G:
            logger.warning("attach_modality: unknown event_id=%s", event_id)
            return
        data = self.G.nodes[event_id]
        modalities = list(data.get("modalities", []))
        if modality not in modalities:
            modalities.append(modality)
        data["modalities"] = modalities
        attrs = dict(data.get("attributes", {}))
        attrs[modality] = evidence
        data["attributes"] = attrs
        data["confidence"] = min(1.0, float(data.get("confidence", 0.0)) + confidence_boost)

    # -- Query -------------------------------------------------------------

    def query_events(
        self,
        event_type: Optional[EventType] = None,
        participant: Optional[str] = None,
        speaker: Optional[str] = None,
        min_confidence: float = 0.0,
        time_window: Optional[tuple[float, float]] = None,
        tense: Optional[str] = None,
    ) -> List[EventNode]:
        results: List[EventNode] = []
        for _, data in self.G.nodes(data=True):
            if event_type and data.get("event_type") != event_type:
                continue
            if data.get("confidence", 0.0) < min_confidence:
                continue
            if participant:
                parts = [p.lower() for p in data.get("participants", [])]
                if participant.lower() not in parts and not any(
                    participant.lower() in p for p in parts
                ):
                    continue
            if speaker and data.get("speaker") != speaker:
                continue
            if tense and data.get("tense") not in (tense, None, "unknown"):
                continue
            if time_window:
                ws, we = time_window
                if not (data.get("start_ts", 0.0) < we and data.get("end_ts", 0.0) > ws):
                    continue
            results.append(_node_from_data(data))
        return sorted(results, key=lambda n: n.start_ts)

    def get_subgraph_around_event(self, event_id: str, hops: int = 2) -> List[EventNode]:
        if event_id not in self.G:
            return []
        # Use undirected view for ego — temporal adjacency is symmetric for context
        undirected = self.G.to_undirected(as_view=True)
        nodes = nx.ego_graph(undirected, event_id, radius=hops).nodes()
        return [_node_from_data(self.G.nodes[n]) for n in nodes]

    def find_overlapping_events(
        self, start: float, end: float, event_type: Optional[EventType] = None
    ) -> List[EventNode]:
        out: List[EventNode] = []
        for _, data in self.G.nodes(data=True):
            if event_type and data.get("event_type") != event_type:
                continue
            if data.get("start_ts", 0.0) < end and data.get("end_ts", 0.0) > start:
                out.append(_node_from_data(data))
        return sorted(out, key=lambda n: n.start_ts)

    # -- Stats / persistence ----------------------------------------------

    def stats(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for _, data in self.G.nodes(data=True):
            t = data.get("event_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "num_nodes": self.G.number_of_nodes(),
            "num_edges": self.G.number_of_edges(),
            "by_type": by_type,
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": [
                {"id": nid, **{k: v for k, v in data.items()}}
                for nid, data in self.G.nodes(data=True)
            ],
            "edges": [
                {"from": u, "to": v, **attrs}
                for u, v, attrs in self.G.edges(data=True)
            ],
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "EventGraph":
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        g = cls()
        for n in payload.get("nodes", []):
            nid = n.pop("id")
            g.G.add_node(nid, **n)
        for e in payload.get("edges", []):
            g.G.add_edge(e.pop("from"), e.pop("to"), **e)
        return g


def _node_from_data(data: Dict[str, Any]) -> EventNode:
    """Reconstruct an :class:`EventNode` from raw NetworkX node attrs."""
    return EventNode(
        event_id=data.get("event_id", ""),
        event_type=data.get("event_type", "speech_act"),  # type: ignore[arg-type]
        start_ts=float(data.get("start_ts", 0.0)),
        end_ts=float(data.get("end_ts", 0.0)),
        participants=list(data.get("participants", [])),
        description=str(data.get("description", "")),
        confidence=float(data.get("confidence", 0.0)),
        modalities=list(data.get("modalities", [])),
        attributes=dict(data.get("attributes", {})),
        segment_id=data.get("segment_id"),
        speaker=data.get("speaker"),
        tense=data.get("tense"),
    )


if __name__ == "__main__":  # pragma: no cover - smoke harness
    logging.basicConfig(level=logging.INFO)
    g = EventGraph()
    g.add_event(
        EventNode(
            event_id="evt_handover",
            event_type="monetary_transfer",
            start_ts=92.5,
            end_ts=108.0,
            participants=["interviewer", "vijay_mallya"],
            description="interviewer gives 101 rupees to Vijay Mallya",
            confidence=0.85,
            modalities=["transcript"],
            segment_id="seg_009",
            speaker="interviewer",
            tense="present",
            attributes={"amount": 101, "currency": "INR"},
        )
    )
    g.add_event(
        EventNode(
            event_id="evt_reaction",
            event_type="action_peak",
            start_ts=108.0,
            end_ts=118.5,
            participants=["vijay_mallya", "audience"],
            description="Vijay accepts the notes, audience erupts",
            confidence=0.7,
            modalities=["transcript"],
            segment_id="seg_010",
            speaker="narrator",
            tense="present",
        )
    )
    print(json.dumps(g.stats(), indent=2))
    hits = g.query_events(event_type="monetary_transfer", participant="vijay_mallya")
    print(f"found {len(hits)} transfer events")
    for h in hits:
        print(" ", h.event_id, h.start_ts, h.end_ts, h.description)
    sub = g.get_subgraph_around_event("evt_handover")
    print(f"context subgraph: {[n.event_id for n in sub]}")
