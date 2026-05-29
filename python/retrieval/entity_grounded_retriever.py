"""
Entity-grounded retriever.

Solves the five root-cause failure modes from the spec:

    1. Transcript-only reasoning  -> consumes (optional) face/event signals.
    2. Prefix-biased retrieval    -> hierarchical moment scoring, not flat chunks.
    3. No entity grounding        -> IdentityRegistry + speaker_face mapping.
    4. No event schema            -> action_type taxonomy + EventGraph.
    5. Flat single-level embeddings -> moment / segment / scene / video tiers.

The retriever decomposes the natural-language query into a strict
:class:`GroundedQuery` (action type, speaker role, recipient, monetary
constraint, tense), scores every moment against the available evidence
channels via :class:`MultimodalFusionScorer`, applies the confidence gate,
and finally frame-precisely refines the winner's timestamps.

This module purposely operates with **zero LLM calls** so it can run inside
unit tests, benchmarks, and on machines without Ollama. The
:class:`SemanticRetrievalPipeline` in ``python.semantic.retrieval_pipeline``
remains the LLM-augmented path; this is the fast, deterministic baseline
that we plug into Phase 16 of the benchmark.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from python.knowledge.event_graph import EventGraph, EventNode
from python.knowledge.hierarchical_index import (
    ACTION_TAXONOMY,
    HierarchicalIndex,
    Moment,
    extract_action_signals,
    extract_monetary,
    extract_vocatives,
    detect_tense,
)
from python.perception.face_identity import IdentityRegistry
from python.perception.speaker_face_correlator import SpeakerFaceMapping
from python.retrieval.frame_precise_refiner import FramePreciseWindow, refine_window
from python.retrieval.multimodal_fusion_scorer import (
    EvidenceBundle,
    FusionResult,
    MultimodalFusionScorer,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Query model                                                                 #
# --------------------------------------------------------------------------- #


# Surface action verbs that strongly imply a particular taxonomy type AND a
# specific speaker role for the *subject* of the action.
_ACTION_LEXICON: Dict[str, List[str]] = {
    "TRANSFER": [
        "give", "gives", "giving", "gave", "given",
        "hand", "hands", "handed", "handing",
        "pass", "passes", "passed", "passing",
        "pay", "pays", "paid", "paying",
        "present", "presents", "presented", "presenting",
        "offer", "offers", "offered", "offering",
    ],
    "RECEIVE": [
        "take", "takes", "accept", "accepts", "accepting",
        "receive", "receives", "receiving",
    ],
    "LAUGH": ["laugh", "laughs", "laughing"],
    "CRY": ["cry", "cries", "crying", "tear", "tears", "tearful"],
    "APPLAUD": ["applaud", "applauding", "cheer", "cheers", "cheering", "clap", "claps", "clapping", "erupts", "erupting", "ovation"],
    "POINT": ["point", "points", "pointing"],
    "STAND": ["stand", "stands", "standing", "stood"],
    "SPEAK": [
        "say", "says", "saying", "tell", "tells", "telling",
        "mention", "mentions", "mentioning", "ask", "asks", "asking",
        "describe", "describes", "describing", "talk", "talks", "talking",
        "deny", "denies", "denying", "admit", "admits", "admitting",
        "discuss", "discusses", "discussing",
    ],
}

_ROLE_LEXICON: Dict[str, str] = {
    "interviewer": "interviewer",
    "host": "interviewer",
    "anchor": "interviewer",
    "presenter": "interviewer",
    "guest": "guest",
    "interviewee": "guest",
    "businessman": "guest",
    "narrator": "narrator",
    "audience": "audience",
    "crowd": "audience",
}


@dataclass
class GroundedQuery:
    """Strict structured intent extracted from a natural-language query."""

    raw_query: str
    action_type: Optional[str] = None
    action_verbs: List[str] = field(default_factory=list)
    subject_role: Optional[str] = None       # "interviewer" / "guest" / ...
    object_entity: Optional[str] = None      # recipient name
    monetary_amount: Optional[float] = None
    monetary_text: Optional[str] = None
    monetary_currency: Optional[str] = None
    target_tense: Optional[str] = None       # "present" | "past" | "future"
    named_entities: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    requires_strict_grounding: bool = False

    def required_channels(self) -> List[str]:
        ch: List[str] = []
        if self.named_entities:
            ch.append("entity_match")
        if self.action_type or self.action_verbs:
            ch.append("action_match")
        if self.subject_role:
            ch.append("speaker_role_match")
        if self.monetary_amount is not None or self.monetary_text:
            ch.append("monetary_match")
        if self.object_entity:
            ch.append("vocative_match")
        return ch

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


# --------------------------------------------------------------------------- #
# Query parser (deterministic, regex-driven)                                  #
# --------------------------------------------------------------------------- #


_KEEP_VERBS_RE = re.compile(
    r"^\s*(?:keep|extract|find|show|isolate|highlight|grab|cut|return|surface)\s+(?:only\s+)?(?:the\s+)?(?:part|moment|clip|segment|scene|exchange|line|portion|sequence|conversation)\s+",
    re.IGNORECASE,
)
_WHERE_CLAUSE_RE = re.compile(r"\bwhere\s+(.*)$", re.IGNORECASE)


def _trim_query(query: str) -> str:
    """Strip leading editorial verbs (\"Keep only the part where\", etc.)."""
    q = _KEEP_VERBS_RE.sub("", query).strip()
    m = _WHERE_CLAUSE_RE.search(q)
    if m:
        return m.group(1).strip()
    return q


def _detect_role_in(query: str) -> Optional[str]:
    q = query.lower()
    for term, role in _ROLE_LEXICON.items():
        if re.search(rf"\b{re.escape(term)}\b", q):
            return role
    return None


def _detect_action(query: str) -> tuple[Optional[str], List[str]]:
    q = query.lower()
    tokens = re.findall(r"[a-z']+", q)
    action_type: Optional[str] = None
    matched_verbs: List[str] = []
    for atype, verbs in _ACTION_LEXICON.items():
        for v in verbs:
            if v in tokens:
                matched_verbs.append(v)
                if action_type is None:
                    action_type = atype
    return action_type, matched_verbs


_QUERY_NOISE_TOKENS = {
    "keep", "extract", "find", "show", "isolate", "highlight", "grab", "cut",
    "when", "where", "what", "which", "who", "whom", "whose", "why", "how",
    "during", "around", "before", "after", "the", "in", "on",
}


def _detect_named_entities(query: str) -> List[str]:
    """Proper-noun chunks (1-3 capitalized words) with sentence-initial filters.

    Drops leading wh-words / editorial verbs that capitalize at the start of
    a sentence (e.g. "When Vijay Mallya..." -> "Vijay Mallya").
    """
    out: List[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", query):
        raw = m.group(0).strip()
        tokens = raw.split()
        # Strip leading noise tokens like "When", "Where", "Keep".
        while tokens and tokens[0].lower() in _QUERY_NOISE_TOKENS:
            tokens.pop(0)
        if not tokens:
            continue
        name = " ".join(tokens).strip()
        if not name or name.lower() in _QUERY_NOISE_TOKENS:
            continue
        if name in seen:
            continue
        out.append(name)
        seen.add(name)
    return out


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "where", "when", "what", "which", "who", "whom", "by", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "i", "you",
    "he", "she", "it", "we", "they", "him", "her", "us", "them", "his", "her",
    "their", "our", "my", "your", "only", "part", "moment", "clip", "segment",
    "keep", "extract", "find", "show", "isolate", "highlight",
}


def _keywords(query: str) -> List[str]:
    return [
        w.lower()
        for w in re.findall(r"[A-Za-z]+", query)
        if len(w) >= 3 and w.lower() not in _STOPWORDS
    ]


def parse_query(query: str) -> GroundedQuery:
    """Deterministic query decomposition — no LLM, fully testable.

    Designed to capture the structure the spec failure analysis demands:
    subject role, action type, recipient, monetary amount, tense.
    """
    trimmed = _trim_query(query)
    role = _detect_role_in(trimmed)
    action_type, action_verbs = _detect_action(trimmed)
    entities = _detect_named_entities(trimmed)
    keywords = _keywords(trimmed)
    monetary = extract_monetary(trimmed)
    monetary_amount = None
    monetary_text = None
    monetary_currency = None
    if monetary:
        monetary_amount = monetary[0].get("amount")
        monetary_text = monetary[0].get("text")
        monetary_currency = monetary[0].get("currency")

    # Recipient: explicit "to X" / "at X" preposition is the strongest signal.
    # For intransitive actions (LAUGH, CRY, STAND, APPLAUD, POINT) there is
    # *no* recipient — the named entity is the subject. Wrongly binding it as
    # an object forces a vocative_match=0 against every truthful candidate.
    object_entity: Optional[str] = None
    to_match = re.search(
        r"\b(?:to|at|toward|towards|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
        trimmed,
    )
    transitive_actions = {"TRANSFER", "RECEIVE", "SPEAK"}
    if to_match:
        object_entity = to_match.group(1).strip()
    elif entities and action_type in transitive_actions:
        # Heuristic: in transitive editorial queries without an explicit "to",
        # the *last* mentioned entity is the most likely recipient
        # ("the interviewer gives 101 rupees Vijay Mallya" -> recipient).
        object_entity = entities[-1]

    target_tense = detect_tense(trimmed)
    if target_tense == "unknown" and action_type in {"TRANSFER", "RECEIVE", "POINT", "STAND", "APPLAUD", "LAUGH"}:
        # Editing prompts default to present (the moment the action *happens*).
        target_tense = "present"

    return GroundedQuery(
        raw_query=query,
        action_type=action_type,
        action_verbs=action_verbs,
        subject_role=role,
        object_entity=object_entity,
        monetary_amount=monetary_amount,
        monetary_text=monetary_text,
        monetary_currency=monetary_currency,
        target_tense=target_tense,
        named_entities=entities,
        keywords=keywords,
        requires_strict_grounding=bool(role and action_type),
    )


# --------------------------------------------------------------------------- #
# Scoring helpers                                                             #
# --------------------------------------------------------------------------- #


def _name_overlap(name: str, candidates: List[str]) -> float:
    if not candidates:
        return 0.0
    n = name.lower().strip()
    best = 0.0
    for c in candidates:
        cl = c.lower()
        if n == cl:
            return 1.0
        if n in cl or cl in n:
            best = max(best, 0.8)
            continue
        # Surname-only / first-name-only matches
        tokens = set(n.split()) & set(cl.split())
        if tokens:
            best = max(best, 0.6)
    try:
        from rapidfuzz import fuzz

        for c in candidates:
            ratio = fuzz.partial_ratio(n, c.lower())
            if ratio >= 90:
                best = max(best, 0.95)
            elif ratio >= 80:
                best = max(best, 0.75)
            elif ratio >= 70:
                best = max(best, 0.55)
    except Exception:
        pass
    return best


def _monetary_match(query: GroundedQuery, moment: Moment) -> float:
    if query.monetary_amount is None and not query.monetary_text:
        return 0.0
    if not moment.monetary:
        return 0.0
    qa = query.monetary_amount
    for m in moment.monetary:
        amt = m.get("amount")
        if qa is not None and amt is not None:
            try:
                if abs(float(amt) - float(qa)) < 0.5:
                    return 1.0
            except (TypeError, ValueError):
                pass
        if query.monetary_text and m.get("text") and query.monetary_text.lower() in m["text"].lower():
            return 0.9
    return 0.3  # partial: some money was mentioned but didn't match exactly


def _action_match(query: GroundedQuery, moment: Moment) -> float:
    if not query.action_type and not query.action_verbs:
        return 0.0
    score = 0.0
    if query.action_type and query.action_type in moment.action_types:
        score = 0.8
    if query.action_verbs:
        for v in query.action_verbs:
            stem = v.rstrip("e")
            for mv in moment.action_verbs:
                if mv == v or mv.startswith(stem):
                    score = max(score, 1.0)
                    break
    return score


def _tense_match(query: GroundedQuery, moment: Moment) -> float:
    if not query.target_tense:
        return 0.0
    if moment.tense == query.target_tense:
        return 1.0
    if moment.tense == "unknown":
        return 0.4
    return 0.0


def _speaker_role_match(query: GroundedQuery, moment: Moment) -> float:
    if not query.subject_role:
        return 0.0
    role = (moment.speaker_role or "").lower()
    if not role:
        return 0.3
    if role == query.subject_role.lower():
        return 1.0
    return 0.0


def _vocative_match(query: GroundedQuery, moment: Moment) -> float:
    if not query.object_entity:
        return 0.0
    return _name_overlap(query.object_entity, moment.vocatives)


def _entity_match(
    query: GroundedQuery,
    moment: Moment,
    identity_registry: Optional[IdentityRegistry] = None,
    speaker_face_map: Optional[Dict[str, SpeakerFaceMapping]] = None,
) -> float:
    """Entity match across three evidence layers.

    1. **Text mention** of the entity in the moment's clause (strongest).
    2. **Speaker-binding**: the moment's speaker resolves (via the identity
       registry or speaker→face map) to the queried entity. This is what lets
       us answer "When Vijay Mallya laughs..." without his name appearing in
       his own utterance.
    3. **Fuzzy overlap** against the moment's entity / vocative lists.
    """
    if not query.named_entities:
        return 0.0
    scores: List[float] = []
    text_lower = (moment.text or "").lower()
    for ent in query.named_entities:
        if ent.lower() in text_lower:
            scores.append(1.0)
            continue
        if moment.speaker and identity_registry is not None:
            track = identity_registry.resolve(moment.speaker)
            if track and (
                ent.lower() == track.display_name.lower()
                or ent.lower() == track.identity_id.lower()
                or any(ent.lower() == a.lower() for a in track.aliases)
                or _name_overlap(ent, [track.display_name] + track.aliases) >= 0.8
            ):
                scores.append(0.92)
                continue
        if moment.speaker and speaker_face_map is not None:
            mapping = speaker_face_map.get(moment.speaker)
            if mapping and mapping.display_name and _name_overlap(ent, [mapping.display_name]) >= 0.8:
                scores.append(0.9)
                continue
        scores.append(_name_overlap(ent, moment.entities + moment.vocatives))
    if not scores:
        return 0.0
    return max(scores)


def _lexical_match(query: GroundedQuery, moment: Moment) -> float:
    if not query.keywords:
        return 0.0
    text = (moment.text or "").lower()
    hits = sum(1 for kw in query.keywords if kw in text)
    if not query.keywords:
        return 0.0
    return min(1.0, hits / max(1, len(query.keywords)))


def _event_graph_match(query: GroundedQuery, moment: Moment, graph: Optional[EventGraph]) -> Optional[float]:
    if graph is None or graph.G.number_of_nodes() == 0:
        return None
    et = None
    if query.action_type == "TRANSFER" or query.monetary_amount is not None:
        et = "monetary_transfer"
    overlaps = graph.find_overlapping_events(moment.start_sec, moment.end_sec, event_type=et)  # type: ignore[arg-type]
    if not overlaps:
        return 0.0
    return max(min(1.0, e.confidence + 0.1) for e in overlaps)


# --------------------------------------------------------------------------- #
# Retriever                                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class GroundedCandidate:
    moment: Moment
    evidence: EvidenceBundle
    fusion: FusionResult
    window: Optional[FramePreciseWindow] = None

    @property
    def score(self) -> float:
        return self.fusion.score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "moment_id": self.moment.moment_id,
            "segment_id": self.moment.segment_id,
            "speaker": self.moment.speaker,
            "speaker_role": self.moment.speaker_role,
            "tense": self.moment.tense,
            "start_sec": self.moment.start_sec,
            "end_sec": self.moment.end_sec,
            "text": self.moment.text,
            "evidence": self.evidence.as_map(),
            "fusion": self.fusion.to_dict(),
            "window": self.window.to_dict() if self.window else None,
        }


