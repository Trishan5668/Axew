"""
Named entity extraction with spaCy, GLiNER, and coreference resolution.

Builds an EntityIndex mapping normalized entity names to timestamped mentions.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from python.models.transcript import TranscriptDocument, Utterance
from python.retrieval.chunker import Chunk
from python.transcription.corrector import get_utterance_text

logger = logging.getLogger(__name__)

SPACY_LABEL_MAP = {
    "PERSON": "person_name",
    "ORG": "organization",
    "GPE": "location",
    "MONEY": "monetary_amount",
    "DATE": "date",
    "TIME": "time",
    "PRODUCT": "product",
    "EVENT": "event",
}

GLINER_LABELS = [
    "person_name",
    "organization",
    "monetary_amount",
    "physical_object",
    "action",
    "emotion",
    "location",
]

_nlp = None
_gliner = None
_coref_available = False


class EntityMention(BaseModel):
    text: str
    entity_type: str
    start_sec: float
    end_sec: float
    chunk_id: str
    confidence: float
    normalized_form: str
    coref_group_id: Optional[str] = None


class EntityIndex(BaseModel):
    """Maps normalized entity name -> mentions sorted by timestamp."""

    mentions_by_entity: Dict[str, List[EntityMention]] = Field(default_factory=dict)
    all_mentions: List[EntityMention] = Field(default_factory=list)

    def lookup(self, entity_name: str) -> List[EntityMention]:
        key = normalize_entity(entity_name)
        return self.mentions_by_entity.get(key, [])

    def lookup_fuzzy(self, entity_name: str) -> List[EntityMention]:
        key = normalize_entity(entity_name)
        results = list(self.mentions_by_entity.get(key, []))
        if results:
            return results
        # Partial match on normalized forms
        for norm, mentions in self.mentions_by_entity.items():
            if key in norm or norm in key:
                results.extend(mentions)
        return results


def normalize_entity(text: str) -> str:
    """Canonical form: strip titles, lowercase for matching."""
    t = text.strip()
    t = re.sub(r"^(Mr\.|Mrs\.|Ms\.|Dr\.|the)\s+", "", t, flags=re.IGNORECASE)
    return t.lower()


def _get_nlp():
    global _nlp, _coref_available
    if _nlp is None:
        # Under memory pressure, skip heavy spacy models entirely
        try:
            from python.resource_manager import should_skip_models

            if should_skip_models():
                logger.info("Memory CRITICAL — skipping spaCy, using regex NER")
                _nlp = False
                return None
        except ImportError:
            pass

        try:
            import spacy

            # Prefer lightweight model on CPU-only machines
            try:
                from python.resource_manager import should_use_lightweight

                prefer_small = should_use_lightweight()
            except ImportError:
                prefer_small = True

            loaded = False
            if not prefer_small:
                try:
                    _nlp = spacy.load("en_core_web_trf")
                    loaded = True
                except OSError:
                    pass

            if not loaded:
                try:
                    _nlp = spacy.load("en_core_web_sm")
                except OSError:
                    _nlp = False
                    return None

            try:
                import coreferee  # noqa: F401

                if "coreferee" not in _nlp.pipe_names:
                    _nlp.add_pipe("coreferee")
                _coref_available = True
            except (ImportError, ValueError):
                _coref_available = False
                logger.warning("coreferee not available; skipping coreference resolution")

            try:
                from python.resource_manager import get_model_lifecycle

                size = 70.0 if prefer_small else 460.0
                get_model_lifecycle().register("spacy_nlp", _nlp, size)
            except ImportError:
                pass
        except ImportError:
            _nlp = False
            logger.warning("spacy not installed; using regex NER fallback")
            return None
    return _nlp if _nlp is not False else None


def _get_gliner():
    global _gliner
    if _gliner is None:
        # GLiNER is ~400 MB — skip under any memory pressure
        try:
            from python.resource_manager import should_use_lightweight

            if should_use_lightweight():
                logger.info("Low-resource mode — skipping GLiNER")
                _gliner = False
                return None
        except ImportError:
            pass

        try:
            from gliner import GLiNER

            _gliner = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
            logger.info("Loaded GLiNER model")

            try:
                from python.resource_manager import get_model_lifecycle

                get_model_lifecycle().register("gliner", _gliner, 400.0)
            except ImportError:
                pass
        except Exception as e:
            _gliner = False
            logger.warning("GLiNER unavailable: %s", e)
    return _gliner if _gliner is not False else None


def _char_span_to_time(
    utterance: Utterance,
    char_start: int,
    char_end: int,
    full_text: str,
) -> Tuple[float, float]:
    if not utterance.words:
        return utterance.start, utterance.end

    char_pos = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    for w in utterance.words:
        idx = full_text.find(w.text, char_pos)
        if idx < 0:
            idx = char_pos
        w_end = idx + len(w.text)
        if w_end > char_start and start_time is None:
            start_time = w.start
        if idx < char_end:
            end_time = w.end
        char_pos = w_end + 1

    return start_time or utterance.start, end_time or utterance.end


def extract_spacy_entities(
    text: str,
    utterance: Utterance,
    chunk_id: str,
) -> List[EntityMention]:
    nlp = _get_nlp()
    if nlp is None:
        return _regex_entities(text, utterance, chunk_id)

    doc = nlp(text)
    mentions: List[EntityMention] = []

    for ent in doc.ents:
        etype = SPACY_LABEL_MAP.get(ent.label_, ent.label_.lower())
        start_sec, end_sec = _char_span_to_time(utterance, ent.start_char, ent.end_char, text)
        mentions.append(
            EntityMention(
                text=ent.text,
                entity_type=etype,
                start_sec=start_sec,
                end_sec=end_sec,
                chunk_id=chunk_id,
                confidence=0.85,
                normalized_form=normalize_entity(ent.text),
            )
        )

    return mentions


def extract_gliner_entities(
    text: str,
    utterance: Utterance,
    chunk_id: str,
) -> List[EntityMention]:
    gliner = _get_gliner()
    if gliner is None:
        return []

    try:
        predictions = gliner.predict_entities(text, GLINER_LABELS, threshold=0.4)
    except Exception as e:
        logger.warning("GLiNER prediction failed: %s", e)
        return []

    mentions: List[EntityMention] = []
    for pred in predictions:
        label = pred.get("label", "unknown")
        start_char = pred.get("start", 0)
        end_char = pred.get("end", len(text))
        start_sec, end_sec = _char_span_to_time(utterance, start_char, end_char, text)
        mentions.append(
            EntityMention(
                text=pred["text"],
                entity_type=label,
                start_sec=start_sec,
                end_sec=end_sec,
                chunk_id=chunk_id,
                confidence=float(pred.get("score", 0.7)),
                normalized_form=normalize_entity(pred["text"]),
            )
        )
    return mentions


def _regex_entities(text: str, utterance: Utterance, chunk_id: str) -> List[EntityMention]:
    """Fallback when spaCy/GLiNER unavailable."""
    mentions: List[EntityMention] = []

    for m in re.finditer(r"\b(\d+\s*(?:rupees?|crore|dollars?))\b", text, re.I):
        mentions.append(
            EntityMention(
                text=m.group(1),
                entity_type="monetary_amount",
                start_sec=utterance.start,
                end_sec=utterance.end,
                chunk_id=chunk_id,
                confidence=0.9,
                normalized_form=normalize_entity(m.group(1)),
            )
        )

    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        mentions.append(
            EntityMention(
                text=m.group(1),
                entity_type="person_name",
                start_sec=utterance.start,
                end_sec=utterance.end,
                chunk_id=chunk_id,
                confidence=0.6,
                normalized_form=normalize_entity(m.group(1)),
            )
        )

    return mentions


def resolve_coreference(
    doc_text: str,
    mentions: List[EntityMention],
) -> List[EntityMention]:
    """Link pronouns and aliases via coreferee."""
    nlp = _get_nlp()
    if nlp is None or not _coref_available:
        return _heuristic_coref(mentions)

    try:
        spacy_doc = nlp(doc_text)
        chains = spacy_doc._.coref_chains if hasattr(spacy_doc._, "coref_chains") else []

        # Map mention text to chain id
        text_to_chain: Dict[str, str] = {}
        for i, chain in enumerate(chains):
            chain_id = f"coref_{i}"
            for mention_idx in chain:
                token = spacy_doc[mention_idx]
                text_to_chain[token.text.lower()] = chain_id
                if token.ent_type_ == "PERSON":
                    text_to_chain[normalize_entity(token.text)] = chain_id

        for mention in mentions:
            key = mention.text.lower()
            if key in text_to_chain:
                mention.coref_group_id = text_to_chain[key]
            elif mention.normalized_form in text_to_chain:
                mention.coref_group_id = text_to_chain[mention.normalized_form]

    except Exception as e:
        logger.warning("Coreference resolution failed: %s", e)
        return _heuristic_coref(mentions)

    return mentions


def _heuristic_coref(mentions: List[EntityMention]) -> List[EntityMention]:
    """Simple alias linking: last name matches, substring matches."""
    person_mentions = [m for m in mentions if m.entity_type in ("person_name", "PERSON")]
    groups: Dict[str, str] = {}

    for m in person_mentions:
        parts = m.normalized_form.split()
        last = parts[-1] if parts else m.normalized_form
        if last in groups:
            m.coref_group_id = groups[last]
        else:
            gid = f"heuristic_{last}"
            groups[last] = gid
            m.coref_group_id = gid

        for other in person_mentions:
            if other is m:
                continue
            if last in other.normalized_form or other.normalized_form in m.normalized_form:
                other.coref_group_id = m.coref_group_id

    return mentions


def deduplicate_mentions(mentions: List[EntityMention]) -> List[EntityMention]:
    seen: set[tuple] = set()
    unique: List[EntityMention] = []
    for m in mentions:
        key = (m.normalized_form, round(m.start_sec, 1), m.entity_type)
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def build_entity_index(
    transcript_doc: TranscriptDocument,
    chunks: List[Chunk],
) -> EntityIndex:
    """Extract entities from all chunks and build searchable index."""
    chunk_by_utt: Dict[str, Chunk] = {c.chunk_id: c for c in chunks}
    all_mentions: List[EntityMention] = []
    full_text = " ".join(get_utterance_text(u) for u in transcript_doc.utterances)

    # Map utterances to best matching chunk
    for chunk in chunks:
        if chunk.chunk_type not in ("sentence", "utterance"):
            continue

        spacy_mentions = extract_spacy_entities(chunk.text, _chunk_to_utterance(chunk, transcript_doc), chunk.chunk_id)
        gliner_mentions = extract_gliner_entities(chunk.text, _chunk_to_utterance(chunk, transcript_doc), chunk.chunk_id)
        all_mentions.extend(spacy_mentions)
        all_mentions.extend(gliner_mentions)

    all_mentions = deduplicate_mentions(all_mentions)
    all_mentions = resolve_coreference(full_text, all_mentions)

    by_entity: Dict[str, List[EntityMention]] = defaultdict(list)
    for m in all_mentions:
        by_entity[m.normalized_form].append(m)

    for key in by_entity:
        by_entity[key].sort(key=lambda x: x.start_sec)

    return EntityIndex(mentions_by_entity=dict(by_entity), all_mentions=all_mentions)


def _chunk_to_utterance(chunk: Chunk, doc: TranscriptDocument) -> Utterance:
    for u in doc.utterances:
        if u.start <= chunk.start_sec and u.end >= chunk.end_sec:
            return u
    # Synthetic utterance for timestamp mapping
    return Utterance(
        words=[],
        start=chunk.start_sec,
        end=chunk.end_sec,
        speaker_id=chunk.speaker_id,
        raw_text=chunk.text,
    )
