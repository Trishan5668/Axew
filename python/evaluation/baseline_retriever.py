"""
Baseline retriever adapter — mirrors current AXEW semantic search in execution.py.

Uses sentence-transformers/all-MiniLM-L6-v2 with cosine similarity over flat segments.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from python.evaluation.benchmark import CandidateWindow, RetrievalOutput

_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


class BaselineRetriever:
    """Current production retrieval: flat segment embedding similarity."""

    def __init__(
        self,
        segments: List[Dict[str, Any]],
        top_k: int = 8,
        min_score: float = 0.22,
        padding_seconds: float = 0.4,
        merge_gap: float = 1.5,
    ) -> None:
        self.segments = segments
        self.top_k = top_k
        self.min_score = min_score
        self.padding_seconds = padding_seconds
        self.merge_gap = merge_gap
        self._segment_vecs = None

    def _encode_segments(self):
        if self._segment_vecs is not None:
            return
        model = _get_embed_model()
        texts = [s["text"] for s in self.segments]
        self._segment_vecs = model.encode(texts, normalize_embeddings=True)

    def _search(self, query: str) -> List[Dict[str, Any]]:
        import numpy as np

        self._encode_segments()
        model = _get_embed_model()
        query_vec = model.encode(query, normalize_embeddings=True)

        scored: List[Dict[str, Any]] = []
        for seg, vec in zip(self.segments, self._segment_vecs):
            score = float(np.dot(query_vec, vec))
            if score >= self.min_score:
                scored.append({**seg, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[: self.top_k]

    def _merge_matches(self, matches: List[Dict[str, Any]]) -> tuple[float, float, float]:
        if not matches:
            return 0.0, 0.0, 0.0

        sorted_m = sorted(matches, key=lambda m: m["start"])
        start = sorted_m[0]["start"]
        end = sorted_m[0]["end"]
        confidence = sorted_m[0]["score"]

        for m in sorted_m[1:]:
            if m["start"] <= end + self.merge_gap:
                end = max(end, m["end"])
                confidence = max(confidence, m["score"])
            else:
                break

        start = max(0.0, start - self.padding_seconds)
        end = end + self.padding_seconds
        return start, end, confidence

    def __call__(self, query: str) -> RetrievalOutput:
        matches = self._search(query)
        candidates = [
            CandidateWindow(
                start_sec=m["start"],
                end_sec=m["end"],
                confidence=m["score"],
            )
            for m in matches
        ]

        if matches:
            start, end, confidence = self._merge_matches(matches)
        else:
            start, end, confidence = 0.0, 0.0, 0.0

        return RetrievalOutput(
            start_sec=start,
            end_sec=end,
            confidence=confidence,
            candidates=candidates,
        )