@dataclass
class GroundedRetrievalResult:
    query: GroundedQuery
    winner: Optional[GroundedCandidate]
    candidates: List[GroundedCandidate]
    debug: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed_gate(self) -> bool:
        return bool(self.winner and self.winner.fusion.passes_gate)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "winner": self.winner.to_dict() if self.winner else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "debug": self.debug,
        }


class EntityGroundedRetriever:
    """Deterministic entity / action / tense-aware retriever over a video.

    Parameters
    ----------
    index:
        The hierarchical index built from this video's transcript.
    identity_registry:
        Optional face/identity registry; passed through to vocative resolution.
    speaker_face_map:
        Optional speaker→identity mapping; if absent, the moment's speaker is
        used directly.
    event_graph:
        Optional event graph; contributes to the ``event_graph`` channel.
    fusion_scorer:
        Custom scorer. When omitted, a fresh one is constructed per query
        with ``required_channels`` derived from the parsed query.
    """

    def __init__(
        self,
        index: HierarchicalIndex,
        identity_registry: Optional[IdentityRegistry] = None,
        speaker_face_map: Optional[Dict[str, SpeakerFaceMapping]] = None,
        event_graph: Optional[EventGraph] = None,
        top_k: int = 8,
    ) -> None:
        self.index = index
        self.identity_registry = identity_registry
        self.speaker_face_map = speaker_face_map or {}
        self.event_graph = event_graph
        self.top_k = top_k

    # ----- Public API ----------------------------------------------------

    def retrieve(self, query: str) -> GroundedRetrievalResult:
        gq = parse_query(query)
        candidates = self._score_all_moments(gq)
        scorer = MultimodalFusionScorer(required_channels=gq.required_channels())
        scored: List[GroundedCandidate] = []
        for m, ev in candidates:
            res = scorer.score(ev)
            scored.append(GroundedCandidate(moment=m, evidence=ev, fusion=res))
        scored.sort(key=lambda c: c.score, reverse=True)

        # Cap to top_k for downstream debug, but always pick the best
        # *gate-passing* candidate as the winner (falls back to top if none).
        winner: Optional[GroundedCandidate] = next(
            (c for c in scored if c.fusion.passes_gate), None
        )
        if winner is None and scored:
            winner = scored[0]

        if winner is not None:
            winner.window = refine_window(
                self.index,
                winner.moment,
                action_verbs=gq.action_verbs or winner.moment.action_verbs,
                vocatives=([gq.object_entity] if gq.object_entity else []) or winner.moment.vocatives,
                monetary_phrases=[gq.monetary_text] if gq.monetary_text else [],
                confidence=winner.score,
            )

        debug = {
            "num_moments": len(self.index.moments),
            "num_candidates_scored": len(scored),
            "num_gate_passers": sum(1 for c in scored if c.fusion.passes_gate),
            "required_channels": gq.required_channels(),
            "event_graph_size": self.event_graph.G.number_of_nodes() if self.event_graph else 0,
            "speaker_face_map_size": len(self.speaker_face_map),
        }
        return GroundedRetrievalResult(
            query=gq,
            winner=winner,
            candidates=scored[: self.top_k],
            debug=debug,
        )

    # ----- Scoring per moment -------------------------------------------

    def _score_all_moments(self, gq: GroundedQuery) -> List[tuple[Moment, EvidenceBundle]]:
        out: List[tuple[Moment, EvidenceBundle]] = []
        for moment in self.index.moments:
            ev = self._evidence_for(moment, gq)
            # Skip moments with literally no signal — speeds up scoring + cleans
            # up the candidate list. We still keep zero-lexical moments if any
            # structural channel has signal (e.g. entity-only mentions).
            if all(v in (None, 0.0) for v in ev.as_map().values()):
                continue
            out.append((moment, ev))
        return out

    def _evidence_for(self, moment: Moment, gq: GroundedQuery) -> EvidenceBundle:
        ev = EvidenceBundle()
        ev.lexical = _lexical_match(gq, moment) if gq.keywords else None
        ev.entity_match = (
            _entity_match(gq, moment, self.identity_registry, self.speaker_face_map)
            if gq.named_entities
            else None
        )
        ev.action_match = _action_match(gq, moment) if (gq.action_type or gq.action_verbs) else None
        ev.tense_match = _tense_match(gq, moment) if gq.target_tense else None
        ev.speaker_role_match = _speaker_role_match(gq, moment) if gq.subject_role else None
        ev.vocative_match = _vocative_match(gq, moment) if gq.object_entity else None
        ev.monetary_match = _monetary_match(gq, moment) if (gq.monetary_amount is not None or gq.monetary_text) else None

        # Event-graph signal (always applicable if we have one)
        eg = _event_graph_match(gq, moment, self.event_graph)
        if eg is not None:
            ev.event_graph = eg

        return ev


