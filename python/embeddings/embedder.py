"""
Bi-encoder and cross-encoder embedding engine.

Primary: BAAI/bge-large-en-v1.5 with instruction prefixes.
Caches embeddings to ~/.axew/embedding_cache/
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from python.retrieval.chunker import Chunk
from python.retrieval.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

QUERY_PREFIX = "Represent this question for retrieving relevant passages: "
PASSAGE_PREFIX = "Represent this sentence for retrieval: "

CACHE_DIR = Path(os.path.expanduser("~/.axew/embedding_cache"))

try:
    from diskcache import Cache as DiskCache

    _DISK_CACHE: Optional[DiskCache] = DiskCache(
        str(CACHE_DIR / "diskcache"),
        size_limit=10 * 2**30,
    )
except ImportError:
    _DISK_CACHE = None


class EmbeddingEngine:
    def __init__(self) -> None:
        self.registry = ModelRegistry()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{key}.npy"

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_cached(self, text: str) -> Optional[np.ndarray]:
        key = self._cache_key(text)
        if _DISK_CACHE is not None:
            cached = _DISK_CACHE.get(key)
            if cached is not None:
                return np.asarray(cached, dtype=np.float32)
        path = self._cache_path(text)
        if path.is_file():
            return np.load(path)
        return None

    def _save_cached(self, text: str, vec: np.ndarray) -> None:
        key = self._cache_key(text)
        if _DISK_CACHE is not None:
            _DISK_CACHE.set(key, vec.tolist())
        np.save(self._cache_path(text), vec)

    def _valid_cached(self, cached: Optional[np.ndarray], expected_dim: Optional[int]) -> Optional[np.ndarray]:
        if cached is None:
            return None
        if expected_dim is None or cached.ndim == 1 and cached.shape[0] == expected_dim:
            return cached
        logger.info(
            "Ignoring stale embedding cache entry with dim=%s; expected dim=%s",
            cached.shape[0] if cached.ndim else "scalar",
            expected_dim,
        )
        return None

    def embed_query(self, query: str, instruction: Optional[str] = None) -> np.ndarray:
        prefix = instruction or QUERY_PREFIX
        text = f"{prefix}{query}"
        model = self.registry.get_bi_encoder()
        expected_dim = model.get_sentence_embedding_dimension()
        cached = self._valid_cached(self._load_cached(text), expected_dim)
        if cached is not None:
            return cached
        vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        vec = np.asarray(vec, dtype=np.float32)
        self._save_cached(text, vec)
        return vec

    def embed_passage(self, text: str) -> np.ndarray:
        full = f"{PASSAGE_PREFIX}{text}"
        model = self.registry.get_bi_encoder()
        expected_dim = model.get_sentence_embedding_dimension()
        cached = self._valid_cached(self._load_cached(full), expected_dim)
        if cached is not None:
            return cached
        vec = model.encode(full, normalize_embeddings=True, show_progress_bar=False)
        vec = np.asarray(vec, dtype=np.float32)
        self._save_cached(full, vec)
        return vec

    def embed_chunks(self, chunks: List[Chunk], batch_size: int = 32) -> List[Chunk]:
        model = self.registry.get_bi_encoder()
        expected_dim = model.get_sentence_embedding_dimension()
        texts = [f"{PASSAGE_PREFIX}{c.text}" for c in chunks]
        to_encode: List[int] = []
        vectors: List[Optional[np.ndarray]] = [None] * len(chunks)

        for i, text in enumerate(texts):
            cached = self._valid_cached(self._load_cached(text), expected_dim)
            if cached is not None:
                vectors[i] = cached
            else:
                to_encode.append(i)

        if to_encode:
            batch_texts = [texts[i] for i in to_encode]
            encoded = model.encode(
                batch_texts,
                normalize_embeddings=True,
                batch_size=batch_size,
                show_progress_bar=len(batch_texts) > batch_size,
            )
            for idx, vec in zip(to_encode, encoded):
                arr = np.asarray(vec, dtype=np.float32)
                vectors[idx] = arr
                self._save_cached(texts[idx], arr)

        for chunk, vec in zip(chunks, vectors):
            if vec is not None:
                chunk.embedding = vec.tolist()
        return chunks

    def rerank(
        self,
        query: str,
        candidates: List[Chunk],
        use_large: bool = False,
    ) -> List[Tuple[Chunk, float]]:
        if not candidates:
            return []
        model = self.registry.get_cross_encoder(use_large=use_large)
        if model is None:
            # Graceful fallback: sort by cosine similarity
            q_vec = self.embed_query(query)
            scored = []
            for c in candidates:
                c_vec = np.array(c.embedding, dtype=np.float32) if c.embedding else self.embed_passage(c.text)
                scored.append((c, float(np.dot(q_vec, c_vec))))
            return sorted(scored, key=lambda x: x[1], reverse=True)
        pairs = [(query, c.text) for c in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        return sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)

    def rerank_with_context(
        self,
        query: str,
        candidates: List[Chunk],
        context_chunks: dict[str, Chunk],
        use_large: bool = False,
    ) -> List[Tuple[Chunk, float]]:
        enriched: List[Chunk] = []
        for c in candidates:
            parts = []
            if c.parent_chunk_id and c.parent_chunk_id in context_chunks:
                parts.append(context_chunks[c.parent_chunk_id].text)
            parts.append(c.text)
            enriched.append(
                Chunk(
                    chunk_id=c.chunk_id,
                    video_id=c.video_id,
                    text=" ".join(parts)[:2000],
                    start_sec=c.start_sec,
                    end_sec=c.end_sec,
                    speaker_id=c.speaker_id,
                    chunk_type=c.chunk_type,
                )
            )
        return self.rerank(query, enriched, use_large=use_large)
