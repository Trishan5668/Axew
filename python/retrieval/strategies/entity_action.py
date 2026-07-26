from __future__ import annotations

import re
from typing import List

from python.intelligence.ner import normalize_entity
from python.intelligence.query_parser import ParsedQuery
from python.retrieval.chunker import Chunk
from python.retrieval.hybrid_retriever import RetrievalResult
from python.retrieval.strategies.base import RetrievalStrategy
from python.retrieval.video_index import VideoIndex


class EntityActionStrategy(RetrievalStrategy):
    MIN_FALLBACK_CANDIDATES = 3

    async def retrieve_candidates(
        self,
        parsed: ParsedQuery,
        index: VideoIndex,
        top_k: int = 50,
    ) -> List[RetrievalResult]:
        artifacts = index.artifacts
        hybrid_results: List[RetrievalResult] = []

        for subq in parsed.decomposed_subqueries:
            hybrid_results.extend(
                await index.hybrid.search(subq, top_k=20, chunk_types=["sentence", "entity_context"])
            )

        # Entity + event intersection windows
        entity_mentions = []
        for ent in parsed.entities:
            entity_mentions.extend(artifacts.entity_index.lookup_fuzzy(ent))

        action_events = artifacts.event_index.lookup_verbs(parsed.actions)
        if not action_events and parsed.actions:
            action_events = artifacts.event_index.lookup("transaction")

        intersection_chunks: List[Chunk] = []
        for em in entity_mentions:
            for ev in action_events:
                if abs(em.start_sec - ev.start_sec) < 30.0:
                    score = em.confidence * ev.confidence
                    if parsed.monetary_amounts:
                        for cid, chunk in index.chunks_by_id.items():
                            if chunk.chunk_type == "entity_context":
                                continue
                            if self._has_monetary(chunk, parsed.monetary_amounts):
                                if parsed.actions and not self._has_action(chunk, parsed.actions):
                                    continue
                                score *= 5.0
                    intersection_chunks.append(
                        Chunk(
                            chunk_id=f"int_{em.start_sec:.1f}_{ev.start_sec:.1f}",
                            video_id=index.video_id,
                            text=em.text,
                            start_sec=min(em.start_sec, ev.start_sec) - 2,
                            end_sec=max(em.end_sec, ev.end_sec) + 2,
                            chunk_type="sentence",
                        )
                    )

        int_results = [
            RetrievalResult(
                chunk_id=c.chunk_id,
                chunk=c,
                text=c.text,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                score_fused=1.0,
            )
            for c in intersection_chunks
        ]

        merged = int_results + hybrid_results
        if len(merged) < self.MIN_FALLBACK_CANDIDATES:
            merged.extend(self._event_fallback(parsed, index))
        seen: set[str] = set()
        out: List[RetrievalResult] = []
        for r in sorted(merged, key=lambda x: x.score_fused, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                out.append(r)
        return out[:top_k]

    def _event_fallback(self, parsed: ParsedQuery, index: VideoIndex) -> List[RetrievalResult]:
        event_index = index.artifacts.event_index
        mentions = []
        if parsed.actions:
            mentions.extend(event_index.lookup_verbs(parsed.actions))
        for event_type in event_index.action_event_types():
            mentions.extend(event_index.lookup(event_type))

        seen: set[tuple[str, str]] = set()
        results: List[RetrievalResult] = []
        for mention in sorted(mentions, key=lambda m: m.confidence, reverse=True):
            key = (mention.chunk_id, mention.verb)
            if key in seen:
                continue
            seen.add(key)
            chunk = index.chunks_by_id.get(mention.chunk_id)
            if not chunk:
                continue
            results.append(
                RetrievalResult(
                    chunk_id=mention.chunk_id,
                    chunk=chunk,
                    text=chunk.text,
                    start_sec=mention.start_sec,
                    end_sec=mention.end_sec,
                    score_fused=max(0.55, float(mention.confidence)),
                    events=[mention.verb, mention.event_type],
                )
            )
        return results

    def _has_monetary(self, chunk: Chunk, amounts: List[str]) -> bool:
        t = chunk.text.lower()
        for m in amounts:
            if m.lower() in t:
                return True
            num = re.search(r"\d+", m)
            if num and num.group() in t:
                return True
        return False

    def _has_action(self, chunk: Chunk, actions: List[str]) -> bool:
        t = chunk.text.lower()
        for a in actions:
            stem = a.rstrip("e")
            if re.search(rf"\b{re.escape(a)}|{re.escape(stem)}ing|{re.escape(stem)}es\b", t):
                return True
        return False
