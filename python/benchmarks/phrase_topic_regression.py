#!/usr/bin/env python3
"""Phrase and topic retrieval regression benchmark.

Uses the production RetrievalPipeline only. Does not alter retrieval behavior.
Records winner chunk, timestamps, confidence, branch, IoU, candidate coverage,
and ground-truth rank for each labeled query.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.benchmarks.action_emotion_phase1 import (
    load_transcript_chunks,
    temporal_iou,
    winning_branch,
)
from python.retrieval.pipeline import RetrievalPipeline


DEFAULT_FIXTURE = PROJECT_ROOT / "python" / "benchmarks" / "fixtures" / "phrase_topic_regression.json"
DEFAULT_RESULTS = PROJECT_ROOT / "python" / "benchmarks" / "results" / "phrase_topic_regression_current.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "phrase_topic_regression.md"

RELEVANT_IOU = 0.5


@dataclass(frozen=True)
class RegressionQuery:
    id: str
    type: str
    video_id: str
    fixture_path: str
    query: str
    expected_chunk_id: str
    expected_start: float
    expected_end: float


def load_queries(path: Path) -> list[RegressionQuery]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        RegressionQuery(
            id=raw["id"],
            type=raw["type"],
            video_id=raw["video_id"],
            fixture_path=raw["fixture_path"],
            query=raw["query"],
            expected_chunk_id=raw["expected_chunk_id"],
            expected_start=float(raw["expected_start"]),
            expected_end=float(raw["expected_end"]),
        )
        for raw in payload["queries"]
    ]


def ground_truth_rank(candidates: list[Any], gt_start: float, gt_end: float) -> int | None:
    for rank, candidate in enumerate(candidates, start=1):
        if temporal_iou(candidate.anchor_start, candidate.anchor_end, gt_start, gt_end) >= RELEVANT_IOU:
            return rank
    return None


def candidate_covered(candidates: list[Any], gt_start: float, gt_end: float) -> bool:
    return ground_truth_rank(candidates, gt_start, gt_end) is not None


def timestamp_valid(start: float, end: float) -> bool:
    return (
        math.isfinite(start)
        and math.isfinite(end)
        and start >= 0.0
        and end > start
    )


def run_query(case: RegressionQuery, chunks: list[Any]) -> dict[str, Any]:
    pipeline = RetrievalPipeline()
    try:
        output = pipeline.retrieve(case.query, chunks)
    except Exception as exc:
        return {
            "id": case.id,
            "type": case.type,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "query": case.query,
            "video_id": case.video_id,
            "expected_chunk_id": case.expected_chunk_id,
            "expected_start": case.expected_start,
            "expected_end": case.expected_end,
        }

    top = output.top_candidate
    candidate_dict = top.to_dict()
    pred_start = float(top.anchor_start)
    pred_end = float(top.anchor_end)
    iou = temporal_iou(pred_start, pred_end, case.expected_start, case.expected_end)
    gt_rank = ground_truth_rank(output.all_candidates, case.expected_start, case.expected_end)
    confidence = float(top.score_final or 0.0)

    return {
        "id": case.id,
        "type": case.type,
        "status": "ok",
        "query": case.query,
        "video_id": case.video_id,
        "expected_chunk_id": case.expected_chunk_id,
        "expected_start": case.expected_start,
        "expected_end": case.expected_end,
        "winner_chunk_id": top.chunk.id,
        "winner_start": pred_start,
        "winner_end": pred_end,
        "confidence": confidence,
        "confidence_finite": math.isfinite(confidence),
        "winning_branch": winning_branch(candidate_dict),
        "iou": round(iou, 4),
        "iou_at_0_5": iou >= RELEVANT_IOU,
        "candidate_coverage": candidate_covered(
            output.all_candidates,
            case.expected_start,
            case.expected_end,
        ),
        "ground_truth_rank": gt_rank,
        "timestamp_valid": timestamp_valid(pred_start, pred_end),
        "winner_text": top.chunk.text,
        "scores": {
            "dense": float(top.score_dense),
            "bm25": float(top.score_bm25),
            "entity": float(top.score_entity),
            "fuzzy": float(top.score_fuzzy),
            "strategy": float(top.score_strategy),
            "final": confidence,
            "calibrated": float(top.score_calibrated),
        },
        "trace": {
            "candidate_count": len(output.all_candidates),
            "stage_latencies": output.trace.to_dict().get("stage_latencies", {}),
        },
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [result for result in results if result.get("status") == "ok"]
    phrase = [result for result in ok if result.get("type") == "phrase"]
    topic = [result for result in ok if result.get("type") == "topic"]

    def bucket_metrics(subset: list[dict[str, Any]]) -> dict[str, Any]:
        if not subset:
            return {
                "queries": 0,
                "iou_at_0_5_rate": 0.0,
                "mean_iou": 0.0,
                "candidate_coverage_rate": 0.0,
            }
        return {
            "queries": len(subset),
            "iou_at_0_5_rate": round(
                sum(1 for result in subset if result["iou_at_0_5"]) / len(subset),
                4,
            ),
            "mean_iou": round(statistics.mean(float(result["iou"]) for result in subset), 4),
            "candidate_coverage_rate": round(
                sum(1 for result in subset if result["candidate_coverage"]) / len(subset),
                4,
            ),
        }

    return {
        "total_queries": len(results),
        "ok_queries": len(ok),
        "error_queries": len(results) - len(ok),
        "phrase": bucket_metrics(phrase),
        "topic": bucket_metrics(topic),
        "overall_iou_at_0_5_rate": round(
            sum(1 for result in ok if result["iou_at_0_5"]) / max(len(ok), 1),
            4,
        ),
        "overall_candidate_coverage_rate": round(
            sum(1 for result in ok if result["candidate_coverage"]) / max(len(ok), 1),
            4,
        ),
        "timestamp_regressions": sum(1 for result in ok if not result["timestamp_valid"]),
        "confidence_nan_count": sum(1 for result in ok if not result["confidence_finite"]),
        "winning_branches": dict(
            sorted(
                {
                    branch: sum(1 for result in ok if result.get("winning_branch") == branch)
                    for branch in {result.get("winning_branch", "unknown") for result in ok}
                }.items()
            )
        ),
    }


def write_report(results: list[dict[str, Any]], summary: dict[str, Any], out_path: Path) -> None:
    rows = []
    for result in results:
        if result.get("status") == "ok":
            rows.append(
                "| {id} | {type} | {branch} | {chunk} | {pred_start:.2f}-{pred_end:.2f} | "
                "{gt_start:.2f}-{gt_end:.2f} | {confidence:.3f} | {iou:.3f} | {coverage} | {rank} |".format(
                    id=result["id"],
                    type=result["type"],
                    branch=result["winning_branch"],
                    chunk=result["winner_chunk_id"],
                    pred_start=result["winner_start"],
                    pred_end=result["winner_end"],
                    gt_start=result["expected_start"],
                    gt_end=result["expected_end"],
                    confidence=result["confidence"],
                    iou=result["iou"],
                    coverage="yes" if result["candidate_coverage"] else "no",
                    rank=result["ground_truth_rank"] if result["ground_truth_rank"] is not None else "none",
                )
            )
        else:
            rows.append(
                f"| {result['id']} | {result['type']} | error:{result['error_type']} | n/a | "
                f"n/a | {result['expected_start']:.2f}-{result['expected_end']:.2f} | 0.000 | 0.000 | no | none |"
            )

    text = "\n".join(
        [
            "# Phrase & Topic Retrieval Regression",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Scope",
            "",
            "Regression-only benchmark over the production retrieval path:",
            "RetrievalPipeline.retrieve() -> HybridRetriever.retrieve() -> ContextExpander.expand() -> ConversationalReranker.rerank().",
            "No retrieval behavior was modified for this run.",
            "",
            "## Summary",
            "",
            f"- Queries: {summary['total_queries']} total, {summary['ok_queries']} completed, {summary['error_queries']} errors.",
            f"- Phrase IoU>=0.5: {summary['phrase']['iou_at_0_5_rate']:.1%} ({summary['phrase']['queries']} queries).",
            f"- Topic IoU>=0.5: {summary['topic']['iou_at_0_5_rate']:.1%} ({summary['topic']['queries']} queries).",
            f"- Overall candidate coverage: {summary['overall_candidate_coverage_rate']:.1%}.",
            f"- Timestamp regressions: {summary['timestamp_regressions']}.",
            f"- Confidence NaN count: {summary['confidence_nan_count']}.",
            f"- Winning branches: {summary['winning_branches']}.",
            "",
            "## Per-Query Results",
            "",
            "| ID | Type | Branch | Winner chunk | Retrieved | Ground truth | Confidence | IoU | Coverage | GT rank |",
            "|----|------|--------|--------------|-----------|--------------|------------|-----|----------|---------|",
            *rows,
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")


def run_benchmark(
    fixture_path: Path | None = None,
    results_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    fixture_path = fixture_path or DEFAULT_FIXTURE
    results_path = results_path or DEFAULT_RESULTS
    report_path = report_path or DEFAULT_REPORT

    queries = load_queries(fixture_path)
    chunk_cache: dict[str, list[Any]] = {}
    results = []
    for case in queries:
        resolved = str((PROJECT_ROOT / case.fixture_path).resolve())
        if resolved not in chunk_cache:
            chunk_cache[resolved] = load_transcript_chunks(Path(case.fixture_path))
        results.append(run_query(case, chunk_cache[resolved]))

    summary = summarize(results)
    payload = {
        "benchmark": "phrase_topic_regression",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(results, summary, report_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run phrase/topic retrieval regression benchmark.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    payload = run_benchmark(
        fixture_path=Path(args.fixture),
        results_path=Path(args.results),
        report_path=Path(args.report),
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {Path(args.results)}")
    print(f"Wrote {Path(args.report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
