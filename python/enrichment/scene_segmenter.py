"""Multi-signal scene boundary detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from python.models.enriched import DiarizationSegment, Scene, TranscriptSegment


@dataclass
class BoundaryCandidate:
    index: int
    score: float


class SceneSegmenter:
    def segment(
        self,
        segments: List[TranscriptSegment],
        embeddings: Optional[np.ndarray] = None,
        diarization: Optional[List[DiarizationSegment]] = None,
        audio_path: Optional[str] = None,
    ) -> List[Scene]:
        if not segments:
            return []
        semantic = self._detect_semantic_valleys(embeddings) if embeddings is not None else []
        speaker = self._detect_speaker_transitions(diarization or [], segments)
        silence = self._detect_silence_gaps(segments, audio_path)
        boundaries = self._merge_boundaries(semantic, speaker, silence, len(segments))
        return self._build_scenes(segments, boundaries)

    def _detect_semantic_valleys(self, embeddings: np.ndarray, window: int = 3) -> List[BoundaryCandidate]:
        from sklearn.metrics.pairwise import cosine_similarity

        scores: List[BoundaryCandidate] = []
        for i in range(window, len(embeddings) - window):
            left = embeddings[i - window : i].mean(axis=0)
            right = embeddings[i : i + window].mean(axis=0)
            sim = float(cosine_similarity([left], [right])[0][0])
            scores.append(BoundaryCandidate(i, 1.0 - sim))
        return self._find_peaks(scores, min_prominence=0.15)

    def _detect_speaker_transitions(
        self, diarization: List[DiarizationSegment], segments: List[TranscriptSegment]
    ) -> List[BoundaryCandidate]:
        out: List[BoundaryCandidate] = []
        prev = None
        for i, seg in enumerate(segments):
            sid = seg.speaker_id
            if prev and sid and prev != sid:
                out.append(BoundaryCandidate(i, 0.7))
            prev = sid or prev
        return out

    def _detect_silence_gaps(
        self, segments: List[TranscriptSegment], audio_path: Optional[str]
    ) -> List[BoundaryCandidate]:
        out: List[BoundaryCandidate] = []
        for i in range(1, len(segments)):
            gap_ms = segments[i].start_ms - segments[i - 1].end_ms
            if gap_ms > 1500:
                out.append(BoundaryCandidate(i, min(1.0, gap_ms / 5000.0)))
        return out

    def _find_peaks(self, scores: List[BoundaryCandidate], min_prominence: float) -> List[BoundaryCandidate]:
        if not scores:
            return []
        vals = [s.score for s in scores]
        mean = sum(vals) / len(vals)
        return [s for s in scores if s.score >= mean + min_prominence]

    def _merge_boundaries(
        self,
        semantic: List[BoundaryCandidate],
        speaker: List[BoundaryCandidate],
        silence: List[BoundaryCandidate],
        n: int,
    ) -> List[int]:
        combined: dict[int, float] = {}
        for group in (semantic, speaker, silence):
            for b in group:
                combined[b.index] = combined.get(b.index, 0) + b.score
        hard = sorted(i for i, s in combined.items() if s >= 0.6)
        if not hard:
            hard = sorted(i for i, s in combined.items() if s >= 0.3)
        if not hard:
            return [0, n]
        edges = [0] + hard + [n]
        return sorted(set(edges))

    def _build_scenes(self, segments: List[TranscriptSegment], edges: List[int]) -> List[Scene]:
        scenes: List[Scene] = []
        for i in range(len(edges) - 1):
            start_i, end_i = edges[i], edges[i + 1]
            chunk = segments[start_i:end_i]
            if not chunk:
                continue
            speakers = [s.speaker_id for s in chunk if s.speaker_id]
            dom = max(set(speakers), key=speakers.count) if speakers else None
            scenes.append(
                Scene(
                    scene_id=str(uuid.uuid4())[:8],
                    start_ms=chunk[0].start_ms,
                    end_ms=chunk[-1].end_ms,
                    segment_ids=[s.segment_id for s in chunk],
                    dominant_speaker=dom,
                    boundary_confidence=0.7,
                )
            )
        return scenes
