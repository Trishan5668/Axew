"""
BM25 sparse index per video, serialized to ~/.axew/bm25/{video_id}.pkl
"""

from __future__ import annotations

import logging
import os
import pickle
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from python.retrieval.chunker import Chunk
from python.retrieval.keyword_extractor import tokenize_for_bm25

logger = logging.getLogger(__name__)

BM25_DIR = Path(os.path.expanduser("~/.axew/bm25"))

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "into", "through", "during", "before", "after",
    "and", "but", "if", "or", "because", "until", "while", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they",
}


class BM25Index:
    def __init__(self) -> None:
        self._indexes: Dict[str, Any] = {}
        self._chunk_ids: Dict[str, List[str]] = {}
        self._corpus_tokens: Dict[str, List[List[str]]] = {}
        BM25_DIR.mkdir(parents=True, exist_ok=True)

    def _index_path(self, video_id: str) -> Path:
        safe = re.sub(r"[^\w.-]", "_", video_id)
        return BM25_DIR / f"{safe}.pkl"

    def build(self, video_id: str, chunks: List[Chunk]) -> None:
        corpus: List[List[str]] = []
        chunk_ids: List[str] = []

        for chunk in chunks:
            keywords = chunk.metadata.get("keywords", [])
            tokens = tokenize_for_bm25(keywords, chunk.text)
            if not tokens:
                tokens = re.findall(r"\b[a-z0-9]+\b", chunk.text.lower())
                tokens = [t for t in tokens if t not in STOPWORDS]
            corpus.append(tokens)
            chunk_ids.append(chunk.chunk_id)

        self._corpus_tokens[video_id] = corpus
        self._chunk_ids[video_id] = chunk_ids

        try:
            from rank_bm25 import BM25Okapi

            self._indexes[video_id] = BM25Okapi(corpus)
        except ImportError:
            logger.warning("rank_bm25 not installed; using simple TF fallback")
            self._indexes[video_id] = None

        with self._index_path(video_id).open("wb") as f:
            pickle.dump(
                {"corpus": corpus, "chunk_ids": chunk_ids, "has_bm25": self._indexes[video_id] is not None},
                f,
            )

    def load(self, video_id: str) -> bool:
        path = self._index_path(video_id)
        if not path.is_file():
            return False
        with path.open("rb") as f:
            data = pickle.load(f)
        self._corpus_tokens[video_id] = data["corpus"]
        self._chunk_ids[video_id] = data["chunk_ids"]
        if data.get("has_bm25"):
            try:
                from rank_bm25 import BM25Okapi

                self._indexes[video_id] = BM25Okapi(data["corpus"])
            except ImportError:
                self._indexes[video_id] = None
        else:
            self._indexes[video_id] = None
        return True

    def query_bm25(self, query: str, video_id: str, top_k: int = 20) -> List[Tuple[str, float]]:
        if video_id not in self._chunk_ids:
            if not self.load(video_id):
                return []

        query_tokens = re.findall(r"\b[a-z0-9]+\b", query.lower())
        query_tokens = [t for t in query_tokens if t not in STOPWORDS]
        if not query_tokens:
            return []

        bm25 = self._indexes.get(video_id)
        chunk_ids = self._chunk_ids[video_id]

        if bm25 is not None:
            scores = bm25.get_scores(query_tokens)
            ranked = sorted(zip(chunk_ids, scores), key=lambda x: x[1], reverse=True)
            return [(cid, float(s)) for cid, s in ranked[:top_k] if s > 0]

        # TF fallback
        corpus = self._corpus_tokens[video_id]
        scores: List[float] = []
        qset = set(query_tokens)
        for tokens in corpus:
            tset = set(tokens)
            overlap = len(qset & tset)
            scores.append(overlap / max(len(qset), 1))
        ranked = sorted(zip(chunk_ids, scores), key=lambda x: x[1], reverse=True)
        return [(cid, s) for cid, s in ranked[:top_k] if s > 0]
