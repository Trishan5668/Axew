"""Regression harness for semantic retrieval quality."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from python.models.transcript import TranscriptChunk
from python.retrieval.pipeline import RetrievalPipeline
from python.retrieval.timestamp_contract import PlannerError


QUALITY_ORDER = {"poor_match": 0, "weak_match": 1, "moderate_match": 2, "strong_match": 3}


@dataclass
class BenchmarkReport:
    cases: int
    hit_at_1: float
    hit_at_3: float
    temporal_iou: float
    timestamp_mae: float
    opener_rate: float
    weak_only_rate: float
    entity_recall_at_3: float
    rejection_rate: float
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegressionReport:
    before: dict[str, Any]
    after: dict[str, Any]
    deltas: dict[str, float]
    regressions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RetrievalBenchmark:
    def run(self, transcript_path: str | Path, cases_path: str | Path) -> BenchmarkReport:
        transcript = self._load_transcript(transcript_path)
        cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
        if isinstance(cases, dict):
            cases = cases.get("cases", [])
        pipeline = RetrievalPipeline()
        details = []
        rejects = 0
        for case in cases:
            try:
                result = pipeline.retrieve(case["query"], transcript, case.get("session_context"))
                candidates = result.all_candidates
                top = candidates[0]
                expected_start = case["expected_start_range"]
                expected_end = case["expected_end_range"]
                hit1 = self._in_range(top, expected_start, expected_end)
                hit3 = any(self._in_range(c, expected_start, expected_end) for c in candidates[:3])
                entity_hit = self._entity_recall(candidates[:3], case.get("required_entities", []))
                details.append({
                    "query": case["query"],
                    "hit1": hit1,
                    "hit3": hit3,
                    "temporal_iou": self._iou(top.expanded_start, top.expanded_end, expected_start, expected_end),
                    "timestamp_mae": abs((top.expanded_start or 0) - sum(expected_start) / 2),
                    "is_opener": top.is_opener,
                    "weak_only": top.match_quality in {"weak_match", "poor_match"},
                    "entity_recall": entity_hit,
                    "match_quality": top.match_quality,
                    "predicted": [c.to_dict() for c in candidates[:3]],
                })
            except PlannerError as e:
                rejects += 1
                details.append({"query": case.get("query"), "rejected": True, "error": str(e)})

        n = max(len(cases), 1)
        valid = [d for d in details if not d.get("rejected")]
        denom = max(len(valid), 1)
        return BenchmarkReport(
            cases=len(cases),
            hit_at_1=sum(bool(d.get("hit1")) for d in valid) / n,
            hit_at_3=sum(bool(d.get("hit3")) for d in valid) / n,
            temporal_iou=sum(float(d.get("temporal_iou", 0)) for d in valid) / denom,
            timestamp_mae=sum(float(d.get("timestamp_mae", 0)) for d in valid) / denom,
            opener_rate=sum(bool(d.get("is_opener")) for d in valid) / denom,
            weak_only_rate=sum(bool(d.get("weak_only")) for d in valid) / denom,
            entity_recall_at_3=sum(float(d.get("entity_recall", 1.0)) for d in valid) / denom,
            rejection_rate=rejects / n,
            details=details,
        )

    def run_regression(self, before_path: str | Path, after_path: str | Path) -> RegressionReport:
        before = json.loads(Path(before_path).read_text(encoding="utf-8"))
        after = json.loads(Path(after_path).read_text(encoding="utf-8"))
        higher_better = {"hit_at_1", "hit_at_3", "temporal_iou", "entity_recall_at_3"}
        lower_better = {"timestamp_mae", "opener_rate", "weak_only_rate", "rejection_rate"}
        metrics = higher_better | lower_better
        deltas = {m: float(after.get(m, 0)) - float(before.get(m, 0)) for m in metrics}
        regressions = []
        for metric in higher_better:
            if deltas[metric] < -0.05:
                regressions.append(metric)
        for metric in lower_better:
            if deltas[metric] > 0.05:
                regressions.append(metric)
        return RegressionReport(before=before, after=after, deltas=deltas, regressions=regressions)

    def _load_transcript(self, path: str | Path) -> list[TranscriptChunk]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        segments = data.get("segments", data if isinstance(data, list) else [])
        return [TranscriptChunk.from_segment_dict(seg, i) for i, seg in enumerate(segments)]

    def _in_range(self, candidate, start_range: list[float], end_range: list[float]) -> bool:
        return (
            candidate.expanded_start is not None
            and candidate.expanded_end is not None
            and start_range[0] <= candidate.expanded_start <= start_range[1]
            and end_range[0] <= candidate.expanded_end <= end_range[1]
        )

    def _iou(self, pred_start: float, pred_end: float, expected_start_range: list[float], expected_end_range: list[float]) -> float:
        expected_start = expected_start_range[0]
        expected_end = expected_end_range[1]
        inter = max(0.0, min(pred_end, expected_end) - max(pred_start, expected_start))
        union = max(pred_end, expected_end) - min(pred_start, expected_start)
        return inter / union if union else 0.0

    def _entity_recall(self, candidates, entities: list[str]) -> float:
        if not entities:
            return 1.0
        text = " ".join(c.chunk.text for c in candidates).lower()
        return sum(1 for e in entities if e.lower() in text) / len(entities)
