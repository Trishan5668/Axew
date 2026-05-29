"""
Unified intelligence extraction pipeline.

Runs NER, event extraction, sentiment, and keyword enrichment on chunked transcripts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from python.intelligence.event_extractor import EventIndex, build_event_index
from python.intelligence.ner import EntityIndex, EntityMention, build_entity_index
from python.intelligence.sentiment import AffectIndex, build_affect_index
from python.models.transcript import TranscriptDocument
from python.retrieval.chunker import Chunk, build_all_chunks
from python.retrieval.keyword_extractor import enrich_chunks_with_keywords
from python.transcription.pipeline import segments_to_document

logger = logging.getLogger(__name__)


@dataclass
class IntelligenceArtifacts:
    document: TranscriptDocument
    chunks: Dict[str, List[Chunk]]
    entity_index: EntityIndex
    event_index: EventIndex
    affect_index: AffectIndex

    def all_retrieval_chunks(self) -> List[Chunk]:
        """Primary + entity-context chunks for retrieval."""
        result: List[Chunk] = []
        result.extend(self.chunks.get("sentence", []))
        result.extend(self.chunks.get("entity_context", []))
        if not result:
            result.extend(self.chunks.get("utterance", []))
        return result


async def extract_intelligence(
    segments: List[Dict[str, Any]],
    video_id: str = "fixture",
    use_ollama_events: bool = False,
    skip_topic_label: bool = True,
) -> IntelligenceArtifacts:
    doc = segments_to_document(segments, video_id)

    entity_mentions_pre: List[Dict[str, Any]] = []
    # Quick pre-pass for entity-context chunking (empty first, rebuilt after NER)
    all_chunks = await build_all_chunks(doc, entity_mentions=[], skip_topic_label=skip_topic_label)

    flat_chunks = (
        all_chunks.get("sentence", [])
        + all_chunks.get("utterance", [])
    )

    entity_index = build_entity_index(doc, flat_chunks)
    event_index = await build_event_index(flat_chunks, use_ollama=use_ollama_events)
    affect_index = build_affect_index(flat_chunks)

    # Attach entities to chunks
    for chunk in flat_chunks:
        chunk_entities = [
            m.text
            for m in entity_index.all_mentions
            if m.chunk_id == chunk.chunk_id
        ]
        chunk.entities = list(dict.fromkeys(chunk_entities))

    # Rebuild entity-context chunks with real mentions
    entity_mention_dicts = [
        {
            "text": m.text,
            "start_sec": m.start_sec,
            "end_sec": m.end_sec,
            "normalized_form": m.normalized_form,
        }
        for m in entity_index.all_mentions
    ]
    from python.retrieval.chunker import strategy_e_entity_context_chunks

    entity_chunks = strategy_e_entity_context_chunks(doc, entity_mention_dicts)
    all_chunks["entity_context"] = entity_chunks

    # Enrich all chunks with keywords
    all_retrieval = flat_chunks + entity_chunks
    enrich_chunks_with_keywords(all_retrieval)

    from python.retrieval.timestamp_refiner import expand_segment_words

    expand_segment_words(doc)

    return IntelligenceArtifacts(
        document=doc,
        chunks=all_chunks,
        entity_index=entity_index,
        event_index=event_index,
        affect_index=affect_index,
    )
