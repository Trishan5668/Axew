"""
Multi-stage semantic retrieval pipeline with intent decomposition,
hybrid BM25+embedding retrieval, entity grounding, LLM reranking,
confidence gating, and temporal refinement.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from python.models.transcript import TranscriptChunk, WordTimestamp
from python.cache.embedding_cache import EmbeddingCache, BM25IndexCache

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.45
OLLAMA_URL = "http://localhost:11434"


class SemanticParseError(Exception):
    """Intent decomposition failed — LLM returned non-JSON."""

    def __init__(self, message: str, raw_response: str = ""):
        self.message = message
        self.raw_response = raw_response
        super().__init__(message)


class LowConfidenceError(Exception):
    """No transcript segment found with sufficient confidence."""

    def __init__(
        self,
        message: str,
        best_score: float,
        best_chunk: "ScoredChunk",
        threshold: float,
        debug_candidates: List["ScoredChunk"],
    ):
        self.message = message
        self.best_score = best_score
        self.best_chunk = best_chunk
        self.threshold = threshold
        self.debug_candidates = debug_candidates
        super().__init__(message)


@dataclass
class IntentGraph:
    action_type: str
    subject: Optional[str]
    verb: str
    object: Optional[str]
    recipient: Optional[str]
    monetary_amount: Optional[str]
    named_entities: List[str]
    keywords: List[str]
    temporal_hints: List[str]
    event_description: str
    raw_prompt: str


@dataclass
class ScoredChunk:
    chunk: TranscriptChunk
    bm25_score: float = 0.0
    embedding_score: float = 0.0
    rerank_score: float = 0.0
    entity_match_score: float = 0.0
    final_score: float = 0.0
    explanation: str = ""


@dataclass
class TimeRange:
    start: float
    end: float
    confidence: float
    method: str  # "word_aligned" | "chunk_boundary" | "expanded"
    word_start_index: int = -1
    word_end_index: int = -1


@dataclass
class RetrievalDebugPayload:
    intent_graph: IntentGraph
    top_k_candidates: List[ScoredChunk]
    reranker_responses: List[dict]
    chosen_chunk: ScoredChunk
    time_range: TimeRange
    confidence_gated: bool
    total_pipeline_ms: float

    def to_dict(self) -> Dict[str, Any]:
        def chunk_to_dict(sc: ScoredChunk) -> dict:
            return {
                "chunk_id": sc.chunk.id,
                "text": sc.chunk.text[:200],
                "start_time": sc.chunk.start_time,
                "end_time": sc.chunk.end_time,
                "bm25_score": round(sc.bm25_score, 4),
                "embedding_score": round(sc.embedding_score, 4),
                "rerank_score": round(sc.rerank_score, 4),
                "entity_match_score": round(sc.entity_match_score, 4),
                "final_score": round(sc.final_score, 4),
                "explanation": sc.explanation,
            }

        return {
            "intent_graph": {
                "action_type": self.intent_graph.action_type,
                "subject": self.intent_graph.subject,
                "verb": self.intent_graph.verb,
                "object": self.intent_graph.object,
                "recipient": self.intent_graph.recipient,
                "monetary_amount": self.intent_graph.monetary_amount,
                "named_entities": self.intent_graph.named_entities,
                "keywords": self.intent_graph.keywords,
                "temporal_hints": self.intent_graph.temporal_hints,
                "event_description": self.intent_graph.event_description,
                "raw_prompt": self.intent_graph.raw_prompt,
            },
            "top_k_candidates": [chunk_to_dict(c) for c in self.top_k_candidates[:10]],
            "reranker_responses": self.reranker_responses,
            "chosen_chunk": chunk_to_dict(self.chosen_chunk),
            "time_range": {
                "start": self.time_range.start,
                "end": self.time_range.end,
                "confidence": self.time_range.confidence,
                "method": self.time_range.method,
            },
            "confidence_gated": self.confidence_gated,
            "total_pipeline_ms": round(self.total_pipeline_ms, 1),
        }


# Request-scoped storage for debug payload
_last_debug_payload: Optional[RetrievalDebugPayload] = None


def get_last_debug_payload() -> Optional[RetrievalDebugPayload]:
    return _last_debug_payload


def _set_last_debug_payload(payload: RetrievalDebugPayload) -> None:
    global _last_debug_payload
    _last_debug_payload = payload


class SemanticRetrievalPipeline:
    """Production-grade multi-stage retrieval pipeline."""

    def __init__(self) -> None:
        self._embed_model = None
        self._embedding_cache = EmbeddingCache()
        self._bm25_cache = BM25IndexCache()

    def _get_embed_model(self):
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer
            self._embed_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded embedding model all-MiniLM-L6-v2")
        return self._embed_model

    # =========================================================================
    # STAGE 0: INTENT + ENTITY + ACTION DECOMPOSITION
    # =========================================================================

    async def decompose_intent(self, prompt: str) -> IntentGraph:
        import httpx

        system_prompt = (
            "You are a semantic event parser. Extract structured information from "
            "editing prompts. Return ONLY valid JSON, no explanation."
        )

        user_prompt = f"""Editing prompt: "{prompt}"

