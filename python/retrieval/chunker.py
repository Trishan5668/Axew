"""
Hierarchical chunking engine for transcript retrieval.

Strategies:
  A — Sentence-level (leaf)
  B — Utterance-level (mid)
  C — Semantic sliding windows (reranking context)
  D — Topic-level (high)
  E — Entity-context (requires entity mentions from NER)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from python.models.transcript import TranscriptDocument, Utterance, Word
from python.transcription.corrector import get_utterance_text

logger = logging.getLogger(__name__)

MIN_SENTENCE_DURATION = 1.5
MAX_SENTENCE_DURATION = 45.0
MAX_UTTERANCE_DURATION = 120.0
TOPIC_SIMILARITY_THRESHOLD = 0.65
SLIDING_WINDOW_DURATIONS = [30.0, 60.0, 120.0]
ENTITY_CONTEXT_PADDING = 15.0
ENTITY_MERGE_GAP = 30.0

_nlp = None
_st_model = None


class Chunk(BaseModel):
    chunk_id: str
    video_id: str
    text: str
    start_sec: float
    end_sec: float
    speaker_id: Optional[str] = None
    chunk_type: str
    parent_chunk_id: Optional[str] = None
    child_chunk_ids: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    events: List[str] = Field(default_factory=list)
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy

            try:
                _nlp = spacy.load("en_core_web_trf")
            except OSError:
                logger.warning("en_core_web_trf not found, falling back to en_core_web_sm")
                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    logger.warning("spacy model not found; using regex sentence splitting")
                    _nlp = False  # sentinel: tried and unavailable
        except ImportError:
            logger.warning("spacy not installed; using regex sentence splitting")
            _nlp = False
    return _nlp if _nlp is not False else None


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer

        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model


def _new_chunk_id() -> str:
    return uuid.uuid4().hex[:12]


def _word_time_range(words: List[Word], char_start: int, char_end: int, full_text: str) -> Tuple[float, float]:
    """Map character span in utterance text to word timestamps."""
    if not words:
        return 0.0, 0.0

    char_pos = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    for w in words:
        word_start_char = full_text.find(w.text, char_pos)
        if word_start_char < 0:
            word_start_char = char_pos
        word_end_char = word_start_char + len(w.text)

        if word_end_char > char_start and start_time is None:
            start_time = w.start
        if word_start_char < char_end:
            end_time = w.end

        char_pos = word_end_char + 1

    return start_time or words[0].start, end_time or words[-1].end


def split_utterance_into_sentences(utterance: Utterance) -> List[Tuple[str, float, float]]:
    text = get_utterance_text(utterance)
    nlp = _get_nlp()

    sentences: List[Tuple[str, float, float]] = []

    if nlp is not None:
        doc = nlp(text)
        offset = 0
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            char_start = text.find(sent_text, offset)
            if char_start < 0:
                char_start = offset
            char_end = char_start + len(sent_text)
            start, end = _word_time_range(utterance.words, char_start, char_end, text)
            sentences.append((sent_text, start, end))
            offset = char_end
    else:
        # Regex fallback
        import re

        parts = re.split(r"(?<=[.!?])\s+", text)
        if not parts:
            parts = [text]
        duration = utterance.end - utterance.start
        chunk_dur = duration / max(len(parts), 1)
        for i, part in enumerate(parts):
            if part.strip():
                sentences.append(
                    (part.strip(), utterance.start + i * chunk_dur, utterance.start + (i + 1) * chunk_dur)
                )

    return _merge_short_sentences(sentences, utterance.speaker_id)


def _merge_short_sentences(
    sentences: List[Tuple[str, float, float]],
    speaker_id: Optional[str],
) -> List[Tuple[str, float, float]]:
    if not sentences:
        return []

    merged: List[Tuple[str, float, float]] = []
    buf_text, buf_start, buf_end = sentences[0]

    for sent_text, start, end in sentences[1:]:
        duration = buf_end - buf_start
        if duration < MIN_SENTENCE_DURATION:
            buf_text = f"{buf_text} {sent_text}"
            buf_end = end
        elif end - start > MAX_SENTENCE_DURATION:
            merged.append((buf_text, buf_start, buf_end))
            # Force-split long sentence at commas
            parts = _force_split_long(sent_text, start, end)
            merged.extend(parts)
            buf_text, buf_start, buf_end = "", start, end
        else:
            merged.append((buf_text, buf_start, buf_end))
            buf_text, buf_start, buf_end = sent_text, start, end

    if buf_text:
        if merged and (buf_end - buf_start) < MIN_SENTENCE_DURATION:
            prev_text, prev_start, prev_end = merged[-1]
            merged[-1] = (f"{prev_text} {buf_text}", prev_start, buf_end)
        else:
            merged.append((buf_text, buf_start, buf_end))

    return merged


def _force_split_long(text: str, start: float, end: float) -> List[Tuple[str, float, float]]:
    import re

    parts = re.split(r",\s*|\b(?:and|but|or|so)\s+", text)
    if len(parts) <= 1:
        return [(text, start, end)]

    duration = end - start
    chunk_dur = duration / len(parts)
    result = []
    for i, part in enumerate(parts):
        if part.strip():
            result.append((part.strip(), start + i * chunk_dur, start + (i + 1) * chunk_dur))
    return result


def strategy_a_sentence_chunks(
    doc: TranscriptDocument,
    utterance_chunks: Optional[Dict[str, str]] = None,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    for utt in doc.utterances:
        sentences = split_utterance_into_sentences(utt)
        for sent_text, start, end in sentences:
            chunk_id = _new_chunk_id()
            parent_id = utterance_chunks.get(f"{utt.start:.2f}") if utterance_chunks else None
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    video_id=doc.video_id,
                    text=sent_text,
                    start_sec=start,
                    end_sec=end,
                    speaker_id=utt.speaker_id,
                    chunk_type="sentence",
                    parent_chunk_id=parent_id,
                )
            )
    return chunks


def strategy_b_utterance_chunks(doc: TranscriptDocument) -> List[Chunk]:
    chunks: List[Chunk] = []
    current_texts: List[str] = []
    current_start = 0.0
    current_end = 0.0
    current_speaker: Optional[str] = None
    current_id = _new_chunk_id()

    def flush():
        nonlocal current_texts, current_start, current_end, current_speaker, current_id
        if current_texts:
            chunks.append(
                Chunk(
                    chunk_id=current_id,
                    video_id=doc.video_id,
                    text=" ".join(current_texts),
                    start_sec=current_start,
                    end_sec=current_end,
                    speaker_id=current_speaker,
                    chunk_type="utterance",
                )
            )
        current_id = _new_chunk_id()
        current_texts = []

    for utt in doc.utterances:
        text = get_utterance_text(utt)
        if current_speaker is None:
            current_speaker = utt.speaker_id
            current_start = utt.start
            current_texts = [text]
            current_end = utt.end
            continue

        same_speaker = utt.speaker_id == current_speaker
        duration = utt.end - current_start

        if same_speaker and duration <= MAX_UTTERANCE_DURATION:
            current_texts.append(text)
            current_end = utt.end
        else:
            flush()
            current_speaker = utt.speaker_id
            current_start = utt.start
            current_end = utt.end
            current_texts = [text]

    flush()
    return chunks


def strategy_c_sliding_windows(doc: TranscriptDocument) -> List[Chunk]:
    chunks: List[Chunk] = []
    duration = doc.duration_sec
    if duration <= 0:
        return chunks

    full_text_parts: List[Tuple[float, float, str]] = [
        (u.start, u.end, get_utterance_text(u)) for u in doc.utterances
    ]

    for window_size in SLIDING_WINDOW_DURATIONS:
        step = window_size * 0.5
        t = 0.0
        while t < duration:
            end = min(t + window_size, duration)
            texts = [txt for s, e, txt in full_text_parts if s < end and e > t]
            if texts:
                chunks.append(
                    Chunk(
                        chunk_id=_new_chunk_id(),
                        video_id=doc.video_id,
                        text=" ".join(texts),
                        start_sec=t,
                        end_sec=end,
                        chunk_type="sliding_window",
                        metadata={"window_size": window_size},
                    )
                )
            t += step

    return chunks


def _detect_topic_boundaries(texts: List[str]) -> List[int]:
    """Return indices where topic boundaries occur (cosine similarity valley)."""
    if len(texts) <= 1:
        return []

    model = _get_st_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    boundaries = []

    for i in range(len(embeddings) - 1):
        sim = float(np.dot(embeddings[i], embeddings[i + 1]))
        if sim < TOPIC_SIMILARITY_THRESHOLD:
            boundaries.append(i + 1)

    return boundaries


async def strategy_d_topic_chunks(
    doc: TranscriptDocument,
    utterance_chunks: List[Chunk],
    ollama_host: str = "http://localhost:11434",
    label_model: str = "llama3.2:3b",
) -> List[Chunk]:
    if not utterance_chunks:
        return []

    texts = [c.text for c in utterance_chunks]
    boundaries = _detect_topic_boundaries(texts)
    boundaries = [0] + boundaries + [len(utterance_chunks)]

    topic_chunks: List[Chunk] = []
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1]
        group = utterance_chunks[start_idx:end_idx]
        if not group:
            continue

        combined_text = " ".join(c.text for c in group)[:2000]
        label = await _label_topic(combined_text, ollama_host, label_model)

        chunk_id = _new_chunk_id()
        child_ids = [c.chunk_id for c in group]
        topic_chunks.append(
            Chunk(
                chunk_id=chunk_id,
                video_id=doc.video_id,
                text=combined_text,
                start_sec=group[0].start_sec,
                end_sec=group[-1].end_sec,
                chunk_type="topic",
                child_chunk_ids=child_ids,
                metadata={"topic_label": label},
            )
        )

        for child in group:
            child.parent_chunk_id = chunk_id

    return topic_chunks


async def _label_topic(text: str, ollama_host: str, model: str) -> str:
    import httpx

    prompt = f"Given this transcript excerpt, generate a 3-5 word topic label: {text[:500]}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            if resp.status_code == 200:
                label = (resp.json().get("response") or "").strip()
                words = label.split()[:5]
                return " ".join(words) if words else "general topic"
    except Exception as e:
        logger.warning("Topic labeling failed: %s", e)

    return "general topic"


def strategy_e_entity_context_chunks(
    doc: TranscriptDocument,
    entity_mentions: List[Dict[str, Any]],
) -> List[Chunk]:
    """
    Create entity-context chunks centered on entity mentions.
    entity_mentions: [{text, start_sec, end_sec, normalized_form}, ...]
    """
    if not entity_mentions:
        return []

    sorted_mentions = sorted(entity_mentions, key=lambda m: m["start_sec"])
    merged_windows: List[Tuple[float, float, List[str]]] = []

    for mention in sorted_mentions:
        center = (mention["start_sec"] + mention["end_sec"]) / 2
        win_start = max(0.0, center - ENTITY_CONTEXT_PADDING)
        win_end = min(doc.duration_sec, center + ENTITY_CONTEXT_PADDING)
        entity_name = mention.get("normalized_form", mention["text"])

        if merged_windows:
            prev_start, prev_end, prev_entities = merged_windows[-1]
            if win_start - prev_end < ENTITY_MERGE_GAP:
                merged_windows[-1] = (
                    prev_start,
                    max(prev_end, win_end),
                    prev_entities + [entity_name],
                )
                continue

        merged_windows.append((win_start, win_end, [entity_name]))

    chunks: List[Chunk] = []
    for win_start, win_end, entities in merged_windows:
        texts = [
            get_utterance_text(u)
            for u in doc.utterances
            if u.start < win_end and u.end > win_start
        ]
        if texts:
            chunks.append(
                Chunk(
                    chunk_id=_new_chunk_id(),
                    video_id=doc.video_id,
                    text=" ".join(texts),
                    start_sec=win_start,
                    end_sec=win_end,
                    chunk_type="entity_context",
                    entities=list(dict.fromkeys(entities)),
                )
            )

    return chunks


def link_sentence_to_utterance_parents(
    sentence_chunks: List[Chunk],
    utterance_chunks: List[Chunk],
) -> None:
    for sent in sentence_chunks:
        for utt in utterance_chunks:
            if utt.start_sec <= sent.start_sec and utt.end_sec >= sent.end_sec:
                sent.parent_chunk_id = utt.chunk_id
                if sent.chunk_id not in utt.child_chunk_ids:
                    utt.child_chunk_ids.append(sent.chunk_id)
                break


async def build_all_chunks(
    doc: TranscriptDocument,
    entity_mentions: Optional[List[Dict[str, Any]]] = None,
    skip_topic_label: bool = False,
) -> Dict[str, List[Chunk]]:
    """Run all chunking strategies and return chunks by type."""
    utterance_chunks = strategy_b_utterance_chunks(doc)
    utt_key_map = {f"{u.start:.2f}": c.chunk_id for u, c in zip(doc.utterances, utterance_chunks) if c}

    sentence_chunks = strategy_a_sentence_chunks(doc)
    link_sentence_to_utterance_parents(sentence_chunks, utterance_chunks)

    sliding_chunks = strategy_c_sliding_windows(doc)

    if skip_topic_label:
        topic_chunks: List[Chunk] = []
    else:
        topic_chunks = await strategy_d_topic_chunks(doc, utterance_chunks)

    entity_chunks = strategy_e_entity_context_chunks(doc, entity_mentions or [])

    return {
        "sentence": sentence_chunks,
        "utterance": utterance_chunks,
        "sliding_window": sliding_chunks,
        "topic": topic_chunks,
        "entity_context": entity_chunks,
    }
