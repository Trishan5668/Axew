"""
Keyword extraction for BM25 sparse retrieval index.

Uses KeyBERT when available; falls back to regex + entity/event token extraction.
"""

from __future__ import annotations

import logging
import re
from typing import List, Set

from python.retrieval.chunker import Chunk

logger = logging.getLogger(__name__)

_keybert_model = None
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "and", "but", "if", "or", "because", "until", "while", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "what",
    "which", "who", "whom", "its", "my", "your", "his", "her", "our", "their",
}


def _get_keybert():
    global _keybert_model
    if _keybert_model is None:
        try:
            from keybert import KeyBERT

            _keybert_model = KeyBERT(model="all-MiniLM-L6-v2")
            logger.info("Loaded KeyBERT model")
        except Exception as e:
            _keybert_model = False
            logger.warning("KeyBERT unavailable: %s", e)
    return _keybert_model if _keybert_model is not False else None


def extract_numbers(text: str) -> List[str]:
    patterns = [
        r"\b\d+\s*(?:rupees?|crore|dollars?|₹|\$)\b",
        r"\b\d+(?:\.\d+)?\b",
    ]
    found: List[str] = []
    for pat in patterns:
        found.extend(re.findall(pat, text, re.IGNORECASE))
    return found


def extract_keyphrases_keybert(text: str, top_n: int = 8) -> List[str]:
    kb = _get_keybert()
    if kb is None:
        return _fallback_keyphrases(text, top_n)

    try:
        keywords = kb.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),
            stop_words="english",
            top_n=top_n,
            use_mmr=True,
            diversity=0.5,
        )
        return [kw for kw, _ in keywords]
    except Exception as e:
        logger.warning("KeyBERT extraction failed: %s", e)
        return _fallback_keyphrases(text, top_n)


def _fallback_keyphrases(text: str, top_n: int) -> List[str]:
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq, key=lambda w: freq[w], reverse=True)
    return sorted_words[:top_n]


def extract_chunk_keywords(chunk: Chunk) -> List[str]:
    """
    Combine KeyBERT keyphrases + entities + events + numbers.
    Stores result in chunk.metadata['keywords'].
    """
    keywords: Set[str] = set()

    for phrase in extract_keyphrases_keybert(chunk.text):
        keywords.add(phrase.lower())

    for entity in chunk.entities:
        keywords.add(entity.lower())

    for event in chunk.events:
        keywords.add(event.lower())

    for num in extract_numbers(chunk.text):
        keywords.add(num.lower())

    # Proper nouns from text
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", chunk.text):
        keywords.add(m.group(1).lower())

    result = sorted(keywords)
    chunk.metadata["keywords"] = result
    return result


def enrich_chunks_with_keywords(chunks: List[Chunk]) -> None:
    for chunk in chunks:
        extract_chunk_keywords(chunk)


def tokenize_for_bm25(keywords: List[str], text: str) -> List[str]:
    """Lemmatized tokens for BM25 indexing (Phase 3)."""
    combined = " ".join(keywords) + " " + text.lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", combined)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]
