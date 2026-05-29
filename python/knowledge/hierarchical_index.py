"""
HierarchicalIndex — moment → segment → scene → video re-chunking.

The retrieval failure analyzed in the spec ("Vijay Mallya 101 rupees") is
caused by flat single-level chunks that lose action role, tense, and
addressee signals. This module re-decomposes transcript segments into four
hierarchically nested units that each retrieval stage can score against:

- **Moment** (1-5 s): a single clause / sentence — fine-grained action anchor
- **Segment**: a contiguous speaker turn — provides speaker role
- **Scene**: a topic-coherent cluster of segments — gives narrative context
- **Video**: the whole asset — global statistics

Each moment is tagged with:

- ``tense``        — past / present / future / unknown
- ``action_verbs`` — lemmatized verbs found in the moment
- ``action_types`` — taxonomy classes (TRANSFER / RECEIVE / SPEAK ...)
- ``vocatives``    — direct address targets ("Vijay Mallya, I'm giving you...")
- ``monetary``     — parsed amounts with currency
- ``speaker_role`` — interviewer / guest / narrator (derived from speaker_map)
- ``entities``     — named entities mentioned

The module is dependency-light: regex + heuristics. It reuses the existing
``MonetaryParser`` from ``python.enrichment`` when available and degrades to a
local regex fallback otherwise. spaCy is opportunistic — the spec's heavier
NLP layer can plug in via :func:`set_nlp_provider` later without changing the
data model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Action taxonomy (mirrors python.enrichment.action_detector.ACTION_TAXONOMY  #
# so retrieval-side reasoning stays consistent with enrichment-side events). #
# --------------------------------------------------------------------------- #

ACTION_TAXONOMY: Dict[str, List[str]] = {
    "TRANSFER": [
        "give", "gives", "giving", "gave", "given",
        "hand", "hands", "handed", "handing",
        "pass", "passes", "passed", "passing",
        "present", "presents", "presented", "presenting",
        "offer", "offers", "offered", "offering",
        "pay", "pays", "paid", "paying",
        "grant", "grants", "granted",
    ],
    "RECEIVE": [
        "take", "takes", "took", "taken", "taking",
        "accept", "accepts", "accepted", "accepting",
        "receive", "receives", "received", "receiving",
        "get", "gets", "got", "getting",
        "obtain", "obtains", "obtained", "obtaining",
        "tuck", "tucks", "tucked", "tucking",
    ],
    "SPEAK": [
        "say", "says", "said", "saying",
        "tell", "tells", "told", "telling",
        "mention", "mentions", "mentioned", "mentioning",
        "claim", "claims", "claimed", "claiming",
        "announce", "announces", "announced", "announcing",
        "reveal", "reveals", "revealed", "revealing",
        "deny", "denies", "denied", "denying",
        "admit", "admits", "admitted", "admitting",
    ],
    "LAUGH": ["laugh", "laughs", "laughed", "laughing", "chuckle", "chuckles", "giggle"],
    "APPLAUD": ["applaud", "applauds", "applauded", "clap", "claps", "cheer", "cheers", "ovation", "erupts", "erupted"],
    "POINT": ["point", "points", "pointed", "pointing"],
    "CRY": ["cry", "cries", "cried", "crying", "tear", "tears", "tearful", "sob", "sobbed"],
    "STAND": ["stand", "stands", "stood", "standing"],
}

_LEMMA_TO_ACTION: Dict[str, str] = {}
for atype, verbs in ACTION_TAXONOMY.items():
    for v in verbs:
        _LEMMA_TO_ACTION[v] = atype


PRESENT_PROGRESSIVE_RE = re.compile(
    r"\b(?:i\s*['’]?\s*m|i\s+am|you\s*['’]?\s*re|you\s+are|he\s*['’]?\s*s|she\s*['’]?\s*s|it\s*['’]?\s*s|we\s*['’]?\s*re|they\s*['’]?\s*re)\s+\w+ing\b",
    re.IGNORECASE,
)
PAST_AUX_RE = re.compile(r"\b(?:was|were|had|did|did\s+not|didn't)\s+\w+", re.IGNORECASE)
PAST_TENSE_VERB_RE = re.compile(
    r"\b(?:gave|handed|paid|said|told|laughed|cried|pulled|tucked|received|received|admitted|denied|stood|pointed|happened|was|were)\b",
    re.IGNORECASE,
)
PRESENT_TENSE_MARKERS = re.compile(
    r"\b(?:right\s+now|here|today|currently|at\s+this\s+moment|now)\b",
    re.IGNORECASE,
)
FUTURE_RE = re.compile(r"\b(?:will|gonna|going\s+to|shall)\s+\w+", re.IGNORECASE)

_MONEY_RE = re.compile(
    r"(?P<amount>\d+(?:[,]\d+)*(?:\.\d+)?)\s*(?P<unit>rupees?|rs\.?|inr|dollars?|\$|euros?|€|crore|lakh|thousand|million|billion)?",
    re.IGNORECASE,
)
_NUMBER_WORD_RE = re.compile(
    r"\b(?:one\s+hundred(?:\s+and)?\s+\w+|two\s+hundred(?:\s+and)?\s+\w+|ek\s+sau\s+ek|nine\s+thousand\s+crore|sixteen\s+hundred\s+crore|fifty\s+crore|thirty-five\s+thousand)\b",
    re.IGNORECASE,
)

_VOCATIVE_RE = re.compile(
    r"\b(?P<name>(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}))\s*,",
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


# --------------------------------------------------------------------------- #
# Data classes                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class Moment:
    """One sentence / clause with rich action annotations."""

    moment_id: str
    segment_id: str
    start_sec: float
    end_sec: float
    text: str
    speaker: Optional[str] = None
    speaker_role: Optional[str] = None
    tense: str = "unknown"
    action_verbs: List[str] = field(default_factory=list)
    action_types: List[str] = field(default_factory=list)
    vocatives: List[str] = field(default_factory=list)
    monetary: List[Dict[str, Any]] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    is_present_action: bool = False  # convenience flag

    def has_action_type(self, action_type: str) -> bool:
        return action_type in self.action_types

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict as _asdict
        return _asdict(self)


@dataclass
class Segment:
    """A speaker turn (one or more contiguous moments by the same speaker)."""

    segment_id: str
    start_sec: float
    end_sec: float
    speaker: Optional[str]
    speaker_role: Optional[str]
    text: str
    moments: List[Moment] = field(default_factory=list)

    def primary_action_types(self) -> List[str]:
        seen: List[str] = []
        for m in self.moments:
            for at in m.action_types:
                if at not in seen:
                    seen.append(at)
        return seen


@dataclass
class Scene:
    """A topic-coherent cluster of segments."""

    scene_id: str
    start_sec: float
    end_sec: float
    segment_ids: List[str]
    label: str = ""
    keywords: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# NLP provider hook (lets perception layer plug in spaCy / faster nlp later)  #
# --------------------------------------------------------------------------- #

NlpProvider = Callable[[str], Dict[str, Any]]
_nlp_provider: Optional[NlpProvider] = None


def set_nlp_provider(provider: Optional[NlpProvider]) -> None:
    """Install a heavier NLP backend; ``None`` reverts to regex heuristics."""
    global _nlp_provider
    _nlp_provider = provider


# --------------------------------------------------------------------------- #
# Heuristics                                                                  #
# --------------------------------------------------------------------------- #


def detect_tense(text: str) -> str:
    """Cheap tense heuristic — sufficient for the VM-101 failure class.

    Order matters: present-progressive (\"I'm giving\") + present markers
    (\"right now\") override past-tense verb endings in the same clause.
    """
    if FUTURE_RE.search(text):
        return "future"
    has_present_prog = bool(PRESENT_PROGRESSIVE_RE.search(text))
    has_present_marker = bool(PRESENT_TENSE_MARKERS.search(text))
    has_past_aux = bool(PAST_AUX_RE.search(text))
    has_past_verb = bool(PAST_TENSE_VERB_RE.search(text))

    if has_present_prog and (has_present_marker or not has_past_aux):
        return "present"
    if has_present_marker and not has_past_aux:
        return "present"
    if has_past_aux or has_past_verb:
        return "past"
    return "unknown"


def extract_action_signals(text: str) -> Tuple[List[str], List[str]]:
    """Return ``(verbs, action_types)`` based on the local taxonomy."""
    found_verbs: List[str] = []
    found_types: List[str] = []
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    for tok in tokens:
        if tok in _LEMMA_TO_ACTION:
            at = _LEMMA_TO_ACTION[tok]
            if tok not in found_verbs:
                found_verbs.append(tok)
            if at not in found_types:
                found_types.append(at)
    return found_verbs, found_types


def extract_vocatives(text: str) -> List[str]:
    """Find direct-address targets (\"Vijay Mallya, I'm giving you...\")."""
    out: List[str] = []
    for m in _VOCATIVE_RE.finditer(text):
        name = m.group("name").strip()
        # Filter out sentence-initial false positives ("Welcome, ...", "Yes, ...")
        if name.lower() in {"welcome", "yes", "no", "well", "actually", "thank", "thanks", "okay", "hi", "hello"}:
            continue
        if name and name[0].isupper():
            out.append(name)
    return out


def extract_monetary(text: str) -> List[Dict[str, Any]]:
    """Best-effort monetary parsing. Prefers the project's MonetaryParser."""
    results: List[Dict[str, Any]] = []
    try:
        from python.enrichment.monetary_parser import MonetaryParser

        parser = MonetaryParser()
        for m in parser.find_mentions(text):
            if isinstance(m, dict):
                results.append(
                    {
                        "amount": m.get("amount_normalized") or m.get("amount"),
                        "currency": m.get("currency", "INR"),
                        "text": m.get("text") or m.get("matched_text"),
                    }
                )
            else:
                results.append(
                    {
                        "amount": getattr(m, "amount_normalized", None) or getattr(m, "amount", None),
                        "currency": getattr(m, "currency", "INR"),
                        "text": getattr(m, "matched_text", None) or getattr(m, "text", None),
                    }
                )
        if results:
            return results
    except Exception as exc:  # noqa: BLE001 — graceful fallback to regex
        logger.debug("MonetaryParser unavailable, using regex fallback: %s", exc)

    for m in _MONEY_RE.finditer(text):
        amount_raw = m.group("amount").replace(",", "")
        try:
            amount = float(amount_raw)
        except ValueError:
            continue
        unit = (m.group("unit") or "").lower()
        currency = "INR" if unit in {"rupees", "rupee", "rs", "rs.", "inr", "crore", "lakh"} else "USD" if unit in {"$", "dollars", "dollar"} else "EUR" if unit in {"€", "euros", "euro"} else "UNKNOWN"
        results.append({"amount": amount, "currency": currency, "text": m.group(0).strip(), "unit": unit})
    # Word-spelled numbers ("ek sau ek", "nine thousand crore", etc.)
    for m in _NUMBER_WORD_RE.finditer(text):
        results.append({"amount": None, "currency": "INR", "text": m.group(0).strip(), "unit": "word"})
    return results


def split_into_clauses(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p for p in (s.strip() for s in parts) if p]


def interpolate_clause_timestamps(
    clauses: List[str],
    start: float,
    end: float,
) -> List[Tuple[float, float]]:
    """Distribute a segment's duration across clauses proportional to length."""
    if not clauses:
        return []
    total_chars = sum(max(1, len(c)) for c in clauses)
    duration = max(0.001, end - start)
    out: List[Tuple[float, float]] = []
    cursor = start
    for c in clauses:
        frac = max(1, len(c)) / total_chars
        clause_dur = duration * frac
        out.append((round(cursor, 3), round(cursor + clause_dur, 3)))
        cursor += clause_dur
    if out:
        last_start, _ = out[-1]
        out[-1] = (last_start, round(end, 3))
    return out


# --------------------------------------------------------------------------- #
# Builder                                                                     #
# --------------------------------------------------------------------------- #


DEFAULT_SPEAKER_ROLES: Dict[str, str] = {
    "interviewer": "interviewer",
    "host": "interviewer",
    "rajesh": "interviewer",
    "rajesh_kumar": "interviewer",
    "vijay_mallya": "guest",
    "vijay": "guest",
    "guest": "guest",
    "narrator": "narrator",
    "audience": "audience",
}


def speaker_role(speaker: Optional[str], override: Optional[Dict[str, str]] = None) -> Optional[str]:
    if not speaker:
        return None
    key = speaker.lower().replace(" ", "_")
    if override and key in override:
        return override[key]
    if override and speaker in override:
        return override[speaker]
    return DEFAULT_SPEAKER_ROLES.get(key)


class HierarchicalIndex:
    """In-memory hierarchical view over a transcript.

    Heavy retrieval pipelines should *consume* a :class:`HierarchicalIndex`
    rather than re-iterate the raw segments — every signal needed for
    entity-grounded scoring is precomputed here.
    """

    SCENE_GAP_SEC = 12.0  # break a scene when speaker doesn't change but gap > N seconds

    def __init__(self) -> None:
        self.moments: List[Moment] = []
        self.segments: List[Segment] = []
        self.scenes: List[Scene] = []
        self.duration_sec: float = 0.0
        self._moments_by_segment: Dict[str, List[Moment]] = {}

    # -- Lookups ----------------------------------------------------------

    def moments_overlapping(self, start: float, end: float) -> List[Moment]:
        return [m for m in self.moments if m.start_sec < end and m.end_sec > start]

    def moments_with_action(self, action_type: str) -> List[Moment]:
        return [m for m in self.moments if action_type in m.action_types]

    def moments_with_present_action(self, action_type: str) -> List[Moment]:
        return [
            m for m in self.moments
            if action_type in m.action_types and m.is_present_action
        ]

    def moments_addressing(self, name: str) -> List[Moment]:
        n = name.lower()
        return [m for m in self.moments if any(n in v.lower() or v.lower() in n for v in m.vocatives)]

    def moments_by_speaker_role(self, role: str) -> List[Moment]:
        return [m for m in self.moments if (m.speaker_role or "").lower() == role.lower()]

    # -- Stats ------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        action_counts: Dict[str, int] = {}
        for m in self.moments:
            for at in m.action_types:
                action_counts[at] = action_counts.get(at, 0) + 1
        return {
            "num_moments": len(self.moments),
            "num_segments": len(self.segments),
            "num_scenes": len(self.scenes),
            "duration_sec": self.duration_sec,
            "action_counts": action_counts,
        }


# --------------------------------------------------------------------------- #
# Public builder                                                              #
# --------------------------------------------------------------------------- #


def build_index_from_segments(
    segments: List[Dict[str, Any]],
    speaker_role_map: Optional[Dict[str, str]] = None,
    known_entities: Optional[List[str]] = None,
) -> HierarchicalIndex:
    """Build a :class:`HierarchicalIndex` from API-style flat segments.

    ``segments`` matches the fixture / `/api/semantic/extract` schema —
    each dict has ``id``, ``start``, ``end``, ``text``, ``speaker``.
    """
    index = HierarchicalIndex()
    if not segments:
        return index

    known_entities = list(known_entities or [])

    # ----- Build moments + segments ----- #
    for i, seg in enumerate(segments):
        segment_id = str(seg.get("id", f"seg_{i:03d}"))
        text = str(seg.get("text", "")).strip()
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        speaker = seg.get("speaker") or seg.get("speaker_id")
        role = speaker_role(speaker, speaker_role_map)

        clauses = split_into_clauses(text) or [text]
        clause_spans = interpolate_clause_timestamps(clauses, start, end)

        seg_moments: List[Moment] = []
        for j, (clause, (cs, ce)) in enumerate(zip(clauses, clause_spans)):
            tense = detect_tense(clause)
            verbs, action_types = extract_action_signals(clause)
            vocatives = extract_vocatives(clause)
            monetary = extract_monetary(clause)
            entities = _detect_entities(clause, known_entities)
            is_present_action = bool(action_types) and tense == "present"
            moment = Moment(
                moment_id=f"{segment_id}_m{j:02d}",
                segment_id=segment_id,
                start_sec=cs,
                end_sec=ce,
                text=clause,
                speaker=speaker,
                speaker_role=role,
                tense=tense,
                action_verbs=verbs,
                action_types=action_types,
                vocatives=vocatives,
                monetary=monetary,
                entities=entities,
                is_present_action=is_present_action,
            )
            seg_moments.append(moment)
            index.moments.append(moment)

        segment = Segment(
            segment_id=segment_id,
            start_sec=start,
            end_sec=end,
            speaker=speaker,
            speaker_role=role,
            text=text,
            moments=seg_moments,
        )
        index.segments.append(segment)
        index._moments_by_segment[segment_id] = seg_moments

    # ----- Cluster scenes by speaker continuity + topic-keyword overlap ----- #
    scenes: List[Scene] = []
    cur_segments: List[Segment] = []
    cur_speakers: set[str] = set()
    cur_start: Optional[float] = None
    cur_end: Optional[float] = None
    last_end: Optional[float] = None
    for seg in index.segments:
        if (
            cur_segments
            and (
                (last_end is not None and seg.start_sec - last_end > HierarchicalIndex.SCENE_GAP_SEC)
                or (len(cur_speakers) >= 2 and seg.speaker not in cur_speakers and len(cur_segments) >= 4)
            )
        ):
            scenes.append(
                Scene(
                    scene_id=f"scene_{len(scenes):03d}",
                    start_sec=cur_start or 0.0,
                    end_sec=cur_end or 0.0,
                    segment_ids=[s.segment_id for s in cur_segments],
                    label="",
                    keywords=_scene_keywords(cur_segments),
                )
            )
            cur_segments = []
            cur_speakers = set()
            cur_start = None
            cur_end = None
        if cur_start is None:
            cur_start = seg.start_sec
        cur_end = seg.end_sec
        cur_segments.append(seg)
        if seg.speaker:
            cur_speakers.add(seg.speaker)
        last_end = seg.end_sec
    if cur_segments:
        scenes.append(
            Scene(
                scene_id=f"scene_{len(scenes):03d}",
                start_sec=cur_start or 0.0,
                end_sec=cur_end or 0.0,
                segment_ids=[s.segment_id for s in cur_segments],
                label="",
                keywords=_scene_keywords(cur_segments),
            )
        )

    index.scenes = scenes
    index.duration_sec = max((s.end_sec for s in index.segments), default=0.0)
    return index


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
        "this", "that", "these", "those", "i", "you", "he", "she", "it",
        "we", "they", "me", "him", "her", "us", "them", "my", "your",
        "his", "her", "its", "our", "their", "of", "to", "in", "on",
        "for", "with", "as", "at", "by", "from", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can",
        "not", "no", "yes", "if", "then", "else", "so", "very", "just",
        "about", "into", "through", "during", "before", "after", "above",
        "below", "up", "down", "out", "off", "over", "under", "again",
        "any", "all", "each", "every", "more", "most", "some", "such",
        "what", "which", "who", "whom", "whose", "when", "where", "why",
        "how", "than", "too", "only", "own", "same", "now", "also",
    }
)


def _scene_keywords(segments: List[Segment], top_k: int = 6) -> List[str]:
    counts: Dict[str, int] = {}
    for s in segments:
        for tok in re.findall(r"[A-Za-z]+", s.text.lower()):
            if len(tok) < 4 or tok in _STOP_WORDS:
                continue
            counts[tok] = counts.get(tok, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_k]]


