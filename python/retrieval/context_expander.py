"""Context expansion and timestamp refinement for retrieval candidates."""

from __future__ import annotations

import re
from copy import copy

import numpy as np

from python.models.transcript import TranscriptChunk
from python.retrieval.timestamp_contract import RetrievalIntegrityError
from python.retrieval.topic_segmenter import cosine
from python.retrieval.types import DecomposedQuery, RetrievalCandidate, TopicSegment


class ContextExpander:
    def expand(
        self,
        candidates: list[RetrievalCandidate],
        all_chunks: list[TranscriptChunk],
        all_segments: list[TopicSegment],
        query: DecomposedQuery,
    ) -> list[RetrievalCandidate]:
        sorted_chunks = sorted(all_chunks, key=lambda c: c.start_time)
        expanded: list[RetrievalCandidate] = []
        for candidate in candidates:
            segment = candidate.segment or self._find_segment(candidate.chunk, all_segments)
            candidate.segment = segment
            expanded.append(self._expand_one(candidate, sorted_chunks, segment, query))
            if segment:
                top = self._top_chunk_in_segment(segment, query)
                if top and top.id != candidate.chunk.id:
                    alt = copy(candidate)
                    alt.chunk = top
                    alt.anchor_start = top.start_time
                    alt.anchor_end = top.end_time
                    alt.match_explanation = f"{candidate.match_explanation}; alternate_top_segment_chunk"
                    expanded.append(self._expand_one(alt, sorted_chunks, segment, query))

        dedup: dict[tuple[str, float, float], RetrievalCandidate] = {}
        for cand in expanded:
            key = (cand.chunk.id, float(cand.expanded_start), float(cand.expanded_end))
            existing = dedup.get(key)
            if existing is None or cand.score_fused > existing.score_fused:
                dedup[key] = cand
        return sorted(dedup.values(), key=lambda c: c.score_fused, reverse=True)

    def _expand_one(
        self,
        candidate: RetrievalCandidate,
        all_chunks: list[TranscriptChunk],
        segment: TopicSegment | None,
        query: DecomposedQuery,
    ) -> RetrievalCandidate:
        candidate.anchor_start = candidate.chunk.start_time
        candidate.anchor_end = candidate.chunk.end_time
        included = {candidate.chunk.id: candidate.chunk}
        idx = next((i for i, c in enumerate(all_chunks) if c.id == candidate.chunk.id), -1)
        if idx >= 0:
            for ni in range(max(0, idx - 2), min(len(all_chunks), idx + 3)):
                neighbor = all_chunks[ni]
                if neighbor.id == candidate.chunk.id:
                    continue
                if self._crosses_pause(candidate.chunk, neighbor):
                    continue
                if self._continuous(candidate.chunk, neighbor, query):
                    included[neighbor.id] = neighbor

        if segment and (segment.end - segment.start) <= 60:
            for chunk in segment.chunks:
                if not self._crosses_pause(candidate.chunk, chunk):
                    included[chunk.id] = chunk
        elif segment:
            lo = max(segment.start, candidate.chunk.start_time - 15.0)
            hi = min(segment.end, candidate.chunk.end_time + 15.0)
            for chunk in segment.chunks:
                if chunk.start_time <= hi and chunk.end_time >= lo:
                    included[chunk.id] = chunk

        chunks = sorted(included.values(), key=lambda c: c.start_time)
        candidate.expanded_start = min(c.start_time for c in chunks)
        candidate.expanded_end = max(c.end_time for c in chunks)
        self._assert_window(candidate)
        return candidate

    def _find_segment(self, chunk: TranscriptChunk, segments: list[TopicSegment]) -> TopicSegment | None:
        for seg in segments:
            if seg.start <= chunk.start_time and seg.end >= chunk.end_time:
                return seg
        return None

    def _top_chunk_in_segment(self, segment: TopicSegment, query: DecomposedQuery) -> TranscriptChunk | None:
        best = None
        best_score = -1
        terms = [t.lower() for t in query.search_terms]
        for chunk in segment.chunks:
            text = chunk.text.lower()
            score = sum(1 for t in terms if t and t in text)
            if score > best_score:
                best = chunk
                best_score = score
        return best

    def _continuous(self, anchor: TranscriptChunk, neighbor: TranscriptChunk, query: DecomposedQuery) -> bool:
        text = neighbor.text.lower()
        if any(e.lower() in text for e in query.entities):
            return True
        if getattr(anchor, "embedding", None) is not None and getattr(neighbor, "embedding", None) is not None:
            if cosine(np.asarray(anchor.embedding), np.asarray(neighbor.embedding)) > 0.55:
                return True
        if not re.search(r"[.?!]\s*$", anchor.text.strip()):
            return True
        gap = min(abs(neighbor.start_time - anchor.end_time), abs(anchor.start_time - neighbor.end_time))
        return bool(anchor.speaker and anchor.speaker == neighbor.speaker and gap <= 1.5)

    def _crosses_pause(self, anchor: TranscriptChunk, other: TranscriptChunk) -> bool:
        if other.start_time >= anchor.end_time:
            return (other.start_time - anchor.end_time) > 3.0
        if anchor.start_time >= other.end_time:
            return (anchor.start_time - other.end_time) > 3.0
        return False

    def _assert_window(self, candidate: RetrievalCandidate) -> None:
        start = candidate.expanded_start
        end = candidate.expanded_end
        if start is None or end is None:
            raise RetrievalIntegrityError(f"expanded timestamp is None | candidate={candidate}")
        if end <= start:
            raise RetrievalIntegrityError(f"expanded_end <= expanded_start | candidate={candidate}")
        if (end - start) < 1.0:
            mid = (start + end) / 2
            candidate.expanded_start = max(0.0, mid - 0.5)
            candidate.expanded_end = mid + 0.5
        if (candidate.expanded_end - candidate.expanded_start) > 180.0:
            raise RetrievalIntegrityError(f"expanded duration > 180s | candidate={candidate}")
