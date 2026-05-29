"""
Word-level timestamp refinement for precise clip boundaries.

Refines approximate retrieval windows using transcript words, entities, and events.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel

from python.intelligence.ner import EntityIndex, normalize_entity
from python.intelligence.event_extractor import EventIndex
from python.intelligence.query_parser import ParsedQuery
from python.models.transcript import TranscriptDocument, Word
from python.retrieval.temporal_coherence import TimeWindow

logger = logging.getLogger(__name__)

LEAD_IN_SEC = 1.5
LEAD_OUT_SEC = 2.0
BUFFER_SEC = 10.0


class RefinedWindow(BaseModel):
    start_sec: float
    end_sec: float
    anchor_word: Optional[str] = None
    confidence: float = 0.0


@dataclass
class CandidateTimestamp:
    start_sec: float
    end_sec: float
    score: float
    anchor_word: Optional[str] = None


def expand_segment_words(doc: TranscriptDocument) -> None:
    """Split coarse segment-level words into per-token timestamps for refinement."""
    if not doc.words:
        return
    # Already granular if average word span < 2s
    avg_span = sum(w.end - w.start for w in doc.words) / max(len(doc.words), 1)
    if avg_span < 2.0 and len(doc.words) > len(doc.utterances) * 2:
        return

    expanded: List[Word] = []
    for utt in doc.utterances:
        text = utt.corrected_text or utt.raw_text
        tokens = re.findall(r"\S+", text)
        if not tokens:
            continue
        duration = utt.end - utt.start
        if duration <= 0:
            duration = 0.1 * len(tokens)
        step = duration / len(tokens)
        for i, tok in enumerate(tokens):
            expanded.append(
                Word(
                    text=tok,
                    start=utt.start + i * step,
                    end=utt.start + (i + 1) * step,
                    confidence=0.8,
                    speaker_id=utt.speaker_id,
                )
            )
    if expanded:
        doc.words = expanded


def get_words_in_range(words: List[Word], start: float, end: float) -> List[Word]:
    return [w for w in words if w.end > start and w.start < end]


def _word_matches_entity(word: Word, entities: List[str]) -> bool:
    wnorm = normalize_entity(word.text)
    for e in entities:
        en = normalize_entity(e)
        if en in wnorm or wnorm in en:
            return True
        # Multi-word entity: check if word is part of entity phrase in context
        if len(en.split()) > 1 and word.text.lower() in en:
            return True
    return False


def _word_matches_monetary(word: Word, amounts: List[str]) -> bool:
    combined = word.text.lower()
    for amt in amounts:
        if amt.lower() in combined:
            return True
        num = re.search(r"\d+", amt)
        if num and num.group() in combined:
            return True
    return False


def _tfidf_weight(word: Word, query_terms: List[str]) -> float:
    w = word.text.lower()
    return sum(1.0 for t in query_terms if t in w or w in t)


def _find_sentence_boundary_end(words: List[Word], from_idx: int) -> int:
    """Return index of last word in sentence (ends at .!?) after from_idx."""
    end_idx = from_idx
    for i in range(from_idx, len(words)):
        end_idx = i
        if words[i].text.rstrip().endswith((".", "!", "?")):
            break
    return end_idx


def refine_window(
    window: TimeWindow,
    transcript_doc: TranscriptDocument,
    query: str,
    parsed_query: ParsedQuery,
) -> RefinedWindow:
    expand_segment_words(transcript_doc)

    buffer_start = max(0.0, window.start_sec - BUFFER_SEC)
    buffer_end = min(transcript_doc.duration_sec, window.end_sec + BUFFER_SEC)
    buffer_words = get_words_in_range(transcript_doc.words, buffer_start, buffer_end)

    if not buffer_words:
        return RefinedWindow(
            start_sec=max(0.0, window.start_sec - LEAD_IN_SEC),
            end_sec=min(transcript_doc.duration_sec, window.end_sec + LEAD_OUT_SEC),
            confidence=0.3,
        )

    query_terms = re.findall(r"\b\w+\b", query.lower())
    query_terms = [t for t in query_terms if len(t) > 2]

    start_idx = 0
    end_idx = len(buffer_words) - 1
    anchor: Optional[str] = None
    confidence = 0.5

    if parsed_query.query_type == "entity_action":
        best_score = -1.0
        for i, w in enumerate(buffer_words):
            score = 0.0
            if parsed_query.entities and _word_matches_entity(w, parsed_query.entities):
                score += 2.0
            if parsed_query.actions:
                stem_hits = any(
                    a in w.text.lower() or f"{a.rstrip('e')}ing" in w.text.lower()
                    for a in parsed_query.actions
                )
                if stem_hits:
                    score += 1.5
            if parsed_query.monetary_amounts and _word_matches_monetary(w, parsed_query.monetary_amounts):
                score += 5.0
            if score > best_score:
                best_score = score
                start_idx = i
                anchor = w.text
                confidence = min(1.0, score / 5.0)
        end_idx = _find_sentence_boundary_end(buffer_words, start_idx)
        # Extend forward to include monetary tokens in same phrase
        if parsed_query.monetary_amounts:
            for j in range(start_idx, min(start_idx + 30, len(buffer_words))):
                if _word_matches_monetary(buffer_words[j], parsed_query.monetary_amounts):
                    end_idx = max(end_idx, j)

    elif parsed_query.query_type == "emotional":
        # Anchor at emotion keywords from query
        emo_terms = parsed_query.emotions or ["cry", "laugh", "fear", "angry", "tear"]
        best_i = start_idx
        for i, w in enumerate(buffer_words):
            if any(e in w.text.lower() for e in emo_terms):
                best_i = i
                anchor = w.text
                break
        start_idx = best_i
        end_idx = _find_sentence_boundary_end(buffer_words, start_idx)
        confidence = 0.6

    else:
        # General: highest TF-IDF weight in window
        best_w = 0.0
        for i, w in enumerate(buffer_words):
            wt = _tfidf_weight(w, query_terms)
            if wt > best_w:
                best_w = wt
                start_idx = i
                anchor = w.text
        end_idx = _find_sentence_boundary_end(buffer_words, start_idx)
        confidence = min(1.0, best_w / max(len(query_terms), 1))

    precise_start = buffer_words[start_idx].start
    precise_end = buffer_words[end_idx].end

    return RefinedWindow(
        start_sec=max(0.0, precise_start - LEAD_IN_SEC),
        end_sec=min(transcript_doc.duration_sec, precise_end + LEAD_OUT_SEC),
        anchor_word=anchor,
        confidence=confidence,
    )


def extract_entity_action_timestamp(
    entities: List[str],
    actions: List[str],
    monetary_amounts: List[str],
    entity_index: EntityIndex,
    event_index: EventIndex,
) -> List[CandidateTimestamp]:
    """
    Find entity-action intersections with optional monetary boost.
    """
    entity_mentions = []
    for ent in entities:
        entity_mentions.extend(entity_index.lookup_fuzzy(ent))

    action_events = event_index.lookup_verbs(actions)
    if not action_events and actions:
        action_events = event_index.lookup("transaction")

    candidates: List[CandidateTimestamp] = []

    for em in entity_mentions:
        for ev in action_events:
            gap = abs(em.start_sec - ev.start_sec)
            if gap >= 30.0:
                continue
            score = em.confidence * ev.confidence / (1.0 + gap)
            if monetary_amounts:
                # Check words in narrow range for amount
                mid = (em.start_sec + ev.start_sec) / 2
                for m in entity_index.all_mentions:
                    if abs(m.start_sec - mid) < 8 and any(
                        amt.lower() in m.text.lower() for amt in monetary_amounts
                    ):
                        score *= 5.0
                        break
                else:
                    if any(num in em.text for num in [re.search(r"\d+", a).group() for a in monetary_amounts if re.search(r"\d+", a)]):
                        score *= 5.0

            candidates.append(
                CandidateTimestamp(
                    start_sec=min(em.start_sec, ev.start_sec) - 2,
                    end_sec=max(em.end_sec, ev.end_sec) + 2,
                    score=score,
                    anchor_word=em.text,
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
