"""Dependency-based action / event extraction."""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from python.models.enriched import ExtractedEvent, TranscriptSegment

ACTION_TAXONOMY = {
    "TRANSFER": ["give", "hand", "pass", "present", "offer", "pay", "grant"],
    "RECEIVE": ["take", "accept", "receive", "get", "obtain"],
    "SPEAK": ["say", "tell", "mention", "claim", "announce", "reveal", "deny", "admit"],
    "LAUGH": ["laugh", "chuckle", "giggle", "smile"],
    "ARGUE": ["argue", "debate", "disagree", "contest", "challenge"],
    "INTERRUPT": ["interrupt", "cut", "interject", "stop"],
    "REACT": ["react", "respond", "reply", "answer"],
    "APPLAUD": ["applaud", "clap", "cheer", "ovation"],
}

_LEMMA_TO_ACTION = {}
for atype, verbs in ACTION_TAXONOMY.items():
    for v in verbs:
        _LEMMA_TO_ACTION[v] = atype

_nlp = None


def _get_nlp():
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


class ActionDetector:
    def extract_events(self, segment: TranscriptSegment) -> List[ExtractedEvent]:
        nlp = _get_nlp()
        if nlp is None:
            return self._regex_events(segment)
        doc = nlp(segment.text)
        events: List[ExtractedEvent] = []
        for token in doc:
            if token.pos_ != "VERB":
                continue
            lemma = token.lemma_.lower()
            action_type = _LEMMA_TO_ACTION.get(lemma)
            if not action_type:
                continue
            subject, dobj, iobj = "", "", ""
            for child in token.children:
                if child.dep_ in ("nsubj", "nsubjpass"):
                    subject = self._expand_span(child)
                elif child.dep_ == "dobj":
                    dobj = self._expand_span(child)
                elif child.dep_ in ("iobj", "pobj") and child.text.lower() in ("to", "for"):
                    for gc in child.children:
                        if gc.dep_ == "pobj":
                            iobj = self._expand_span(gc)
            start_ms, end_ms = self._verb_timestamps(token, segment)
            events.append(
                ExtractedEvent(
                    subject=subject or "unknown",
                    subject_entity_id="",
                    verb=lemma,
                    action_type=action_type,
                    object_=dobj or iobj,
                    object_entity_id="",
                    indirect_object=iobj,
                    raw_text=segment.text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    segment_id=segment.segment_id,
                    confidence=0.8,
                )
            )
        return events

    def _expand_span(self, token) -> str:
        return " ".join(t.text for t in token.subtree)

    def _verb_timestamps(self, token, segment: TranscriptSegment) -> tuple[int, int]:
        if not segment.words:
            return segment.start_ms, segment.end_ms
        vstart = token.idx
        vend = token.idx + len(token.text)
        text = segment.text
        cum = 0
        for w in segment.words:
            idx = text.find(w.word, cum)
            if idx < 0:
                continue
            if idx <= vstart < idx + len(w.word):
                return w.start_ms, w.end_ms
            cum = idx + len(w.word)
        return segment.start_ms, segment.end_ms

    def _regex_events(self, segment: TranscriptSegment) -> List[ExtractedEvent]:
        events: List[ExtractedEvent] = []
        lower = segment.text.lower()
        for action_type, verbs in ACTION_TAXONOMY.items():
            for v in verbs:
                if re.search(rf"\b{re.escape(v)}", lower):
                    events.append(
                        ExtractedEvent(
                            subject="unknown",
                            subject_entity_id="",
                            verb=v,
                            action_type=action_type,
                            object_="",
                            object_entity_id="",
                            indirect_object="",
                            raw_text=segment.text,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                            segment_id=segment.segment_id,
                            confidence=0.55,
                        )
                    )
                    break
        return events
