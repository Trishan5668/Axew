"""Embedding TextTiling topic segmentation and segment-level retrieval index."""

from __future__ import annotations

import re
import uuid
from typing import Any

import numpy as np

from python.embeddings.embedder import EmbeddingEngine
from python.models.transcript import TranscriptChunk
from python.retrieval.types import TopicSegment


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]+\b", text.lower()))


class TopicSegmenter:
    CATEGORIES = [
        "funding", "controversy", "emotional", "joke/humor", "money/finance",
        "personal story", "debate", "advice",
    ]

    def __init__(self) -> None:
        self.embedder = EmbeddingEngine()
        self._embedding_by_chunk_id: dict[str, np.ndarray] = {}
        self._category_embeddings: dict[str, np.ndarray] = {}

    def segment(self, transcript: list[TranscriptChunk]) -> list[TopicSegment]:
        chunks = sorted([c for c in transcript if c.start_time is not None and c.end_time is not None], key=lambda c: c.start_time)
        if not chunks:
            return []
        embeddings = [self._chunk_embedding(c) for c in chunks]
        boundaries = {0, len(chunks)}
        drift_scores: dict[int, float] = {}
        W = 5

        distances = []
        for i in range(1, len(chunks)):
            left = np.mean(embeddings[max(0, i - W):i], axis=0)
            right = np.mean(embeddings[i:min(len(chunks), i + W)], axis=0)
            distances.append(1.0 - cosine(left, right))
        if distances:
            mean = float(np.mean(distances))
            std = float(np.std(distances))
            spike_threshold = mean + 1.5 * std
            for i, dist in enumerate(distances, start=1):
                drift_scores[i] = dist
                if dist > spike_threshold and self._lexical_change(chunks, i, W) > 0.45:
                    boundaries.add(i)

        for i in range(1, len(chunks)):
            gap = chunks[i].start_time - chunks[i - 1].end_time
            if gap > 2.5:
                boundaries.add(i)
            if chunks[i].speaker and chunks[i - 1].speaker and chunks[i].speaker != chunks[i - 1].speaker:
                boundaries.add(i)

        raw_segments = []
        ordered = sorted(boundaries)
        for start_idx, end_idx in zip(ordered, ordered[1:]):
            if start_idx < end_idx:
                raw_segments.append(chunks[start_idx:end_idx])

        merged = self._merge_short_segments(raw_segments)
        segments: list[TopicSegment] = []
        for seg_chunks in merged:
            emb = np.mean([self._chunk_embedding(c) for c in seg_chunks], axis=0).astype(np.float32)
            segments.append(
                TopicSegment(
                    segment_id=str(uuid.uuid4()),
                    chunks=seg_chunks,
                    start=float(seg_chunks[0].start_time),
                    end=float(seg_chunks[-1].end_time),
                    topic_label=self._label_segment(seg_chunks, emb),
                    embedding=emb,
                    boundary_confidence=max((drift_scores.get(chunks.index(seg_chunks[0]), 0.0), 0.5)),
                )
            )
        return segments

    def rebuild_index(self, segments: list[TopicSegment], chunk_index: Any = None) -> "SegmentIndex":
        return SegmentIndex.build(segments)

    def _chunk_embedding(self, chunk: TranscriptChunk) -> np.ndarray:
        if chunk.id in self._embedding_by_chunk_id:
            return self._embedding_by_chunk_id[chunk.id]
        existing = getattr(chunk, "embedding", None)
        if existing is not None:
            emb = np.asarray(existing, dtype=np.float32)
        else:
            emb = self.embedder.embed_passage(chunk.text or "")
        self._embedding_by_chunk_id[chunk.id] = emb
        return emb

    def _lexical_change(self, chunks: list[TranscriptChunk], idx: int, window: int) -> float:
        left = tokens(" ".join(c.text for c in chunks[max(0, idx - window):idx]))
        right = tokens(" ".join(c.text for c in chunks[idx:min(len(chunks), idx + window)]))
        union = left | right
        return 1.0 - (len(left & right) / max(len(union), 1))

    def _merge_short_segments(self, segments: list[list[TranscriptChunk]]) -> list[list[TranscriptChunk]]:
        merged = [list(s) for s in segments if s]
        i = 0
        while i < len(merged):
            duration = merged[i][-1].end_time - merged[i][0].start_time
            if duration >= 15.0 or len(merged) == 1:
                i += 1
                continue
            left_sim = right_sim = -1.0
            cur_emb = np.mean([self._chunk_embedding(c) for c in merged[i]], axis=0)
            if i > 0:
                left_emb = np.mean([self._chunk_embedding(c) for c in merged[i - 1]], axis=0)
                left_sim = cosine(cur_emb, left_emb)
            if i < len(merged) - 1:
                right_emb = np.mean([self._chunk_embedding(c) for c in merged[i + 1]], axis=0)
                right_sim = cosine(cur_emb, right_emb)
            if right_sim > left_sim and i < len(merged) - 1:
                merged[i + 1] = merged[i] + merged[i + 1]
                del merged[i]
            elif i > 0:
                merged[i - 1].extend(merged[i])
                del merged[i]
            else:
                merged[i + 1] = merged[i] + merged[i + 1]
                del merged[i]
        return merged

    def _label_segment(self, chunks: list[TranscriptChunk], emb: np.ndarray) -> str:
        text = " ".join(c.text for c in chunks).lower()
        keyword_labels = {
            "money/finance": ["money", "rupee", "debt", "loan", "bank", "funding", "crore", "lakh"],
            "joke/humor": ["laugh", "funny", "joke"],
            "emotional": ["emotional", "cry", "sad"],
            "controversy": ["controversy", "scam", "case", "fraud"],
            "debate": ["debate", "argue", "disagree"],
            "advice": ["advice", "lesson", "suggest"],
            "personal story": ["story", "journey", "life"],
            "funding": ["funding", "startup", "investment"],
        }
        for label, words in keyword_labels.items():
            if any(w in text for w in words):
                return label
        best_label, best_score = "general", -1.0
        for label in self.CATEGORIES:
            if label not in self._category_embeddings:
                self._category_embeddings[label] = self.embedder.embed_passage(label)
            score = cosine(emb, self._category_embeddings[label])
            if score > best_score:
                best_label, best_score = label, score
        return best_label if best_score >= 0.35 else "general"


