#!/usr/bin/env python3
"""Phase 1 diagnostic benchmark for action/emotion retrieval.

This runner deliberately does not alter retrieval behavior. It loads labeled
cases, calls the existing production RetrievalPipeline, and records timestamp,
confidence, branch-winner, IoU, and failure-category evidence.
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

from python.models.transcript import TranscriptChunk
from python.retrieval.pipeline import RetrievalPipeline


DEFAULT_FIXTURE = PROJECT_ROOT / "python" / "benchmarks" / "fixtures" / "action_emotion_phase1.json"
DEFAULT_RESULTS = PROJECT_ROOT / "python" / "benchmarks" / "results" / "action_emotion_phase1_current.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "action_emotion_phase1_failure_analysis.md"
DEFAULT_BASELINE = (
    PROJECT_ROOT
    / "python"
    / "benchmarks"
    / "results"
    / "action_emotion_phase1_before_strict_errors.json"
)

HIGH_CONFIDENCE_WRONG_THRESHOLD = 0.75


@dataclass(frozen=True)
class GroundTruth:
    start: float
    end: float


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    category: str
    video_id: str
    fixture_path: str
    query: str
    ground_truth: GroundTruth
    primary_modality: str
    transcript_cue: str
    notes: str


def temporal_iou(pred_start: float, pred_end: float, gt_start: float, gt_end: float) -> float:
    """Compute intersection-over-union for temporal windows."""
    intersection = max(0.0, min(pred_end, gt_end) - max(pred_start, gt_start))
    union = max(pred_end, gt_end) - min(pred_start, gt_start)
    if union <= 0:
        return 0.0
    return intersection / union


def interval_overlaps(pred_start: float, pred_end: float, gt_start: float, gt_end: float) -> bool:
    return min(pred_end, gt_end) > max(pred_start, gt_start)


def winning_branch(candidate: dict[str, Any]) -> str:
    """Return the retrieval branch with the strongest top-candidate score."""
    branch_scores = {
        "dense": float(candidate.get("score_dense") or 0.0),
        "bm25": float(candidate.get("score_bm25") or 0.0),
        "entity": float(candidate.get("score_entity") or 0.0),
        "fuzzy": float(candidate.get("score_fuzzy") or 0.0),
        "strategy": float(candidate.get("score_strategy") or 0.0),
    }
    branch = max(branch_scores, key=branch_scores.get)
    if branch == "strategy":
        origins = candidate.get("strategy_origins") or []
        return f"strategy:{'+'.join(origins)}" if origins else "strategy"
    return branch


def categorize_failure(case: BenchmarkCase, result: dict[str, Any]) -> list[str]:
    """Assign Phase 1 failure buckets from retrieval evidence."""
    if result.get("status") != "ok":
        return ["retrieval_error"]

    iou = float(result["iou"])
    confidence = float(result.get("confidence") or 0.0)
    pred_start = float(result["retrieved"]["start"])
    pred_end = float(result["retrieved"]["end"])
    gt = case.ground_truth
    categories: list[str] = []

    if iou >= 0.5:
        return categories

    modality = case.primary_modality
    if "visual_action" in modality or "audio_action" in modality:
        categories.append("action verb not in transcript at all")
    if "emotion" in case.category and (
        "paralinguistic" in modality or "facial" in modality or "audio" in modality or "visual" in modality
    ):
        categories.append("emotion expressed via tone/visual not text")
    if interval_overlaps(pred_start, pred_end, gt.start, gt.end):
        categories.append("correct moment retrieved but wrong boundary")
    if confidence >= HIGH_CONFIDENCE_WRONG_THRESHOLD:
        categories.append("high confidence on wrong segment")
    if not categories:
        categories.append("wrong semantic segment")
    return categories


def load_cases(path: Path) -> list[BenchmarkCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for raw in payload["cases"]:
        gt = raw["ground_truth"]
        cases.append(
            BenchmarkCase(
                id=raw["id"],
                category=raw["category"],
                video_id=raw["video_id"],
                fixture_path=raw["fixture_path"],
                query=raw["query"],
                ground_truth=GroundTruth(start=float(gt["start"]), end=float(gt["end"])),
                primary_modality=raw["primary_modality"],
                transcript_cue=raw.get("transcript_cue", ""),
                notes=raw.get("notes", ""),
            )
        )
    return cases


def load_transcript_chunks(path: Path) -> list[TranscriptChunk]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_segments = payload["segments"] if isinstance(payload, dict) and "segments" in payload else payload
    chunks = []
    for index, raw in enumerate(raw_segments):
        segment = normalize_segment(raw, index)
        chunk = TranscriptChunk.from_segment_dict(segment, index)
        chunk.interpolate_word_timestamps()
        chunks.append(chunk)
    return chunks


def normalize_segment(raw: dict[str, Any], index: int) -> dict[str, Any]:
    start = raw.get("start", raw.get("start_time"))
    end = raw.get("end", raw.get("end_time"))
    if start is None:
        start = float(raw.get("start_ms", 0)) / 1000.0
    if end is None:
        end = float(raw.get("end_ms", 0)) / 1000.0
    words = []
    for word in raw.get("words", []) or []:
        word_start = word.get("start", word.get("start_ms", start))
        word_end = word.get("end", word.get("end_ms", end))
        if word_start and float(word_start) > 1000:
            word_start = float(word_start) / 1000.0
        if word_end and float(word_end) > 1000:
            word_end = float(word_end) / 1000.0
        words.append(
            {
                "word": word.get("word", word.get("text", "")),
                "start": float(word_start),
                "end": float(word_end),
                "confidence": float(word.get("confidence", word.get("probability", 0.0))),
            }
        )
    return {
        "id": raw.get("id", raw.get("segment_id", str(index))),
        "text": raw.get("text", ""),
        "start": float(start),
        "end": float(end),
        "speaker": raw.get("speaker", raw.get("speaker_id")),
        "words": words,
    }


def run_case(case: BenchmarkCase, chunks: list[TranscriptChunk]) -> dict[str, Any]:
    pipeline = RetrievalPipeline()
    try:
        output = pipeline.retrieve(case.query, chunks)
    except Exception as exc:
        result = {
            "id": case.id,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "query": case.query,
            "category": case.category,
            "video_id": case.video_id,
            "ground_truth": {"start": case.ground_truth.start, "end": case.ground_truth.end},
        }
        for field in ("strategy_name", "exception_type", "exception_message"):
            if hasattr(exc, field):
                result[field] = getattr(exc, field)
        return result

    top = output.top_candidate
    pred_start = float(top.anchor_start)
    pred_end = float(top.anchor_end)
    iou = temporal_iou(pred_start, pred_end, case.ground_truth.start, case.ground_truth.end)
    candidate_dict = top.to_dict()
    trace_dict = output.trace.to_dict()
    result = {
        "id": case.id,
        "status": "ok",
        "query": case.query,
        "category": case.category,
        "video_id": case.video_id,
        "primary_modality": case.primary_modality,
        "ground_truth": {"start": case.ground_truth.start, "end": case.ground_truth.end},
        "retrieved": {"start": pred_start, "end": pred_end, "text": top.chunk.text},
        "confidence": float(top.score_final or 0.0),
        "rank_percentile": float(top.score_calibrated),
        "iou": iou,
        "iou_at_0_5": iou >= 0.5,
        "winning_branch": winning_branch(candidate_dict),
        "scores": {
            "dense": float(top.score_dense),
            "bm25": float(top.score_bm25),
            "entity": float(top.score_entity),
            "fuzzy": float(top.score_fuzzy),
            "strategy": float(top.score_strategy),
            "cross_encoder": float(top.score_cross_encoder),
            "final": float(top.score_final or 0.0),
            "calibrated": float(top.score_calibrated),
        },
        "trace": {
            "decomposed": trace_dict.get("decomposed"),
            "strategy_errors": trace_dict.get("strategy_errors", []),
            "opener_suppressions": trace_dict.get("opener_suppressions", []),
            "stage_latencies": trace_dict.get("stage_latencies", {}),
            "top_after_retrieval": first_or_none(trace_dict.get("candidates_after_retrieval", [])),
            "top_after_expansion": first_or_none(trace_dict.get("candidates_after_expansion", [])),
            "top_after_reranking": first_or_none(trace_dict.get("candidates_after_reranking", [])),
        },
        "candidate_diversity": candidate_diversity(output.all_candidates),
    }
    result["failure_modes"] = categorize_failure(case, result)
    return result


def first_or_none(values: list[Any]) -> Any:
    return values[0] if values else None


def candidate_diversity(candidates: list[Any], top_k: int = 5) -> dict[str, Any]:
    selected = candidates[:top_k]
    windows = {
        (round(float(c.anchor_start), 3), round(float(c.anchor_end), 3))
        for c in selected
    }
    chunks = {c.chunk.id for c in selected}
    starts = [float(c.anchor_start) for c in selected]
    return {
        "candidate_count": len(candidates),
        "top_k": len(selected),
        "unique_windows_top_k": len(windows),
        "unique_chunks_top_k": len(chunks),
        "temporal_span_top_k": max(starts) - min(starts) if starts else 0.0,
    }


def confidence_distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "stddev": 0.0,
            "saturated_at_1_count": 0,
        }
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "count": len(values),
        "min": round(min(values), 4),
        "p25": round(percentile(0.25), 4),
        "median": round(percentile(0.5), 4),
        "p75": round(percentile(0.75), 4),
        "max": round(max(values), 4),
        "mean": round(statistics.mean(values), 4),
        "stddev": round(statistics.pstdev(values), 4),
        "saturated_at_1_count": sum(1 for value in values if value >= 1.0 - 1e-9),
    }


def compare_successful_behavior(
    before_results: list[dict[str, Any]],
    after_results: list[dict[str, Any]],
) -> dict[str, Any]:
    before_by_id = {result["id"]: result for result in before_results}
    after_by_id = {result["id"]: result for result in after_results}
    prior_clean_ids = [
        result_id
        for result_id, result in before_by_id.items()
        if result.get("status") == "ok"
        and not result.get("trace", {}).get("strategy_errors")
    ]
    changed = []
    for result_id in prior_clean_ids:
        before = before_by_id[result_id]
        after = after_by_id.get(result_id, {})
        before_signature = (
            before.get("retrieved", {}).get("start"),
            before.get("retrieved", {}).get("end"),
            before.get("retrieved", {}).get("text"),
            before.get("winning_branch"),
        )
        after_signature = (
            after.get("retrieved", {}).get("start"),
            after.get("retrieved", {}).get("end"),
            after.get("retrieved", {}).get("text"),
            after.get("winning_branch"),
        )
        if before_signature != after_signature:
            changed.append(result_id)
    return {
        "prior_successful_cases": len(prior_clean_ids),
        "identical_cases": len(prior_clean_ids) - len(changed),
        "changed_case_ids": changed,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r.get("status") == "ok"]
    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({r.get("category", "unknown") for r in results}):
        subset = [r for r in ok if r.get("category") == category]
        if not subset:
            by_category[category] = {"cases": 0, "iou_at_0_5": 0.0, "mean_iou": 0.0}
            continue
        by_category[category] = {
            "cases": len(subset),
            "iou_at_0_5": round(sum(1 for r in subset if r["iou_at_0_5"]) / len(subset), 4),
            "mean_iou": round(statistics.mean(float(r["iou"]) for r in subset), 4),
            "mean_confidence": round(statistics.mean(float(r["confidence"]) for r in subset), 4),
        }

    failures: dict[str, int] = {}
    for result in ok:
        for mode in result.get("failure_modes", []):
            failures[mode] = failures.get(mode, 0) + 1

    branches: dict[str, int] = {}
    for result in ok:
        branch = str(result.get("winning_branch", "unknown"))
        branches[branch] = branches.get(branch, 0) + 1

    strategy_failures = [
        result for result in results
        if result.get("error_type") == "StrategyExecutionError"
    ]
    diversity = [result["candidate_diversity"] for result in ok]
    confidence_values = [float(result["confidence"]) for result in ok]
    percentile_values = [float(result["rank_percentile"]) for result in ok]

    return {
        "total_cases": len(results),
        "ok_cases": len(ok),
        "error_cases": len(results) - len(ok),
        "overall_iou_at_0_5": round(sum(1 for r in ok if r["iou_at_0_5"]) / max(len(ok), 1), 4),
        "overall_mean_iou": round(statistics.mean(float(r["iou"]) for r in ok), 4) if ok else 0.0,
        "by_category": by_category,
        "failure_modes": dict(sorted(failures.items())),
        "winning_branches": dict(sorted(branches.items())),
        "strategy_failure_count": len(strategy_failures),
        "strategy_failures": [
            {
                "id": result["id"],
                "query": result["query"],
                "strategy": result.get("strategy_name"),
                "exception_type": result.get("exception_type"),
                "exception_message": result.get("exception_message"),
            }
            for result in strategy_failures
        ],
        "confidence_distribution": confidence_distribution(confidence_values),
        "rank_percentile_distribution": confidence_distribution(percentile_values),
        "candidate_diversity": {
            "mean_candidate_count": round(
                statistics.mean(item["candidate_count"] for item in diversity), 4
            ) if diversity else 0.0,
            "mean_unique_windows_top_5": round(
                statistics.mean(item["unique_windows_top_k"] for item in diversity), 4
            ) if diversity else 0.0,
            "mean_unique_chunks_top_5": round(
                statistics.mean(item["unique_chunks_top_k"] for item in diversity), 4
            ) if diversity else 0.0,
            "mean_temporal_span_top_5": round(
                statistics.mean(item["temporal_span_top_k"] for item in diversity), 4
            ) if diversity else 0.0,
        },
    }


def write_report(results: list[dict[str, Any]], summary: dict[str, Any], out_path: Path) -> None:
    rows = []
    for result in results:
        if result.get("status") == "ok":
            gt = result["ground_truth"]
            pred = result["retrieved"]
            rows.append(
                "| {id} | {category} | {branch} | {pred_start:.2f}-{pred_end:.2f} | "
                "{gt_start:.2f}-{gt_end:.2f} | {confidence:.3f} | {iou:.3f} | {modes} |".format(
                    id=result["id"],
                    category=result["category"],
                    branch=result["winning_branch"],
                    pred_start=pred["start"],
                    pred_end=pred["end"],
                    gt_start=gt["start"],
                    gt_end=gt["end"],
                    confidence=result["confidence"],
                    iou=result["iou"],
                    modes=", ".join(result.get("failure_modes") or ["pass"]),
                )
            )
        else:
            gt = result["ground_truth"]
            rows.append(
                f"| {result['id']} | {result['category']} | error:{result['error_type']} | n/a | "
                f"{gt['start']:.2f}-{gt['end']:.2f} | 0.000 | 0.000 | retrieval_error |"
            )

    category_lines = [
        f"- {category}: IoU>=0.5 {values['iou_at_0_5']:.1%}, mean IoU {values['mean_iou']:.3f}, "
        f"mean confidence {values.get('mean_confidence', 0.0):.3f}"
        for category, values in summary["by_category"].items()
    ]
    failure_lines = [
        f"- {mode}: {count}"
        for mode, count in summary["failure_modes"].items()
    ] or ["- No failures categorized."]
    branch_lines = [
        f"- {branch}: {count}"
        for branch, count in summary.get("winning_branches", {}).items()
    ] or ["- No winning branch data."]

    text = "\n".join(
        [
            "# Phase 1 Action/Emotion Retrieval Failure Analysis",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Scope",
            "",
            "This is diagnostic-only. The production dense/BM25/entity/fuzzy hybrid retrieval scaffold was not modified.",
            "The benchmark uses available AXEW transcript fixtures rather than raw video/audio, so visual/audio labels are fixture-derived and mark where current transcript-heavy retrieval is expected to be weak.",
            "",
            "## Summary",
            "",
            f"- Cases: {summary['total_cases']} total, {summary['ok_cases']} completed, {summary['error_cases']} errors.",
            f"- Overall IoU>=0.5: {summary['overall_iou_at_0_5']:.1%}.",
            f"- Overall mean IoU: {summary['overall_mean_iou']:.3f}.",
            *category_lines,
            f"- Strategy failures surfaced as typed errors: {summary.get('strategy_failure_count', 0)}.",
            f"- Absolute confidence distribution: {summary.get('confidence_distribution', {})}.",
            f"- Candidate diversity: {summary.get('candidate_diversity', {})}.",
            "",
            "## Failure Modes",
            "",
            *failure_lines,
            "",
            "## Swallowed Exceptions Removed",
            "",
            "- strategy_context: intelligence artifact construction.",
            "- strategy_side_index: side-index construction for strategy artifacts.",
            "- emotion: EmotionalStrategy candidate retrieval.",
            "- action: EntityActionStrategy candidate retrieval.",
            "- event_index: event-index candidate bridge.",
            "",
            "## Winning Branch Distribution",
            "",
            *branch_lines,
            "",
            "## Per-Query Results",
            "",
            "| ID | Category | Winning branch | Retrieved | Ground truth | Confidence | IoU | Failure modes |",
            "|----|----------|----------------|-----------|--------------|------------|-----|---------------|",
            *rows,
            "",
            "## Diagnostic Conclusions",
            "",
            "- Current retrieval remains dominated by transcript-derived dense/BM25/fuzzy/entity evidence; action and emotion cases that require visual, facial, or paralinguistic confirmation are not directly observable.",
            "- Reported confidence is the existing absolute final score. The percentile rank score is retained separately as rank_percentile because its top candidate is expected to equal 1.0 by construction.",
            "- Strategy failures surface as StrategyExecutionError with structured query, strategy, exception type, and exception message fields; no strategy fallback result is emitted.",
            f"- Successful-case behavior comparison: {summary.get('successful_behavior_comparison', {})}.",
            "- Boundary failures are expected where query intent spans a question-answer exchange or a short reaction inside a longer transcript segment.",
            "- No Phase 2 fixes were applied in this run.",
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 1 action/emotion retrieval diagnostics.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    args = parser.parse_args()

    cases = load_cases(Path(args.fixture))
    chunk_cache: dict[str, list[TranscriptChunk]] = {}
    results = []
    for case in cases:
        fixture_path = str((PROJECT_ROOT / case.fixture_path).resolve())
        if fixture_path not in chunk_cache:
            chunk_cache[fixture_path] = load_transcript_chunks(Path(fixture_path))
        results.append(run_case(case, chunk_cache[fixture_path]))

    summary = summarize(results)
    baseline_path = Path(args.baseline)
    if baseline_path.is_file():
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        summary["successful_behavior_comparison"] = compare_successful_behavior(
            baseline_payload.get("results", []),
            results,
        )
    payload = {
        "benchmark": "action_emotion_phase1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(results, summary, Path(args.report))
    print(json.dumps(summary, indent=2))
    print(f"Wrote {results_path}")
    print(f"Wrote {Path(args.report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
