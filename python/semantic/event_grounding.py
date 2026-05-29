"""Structured transcript event grounding for executable retrieval."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from python.enrichment.monetary_parser import MonetaryParser
from python.intelligence.ner import normalize_entity
from python.models.enriched import EnrichedTranscript, TranscriptSegment

logger = logging.getLogger(__name__)

TRANSFER_VERBS = {
    "give",
    "gives",
    "gave",
    "hand",
    "hands",
    "handed",
    "pass",
    "passes",
    "passed",
    "pay",
    "pays",
    "paid",
    "offer",
    "offers",
    "offered",
    "present",
    "presents",
    "presented",
    "brought",
    "bring",
    "brought",
    "take",
    "takes",
    "took",
}
REACTION_VERBS = {
    "laugh",
    "laughs",
    "laughed",
    "applaud",
    "applauds",
    "applauded",
    "clap",
    "claps",
    "clapped",
    "smile",
    "smiles",
    "smiled",
}
SPEECH_VERBS = {
    "say",
    "says",
    "said",
    "tell",
    "tells",
    "told",
    "speak",
    "speaks",
    "spoke",
    "mention",
    "mentions",
    "mentioned",
    "ask",
    "asks",
    "asked",
}
PRONOUNS = {
    "i",
    "me",
    "my",
    "mine",
    "we",
    "our",
    "ours",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "they",
    "them",
    "their",
    "theirs",
}

_nlp = None


@dataclass
class SemanticEvent:
    id: str
    actor: Optional[str]
    action: str
    object: Optional[str]
    recipient: Optional[str]
    monetary_amount: Optional[str]
    transcript_text: str
    start_time: float
    end_time: float
    confidence: float
    source_chunk_id: str


class EventGrounder:
    """Convert transcript segments into structured, timestamped semantic events."""

    def __init__(self) -> None:
        self.monetary_parser = MonetaryParser()

    def ground_transcript(self, transcript: EnrichedTranscript) -> List[SemanticEvent]:
        alias_map = self._build_alias_map(transcript)
        events: List[SemanticEvent] = []

        for segment in transcript.segments:
            segment_events = self._extract_segment_events(segment, alias_map)
            if not segment_events:
                segment_events = self._fallback_segment_events(segment, alias_map)
            events.extend(segment_events)

        deduped = self._dedupe(events)
        logger.info(
            "[EventGrounder] grounded %d events across %d segments",
            len(deduped),
            len(transcript.segments),
        )
        return deduped

    def _extract_segment_events(
        self,
        segment: TranscriptSegment,
        alias_map: Dict[str, str],
    ) -> List[SemanticEvent]:
        nlp = self._get_nlp()
        if nlp is None:
            return []

        try:
            doc = nlp(segment.text)
        except Exception as exc:
            logger.debug("spaCy event grounding failed for %s: %s", segment.segment_id, exc)
            return []

        events: List[SemanticEvent] = []
        money = self._money_for_segment(segment)
        for token in doc:
            if token.pos_ not in {"VERB", "AUX"}:
                continue
            lemma = token.lemma_.lower().strip()
            if len(lemma) < 3:
                continue

            actor = None
            obj = None
            recipient = None

            for child in token.children:
                if child.dep_ in {"nsubj", "nsubjpass"}:
                    actor = self._expand_span(child)
                elif child.dep_ in {"dobj", "obj", "attr", "oprd"}:
                    obj = self._expand_span(child)
                elif child.dep_ == "iobj":
                    recipient = self._expand_span(child)
                elif child.dep_ == "prep" and child.lemma_.lower() in {"to", "for"}:
                    for grandchild in child.children:
                        if grandchild.dep_ == "pobj":
                            recipient = self._expand_span(grandchild)
                elif child.dep_ == "pobj" and child.head.lemma_.lower() in {"to", "for"}:
                    recipient = self._expand_span(child)

            actor = self._resolve_actor(actor, segment, alias_map)
            recipient = self._normalize_entity_text(recipient, alias_map)
            obj = self._normalize_object(obj, alias_map)

            if money and (obj is None or any(ch.isdigit() for ch in money)):
                obj = obj or money

            if lemma in TRANSFER_VERBS and money and recipient and obj and obj != money:
                obj = f"{money} {obj}".strip()

            start_time, end_time = self._token_time_bounds(token, segment)
            confidence = self._score_event(actor, lemma, obj, recipient, money, segment)
            if confidence < 0.35:
                continue

            events.append(
                SemanticEvent(
                    id=f"evt_{uuid.uuid4().hex[:10]}",
                    actor=actor,
                    action=lemma,
                    object=obj,
                    recipient=recipient,
                    monetary_amount=money,
                    transcript_text=segment.text,
                    start_time=start_time,
                    end_time=end_time,
                    confidence=confidence,
                    source_chunk_id=segment.segment_id,
                )
            )
        return events

    def _fallback_segment_events(
        self,
        segment: TranscriptSegment,
        alias_map: Dict[str, str],
    ) -> List[SemanticEvent]:
        text = segment.text.strip()
        lower = text.lower()
        money = self._money_for_segment(segment)
        events: List[SemanticEvent] = []

        transfer = re.search(
            r"(?:(?P<actor>[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*|interviewer|host|i|he|she|we)\s+)?"
            r"(?P<verb>give|gives|gave|hand|hands|handed|pay|pays|paid|pass|passes|passed|bring|brought|take|takes|took)\w*"
            r"(?:\s+(?P<object>.*?))?"
            r"(?:\s+(?:to|for)\s+(?P<recipient>[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*|him|her|you))?",
            text,
            re.IGNORECASE,
        )
        if transfer:
            actor = self._resolve_actor(transfer.group("actor"), segment, alias_map)
            recipient = self._normalize_entity_text(transfer.group("recipient"), alias_map)
            obj = self._normalize_object(transfer.group("object"), alias_map)
            if not recipient:
                for_hint = re.search(r"\b(?:for|to)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*|him|her|you)\b", text)
                if for_hint:
                    recipient = self._normalize_entity_text(for_hint.group(1), alias_map)
            if not obj and money:
                obj = money
            if not actor:
                actor = self._resolve_actor(None, segment, alias_map)
            events.append(
                SemanticEvent(
                    id=f"evt_{uuid.uuid4().hex[:10]}",
                    actor=actor,
                    action=transfer.group("verb").lower(),
                    object=obj or money,
                    recipient=recipient,
                    monetary_amount=money,
                    transcript_text=text,
                    start_time=segment.start_ms / 1000.0,
                    end_time=segment.end_ms / 1000.0,
                    confidence=0.76 if (money or recipient) else 0.64,
                    source_chunk_id=segment.segment_id,
                )
            )

        if money and re.search(r"\b(here(?:'s| is)|this is|take this|for you|for him|for her)\b", lower):
            events.append(
                SemanticEvent(
                    id=f"evt_{uuid.uuid4().hex[:10]}",
                    actor=self._resolve_actor(None, segment, alias_map),
                    action="give",
                    object=money,
                    recipient=self._normalize_entity_text("you", alias_map) if "for you" in lower else None,
                    monetary_amount=money,
                    transcript_text=text,
                    start_time=segment.start_ms / 1000.0,
                    end_time=segment.end_ms / 1000.0,
                    confidence=0.72,
                    source_chunk_id=segment.segment_id,
                )
            )

        for verb_set, default_conf in ((REACTION_VERBS, 0.6), (SPEECH_VERBS, 0.55), (TRANSFER_VERBS, 0.6)):
            for verb in verb_set:
                if re.search(rf"\b{re.escape(verb)}\b", lower):
                    actor = self._resolve_actor(None, segment, alias_map)
                    if events and any(e.action == verb for e in events):
                        continue
                    events.append(
                        SemanticEvent(
                            id=f"evt_{uuid.uuid4().hex[:10]}",
                            actor=actor,
                            action=verb,
                            object=money if verb in TRANSFER_VERBS else None,
                            recipient=None,
                            monetary_amount=money,
                            transcript_text=text,
                            start_time=segment.start_ms / 1000.0,
                            end_time=segment.end_ms / 1000.0,
                            confidence=default_conf + (0.08 if money else 0.0),
                            source_chunk_id=segment.segment_id,
                        )
                    )
                    break

        return events

    def _build_alias_map(self, transcript: EnrichedTranscript) -> Dict[str, str]:
        candidates: Dict[str, str] = {}

        def add_alias(raw: str, canonical: Optional[str] = None) -> None:
            value = (raw or "").strip()
            if not value:
                return
            canonical_value = (canonical or raw).strip()
            key = normalize_entity(value)
            if not key:
                return
            existing = candidates.get(key)
            if existing is None or len(canonical_value) > len(existing):
                candidates[key] = canonical_value
            parts = canonical_value.split()
            if len(parts) > 1:
                first = normalize_entity(parts[0])
                last = normalize_entity(parts[-1])
                if first and first not in candidates:
                    candidates[first] = canonical_value
                if last and last not in candidates:
                    candidates[last] = canonical_value

        for entity in transcript.entities:
            add_alias(entity.text, entity.normalized or entity.text)
            if entity.normalized:
                add_alias(entity.normalized, entity.text)
        for role in transcript.speaker_map.values():
            add_alias(str(role))
        for segment in transcript.segments:
            if segment.speaker_id:
                add_alias(str(segment.speaker_id))

        normalized_keys = list(candidates.keys())
        for key in normalized_keys:
            for other in normalized_keys:
                if key == other:
                    continue
                if key in other and key not in candidates:
                    candidates[key] = candidates[other]

        return candidates

    def _resolve_actor(
        self,
        actor: Optional[str],
        segment: TranscriptSegment,
        alias_map: Dict[str, str],
    ) -> Optional[str]:
        text = (actor or "").strip()
        if text.lower() in {"", "unknown"}:
            text = str(segment.speaker_id or "").strip()
        if text.lower() in PRONOUNS and segment.speaker_id:
            text = str(segment.speaker_id)
        return self._normalize_entity_text(text or None, alias_map)

    def _normalize_object(self, text: Optional[str], alias_map: Dict[str, str]) -> Optional[str]:
        value = (text or "").strip()
        if not value:
            return None
        if any(ch.isdigit() for ch in value):
            return re.sub(r"\s+", " ", value)
        return self._normalize_entity_text(value, alias_map) or re.sub(r"\s+", " ", value)

    def _normalize_entity_text(self, text: Optional[str], alias_map: Dict[str, str]) -> Optional[str]:
        value = (text or "").strip(" ,.")
        if not value:
            return None
        norm = normalize_entity(value)
        if norm in alias_map:
            return alias_map[norm]

        best_score = 0
        best_match: Optional[str] = None
        for alias, canonical in alias_map.items():
            score = self._fuzzy_score(norm, alias)
            if score > best_score:
                best_score = score
                best_match = canonical
        if best_match and best_score >= 86:
            return best_match
        return re.sub(r"\s+", " ", value)

    def _money_for_segment(self, segment: TranscriptSegment) -> Optional[str]:
        mentions = self.monetary_parser.parse_segment(segment)
        if not mentions:
            return None
        return mentions[0].raw_text

    def _score_event(
        self,
        actor: Optional[str],
        action: str,
        obj: Optional[str],
        recipient: Optional[str],
        money: Optional[str],
        segment: TranscriptSegment,
    ) -> float:
        score = 0.38
        if actor:
            score += 0.17
        if action in TRANSFER_VERBS | REACTION_VERBS | SPEECH_VERBS:
            score += 0.14
        if obj:
            score += 0.10
        if recipient:
            score += 0.08
        if money:
            score += 0.16
        if segment.speaker_id and actor and normalize_entity(actor) == normalize_entity(str(segment.speaker_id)):
            score += 0.08
        text_lower = (segment.text or "").lower()
        if action in TRANSFER_VERBS and any(token in text_lower for token in ("for ", "to ", "here", "this is", "take")):
            score += 0.06
        if action in TRANSFER_VERBS and not recipient:
            score += 0.05
        if action in TRANSFER_VERBS and not obj and money:
            score += 0.05
        return min(0.95, score)

    def _expand_span(self, token: Any) -> str:
        return " ".join(t.text for t in token.subtree).strip()

    def _token_time_bounds(self, token: Any, segment: TranscriptSegment) -> tuple[float, float]:
        if not segment.words:
            return segment.start_ms / 1000.0, segment.end_ms / 1000.0

        text = segment.text
        char_start = getattr(token, "idx", 0)
        char_end = char_start + len(token.text)
        cursor = 0
        start_ms = segment.start_ms
        end_ms = segment.end_ms

        for word in segment.words:
            idx = text.find(word.word, cursor)
            if idx < 0:
                cursor += len(word.word) + 1
                continue
            word_end = idx + len(word.word)
            if idx <= char_start < word_end:
                start_ms = word.start_ms
            if idx < char_end <= word_end or (char_start <= idx < char_end):
                end_ms = word.end_ms
                break
            cursor = word_end

        return start_ms / 1000.0, end_ms / 1000.0

    def _dedupe(self, events: Iterable[SemanticEvent]) -> List[SemanticEvent]:
        seen = set()
        unique: List[SemanticEvent] = []
        for event in events:
            key = (
                event.source_chunk_id,
                normalize_entity(event.actor or ""),
                event.action,
                normalize_entity(event.object or ""),
                normalize_entity(event.recipient or ""),
                re.sub(r"\s+", "", (event.monetary_amount or "").lower()),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(event)
        unique.sort(key=lambda item: (item.start_time, -item.confidence))
        return unique

    def _fuzzy_score(self, left: str, right: str) -> int:
        try:
            from rapidfuzz import fuzz

            return int(fuzz.partial_ratio(left, right))
        except Exception:
            return 100 if left == right else 0

    def _get_nlp(self):
        global _nlp
        if _nlp is None:
            try:
                import spacy

                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    _nlp = False
            except ImportError:
                _nlp = False
        return _nlp if _nlp is not False else None