class SegmentIndex:
    def __init__(self, segments: list[TopicSegment]) -> None:
        self.segments = segments
        self._matrix = np.array([s.embedding for s in segments], dtype=np.float32) if segments else np.zeros((0, 1), dtype=np.float32)
        self._faiss_index = None
        self._bm25 = None
        self._corpus = [re.findall(r"\b[a-z0-9]+\b", " ".join(c.text for c in s.chunks).lower()) for s in segments]
        if segments:
            try:
                import faiss

                matrix = self._matrix.copy()
                faiss.normalize_L2(matrix)
                self._faiss_index = faiss.IndexFlatIP(matrix.shape[1])
                self._faiss_index.add(matrix)
            except Exception:
                self._faiss_index = None
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._corpus)
        except Exception:
            self._bm25 = None

    @classmethod
    def build(cls, segments: list[TopicSegment]) -> "SegmentIndex":
        return cls(segments)

    def search(self, query_embedding: np.ndarray, query_text: str, k: int = 10) -> list[TopicSegment]:
        if not self.segments:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        if self._faiss_index is not None:
            q2 = q.reshape(1, -1).copy()
            try:
                import faiss

                faiss.normalize_L2(q2)
                dense = np.zeros(len(self.segments), dtype=np.float32)
                scores, ids = self._faiss_index.search(q2, len(self.segments))
                for score, idx in zip(scores[0], ids[0]):
                    if idx >= 0:
                        dense[int(idx)] = float(score)
            except Exception:
                dense = self._matrix @ q / np.maximum(np.linalg.norm(self._matrix, axis=1) * np.linalg.norm(q), 1e-6)
        else:
            dense = self._matrix @ q / np.maximum(np.linalg.norm(self._matrix, axis=1) * np.linalg.norm(q), 1e-6)
        sparse = np.zeros(len(self.segments), dtype=np.float32)
        q_tokens = re.findall(r"\b[a-z0-9]+\b", query_text.lower())
        if self._bm25 is not None and q_tokens:
            sparse = np.asarray(self._bm25.get_scores(q_tokens), dtype=np.float32)
            if sparse.max() > 0:
                sparse = sparse / sparse.max()
        scores = 0.7 * dense + 0.3 * sparse
        order = np.argsort(-scores)[:k]
        return [self.segments[int(i)] for i in order if scores[int(i)] > 0]