Extract and return JSON with exactly these fields:
{{
    "action_type": "keep" | "remove" | "cut" | "extract",
    "subject": "<who performs the action, or null>",
    "verb": "<the action being performed>",
    "object": "<what is transferred/acted upon, or null>",
    "recipient": "<who receives the action, or null>",
    "monetary_amount": "<currency amount as string, or null>",
    "named_entities": ["<list of all proper nouns>"],
    "keywords": ["<list of high-signal search terms>"],
    "temporal_hints": ["<any time references like 'beginning', 'end', etc>"],
    "event_description": "<one sentence plain English description of the event>"
}}"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": "llama3.2:3b",
                        "prompt": f"[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{user_prompt} [/INST]",
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                raw_response = data.get("response", "")
        except Exception as e:
            logger.error("Ollama intent decomposition request failed: %s", e)
            raise SemanticParseError(
                f"Intent decomposition failed — Ollama unreachable: {e}",
                raw_response="",
            )

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            cleaned = re.sub(r"```(?:json)?|```", "", raw_response).strip()
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error(
                    "Intent decomposition returned non-JSON: %s", raw_response[:500]
                )
                raise SemanticParseError(
                    "Intent decomposition failed — LLM returned non-JSON",
                    raw_response=raw_response[:1000],
                )

        return IntentGraph(
            action_type=parsed.get("action_type", "keep"),
            subject=parsed.get("subject"),
            verb=parsed.get("verb", ""),
            object=parsed.get("object"),
            recipient=parsed.get("recipient"),
            monetary_amount=parsed.get("monetary_amount"),
            named_entities=parsed.get("named_entities", []) or [],
            keywords=parsed.get("keywords", []) or [],
            temporal_hints=parsed.get("temporal_hints", []) or [],
            event_description=parsed.get("event_description", prompt),
            raw_prompt=prompt,
        )

    # =========================================================================
    # STAGE 1: MULTI-QUERY KEYWORD RETRIEVAL (BM25)
    # =========================================================================

    def keyword_retrieve(
        self,
        transcript_chunks: List[TranscriptChunk],
        intent: IntentGraph,
        top_k: int = 20,
    ) -> List[ScoredChunk]:
        from rank_bm25 import BM25Okapi

        corpus = [chunk.text.lower().split() for chunk in transcript_chunks]
        bm25 = BM25Okapi(corpus)

        queries = [
            intent.event_description,
            " ".join(intent.named_entities),
            " ".join(intent.keywords),
            f"{intent.subject or ''} {intent.verb} {intent.object or ''}",
            f"{intent.monetary_amount or ''} {intent.recipient or ''}",
        ]
        queries = [q.strip() for q in queries if q.strip()]

        chunk_max_scores: Dict[int, float] = {}

        for query in queries:
            tokens = query.lower().split()
            if not tokens:
                continue
            scores = bm25.get_scores(tokens)
            for idx, score in enumerate(scores):
                if score > 0:
                    chunk_max_scores[idx] = max(chunk_max_scores.get(idx, 0), score)

        sorted_indices = sorted(chunk_max_scores, key=chunk_max_scores.get, reverse=True)[:top_k]

        results = []
        for idx in sorted_indices:
            results.append(
                ScoredChunk(
                    chunk=transcript_chunks[idx],
                    bm25_score=chunk_max_scores[idx],
                )
            )

        return results

    # =========================================================================
    # STAGE 2: EMBEDDING RETRIEVAL
    # =========================================================================

    async def embedding_retrieve(
        self,
        transcript_chunks: List[TranscriptChunk],
        intent: IntentGraph,
        top_k: int = 20,
    ) -> List[ScoredChunk]:
        model = self._get_embed_model()

        query_texts = [
            intent.event_description,
            " ".join(intent.named_entities + intent.keywords),
        ]
        query_texts = [q.strip() for q in query_texts if q.strip()]

        query_embeddings = []
        for qt in query_texts:
            cached = self._embedding_cache.get(f"__query__:{qt}")
            if cached is not None:
                query_embeddings.append(cached)
            else:
                emb = model.encode(qt, normalize_embeddings=True)
                query_embeddings.append(emb)

        chunk_embeddings = []
        for chunk in transcript_chunks:
            cached = self._embedding_cache.get(chunk.text)
            if cached is not None:
                chunk_embeddings.append(cached)
            else:
                emb = model.encode(chunk.text, normalize_embeddings=True)
                self._embedding_cache.set(chunk.text, emb)
                chunk_embeddings.append(emb)

        chunk_matrix = np.array(chunk_embeddings)
        chunk_norms = np.linalg.norm(chunk_matrix, axis=1, keepdims=True)
        chunk_norms = np.where(chunk_norms == 0, 1, chunk_norms)

        chunk_max_scores: Dict[int, float] = {}

        for q_emb in query_embeddings:
            q_vec = np.array(q_emb)
            q_norm = np.linalg.norm(q_vec)
            if q_norm == 0:
                continue
            scores = (chunk_matrix @ q_vec) / (chunk_norms.flatten() * q_norm)
            for idx, score in enumerate(scores):
                chunk_max_scores[idx] = max(chunk_max_scores.get(idx, 0.0), float(score))

        sorted_indices = sorted(chunk_max_scores, key=chunk_max_scores.get, reverse=True)[:top_k]

        results = []
        for idx in sorted_indices:
            results.append(
                ScoredChunk(
                    chunk=transcript_chunks[idx],
                    embedding_score=chunk_max_scores[idx],
                )
            )

        return results

    # =========================================================================
    # STAGE 3: ENTITY MATCH SCORING
    # =========================================================================

    def entity_match_score(self, chunk: TranscriptChunk, intent: IntentGraph) -> float:
        score = 0.0
        max_possible = 0.0
        text_lower = chunk.text.lower()

        for entity in intent.named_entities:
            max_possible += 1.0
            if entity.lower() in text_lower:
                score += 1.0
            else:
                try:
                    from rapidfuzz import fuzz
                    ratio = fuzz.partial_ratio(entity.lower(), text_lower)
                    if ratio > 80:
                        score += 0.5
                except ImportError:
                    pass

        if intent.monetary_amount:
            max_possible += 2.0
            amount_str = re.sub(r"[^\d.]", "", intent.monetary_amount)
            currency_pattern = r"\d+[\s]*(rupees?|Rs\.?|INR|\$|dollars?|€|euros?)"
            found_currencies = re.findall(currency_pattern, chunk.text, re.I)

            if amount_str and amount_str in chunk.text:
                score += 2.0
            elif found_currencies:
                numbers_in_text = re.findall(r"\d+", chunk.text)
                if amount_str and amount_str in numbers_in_text:
                    score += 2.0
                elif any(
                    abs(float(n) - float(amount_str)) < 1
                    for n in numbers_in_text
                    if n.isdigit() and amount_str
                ):
                    score += 1.5

        if intent.subject:
            max_possible += 1.5
            if intent.subject.lower() in text_lower:
                score += 1.5
            else:
                try:
                    from rapidfuzz import fuzz
                    if fuzz.partial_ratio(intent.subject.lower(), text_lower) > 80:
                        score += 0.75
                except ImportError:
                    pass

        if intent.recipient:
            max_possible += 1.5
            if intent.recipient.lower() in text_lower:
                score += 1.5
            else:
                try:
                    from rapidfuzz import fuzz
                    if fuzz.partial_ratio(intent.recipient.lower(), text_lower) > 80:
                        score += 0.75
                except ImportError:
                    pass

        if max_possible == 0:
            return 0.0
        return min(1.0, score / max_possible)

    # =========================================================================
    # STAGE 4: FUSION + RERANKING
    # =========================================================================

    async def fuse_and_rerank(
        self,
        bm25_chunks: List[ScoredChunk],
        embedding_chunks: List[ScoredChunk],
        intent: IntentGraph,
        all_chunks: List[TranscriptChunk],
    ) -> Tuple[List[ScoredChunk], List[dict]]:
        chunk_map: Dict[str, ScoredChunk] = {}

        for sc in bm25_chunks:
            chunk_map[sc.chunk.id] = ScoredChunk(
                chunk=sc.chunk,
                bm25_score=sc.bm25_score,
            )

        for sc in embedding_chunks:
            if sc.chunk.id in chunk_map:
                chunk_map[sc.chunk.id].embedding_score = sc.embedding_score
            else:
                chunk_map[sc.chunk.id] = ScoredChunk(
                    chunk=sc.chunk,
                    embedding_score=sc.embedding_score,
                )

        max_bm25 = max((sc.bm25_score for sc in chunk_map.values()), default=1.0) or 1.0
        max_embed = max((sc.embedding_score for sc in chunk_map.values()), default=1.0) or 1.0

        for sc in chunk_map.values():
            sc.entity_match_score = self.entity_match_score(sc.chunk, intent)
            norm_bm25 = sc.bm25_score / max_bm25
            norm_embed = sc.embedding_score / max_embed
            sc.final_score = (
                0.25 * norm_bm25 +
                0.35 * norm_embed +
                0.40 * sc.entity_match_score
            )

        candidates = sorted(chunk_map.values(), key=lambda x: x.final_score, reverse=True)

        reranker_responses = []
        top_5 = candidates[:5]

        import httpx

        for sc in top_5:
            rerank_prompt = f"""Editing request: "{intent.raw_prompt}"

Transcript segment (timestamps {sc.chunk.start_time:.2f}s - {sc.chunk.end_time:.2f}s):
"{sc.chunk.text}"

Does this transcript segment contain the described event?
Answer with JSON: {{"contains_event": true/false, "confidence": 0.0-1.0, "reasoning": "one sentence"}}"""

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={
                            "model": "llama3.2:3b",
                            "prompt": rerank_prompt,
                            "stream": False,
                            "format": "json",
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json().get("response", "")

                try:
                    rerank_result = json.loads(raw)
                except json.JSONDecodeError:
                    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
                    try:
                        rerank_result = json.loads(cleaned)
                    except json.JSONDecodeError:
                        rerank_result = {"contains_event": False, "confidence": 0.0, "reasoning": "parse_error"}

                contains_event = rerank_result.get("contains_event", False)
                confidence = float(rerank_result.get("confidence", 0.0))

                if contains_event:
                    sc.final_score *= (1.0 + confidence)
                else:
                    sc.final_score *= 0.1

                sc.rerank_score = confidence if contains_event else -confidence
                sc.explanation = rerank_result.get("reasoning", "")

                reranker_responses.append({
                    "chunk_id": sc.chunk.id,
                    "start_time": sc.chunk.start_time,
                    "end_time": sc.chunk.end_time,
                    "contains_event": contains_event,
                    "confidence": confidence,
                    "reasoning": rerank_result.get("reasoning", ""),
                })

            except Exception as e:
                logger.warning("Reranker call failed for chunk %s: %s", sc.chunk.id, e)
                reranker_responses.append({
                    "chunk_id": sc.chunk.id,
                    "error": str(e),
                })

        candidates = sorted(chunk_map.values(), key=lambda x: x.final_score, reverse=True)
        return candidates, reranker_responses

    # =========================================================================
    # STAGE 5: CONFIDENCE GATING
    # =========================================================================

    def confidence_gate(
        self, candidates: List[ScoredChunk]
    ) -> ScoredChunk:
        if not candidates:
            raise LowConfidenceError(
                message="No candidates found",
                best_score=0.0,
                best_chunk=ScoredChunk(chunk=TranscriptChunk(id="none", text="", start_time=0, end_time=0)),
                threshold=CONFIDENCE_THRESHOLD,
                debug_candidates=[],
            )

        best = candidates[0]
        if best.final_score < CONFIDENCE_THRESHOLD:
            raise LowConfidenceError(
                message="No transcript segment found with sufficient confidence",
                best_score=best.final_score,
                best_chunk=best,
                threshold=CONFIDENCE_THRESHOLD,
                debug_candidates=candidates[:10],
            )

        return best

    # =========================================================================
    # STAGE 6: TEMPORAL REFINEMENT
    # =========================================================================

    def refine_timestamps(
        self,
        best_chunk: ScoredChunk,
        all_chunks: List[TranscriptChunk],
        intent: IntentGraph,
    ) -> TimeRange:
        chunk = best_chunk.chunk

        if not chunk.words:
            chunk.interpolate_word_timestamps()

        if not chunk.words:
            duration = chunk.end_time - chunk.start_time
            if duration < 3.0:
                expansion = (3.0 - duration) / 2
                return TimeRange(
                    start=max(0, chunk.start_time - expansion),
                    end=chunk.end_time + expansion,
                    confidence=best_chunk.final_score,
                    method="chunk_boundary",
                )
            return TimeRange(
                start=chunk.start_time,
                end=chunk.end_time,
                confidence=best_chunk.final_score,
                method="chunk_boundary",
            )

        search_terms = set()
        for entity in intent.named_entities:
            for word in entity.lower().split():
                search_terms.add(word)
        if intent.verb:
            search_terms.add(intent.verb.lower())
        if intent.monetary_amount:
            digits = re.sub(r"[^\d]", "", intent.monetary_amount)
            if digits:
                search_terms.add(digits)
        if intent.object:
            for word in intent.object.lower().split():
                search_terms.add(word)

        word_start_idx = 0
        word_end_idx = len(chunk.words) - 1

        for i, w in enumerate(chunk.words):
            word_clean = re.sub(r"[^\w]", "", w.word.lower())
            if word_clean in search_terms:
                word_start_idx = i
                break

        for i in range(len(chunk.words) - 1, -1, -1):
            word_clean = re.sub(r"[^\w]", "", chunk.words[i].word.lower())
            if word_clean in search_terms:
                word_end_idx = i
                break

        # Walk backward to sentence boundary
        for i in range(word_start_idx - 1, -1, -1):
            if any(p in chunk.words[i].word for p in [".", "?", "!"]):
                word_start_idx = i + 1
                break
            if i > 0 and (chunk.words[i].start - chunk.words[i - 1].end) > 0.5:
                word_start_idx = i
                break
        else:
            word_start_idx = 0

        # Walk forward to sentence boundary
        for i in range(word_end_idx + 1, len(chunk.words)):
            if any(p in chunk.words[i].word for p in [".", "?", "!"]):
                word_end_idx = i
                break
            if i < len(chunk.words) - 1 and (chunk.words[i + 1].start - chunk.words[i].end) > 0.5:
                word_end_idx = i
                break
        else:
            word_end_idx = len(chunk.words) - 1

        start = chunk.words[word_start_idx].start
        end = chunk.words[word_end_idx].end
        method = "word_aligned"

        # Context expansion: check adjacent chunks
        chunk_idx = chunk.chunk_index
        if chunk_idx > 0:
            prev_chunk = next((c for c in all_chunks if c.chunk_index == chunk_idx - 1), None)
            if prev_chunk and prev_chunk.text.rstrip()[-1:] not in ".?!":
                start = min(start, prev_chunk.start_time)
                method = "expanded"

        # Minimum duration enforcement
        duration = end - start
        if duration < 3.0:
            expansion = (3.0 - duration) / 2
            start = max(0, start - expansion)
            end = end + expansion

        return TimeRange(
            start=round(start, 3),
            end=round(end, 3),
            confidence=best_chunk.final_score,
            method=method,
            word_start_index=word_start_idx,
            word_end_index=word_end_idx,
        )

    # =========================================================================
    # MAIN PIPELINE ORCHESTRATOR
    # =========================================================================

    async def run(
        self, prompt: str, transcript_chunks: List[TranscriptChunk]
    ) -> Tuple[TimeRange, RetrievalDebugPayload]:
        t0 = time.time()

        # Stage 0: Intent decomposition
        intent = await self.decompose_intent(prompt)
        logger.info(
            "[Pipeline] Intent: entities=%s, verb=%s, monetary=%s",
            intent.named_entities, intent.verb, intent.monetary_amount,
        )

        # Stage 1: BM25 keyword retrieval
        bm25_results = self.keyword_retrieve(transcript_chunks, intent, top_k=20)
        logger.info("[Pipeline] BM25 returned %d candidates", len(bm25_results))

        # Stage 2: Embedding retrieval
        embedding_results = await self.embedding_retrieve(transcript_chunks, intent, top_k=20)
        logger.info("[Pipeline] Embedding returned %d candidates", len(embedding_results))

        # Stage 3 + 4: Entity scoring + Fusion + Reranking
        candidates, reranker_responses = await self.fuse_and_rerank(
            bm25_results, embedding_results, intent, transcript_chunks
        )
        logger.info(
            "[Pipeline] After fusion+rerank: top score=%.4f",
            candidates[0].final_score if candidates else 0.0,
        )

        # Stage 5: Confidence gating
        confidence_gated = False
        try:
            best_chunk = self.confidence_gate(candidates)
        except LowConfidenceError as e:
            confidence_gated = True
            elapsed = (time.time() - t0) * 1000
            debug_payload = RetrievalDebugPayload(
                intent_graph=intent,
                top_k_candidates=e.debug_candidates,
                reranker_responses=reranker_responses,
                chosen_chunk=e.best_chunk,
                time_range=TimeRange(start=0, end=0, confidence=e.best_score, method="none"),
                confidence_gated=True,
                total_pipeline_ms=elapsed,
            )
            _set_last_debug_payload(debug_payload)
            raise

        # Stage 6: Temporal refinement
        time_range = self.refine_timestamps(best_chunk, transcript_chunks, intent)

        elapsed = (time.time() - t0) * 1000
        debug_payload = RetrievalDebugPayload(
            intent_graph=intent,
            top_k_candidates=candidates[:10],
            reranker_responses=reranker_responses,
            chosen_chunk=best_chunk,
            time_range=time_range,
            confidence_gated=False,
            total_pipeline_ms=elapsed,
        )
        _set_last_debug_payload(debug_payload)

        logger.info(
            "[Pipeline] Complete in %.1fms: %.2fs-%.2fs (confidence=%.3f, method=%s)",
            elapsed, time_range.start, time_range.end, time_range.confidence, time_range.method,
        )

        return time_range, debug_payload
