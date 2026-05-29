"""
Phase 2 retriever — entity/event-aware retrieval over enriched chunks.

Combines semantic similarity with entity match, event match, and monetary boosts.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from python.evaluation.baseline_retriever import BaselineRetriever
from python.evaluation.benchmark import CandidateWindow, RetrievalOutput
from python.intelligence.extraction_pipeline import IntelligenceArtifacts, extract_intelligence
from python.intelligence.ner import normalize_entity

_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


class Phase2Retriever:
    """Entity and event-aware retrieval with semantic fallback."""

    def __init__(
        self,
        segments: List[Dict[str, Any]],
        top_k: int = 8,
        min_score: float = 0.15,
        entity_boost: float = 3.0,
        event_boost: float = 2.0,
        monetary_boost: float = 5.0,
    ) -> None:
        self.segments = segments
        self.top_k = top_k
        self.min_score = min_score
        self.entity_boost = entity_boost
        self.event_boost = event_boost
        self.monetary_boost = monetary_boost
        self._artifacts: Optional[IntelligenceArtifacts] = None
        self._semantic: Optional[BaselineRetriever] = None
        self._ready = False

    def _ensure_ready(self) -> None:
        if self._ready:
            return

        self._artifacts = asyncio.run(
            extract_intelligence(self.segments, skip_topic_label=True)
        )
        chunks = self._artifacts.all_retrieval_chunks()
        seg_like = [
            {
                "id": c.chunk_id,
                "start": c.start_sec,
                "end": c.end_sec,
                "text": c.text,
                "speaker": c.speaker_id,
            }
            for c in chunks
        ]
        self._semantic = BaselineRetriever(seg_like, top_k=50, min_score=0.1)
        self._ready = True

    def _parse_query(self, query: str) -> Dict[str, Any]:
        lower = query.lower()
        entities: List[str] = []
        actions: List[str] = []
        monetary: List[str] = []

        for m in re.finditer(r"\b(\d+\s*(?:rupees?|crore|dollars?))\b", query, re.I):
            monetary.append(m.group(1).lower())

        for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query):
            entities.append(m.group(1))

        name_patterns = [
            (r"vijay\s+mallya", "Vijay Mallya"),
            (r"kingfisher(?:\s+airlines)?", "Kingfisher Airlines"),
            (r"\bsbi\b", "SBI"),
            (r"\bpnb\b", "PNB"),
            (r"sanjeev\s+kapoor", "Sanjeev Kapoor"),
            (r"air\s+deccan", "Air Deccan"),
            (r"vittal\s+mallya", "Vittal Mallya"),
            (r"rajesh\s+kumar", "Rajesh Kumar"),
            (r"force\s+india", "Force India"),
        ]
        for pat, name in name_patterns:
            if re.search(pat, lower):
                entities.append(name)

        action_verbs = [
            "give", "hand", "pay", "receive", "transfer", "present",
            "laugh", "cry", "point", "stand", "applaud", "cheer", "deny",
        ]
        actions = [v for v in action_verbs if v in lower]

        return {
            "entities": list(dict.fromkeys(entities)),
            "actions": actions,
            "monetary": monetary,
            "is_emotional": any(w in lower for w in ("emotional", "cry", "tear", "fear", "laugh", "shocked")),
            "is_audience": any(w in lower for w in ("audience", "applause", "cheering", "booing", "laughter")),
        }

    def _entity_match_score(
        self,
        chunk,
        query_entities: List[str],
        artifacts: IntelligenceArtifacts,
    ) -> float:
        if not query_entities:
            return 0.0

        chunk_norm = {normalize_entity(e) for e in chunk.entities}
        chunk_text_norm = normalize_entity(chunk.text)

        matched = 0
        for qe in query_entities:
            qn = normalize_entity(qe)
            if qn in chunk_norm:
                matched += 1
            elif qn in chunk_text_norm:
                matched += 1
            elif artifacts.entity_index.lookup_fuzzy(qe):
                for m in artifacts.entity_index.lookup_fuzzy(qe):
                    if m.start_sec <= chunk.end_sec and m.end_sec >= chunk.start_sec:
                        matched += 1
                        break

        return matched / max(len(query_entities), 1)

    def _event_match_score(self, chunk, query_actions: List[str], artifacts: IntelligenceArtifacts) -> float:
        if not query_actions:
            return 0.0

        chunk_verbs = {e.lower() for e in chunk.events}
        matched = sum(1 for a in query_actions if a in chunk_verbs or a in chunk.text.lower())
        return matched / max(len(query_actions), 1)

    def _monetary_match_score(self, chunk, monetary: List[str]) -> float:
        if not monetary:
            return 0.0
        text_lower = chunk.text.lower()
        for m in monetary:
            if m in text_lower or m.replace(" ", "") in text_lower.replace(" ", ""):
                return 1.0
            # Match number only
            num = re.search(r"\d+", m)
            if num and num.group() in text_lower:
                return 0.8
        return 0.0

    def _query_action_in_text(self, text_lower: str, actions: List[str]) -> bool:
        if not actions:
            return True
        for action in actions:
            stem = action.rstrip("e")  # give -> giv
            if re.search(rf"\b{re.escape(action)}|{re.escape(stem)}ing|{re.escape(stem)}es\b", text_lower):
                return True
        return False

    def _emotional_score(self, chunk, artifacts: IntelligenceArtifacts) -> float:
        affect = artifacts.affect_index.by_chunk.get(chunk.chunk_id)
        if not affect:
            return 0.0
        return max(affect.sentiment.intensity, affect.emotion.dominant_score)

    def _score_chunks(self, query: str) -> List[Tuple[Any, float]]:
        assert self._artifacts is not None
        assert self._semantic is not None

        parsed = self._parse_query(query)
        chunks = self._artifacts.all_retrieval_chunks()

        model = _get_embed_model()
        query_vec = model.encode(query, normalize_embeddings=True)
        texts = [c.text for c in chunks]
        vecs = model.encode(texts, normalize_embeddings=True)

        scored: List[Tuple[Any, float]] = []
        for chunk, vec in zip(chunks, vecs):
            sem = float(np.dot(query_vec, vec))
            ent = self._entity_match_score(chunk, parsed["entities"], self._artifacts)
            evt = self._event_match_score(chunk, parsed["actions"], self._artifacts)
            mon = self._monetary_match_score(chunk, parsed["monetary"])

            combined = sem
            combined += ent * self.entity_boost * 0.1
            combined += evt * self.event_boost * 0.1
            if mon > 0:
                combined += mon * self.monetary_boost * 0.1

            if parsed["is_emotional"]:
                combined += self._emotional_score(chunk, self._artifacts) * 0.3

            if parsed["is_audience"]:
                if any(v in chunk.text.lower() for v in ("applause", "audience", "cheer", "laugh")):
                    combined += 0.4

            scored.append((chunk, combined))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _direct_monetary_match(
        self, parsed: Dict[str, Any]
    ) -> Optional[Tuple[float, float, float]]:
        """Find chunk where monetary amount, entity, and action co-occur in text."""
        if not parsed["monetary"] or not parsed["entities"]:
            return None

        assert self._artifacts is not None
        candidates: List[Tuple[float, float, float]] = []

        for chunk in self._artifacts.all_retrieval_chunks():
            if chunk.chunk_type == "entity_context":
                continue

            text_lower = chunk.text.lower()
            has_money = False
            for m in parsed["monetary"]:
                if m in text_lower:
                    has_money = True
                    break
                num = re.search(r"\d+", m)
                if num and num.group() in text_lower:
                    has_money = True
                    break
            has_entity = any(normalize_entity(e) in text_lower for e in parsed["entities"])
            has_action = self._query_action_in_text(text_lower, parsed["actions"])
            if has_money and has_entity and has_action:
                duration = chunk.end_sec - chunk.start_sec
                # Prefer shorter, more precise windows (higher score = better)
                precision = 1.0 / max(duration, 1.0)
                candidates.append((chunk.start_sec, chunk.end_sec, precision))

        if not candidates:
            return None

        best = max(candidates, key=lambda x: x[2])
        start, end, score = best
        center = (start + end) / 2

        # Expand to the single source segment with best overlap (avoid merging unrelated segments)
        best_seg = None
        best_overlap = 0.0
        for seg in self.segments:
            s, e = float(seg["start"]), float(seg["end"])
            overlap = max(0.0, min(end, e) - max(start, s))
            if overlap > best_overlap or (s <= center <= e and overlap >= best_overlap):
                best_overlap = overlap
                best_seg = seg

        if best_seg:
            start = float(best_seg["start"])
            end = float(best_seg["end"])

        return (start, end, score)

    def _entity_action_windows(
        self, parsed: Dict[str, Any]
    ) -> List[Tuple[float, float, float]]:
        """Find temporal intersections of entity mentions and action events."""
        assert self._artifacts is not None
        windows: List[Tuple[float, float, float]] = []

        entity_mentions = []
        for ent in parsed["entities"]:
            entity_mentions.extend(self._artifacts.entity_index.lookup_fuzzy(ent))

        action_events = self._artifacts.event_index.lookup_verbs(parsed["actions"])
        if not action_events and parsed["actions"]:
            for etype in ("transaction", "emotional", "physical_action", "audience_reaction"):
                action_events.extend(self._artifacts.event_index.lookup(etype))

        chunks = self._artifacts.all_retrieval_chunks()

        for em in entity_mentions:
            for ev in action_events:
                gap = abs(em.start_sec - ev.start_sec)
                if gap < 30.0:
                    win_start = min(em.start_sec, ev.start_sec) - 2.0
                    win_end = max(em.end_sec, ev.end_sec) + 2.0

                    # Include overlapping chunk boundaries
                    for chunk in chunks:
                        if chunk.start_sec <= win_end and chunk.end_sec >= win_start:
                            win_start = min(win_start, chunk.start_sec)
                            win_end = max(win_end, chunk.end_sec)

                    score = em.confidence * ev.confidence / (1.0 + gap)

                    has_monetary = False
                    if parsed["monetary"]:
                        for chunk in chunks:
                            if (
                                chunk.start_sec <= win_end
                                and chunk.end_sec >= win_start
                                and self._monetary_match_score(chunk, parsed["monetary"]) > 0
                            ):
                                # Require action verb in same chunk when query has action
                                chunk_lower = chunk.text.lower()
                                has_action = self._query_action_in_text(chunk_lower, parsed["actions"])
                                if parsed["actions"] and not has_action:
                                    continue
                                has_monetary = True
                                score *= self.monetary_boost
                                win_start = min(win_start, chunk.start_sec)
                                win_end = max(win_end, chunk.end_sec)
                                break
                        if not has_monetary:
                            continue

                    windows.append((max(0.0, win_start), win_end, score))

        return sorted(windows, key=lambda x: x[2], reverse=True)

    def __call__(self, query: str) -> RetrievalOutput:
        self._ensure_ready()
        assert self._artifacts is not None

        parsed = self._parse_query(query)

        # Highest priority: direct text co-occurrence for monetary entity-action queries
        if parsed["monetary"] and parsed["entities"]:
            direct = self._direct_monetary_match(parsed)
            if direct:
                start, end, score = direct
                return RetrievalOutput(
                    start_sec=max(0.0, start - 0.4),
                    end_sec=end + 0.4,
                    confidence=min(score, 1.0),
                    candidates=[CandidateWindow(start_sec=start, end_sec=end, confidence=score)],
                )

        # Entity-action intersection for transaction queries
        if parsed["entities"] and parsed["actions"]:
            windows = self._entity_action_windows(parsed)
            if windows:
                start, end, score = windows[0]
                # Clamp window to reasonable duration (max 90s)
                if end - start > 90.0:
                    end = start + 90.0
                candidates = [CandidateWindow(start_sec=start, end_sec=end, confidence=score)]
                return RetrievalOutput(
                    start_sec=max(0.0, start - 0.4),
                    end_sec=end + 0.4,
                    confidence=min(score, 1.0),
                    candidates=candidates,
                )

        scored = self._score_chunks(query)
        filtered = [(c, s) for c, s in scored if s >= self.min_score]
        top = filtered[: self.top_k]

        candidates = [
            CandidateWindow(start_sec=c.start_sec, end_sec=c.end_sec, confidence=s)
            for c, s in top
        ]

        if top:
            # Merge top matches like baseline
            best_chunk, best_score = top[0]
            start = best_chunk.start_sec
            end = best_chunk.end_sec
            for chunk, score in top[1:4]:
                if chunk.start_sec <= end + 1.5:
                    end = max(end, chunk.end_sec)
            start = max(0.0, start - 0.4)
            end = end + 0.4
            confidence = best_score
        else:
            start, end, confidence = 0.0, 0.0, 0.0

        return RetrievalOutput(
            start_sec=start,
            end_sec=end,
            confidence=confidence,
            candidates=candidates,
        )
