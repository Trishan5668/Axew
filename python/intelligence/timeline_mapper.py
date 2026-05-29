"""
Semantic timeline mapping — entity coverage, gaps, redundancy, cut suggestions.

Phase 7.2
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from python.retrieval.temporal_coherence import TimeWindow


class TimelineClip(BaseModel):
    clip_id: str
    start_sec: float
    end_sec: float
    label: str = ""
    entities: List[str] = Field(default_factory=list)
    topic: str = ""


class SemanticTimelineMap(BaseModel):
    clips: List[TimelineClip] = Field(default_factory=list)
    coverage_map: Dict[str, str] = Field(default_factory=dict)
    entity_coverage: Dict[str, List[TimeWindow]] = Field(default_factory=dict)
    topic_coverage: List[Tuple[str, TimeWindow]] = Field(default_factory=list)
    duration_sec: float = 0.0

    @classmethod
    def from_clips(
        cls,
        clips: List[TimelineClip],
        duration_sec: float,
    ) -> "SemanticTimelineMap":
        stm = cls(clips=clips, duration_sec=duration_sec)
        stm._build_coverage()
        return stm

    def _build_coverage(self) -> None:
        self.entity_coverage.clear()
        self.topic_coverage.clear()
        self.coverage_map.clear()

        for clip in self.clips:
            tw = TimeWindow(start_sec=clip.start_sec, end_sec=clip.end_sec, score=1.0)
            label = clip.label or clip.topic or "clip"
            step = max(1.0, (clip.end_sec - clip.start_sec) / 10)
            t = clip.start_sec
            while t < clip.end_sec:
                self.coverage_map[f"{t:.1f}"] = label
                t += step

            for ent in clip.entities:
                self.entity_coverage.setdefault(ent, []).append(tw)

            if clip.topic:
                self.topic_coverage.append((clip.topic, tw))

    def find_gap(self, entity: str) -> Optional[TimeWindow]:
        """Find largest uncovered window for an entity on the source timeline."""
        windows = sorted(self.entity_coverage.get(entity, []), key=lambda w: w.start_sec)
        if not windows:
            return TimeWindow(start_sec=0.0, end_sec=min(60.0, self.duration_sec), score=0.5)

        gaps: List[TimeWindow] = []
        prev_end = 0.0
        for w in windows:
            if w.start_sec > prev_end + 2.0:
                gaps.append(
                    TimeWindow(start_sec=prev_end, end_sec=w.start_sec, score=w.start_sec - prev_end)
                )
            prev_end = max(prev_end, w.end_sec)

        if prev_end < self.duration_sec - 2.0:
            gaps.append(
                TimeWindow(
                    start_sec=prev_end,
                    end_sec=self.duration_sec,
                    score=self.duration_sec - prev_end,
                )
            )

        if not gaps:
            return None
        return max(gaps, key=lambda g: g.score)

    def detect_redundancy(self) -> List[Tuple[TimeWindow, TimeWindow]]:
        """Find clip pairs with high temporal overlap and similar labels."""
        redundant: List[Tuple[TimeWindow, TimeWindow]] = []
        for i, a in enumerate(self.clips):
            wa = TimeWindow(a.start_sec, a.end_sec, 1.0)
            for b in self.clips[i + 1 :]:
                wb = TimeWindow(b.start_sec, b.end_sec, 1.0)
                overlap = max(0.0, min(wa.end_sec, wb.end_sec) - max(wa.start_sec, wb.start_sec))
                span = min(wa.end_sec - wa.start_sec, wb.end_sec - wb.start_sec)
                if span <= 0:
                    continue
                same_topic = a.topic and a.topic == b.topic
                same_label = a.label and a.label == b.label
                if overlap / span > 0.6 and (same_topic or same_label):
                    redundant.append((wa, wb))
        return redundant

    def suggest_cuts(self, target_duration: float) -> List[TimeWindow]:
        """Suggest low-priority windows to trim toward target_duration."""
        current = sum(c.end_sec - c.start_sec for c in self.clips)
        if current <= target_duration or not self.clips:
            return []

        ranked = sorted(
            self.clips,
            key=lambda c: (len(c.entities), c.end_sec - c.start_sec),
        )
        to_cut: List[TimeWindow] = []
        excess = current - target_duration
        for clip in ranked:
            if excess <= 0:
                break
            span = clip.end_sec - clip.start_sec
            if len(clip.entities) == 0 or span > 30:
                cut_span = min(span * 0.5, excess)
                to_cut.append(
                    TimeWindow(
                        start_sec=clip.end_sec - cut_span,
                        end_sec=clip.end_sec,
                        score=cut_span,
                    )
                )
                excess -= cut_span
        return to_cut
