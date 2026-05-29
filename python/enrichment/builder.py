"""Build EnrichedTranscript from API-style segments."""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from python.enrichment.action_detector import ActionDetector
from python.enrichment.diarization import classify_speaker_roles
from python.enrichment.entity_graph import EntityMention, EntityRecord, EntityTimelineGraph
from python.enrichment.monetary_parser import MonetaryParser
from python.enrichment.scene_segmenter import SceneSegmenter
from python.intelligence.ner import build_entity_index, normalize_entity
from python.models.enriched import (
    EnrichedTranscript,
    ExtractedEntity,
    TranscriptSegment,
    TranscriptWord,
    persist_enriched,
)
from python.models.transcript import TranscriptDocument
from python.retrieval.chunker import Chunk
from python.transcription.pipeline import segments_to_document


def _seg_dict_to_enriched_segment(seg: Dict[str, Any]) -> TranscriptSegment:
    start_ms = int(float(seg["start"]) * 1000)
    end_ms = int(float(seg["end"]) * 1000)
    text = str(seg.get("text", ""))
    words: List[TranscriptWord] = []
    if seg.get("words"):
        for w in seg["words"]:
            words.append(
                TranscriptWord(
                    word=str(w.get("word", w.get("text", ""))).strip(),
                    start_ms=int(float(w["start"]) * 1000),
                    end_ms=int(float(w["end"]) * 1000),
                    confidence=float(w.get("confidence", 0.9)),
                    speaker_id=seg.get("speaker"),
                )
            )
    else:
        for token in text.split():
            words.append(
                TranscriptWord(
                    word=token,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    confidence=0.8,
                    speaker_id=seg.get("speaker"),
                )
            )
    speaker = seg.get("speaker")
    return TranscriptSegment(
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        words=words,
        speaker_id=speaker,
        segment_id=str(seg.get("id", uuid.uuid4())[:12]),
    )


def build_enriched_transcript(
    segments: List[Dict[str, Any]],
    video_id: str = "default",
    audio_path: Optional[str] = None,
) -> EnrichedTranscript:
    """Full enrichment pipeline from segment dicts."""
    enriched_segs = [_seg_dict_to_enriched_segment(s) for s in segments]

    # Speaker roles from fixture labels or heuristics
    for seg in enriched_segs:
        if seg.speaker_id and seg.speaker_id in ("interviewer", "vijay_mallya", "narrator"):
            pass
        elif not seg.speaker_id:
            raw = next((s for s in segments if s.get("id") == seg.segment_id), {})
            seg.speaker_id = raw.get("speaker")

    role_map = classify_speaker_roles(enriched_segs)
    for seg in enriched_segs:
        if seg.speaker_id and seg.speaker_id in role_map:
            mapped = role_map[seg.speaker_id]
            if mapped != seg.speaker_id:
                seg.speaker_id = mapped

    monetary_parser = MonetaryParser()
    action_detector = ActionDetector()
    all_monetary = []
    all_events = []
    for seg in enriched_segs:
        all_monetary.extend(monetary_parser.parse_segment(seg))
        all_events.extend(action_detector.extract_events(seg))

    # NER via existing intelligence stack
    doc = segments_to_document(segments, video_id)
    flat_chunks: List[Chunk] = []
    for seg in enriched_segs:
        flat_chunks.append(
            Chunk(
                chunk_id=seg.segment_id,
                video_id=video_id,
                text=seg.text,
                start_sec=seg.start_ms / 1000.0,
                end_sec=seg.end_ms / 1000.0,
                chunk_type="utterance",
            )
        )
    entity_index = build_entity_index(doc, flat_chunks)
    entities: List[ExtractedEntity] = []
    for m in entity_index.all_mentions:
        entities.append(
            ExtractedEntity(
                text=m.text,
                entity_type=m.entity_type,
                start_ms=int(m.start_sec * 1000),
                end_ms=int(m.end_sec * 1000),
                segment_id=m.chunk_id,
                confidence=m.confidence,
                normalized=m.normalized_form,
            )
        )

    # Entity graph persistence
    records: List[EntityRecord] = []
    by_name: Dict[str, EntityRecord] = {}
    for e in entities:
        key = e.normalized or normalize_entity(e.text)
        if key not in by_name:
            by_name[key] = EntityRecord(
                canonical_name=e.text,
                aliases=[e.text],
                entity_type=e.entity_type,
                entity_id=key,
            )
        rec = by_name[key]
        rec.mentions.append(
            EntityMention(
                entity_id=rec.entity_id,
                start_ms=e.start_ms,
                end_ms=e.end_ms,
                segment_id=e.segment_id,
                confidence=e.confidence,
            )
        )
    records = list(by_name.values())

    from pathlib import Path

    graph_path = Path(__file__).resolve().parents[2] / "data" / video_id / "entity_graph.db"
    EntityTimelineGraph(graph_path).build(records)

    # Scene segmentation (embedding optional)
    try:
        from python.embeddings.embedder import EmbeddingEngine

        embedder = EmbeddingEngine()
        import numpy as np

        embeddings = np.array([embedder.embed_passage(s.text) for s in enriched_segs])
    except Exception:
        embeddings = None

    scenes = SceneSegmenter().segment(enriched_segs, embeddings=embeddings)

    transcript = EnrichedTranscript(
        video_id=video_id,
        segments=enriched_segs,
        entities=entities,
        events=all_events,
        scenes=scenes,
        monetary_mentions=all_monetary,
        speaker_map=role_map,
    )
    persist_enriched(transcript)
    return transcript