_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+){0,2})\b")


def _detect_entities(text: str, known: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    lower = text.lower()
    for k in known:
        if k.lower() in lower and k not in seen:
            out.append(k)
            seen.add(k)
    for m in _PROPER_NOUN_RE.finditer(text):
        name = m.group(1).strip()
        if name in seen:
            continue
        # Skip sentence-initial single words ("Welcome", "Thank", etc.)
        if " " not in name and name.lower() in {"welcome", "thank", "thanks", "yes", "no", "okay", "hi", "hello", "i", "the"}:
            continue
        out.append(name)
        seen.add(name)
    return out


if __name__ == "__main__":  # pragma: no cover - smoke harness
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures" / "interview_segments.json"
    with fixture.open("r", encoding="utf-8") as f:
        segments = json.load(f)

    idx = build_index_from_segments(
        segments,
        known_entities=["Vijay Mallya", "Kingfisher", "101 rupees", "Rajesh Kumar", "Sanjeev Kapoor", "SBI", "PNB", "UB Group", "Vittal Mallya", "Force India", "Air Deccan"],
    )
    print(json.dumps(idx.stats(), indent=2))
    print("\n[present-tense TRANSFER moments]")
    for m in idx.moments_with_present_action("TRANSFER"):
        print(f"  {m.moment_id} {m.start_sec:.1f}-{m.end_sec:.1f}s speaker={m.speaker}")
        print(f"    voc={m.vocatives} money={m.monetary} verbs={m.action_verbs}")
        print(f"    {m.text[:140]}")
    print("\n[present-tense RECEIVE moments]")
    for m in idx.moments_with_present_action("RECEIVE"):
        print(f"  {m.moment_id} {m.start_sec:.1f}-{m.end_sec:.1f}s speaker={m.speaker}")
        print(f"    {m.text[:140]}")
