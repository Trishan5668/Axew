"""
Hybrid retrieval: dense (BGE/Chroma) + sparse (BM25) with RRF fusion.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field
try:
    from thefuzz import fuzz
except Exception:
    try:
        from rapidfuzz import fuzz
    except Exception:
        from difflib import SequenceMatcher

        class _Fuzz:
            @staticmethod
            def partial_ratio(a: str, b: str) -> int:
                a = (a or "").lower()
                b = (b or "").lower()
                if not a or not b:
                    return 0
                if a in b or b in a:
                    return 100
                short, long = (a, b) if len(a) <= len(b) else (b, a)
                best = 0.0
                for i in range(0, max(1, len(long) - len(short) + 1)):
                    best = max(best, SequenceMatcher(None, short, long[i:i + len(short)]).ratio())
                return int(best * 100)

        fuzz = _Fuzz()

from python.embeddings.embedder import EmbeddingEngine
from python.retrieval.bm25_index import BM25Index
from python.retrieval.chunker import Chunk
from python.retrieval.types import DecomposedQuery, RetrievalCandidate, TopicSegment
from python.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RetrievalResult(BaseModel):
    chunk_id: str
    chunk: Optional[Chunk] = None
    text: str
    start_sec: float
    end_sec: float
    score_dense: float = 0.0
    score_bm25: float = 0.0
    score_fused: float = 0.0
    speaker_id: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    events: List[str] = Field(default_factory=list)


def reciprocal_rank_fusion(
    rankings: List[List[Tuple[str, float]]],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """Standard RRF over multiple ranked lists."""
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def rrf_fusion(
    dense_results: List[Tuple[str, float]],
    sparse_results: List[Tuple[str, float]],
    k: int = 60,
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
) -> List[Tuple[str, float]]:
    dense_rank = {cid: i + 1 for i, (cid, _) in enumerate(dense_results)}
    sparse_rank = {cid: i + 1 for i, (cid, _) in enumerate(sparse_results)}
    all_ids = set(dense_rank) | set(sparse_rank)
    max_rank = max(len(dense_results), len(sparse_results), 1) + 1

    fused: List[Tuple[str, float]] = []
    for cid in all_ids:
        dr = dense_rank.get(cid, max_rank)
        sr = sparse_rank.get(cid, max_rank)
        score = dense_weight / (k + dr) + sparse_weight / (k + sr)
        fused.append((cid, score))

    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


def linear_combination_fusion(
    dense_results: List[Tuple[str, float]],
    sparse_results: List[Tuple[str, float]],
    alpha: float = 0.7,
) -> List[Tuple[str, float]]:
    def normalize(results: List[Tuple[str, float]]) -> Dict[str, float]:
        if not results:
            return {}
        scores = [s for _, s in results]
        mn, mx = min(scores), max(scores)
        span = mx - mn or 1.0
        return {cid: (s - mn) / span for cid, s in results}

    dense_n = normalize(dense_results)
    sparse_n = normalize(sparse_results)
    all_ids = set(dense_n) | set(sparse_n)
    fused = [
        (cid, alpha * dense_n.get(cid, 0.0) + (1 - alpha) * sparse_n.get(cid, 0.0))
        for cid in all_ids
    ]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


class HybridRetriever:
    def __init__(
        self,
        video_id: str = "default",
        chunks_by_id: Optional[Dict[str, Chunk]] = None,
        chunk_types: Optional[List[str]] = None,
    ) -> None:
        self.video_id = video_id
        self.chunks_by_id = chunks_by_id or {}
        self.chunk_types = chunk_types or ["sentence", "utterance"]
        self.embedder = EmbeddingEngine()
        self.vector_store = VectorStore()
        self.bm25 = BM25Index()
        self.trace_events: Dict[str, List[dict]] = {"opener_suppressions": [], "discarded": []}

    def index(self, chunks: List[Chunk]) -> None:
        """Embed and index all chunks."""
        sentence_chunks = [c for c in chunks if c.chunk_type == "sentence"]
        utterance_chunks = [c for c in chunks if c.chunk_type == "utterance"]
        entity_chunks = [c for c in chunks if c.chunk_type == "entity_context"]

        for group, ctype in [
            (sentence_chunks, "sentence"),
            (utterance_chunks, "utterance"),
            (entity_chunks, "entity_context"),
        ]:
            if not group:
                continue
            self.embedder.embed_chunks(group)
            self.vector_store.upsert_chunks(group, ctype, self.video_id)

        index_chunks = sentence_chunks or utterance_chunks
        self.bm25.build(self.video_id, index_chunks)

    async def search(
        self,
        query: str,
        top_k: int = 20,
        chunk_types: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        fusion: str = "rrf",
    ) -> List[RetrievalResult]:
        ctypes = chunk_types or self.chunk_types
        query_vec = self.embedder.embed_query(query)

        dense_raw = self.vector_store.query_collection(
            query_vec, self.video_id, ctypes, top_k=top_k * 2, filters=filters
        )
        dense_results = [(cid, score) for cid, score, _ in dense_raw]

        sparse_results = self.bm25.query_bm25(query, self.video_id, top_k=top_k * 2)

        if fusion == "linear":
            fused = linear_combination_fusion(dense_results, sparse_results)
        else:
            fused = rrf_fusion(dense_results, sparse_results)

        dense_map = dict(dense_results)
        sparse_map = dict(sparse_results)

        results: List[RetrievalResult] = []
        for cid, fscore in fused[:top_k]:
            chunk = self.chunks_by_id.get(cid)
            if not chunk:
                continue
            results.append(
                RetrievalResult(
                    chunk_id=cid,
                    chunk=chunk,
                    text=chunk.text,
                    start_sec=chunk.start_sec,
                    end_sec=chunk.end_sec,
                    score_dense=dense_map.get(cid, 0.0),
                    score_bm25=sparse_map.get(cid, 0.0),
                    score_fused=fscore,
                    speaker_id=chunk.speaker_id,
                    entities=chunk.entities,
                    events=chunk.events,
                )
            )
        return results

    def retrieve(
        self,
        query: DecomposedQuery,
        chunk_index,
        segment_index,
        bm25_index,
        k_dense: int = 30,
        k_sparse: int = 30,
        k_entity: int = 20,
        k_final: int = 15,
    ) -> List[RetrievalCandidate]:
        """Production hybrid retrieval with dense, sparse, entity, fuzzy, and opener control."""
        self.trace_events = {"opener_suppressions": [], "discarded": []}
        query_text = f"{query.original} {' '.join(query.paraphrases)}".strip()
        query_emb = self.embedder.embed_query(query_text)
        all_chunks = self._all_chunks(chunk_index, bm25_index)
        chunk_by_id = {c.id: c for c in all_chunks}
        segment_by_chunk_id: Dict[str, TopicSegment] = {}
        for seg in getattr(segment_index, "segments", []) or []:
            for chunk in seg.chunks:
                segment_by_chunk_id[chunk.id] = seg

        pool: Dict[str, RetrievalCandidate] = {}

        for chunk, score in self._dense_search(chunk_index, all_chunks, query_emb, k_dense):
            cand = pool.setdefault(chunk.id, RetrievalCandidate(chunk=chunk, segment=segment_by_chunk_id.get(chunk.id)))
            cand.score_dense = max(cand.score_dense, score)

        if segment_index is not None:
            for seg in segment_index.search(query_emb, query.original, k=10):
                for chunk in seg.chunks:
                    cand = pool.setdefault(chunk.id, RetrievalCandidate(chunk=chunk, segment=seg))
                    cand.score_dense = max(cand.score_dense, max(0.0, float(np.dot(query_emb, self._chunk_embedding(chunk)))))

        sparse_scores = self._bm25_scores(bm25_index, query.search_terms, query.entities, k_sparse)
        for cid, score in sparse_scores.items():
            chunk = chunk_by_id.get(cid)
            if not chunk:
                continue
            cand = pool.setdefault(cid, RetrievalCandidate(chunk=chunk, segment=segment_by_chunk_id.get(cid)))
            cand.score_bm25 = max(cand.score_bm25, score)

        if query.entity_anchored:
            for entity in query.entities[:8]:
                for idx, chunk in enumerate(all_chunks):
                    text = chunk.text.lower()
                    exact = entity.lower() in text
                    ratio = 100 if exact else fuzz.partial_ratio(entity.lower(), text)
                    if ratio >= 80:
                        for n in range(max(0, idx - 3), min(len(all_chunks), idx + 4)):
                            neighbor = all_chunks[n]
                            cand = pool.setdefault(neighbor.id, RetrievalCandidate(chunk=neighbor, segment=segment_by_chunk_id.get(neighbor.id)))
                            cand.score_entity = max(cand.score_entity, 1.0 if exact and n == idx else ratio / 100.0)
                            cand.score_entity_bonus = True

        for cand in pool.values():
            text = cand.chunk.text.lower()
            for term in query.search_terms:
                ratio = fuzz.partial_ratio(term.lower(), text)
                if ratio >= 70:
                    cand.score_fuzzy = max(cand.score_fuzzy, ratio / 100.0)
            bm25_weight = 0.25 * (1.2 if query.lang_hint == "hinglish" else 1.0)
            fuzzy_weight = 0.15 * (1.2 if query.lang_hint == "hinglish" else 1.0)
            cand.score_fused = (
                0.35 * cand.score_dense +
                bm25_weight * cand.score_bm25 +
                0.25 * cand.score_entity +
                fuzzy_weight * cand.score_fuzzy
            )
            if cand.score_entity_bonus:
                cand.score_fused *= 1.15
            if cand.is_opener and not (cand.score_entity > 0.9 and query.entity_anchored):
                before = cand.score_fused
                cand.score_fused *= 0.4
                self.trace_events["opener_suppressions"].append({
                    "chunk_id": cand.chunk.id,
                    "start": cand.chunk.start_time,
                    "score_before": before,
                    "score_after": cand.score_fused,
                })
            if 0.15 <= cand.score_fused <= 0.30:
                cand.tags.append("weak_candidate")
            cand.match_explanation = (
                f"Dense:{cand.score_dense:.2f} BM25:{cand.score_bm25:.2f} "
                f"Entity:{cand.score_entity:.2f} Fuzzy:{cand.score_fuzzy:.2f} "
                f"-> Fused:{cand.score_fused:.2f}"
            )

        survivors = []
        for cand in pool.values():
            if cand.score_fused >= 0.15:
                survivors.append(cand)
            else:
                self.trace_events["discarded"].append({
                    "chunk_id": cand.chunk.id,
                    "start": cand.chunk.start_time,
                    "reason": "score_fused < 0.15",
                    "score_fused": cand.score_fused,
                })

        deduped: List[RetrievalCandidate] = []
        for cand in sorted(survivors, key=lambda c: c.score_fused, reverse=True):
            near = next((d for d in deduped if abs(d.chunk.start_time - cand.chunk.start_time) < 2.0), None)
            if near:
                near.match_explanation = f"{near.match_explanation}; merged {cand.match_explanation}"
                continue
            deduped.append(cand)

        for rank, cand in enumerate(deduped[:k_final], start=1):
            cand.rank = rank
        return deduped[:k_final]

    def _all_chunks(self, chunk_index, bm25_index) -> List[Any]:
        for obj in (chunk_index, bm25_index):
            chunks = getattr(obj, "chunks", None)
            if chunks:
                return sorted(chunks, key=lambda c: c.start_time)
        return []

    def _dense_search(self, chunk_index, all_chunks: List[Any], query_emb: np.ndarray, k: int) -> List[Tuple[Any, float]]:
        if hasattr(chunk_index, "search"):
            found = chunk_index.search(query_emb, k)
            if found and isinstance(found[0], tuple):
                return [(c, float(s)) for c, s in found]
        scored = [(c, max(0.0, float(np.dot(query_emb, self._chunk_embedding(c))))) for c in all_chunks]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def _bm25_scores(self, bm25_index, terms: List[str], entities: List[str], k: int) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        queries = [" ".join(terms)] + entities
        for q in [q for q in queries if q.strip()]:
            if hasattr(bm25_index, "query"):
                raw = bm25_index.query(q, k)
            elif hasattr(bm25_index, "query_bm25"):
                raw = bm25_index.query_bm25(q, self.video_id, top_k=k)
            else:
                raw = []
            if not raw:
                continue
            max_score = max(float(item[1]) for item in raw) or 1.0
            for item in raw:
                cid = item[0].id if hasattr(item[0], "id") else item[0]
                scores[cid] = max(scores.get(cid, 0.0), float(item[1]) / max_score)
        return scores

    def _chunk_embedding(self, chunk) -> np.ndarray:
        emb = getattr(chunk, "embedding", None)
        if emb is not None:
            return np.asarray(emb, dtype=np.float32)
        return self.embedder.embed_passage(chunk.text or "")
