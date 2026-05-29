"""Production semantic retrieval pipeline orchestration."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np

from python.models.transcript import TranscriptChunk
from python.retrieval.context_expander import ContextExpander
from python.retrieval.hybrid_retriever import HybridRetriever
from python.retrieval.query_decomposer import QueryDecomposer
from python.retrieval.reranker import ConversationalReranker
from python.retrieval.timestamp_contract import PlannerError, TimestampContract
from python.retrieval.topic_segmenter import SegmentIndex, TopicSegmenter
from python.retrieval.trace import RetrievalTrace, add_trace
from python.retrieval.types import RetrievalCandidate


@dataclass
class RetrievalResult:
    top_candidate: RetrievalCandidate
    all_candidates: list[RetrievalCandidate]
    trace: RetrievalTrace


class InMemoryChunkIndex:
    def __init__(self, chunks: list[TranscriptChunk], embeddings: list[np.ndarray]) -> None:
        self.chunks = chunks
        self.embeddings = np.asarray(embeddings, dtype=np.float32)

    def search(self, query_embedding: np.ndarray, k: int) -> list[tuple[TranscriptChunk, float]]:
        if not self.chunks:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        scores = self.embeddings @ q / np.maximum(np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(q), 1e-6)
        order = np.argsort(-scores)[:k]
        return [(self.chunks[int(i)], float(scores[int(i)])) for i in order]


class InMemoryBM25:
    def __init__(self, chunks: list[TranscriptChunk]) -> None:
        self.chunks = chunks
        self._bm25 = None
        self._corpus = [re.findall(r"\b[a-z0-9]+\b", c.text.lower()) for c in chunks]
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._corpus)
        except Exception:
            self._bm25 = None

    def query(self, query_text: str, k: int) -> list[tuple[str, float]]:
        q = re.findall(r"\b[a-z0-9]+\b", query_text.lower())
        if not q:
            return []
        if self._bm25 is not None:
            scores = self._bm25.get_scores(q)
        else:
            qset = set(q)
            scores = [len(qset & set(doc)) / max(len(qset), 1) for doc in self._corpus]
        order = np.argsort(-np.asarray(scores, dtype=np.float32))[:k]
        return [(self.chunks[int(i)].id, float(scores[int(i)])) for i in order if scores[int(i)] > 0]


class RetrievalPipeline:
    def __init__(self) -> None:
        self.decomposer = QueryDecomposer()
        self.segmenter = TopicSegmenter()
        self.retriever = HybridRetriever()
        self.expander = ContextExpander()
        self.reranker = ConversationalReranker()

    def retrieve(
        self,
        raw_query: str,
        transcript: list[TranscriptChunk],
        session_context: list[str] | None = None,
    ) -> RetrievalResult:
        trace = RetrievalTrace(query_original=raw_query)
        t0 = time.monotonic()
        try:
            t = time.monotonic()
            query = self.decomposer.decompose(raw_query)
            trace.decomposed = query
            trace.stage_latencies["decompose_ms"] = (time.monotonic() - t) * 1000

            t = time.monotonic()
            segments = self.segmenter.segment(transcript)
            segment_index = SegmentIndex.build(segments)
            embeddings = [self.segmenter._chunk_embedding(c) for c in sorted(transcript, key=lambda c: c.start_time)]
            sorted_transcript = sorted(transcript, key=lambda c: c.start_time)
            chunk_index = InMemoryChunkIndex(sorted_transcript, embeddings)
            bm25_index = InMemoryBM25(sorted_transcript)
            trace.stage_latencies["segment_ms"] = (time.monotonic() - t) * 1000

            t = time.monotonic()
            candidates = self.retriever.retrieve(query, chunk_index, segment_index, bm25_index)
            trace.opener_suppressions.extend(self.retriever.trace_events.get("opener_suppressions", []))
            for c in candidates:
                TimestampContract.validate_candidate(c, "post_retrieval")
            trace.candidates_after_retrieval = [c.to_dict() for c in candidates]
            trace.stage_latencies["retrieval_ms"] = (time.monotonic() - t) * 1000

            t = time.monotonic()
            candidates = self.expander.expand(candidates, sorted_transcript, segments, query)
            for c in candidates:
                TimestampContract.validate_candidate(c, "post_expansion")
            trace.candidates_after_expansion = [c.to_dict() for c in candidates]
            trace.stage_latencies["expansion_ms"] = (time.monotonic() - t) * 1000

            t = time.monotonic()
            candidates = self.reranker.rerank(query, candidates, session_context)
            for c in candidates:
                TimestampContract.validate_candidate(c, "post_reranking")
            trace.candidates_after_reranking = [c.to_dict() for c in candidates]
            trace.stage_latencies["rerank_ms"] = (time.monotonic() - t) * 1000

            if not candidates:
                raise PlannerError(
                    "Retrieval returned no valid candidates. "
                    f"Query: '{raw_query}'. Decomposed: {query}. "
                    "Check retrieval trace for diagnostics."
                )
            trace.final_result = candidates[0].to_dict()
            return RetrievalResult(top_candidate=candidates[0], all_candidates=candidates, trace=trace)
        finally:
            trace.total_latency_ms = (time.monotonic() - t0) * 1000
            add_trace(trace)
