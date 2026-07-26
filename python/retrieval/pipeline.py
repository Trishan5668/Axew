"""Production semantic retrieval pipeline orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from python.models.transcript import TranscriptChunk
from python.retrieval.context_expander import ContextExpander
from python.retrieval.hybrid_retriever import HybridRetriever, StrategyRetrievalContext
from python.retrieval.query_decomposer import QueryDecomposer
from python.retrieval.reranker import ConversationalReranker
from python.retrieval.routing import strategy_routing_decisions
from python.retrieval.timestamp_contract import (
    RetrievalLowConfidenceError,
    StrategyExecutionError,
    TimestampContract,
)
from python.retrieval.topic_segmenter import SegmentIndex, TopicSegmenter
from python.retrieval.trace import RetrievalTrace, add_trace
from python.retrieval.types import DecomposedQuery, RetrievalCandidate

logger = logging.getLogger(__name__)


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
    _EMOTION_TERMS = {
        "emotional", "emotion", "cry", "cries", "crying", "cried", "tears",
        "sad", "heartfelt", "upset",
    }
    _HUMOR_TERMS = {
        "funny", "funnier", "funniest", "hilarious", "joke", "laugh",
        "laughs", "laughed", "laughter", "humor", "chuckle", "giggle",
    }
    _TRANSFER_TERMS = {
        "give", "gives", "gave", "giving", "hand", "hands", "handed",
        "handover", "hand over", "pay", "pays", "paid", "payment",
        "transfer", "transfers", "transferred", "receive", "receives",
        "received", "accept", "accepts", "accepted", "take", "takes", "took",
        "present", "presents", "presented",
    }
    _MONEY_TERMS = {
        "money", "rupee", "rupees", "rs", "inr", "cash", "payment",
        "paid", "pay", "paisa", "paise", "amount",
    }
    _APPLAUSE_TERMS = {
        "applause", "applaud", "applauds", "applauded", "clap", "claps",
        "clapped", "cheer", "cheers", "cheered", "audience reaction",
    }

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
            trace.routing_decisions = {
                strategy: decision.to_dict()
                for strategy, decision in strategy_routing_decisions(raw_query, query).items()
            }
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
            strategy_context = self._build_strategy_context(query, sorted_transcript)
            trace.stage_latencies["intelligence_ms"] = (time.monotonic() - t) * 1000

            t = time.monotonic()
            try:
                candidates = self.retriever.retrieve(
                    query,
                    chunk_index,
                    segment_index,
                    bm25_index,
                    strategy_context=strategy_context,
                )
            except StrategyExecutionError:
                self._copy_retriever_trace_events(trace)
                raise
            self._copy_retriever_trace_events(trace)
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
                raise RetrievalLowConfidenceError(
                    "Retrieval returned no valid candidates. "
                    f"Query: '{raw_query}'. Decomposed: {query}. "
                    "Check retrieval trace for diagnostics."
                )
            trace.final_result = candidates[0].to_dict()
            return RetrievalResult(top_candidate=candidates[0], all_candidates=candidates, trace=trace)
        finally:
            trace.total_latency_ms = (time.monotonic() - t0) * 1000
            add_trace(trace)

    def _build_strategy_context(
        self,
        query: DecomposedQuery,
        transcript: list[TranscriptChunk],
    ) -> StrategyRetrievalContext | None:
        modes = self._strategy_modes(query)
        if not modes:
            return None

        try:
            from python.intelligence.extraction_pipeline import extract_intelligence
            from python.retrieval.vector_store import VectorStore
            from python.retrieval.video_index import VideoIndex

            segments = [
                {
                    "id": chunk.id,
                    "start": float(chunk.start_time),
                    "end": float(chunk.end_time),
                    "text": chunk.text,
                    "speaker": chunk.speaker,
                }
                for chunk in transcript
            ]
            fingerprint = hashlib.sha1(
                " ".join(f"{s['start']:.2f}:{s['end']:.2f}:{s['text']}" for s in segments).encode("utf-8")
            ).hexdigest()[:12]
            video_id = f"production_{fingerprint}"
            artifacts = self._run_async_blocking(
                extract_intelligence(
                    segments,
                    video_id=video_id,
                    use_ollama_events=False,
                    skip_topic_label=True,
                )
            )
            video_index = VideoIndex(artifacts, video_id=video_id)
            try:
                video_index.hybrid.vector_store = VectorStore(use_chroma=False)
                video_index.index()
            except Exception as exc:
                self._raise_strategy_context_error(query.original, "strategy_side_index", exc)

            return StrategyRetrievalContext(
                parsed_query=self._build_parsed_strategy_query(query, modes),
                video_index=video_index,
                use_emotion=bool({"emotion", "humor", "applause"} & set(modes)),
                use_action=bool({"action", "money_transfer", "applause"} & set(modes)),
                modes=modes,
            )
        except StrategyExecutionError:
            raise
        except Exception as exc:
            self._raise_strategy_context_error(query.original, "strategy_context", exc)

    def _strategy_modes(self, query: DecomposedQuery) -> list[str]:
        decisions = strategy_routing_decisions(query.original, query)
        concepts = {c.lower() for c in query.semantic_concepts}
        event_types = set(query.event_types)
        modes: list[str] = []

        if decisions["emotion"].invoked:
            modes.append("emotion")
        if "joke/humor" in concepts:
            modes.append("humor")
        if decisions["action"].invoked:
            modes.append("action")
        if decisions["action"].invoked and bool(query.monetary_refs):
            modes.append("money_transfer")
        if "audience_reaction" in event_types:
            modes.append("applause")
        return list(dict.fromkeys(modes))

    def _build_parsed_strategy_query(self, query: DecomposedQuery, modes: list[str]):
        from python.intelligence.query_parser import ParsedQuery

        mode_set = set(modes)
        actions: list[str] = []
        if "humor" in mode_set:
            actions.extend(["laugh"])
        if "emotion" in mode_set:
            actions.extend(["cry", "laugh", "smile"])
        if "action" in mode_set or "money_transfer" in mode_set:
            actions.extend(["give", "hand", "pay", "transfer", "receive", "present", "accept", "take"])
        if "applause" in mode_set:
            actions.extend(["applause", "applaud", "clap", "cheer"])
        for action in query.actions:
            first = action.split()[0].lower()
            if first:
                actions.append(first)
        for action in query.event_verbs:
            first = action.split()[0].lower()
            if first:
                actions.append(first)

        emotions: list[str] = []
        if "humor" in mode_set:
            emotions.extend(["joy", "laughter", "humor"])
        if "emotion" in mode_set:
            emotions.extend(["emotional", "sadness", "joy"])
        if "applause" in mode_set:
            emotions.append("audience_reaction")
        emotions.extend(signal.split(":", 1)[-1] for signal in query.affect_signals)

        monetary = list(query.monetary_refs)
        if "money_transfer" in mode_set and not monetary:
            monetary.append("money")

        objects: list[str] = []
        if "money_transfer" in mode_set:
            objects.append("money")
        if "applause" in mode_set:
            objects.append("applause")
        if "humor" in mode_set:
            objects.append("laughter")

        subqueries = [query.original]
        subqueries.extend(query.search_terms[:6])
        subqueries.extend(query.paraphrases[:3])

        return ParsedQuery(
            original_query=query.original,
            query_type="entity_action" if {"action", "money_transfer"} & mode_set else "emotional",
            entities=query.entities,
            actions=list(dict.fromkeys(actions)),
            emotions=list(dict.fromkeys(emotions)),
            monetary_amounts=list(dict.fromkeys(monetary)),
            objects=list(dict.fromkeys(objects)),
            decomposed_subqueries=list(dict.fromkeys([s for s in subqueries if s.strip()]))[:8],
            retrieval_strategy="entity_focused" if {"action", "money_transfer"} & mode_set else "emotion_focused",
            confidence=0.75,
        )

    def _contains_any(self, text: str, terms: set[str]) -> bool:
        return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)

    def _copy_retriever_trace_events(self, trace: RetrievalTrace) -> None:
        trace.opener_suppressions.extend(self.retriever.trace_events.get("opener_suppressions", []))
        trace.hybrid_candidates.extend(self.retriever.trace_events.get("hybrid_candidates", []))
        trace.emotional_strategy_candidates.extend(
            self.retriever.trace_events.get("emotional_strategy_candidates", [])
        )
        trace.entity_action_strategy_candidates.extend(
            self.retriever.trace_events.get("entity_action_strategy_candidates", [])
        )
        trace.event_index_candidates.extend(self.retriever.trace_events.get("event_index_candidates", []))
        trace.merged_pool.extend(self.retriever.trace_events.get("merged_pool", []))
        trace.strategy_errors.extend(self.retriever.trace_events.get("strategy_errors", []))

    def _raise_strategy_context_error(self, query: str, strategy_name: str, exc: Exception) -> None:
        logger.exception(
            "strategy_execution_failed",
            extra={
                "query": query,
                "strategy_name": strategy_name,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        )
        raise StrategyExecutionError(query, strategy_name, exc) from exc

    def _run_async_blocking(self, awaitable):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        if not loop.is_running():
            return loop.run_until_complete(awaitable)
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(awaitable)).result()
