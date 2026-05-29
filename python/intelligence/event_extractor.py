"""
Event extraction from utterance chunks via dependency parsing and Ollama.

Builds an EventIndex mapping event types to timestamped mentions.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from python.models.transcript import TranscriptDocument
from python.retrieval.chunker import Chunk

logger = logging.getLogger(__name__)

OLLAMA_TIMEOUT_SEC = 30.0

EVENT_SCHEMA: Dict[str, List[str]] = {
    "transaction": ["give", "hand", "pay", "transfer", "receive", "present"],
    "emotional": ["laugh", "cry", "smile", "angry", "shocked", "nervous", "excited"],
    "speech_act": ["announce", "reveal", "admit", "deny", "promise", "threaten", "joke", "insult"],
    "audience_reaction": ["applause", "laughter", "booing", "cheering"],
    "physical_action": ["stand", "sit", "leave", "enter", "point", "hold", "show"],
    "interview_event": ["question", "answer", "interrupt", "pause", "cut_to"],
}

# Flat lemma -> event_type lookup
_LEMMA_TO_TYPE: Dict[str, str] = {}
for etype, lemmas in EVENT_SCHEMA.items():
    for lemma in lemmas:
        _LEMMA_TO_TYPE[lemma] = etype

_nlp = None


class EventMention(BaseModel):
    event_type: str
    subject: Optional[str] = None
    object: Optional[str] = None
    verb: str
    start_sec: float
    end_sec: float
    chunk_id: str
    confidence: float


class EventIndex(BaseModel):
    mentions_by_type: Dict[str, List[EventMention]] = Field(default_factory=dict)
    all_mentions: List[EventMention] = Field(default_factory=list)

    def lookup(self, event_type: str) -> List[EventMention]:
        return self.mentions_by_type.get(event_type, [])

    def lookup_verbs(self, verbs: List[str]) -> List[EventMention]:
        verb_set = {v.lower() for v in verbs}
        return [m for m in self.all_mentions if m.verb.lower() in verb_set]


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy

            try:
                _nlp = spacy.load("en_core_web_trf")
            except OSError:
                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    _nlp = False
        except ImportError:
            _nlp = False
    return _nlp if _nlp is not False else None


def extract_events_spacy(text: str, chunk: Chunk) -> List[EventMention]:
    nlp = _get_nlp()
    if nlp is None:
        return _regex_events(text, chunk)

    doc = nlp(text)
    events: List[EventMention] = []

    for token in doc:
        if token.pos_ != "VERB":
            continue
        lemma = token.lemma_.lower()
        event_type = _LEMMA_TO_TYPE.get(lemma)
        if not event_type:
            continue

        subject = None
        obj = None
        for child in token.children:
            if child.dep_ in ("nsubj", "nsubjpass"):
                subject = child.text
            elif child.dep_ in ("dobj", "pobj", "attr"):
                obj = child.text

        events.append(
            EventMention(
                event_type=event_type,
                subject=subject,
                object=obj,
                verb=lemma,
                start_sec=chunk.start_sec,
                end_sec=chunk.end_sec,
                chunk_id=chunk.chunk_id,
                confidence=0.75,
            )
        )

    return events


def _regex_events(text: str, chunk: Chunk) -> List[EventMention]:
    events: List[EventMention] = []
    lower = text.lower()
    for lemma, etype in _LEMMA_TO_TYPE.items():
        # Match verb forms but not "gives" when part of audience/crowd subject patterns
        if re.search(rf"\b{re.escape(lemma)}s?\b", lower):
            if lemma == "give" and re.search(r"\b(audience|crowd|people|ovation)\b.*\bgives?\b", lower):
                continue
            if lemma == "give" and re.search(r"\bgives?\b.*\b(audience|ovation|cheer)", lower):
                continue
            events.append(
                EventMention(
                    event_type=etype,
                    subject=None,
                    object=None,
                    verb=lemma,
                    start_sec=chunk.start_sec,
                    end_sec=chunk.end_sec,
                    chunk_id=chunk.chunk_id,
                    confidence=0.6,
                )
            )
    return events


async def extract_events_ollama(
    text: str,
    chunk: Chunk,
    ollama_host: str = "http://localhost:11434",
    model: str = "llama3.1:8b",
) -> List[EventMention]:
    schema_keys = list(EVENT_SCHEMA.keys())
    prompt = (
        f"Classify the events in this transcript segment. "
        f"Output JSON array of {{event_type, subject, object, confidence}}. "
        f"Possible types: {schema_keys}. "
        f"Segment: {text[:800]}"
    )

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            if resp.status_code != 200:
                return []
            raw = (resp.json().get("response") or "").strip()
            # Extract JSON array from response
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                return []
            items = json.loads(match.group())
    except Exception as e:
        logger.warning("Ollama event extraction failed: %s", e)
        return []

    events: List[EventMention] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        etype = item.get("event_type", "")
        if etype not in EVENT_SCHEMA:
            continue
        events.append(
            EventMention(
                event_type=etype,
                subject=item.get("subject"),
                object=item.get("object"),
                verb=etype,
                start_sec=chunk.start_sec,
                end_sec=chunk.end_sec,
                chunk_id=chunk.chunk_id,
                confidence=float(item.get("confidence", 0.7)),
            )
        )
    return events


async def extract_chunk_events(
    chunk: Chunk,
    use_ollama: bool = False,
    ollama_host: str = "http://localhost:11434",
) -> List[EventMention]:
    spacy_events = extract_events_spacy(chunk.text, chunk)
    if use_ollama:
        ollama_events = await extract_events_ollama(chunk.text, chunk, ollama_host)
        # Merge, prefer higher confidence
        seen_verbs = {e.verb for e in spacy_events}
        for oe in ollama_events:
            if oe.verb not in seen_verbs:
                spacy_events.append(oe)
    return spacy_events


async def build_event_index(
    chunks: List[Chunk],
    use_ollama: bool = False,
) -> EventIndex:
    all_mentions: List[EventMention] = []

    target_chunks = [c for c in chunks if c.chunk_type in ("sentence", "utterance")]
    for chunk in target_chunks:
        events = await extract_chunk_events(chunk, use_ollama=use_ollama)
        all_mentions.extend(events)
        chunk.events = list({e.verb for e in events})

    by_type: Dict[str, List[EventMention]] = defaultdict(list)
    for m in all_mentions:
        by_type[m.event_type].append(m)

    for key in by_type:
        by_type[key].sort(key=lambda x: x.start_sec)

    return EventIndex(mentions_by_type=dict(by_type), all_mentions=all_mentions)