if __name__ == "__main__":  # pragma: no cover - smoke harness
    import json
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures" / "interview_segments.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        segments = json.load(f)

    from python.knowledge.hierarchical_index import build_index_from_segments
    from python.perception.face_identity import IdentityRegistry
    from python.perception.speaker_face_correlator import correlate_speakers_to_faces

    idx = build_index_from_segments(
        segments,
        known_entities=[
            "Vijay Mallya", "101 rupees", "Kingfisher", "Kingfisher Airlines",
            "SBI", "PNB", "Sanjeev Kapoor", "Vittal Mallya", "UB Group",
            "Force India", "Air Deccan", "Rajesh Kumar",
        ],
    )
    reg = IdentityRegistry(project_id="fixture", root=Path("./.axew_test_cache/fixture"))
    reg.register_from_transcript(
        identity_id="vijay_mallya",
        display_name="Vijay Mallya",
        aliases=["Vijay", "Mallya", "the businessman"],
        appearances=[{"start": s["start"], "end": s["end"]} for s in segments if s["speaker"] == "vijay_mallya"],
    )
    reg.register_from_transcript(
        identity_id="rajesh_kumar",
        display_name="Rajesh Kumar",
        aliases=["Rajesh", "interviewer", "host"],
        appearances=[{"start": s["start"], "end": s["end"]} for s in segments if s["speaker"] == "interviewer"],
    )
    mapping = correlate_speakers_to_faces(segments, reg)
    retriever = EntityGroundedRetriever(idx, identity_registry=reg, speaker_face_map=mapping)
    queries = [
        "Keep only the part where the interviewer gives 101 rupees to Vijay Mallya",
        "When the interviewer hands over money to Vijay Mallya on live TV",
        "When Vijay Mallya laughs about the launch party",
        "Closing segment where he says every empire starts with 101 rupees",
    ]
    for q in queries:
        result = retriever.retrieve(q)
        w = result.winner
        print(f"\nQ: {q}")
        print(f"  query: action={result.query.action_type} role={result.query.subject_role} obj={result.query.object_entity} money={result.query.monetary_amount} tense={result.query.target_tense}")
        if w:
            print(f"  winner: {w.moment.moment_id} {w.moment.start_sec:.1f}-{w.moment.end_sec:.1f} speaker={w.moment.speaker} score={w.score:.3f} pass={w.fusion.passes_gate}")
            if w.window:
                print(f"  window: {w.window.start_sec:.1f} -> {w.window.end_sec:.1f} ({w.window.anchor_kind})")
            print(f"  text: {w.moment.text[:100]}")
        else:
            print("  winner: NONE")
        print(f"  debug: {result.debug}")
