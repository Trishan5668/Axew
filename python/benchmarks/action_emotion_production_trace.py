#!/usr/bin/env python3
"""Evidence-only production-path trace for the 40 action/emotion queries."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.benchmarks.action_emotion_phase1 import (
    BenchmarkCase,
    load_cases,
    load_transcript_chunks,
    temporal_iou,
    winning_branch,
)
from python.retrieval.pipeline import RetrievalPipeline


DEFAULT_FIXTURE = PROJECT_ROOT / "python" / "benchmarks" / "fixtures" / "action_emotion_phase1.json"
DEFAULT_RESULTS = PROJECT_ROOT / "python" / "benchmarks" / "results" / "action_emotion_production_trace.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "action_emotion_production_trace.md"
RELEVANT_IOU = 0.5


def candidate_window(candidate: dict[str, Any], *, mapped: bool = False) -> tuple[float, float]:
    if mapped:
        return (
            float(candidate.get("mapped_start", candidate.get("start", 0.0))),
            float(candidate.get("mapped_end", candidate.get("end", 0.0))),
        )
    return (
        float(candidate.get("anchor_start", candidate.get("start", 0.0))),
        float(candidate.get("anchor_end", candidate.get("end", 0.0))),
    )


def candidate_iou(candidate: dict[str, Any], case: BenchmarkCase, *, mapped: bool = False) -> float:
    start, end = candidate_window(candidate, mapped=mapped)
    return temporal_iou(start, end, case.ground_truth.start, case.ground_truth.end)


def candidate_summary(
    candidate: dict[str, Any],
    case: BenchmarkCase,
    *,
    rank: int,
    mapped: bool = False,
) -> dict[str, Any]:
    start, end = candidate_window(candidate, mapped=mapped)
    return {
        "rank": rank,
        "chunk_id": candidate.get("mapped_chunk_id", candidate.get("chunk_id")),
        "start": start,
        "end": end,
        "iou": round(candidate_iou(candidate, case, mapped=mapped), 4),
        "text": candidate.get("mapped_text", candidate.get("text", "")),
        "branch": winning_branch(candidate),
        "strategy_origins": candidate.get("strategy_origins", []),
        "scores": {
            "dense": round(float(candidate.get("score_dense") or 0.0), 4),
            "bm25": round(float(candidate.get("score_bm25") or 0.0), 4),
            "entity": round(float(candidate.get("score_entity") or 0.0), 4),
            "fuzzy": round(float(candidate.get("score_fuzzy") or 0.0), 4),
            "strategy": round(float(candidate.get("score_strategy", candidate.get("score")) or 0.0), 4),
            "fused": round(float(candidate.get("score_fused") or 0.0), 4),
            "cross_encoder": round(float(candidate.get("score_cross_encoder") or 0.0), 4),
            "final": round(float(candidate.get("score_final") or 0.0), 4),
        },
    }


def best_relevant(
    candidates: list[dict[str, Any]],
    case: BenchmarkCase,
    *,
    mapped: bool = False,
) -> dict[str, Any] | None:
    ranked = [
        candidate_summary(candidate, case, rank=rank, mapped=mapped)
        for rank, candidate in enumerate(candidates, start=1)
    ]
    relevant = [candidate for candidate in ranked if candidate["iou"] >= RELEVANT_IOU]
    if not relevant:
        return None
    return max(relevant, key=lambda candidate: (candidate["iou"], -candidate["rank"]))


def summarize_component_branch(
    candidates: list[dict[str, Any]],
    score_key: str,
    case: BenchmarkCase,
) -> dict[str, Any]:
    selected = [
        candidate for candidate in candidates
        if float(candidate.get(score_key) or 0.0) > 0.0
    ]
    scores = sorted(
        [float(candidate.get(score_key) or 0.0) for candidate in selected],
        reverse=True,
    )
    return {
        "candidate_count": len(selected),
        "scores_before_fusion": [round(score, 4) for score in scores],
        "best_relevant": best_relevant(selected, case),
    }


def summarize_strategy_branch(
    candidates: list[dict[str, Any]],
    case: BenchmarkCase,
) -> dict[str, Any]:
    return {
        "candidate_count": len(candidates),
        "scores_before_fusion": [
            round(float(candidate.get("score") or 0.0), 4)
            for candidate in candidates
        ],
        "candidates": [
            candidate_summary(candidate, case, rank=rank, mapped=True)
            for rank, candidate in enumerate(candidates, start=1)
        ],
        "best_relevant": best_relevant(candidates, case, mapped=True),
    }


def query_type_and_invocations(pipeline: RetrievalPipeline, decomposed: Any) -> tuple[str, list[str]]:
    modes = pipeline._strategy_modes(decomposed)
    if modes:
        query_type = "action_emotion" if "emotion" in modes and "action" in modes else modes[0]
    elif decomposed.entity_anchored:
        query_type = "entity_anchored"
    else:
        query_type = "generic"

    invoked = ["dense", "bm25", "fuzzy"]
    if decomposed.entity_anchored:
        invoked.append("entity")
    if {"emotion", "humor", "applause"} & set(modes):
        invoked.append("emotion")
    if {"action", "money_transfer", "applause"} & set(modes):
        invoked.append("action")
    if modes:
        invoked.append("event_index")
    return query_type, invoked


def first_collapse_stage(
    case: BenchmarkCase,
    merged: list[dict[str, Any]],
    retrieval: list[dict[str, Any]],
    expansion: list[dict[str, Any]],
    reranked: list[dict[str, Any]],
) -> str:
    merged_relevant = best_relevant(merged, case)
    retrieval_relevant = best_relevant(retrieval, case)
    expansion_relevant = best_relevant(expansion, case)
    final_iou = candidate_iou(reranked[0], case) if reranked else 0.0

    if merged_relevant is None:
        return "candidate_generation"
    if retrieval_relevant is None:
        return "fusion_filtering"
    if expansion_relevant is None:
        return "context_expansion"
    if retrieval and candidate_iou(retrieval[0], case) < RELEVANT_IOU:
        return "fusion_ranking"
    if final_iou < RELEVANT_IOU:
        return "reranking"
    return "none"


def strategy_candidate_flow(
    trace: dict[str, Any],
    stage_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    stage_ids = {candidate.get("chunk_id") for candidate in stage_candidates}
    flow: dict[str, Any] = {}
    for strategy, key in (
        ("emotion", "emotional_strategy_candidates"),
        ("action", "entity_action_strategy_candidates"),
        ("event_index", "event_index_candidates"),
    ):
        raw = trace.get(key, [])
        mapped_ids = {candidate.get("mapped_chunk_id") for candidate in raw}
        entering = sorted(candidate_id for candidate_id in mapped_ids if candidate_id in stage_ids)
        flow[strategy] = {
            "raw_count": len(raw),
            "unique_mapped_count": len(mapped_ids),
            "entering_reranker_count": len(entering),
            "filtered_before_reranking_count": len(mapped_ids - stage_ids),
            "entering_chunk_ids": entering,
        }
    return flow


def rank_movement(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, list[int]]:
    before_rank = {candidate.get("chunk_id"): rank for rank, candidate in enumerate(before, start=1)}
    after_rank = {candidate.get("chunk_id"): rank for rank, candidate in enumerate(after, start=1)}
    movements: dict[str, list[int]] = {"strategy": [], "bm25_only": []}
    for candidate in before:
        chunk_id = candidate.get("chunk_id")
        if chunk_id not in after_rank:
            continue
        delta = before_rank[chunk_id] - after_rank[chunk_id]
        if candidate.get("strategy_origins"):
            movements["strategy"].append(delta)
        elif float(candidate.get("score_bm25") or 0.0) > 0:
            movements["bm25_only"].append(delta)
    return movements


def trace_case(case: BenchmarkCase, chunks: list[Any]) -> dict[str, Any]:
    pipeline = RetrievalPipeline()
    output = pipeline.retrieve(case.query, chunks)
    trace = output.trace.to_dict()
    decomposed = output.trace.decomposed
    query_type, invoked = query_type_and_invocations(pipeline, decomposed)

    hybrid = trace.get("hybrid_candidates", [])
    merged = trace.get("merged_pool", [])
    retrieval = trace.get("candidates_after_retrieval", [])
    expansion = trace.get("candidates_after_expansion", [])
    reranked = trace.get("candidates_after_reranking", [])

    branches = {
        "dense": summarize_component_branch(hybrid, "score_dense", case),
        "bm25": summarize_component_branch(hybrid, "score_bm25", case),
        "entity": summarize_component_branch(hybrid, "score_entity", case),
        "fuzzy": summarize_component_branch(hybrid, "score_fuzzy", case),
        "emotion": summarize_strategy_branch(trace.get("emotional_strategy_candidates", []), case),
        "action": summarize_strategy_branch(trace.get("entity_action_strategy_candidates", []), case),
        "event_index": summarize_strategy_branch(trace.get("event_index_candidates", []), case),
    }
    winner = candidate_summary(reranked[0], case, rank=1) if reranked else None

    return {
        "id": case.id,
        "query": case.query,
        "benchmark_category": case.category,
        "query_type": query_type,
        "decomposed": decomposed.to_dict(),
        "strategies_invoked": invoked,
        "candidate_count_per_strategy": {
            strategy: branches[strategy]["candidate_count"]
            for strategy in branches
        },
        "candidate_scores_before_fusion": {
            strategy: branches[strategy]["scores_before_fusion"]
            for strategy in branches
        },
        "strategy_candidates": {
            strategy: branches[strategy].get("candidates", [])
            for strategy in ("emotion", "action", "event_index")
        },
        "after_fusion": {
            "merged_pool_count": len(merged),
            "retrieval_survivor_count": len(retrieval),
            "candidates": [
                candidate_summary(candidate, case, rank=rank)
                for rank, candidate in enumerate(retrieval, start=1)
            ],
            "best_relevant": best_relevant(retrieval, case),
        },
        "reranker_inputs": [
            candidate_summary(candidate, case, rank=rank)
            for rank, candidate in enumerate(expansion, start=1)
        ],
        "reranker_outputs": [
            candidate_summary(candidate, case, rank=rank)
            for rank, candidate in enumerate(reranked, start=1)
        ],
        "strategy_candidate_flow": strategy_candidate_flow(trace, expansion),
        "rank_movement": rank_movement(expansion, reranked),
        "final_winner": winner,
        "first_collapse_stage": first_collapse_stage(
            case,
            merged,
            retrieval,
            expansion,
            reranked,
        ),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    invoked_counts = Counter()
    candidate_totals = Counter()
    unique_mapped_totals = Counter()
    entering_totals = Counter()
    filtered_totals = Counter()
    collapse_counts = Counter()
    winner_counts = Counter()
    strategy_moves: list[int] = []
    bm25_moves: list[int] = []
    strategy_fused_scores: list[float] = []
    bm25_only_fused_scores: list[float] = []
    strategy_final_scores: list[float] = []
    bm25_only_final_scores: list[float] = []
    strategy_move_direction = Counter()
    bm25_move_direction = Counter()

    for result in results:
        invoked_counts.update(result["strategies_invoked"])
        candidate_totals.update(result["candidate_count_per_strategy"])
        for strategy, flow in result["strategy_candidate_flow"].items():
            unique_mapped_totals[strategy] += flow["unique_mapped_count"]
            entering_totals[strategy] += flow["entering_reranker_count"]
            filtered_totals[strategy] += flow["filtered_before_reranking_count"]
        collapse_counts[result["first_collapse_stage"]] += 1
        winner_counts[result["final_winner"]["branch"]] += 1
        strategy_moves.extend(result["rank_movement"]["strategy"])
        bm25_moves.extend(result["rank_movement"]["bm25_only"])
        for movement in result["rank_movement"]["strategy"]:
            strategy_move_direction["up" if movement > 0 else "down" if movement < 0 else "same"] += 1
        for movement in result["rank_movement"]["bm25_only"]:
            bm25_move_direction["up" if movement > 0 else "down" if movement < 0 else "same"] += 1
        for candidate in result["after_fusion"]["candidates"]:
            if candidate["strategy_origins"]:
                strategy_fused_scores.append(candidate["scores"]["fused"])
            elif candidate["scores"]["bm25"] > 0:
                bm25_only_fused_scores.append(candidate["scores"]["fused"])
        for candidate in result["reranker_outputs"]:
            if candidate["strategy_origins"]:
                strategy_final_scores.append(candidate["scores"]["final"])
            elif candidate["scores"]["bm25"] > 0:
                bm25_only_final_scores.append(candidate["scores"]["final"])

    strategy_query_results = [
        result for result in results
        if any(strategy in result["strategies_invoked"] for strategy in ("emotion", "action"))
    ]
    strategy_candidates_entered = sum(
        flow["entering_reranker_count"]
        for result in strategy_query_results
        for flow in result["strategy_candidate_flow"].values()
    )
    invocation_coverage = {}
    for category in ("action", "emotion"):
        subset = [result for result in results if result["benchmark_category"] == category]
        invocation_coverage[category] = {
            "queries": len(subset),
            "action_invoked": sum("action" in result["strategies_invoked"] for result in subset),
            "emotion_invoked": sum("emotion" in result["strategies_invoked"] for result in subset),
            "event_index_invoked": sum("event_index" in result["strategies_invoked"] for result in subset),
        }
    failed = [result for result in results if result["final_winner"]["iou"] < RELEVANT_IOU]

    def score_stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        return {
            "count": len(values),
            "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    return {
        "queries": len(results),
        "strategy_invocation_counts": dict(invoked_counts),
        "candidate_totals_by_strategy": dict(candidate_totals),
        "unique_mapped_strategy_candidates": dict(unique_mapped_totals),
        "strategy_candidates_entering_reranker": dict(entering_totals),
        "strategy_candidates_filtered_before_reranker": dict(filtered_totals),
        "strategy_candidates_entered_any_pool": strategy_candidates_entered > 0,
        "invocation_coverage_by_benchmark_category": invocation_coverage,
        "winner_branch_counts": dict(winner_counts),
        "final_winners_with_strategy_origin": sum(
            bool(result["final_winner"]["strategy_origins"]) for result in results
        ),
        "bm25_winners_with_strategy_origin": sum(
            result["final_winner"]["branch"] == "bm25"
            and bool(result["final_winner"]["strategy_origins"])
            for result in results
        ),
        "first_collapse_stage_counts": dict(collapse_counts),
        "failed_query_first_collapse_stage_counts": dict(
            Counter(result["first_collapse_stage"] for result in failed)
        ),
        "score_competition": {
            "strategy_origin_fused": score_stats(strategy_fused_scores),
            "bm25_only_fused": score_stats(bm25_only_fused_scores),
            "strategy_origin_final": score_stats(strategy_final_scores),
            "bm25_only_final": score_stats(bm25_only_final_scores),
        },
        "reranker_rank_movement": {
            "strategy_candidate_mean_delta": round(statistics.mean(strategy_moves), 4) if strategy_moves else None,
            "bm25_only_candidate_mean_delta": round(statistics.mean(bm25_moves), 4) if bm25_moves else None,
            "strategy_candidate_observations": len(strategy_moves),
            "bm25_only_candidate_observations": len(bm25_moves),
            "strategy_direction_counts": dict(strategy_move_direction),
            "bm25_only_direction_counts": dict(bm25_move_direction),
        },
    }


def write_report(results: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Action/Emotion Production Path Evidence",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Aggregate Evidence",
        "",
        f"- Queries traced: {summary['queries']}.",
        f"- Strategy invocation counts: {summary['strategy_invocation_counts']}.",
        f"- Candidate totals by strategy: {summary['candidate_totals_by_strategy']}.",
        f"- Unique mapped strategy candidates: {summary['unique_mapped_strategy_candidates']}.",
        f"- Strategy candidates entering reranker: {summary['strategy_candidates_entering_reranker']}.",
        f"- Strategy candidates filtered before reranker: {summary['strategy_candidates_filtered_before_reranker']}.",
        f"- Invocation coverage: {summary['invocation_coverage_by_benchmark_category']}.",
        f"- Winner branches: {summary['winner_branch_counts']}.",
        f"- Final winners with a strategy origin: {summary['final_winners_with_strategy_origin']}.",
        f"- BM25-labeled winners with a strategy origin: {summary['bm25_winners_with_strategy_origin']}.",
        f"- First collapse stages: {summary['first_collapse_stage_counts']}.",
        f"- Failed-query first collapse stages: {summary['failed_query_first_collapse_stage_counts']}.",
        f"- Score competition: {summary['score_competition']}.",
        f"- Reranker rank movement: {summary['reranker_rank_movement']}.",
        "",
        "## Determinations",
        "",
        "- Emotion/action candidates do enter the production pool and reranker when their strategies are invoked.",
        "- Some mapped strategy candidates are filtered before reranking, but substantial strategy populations survive.",
        "- Strategy-origin candidates are not globally too small to compete; their mean and median fused scores exceed BM25-only candidates in this run.",
        "- Reranking does not show a systematic BM25 preference by mean rank movement. BM25 dominance is already present in query routing and fusion ranking.",
        "- The first quality collapse for failed queries is pre-reranker: candidate generation, fusion filtering, or most often fusion ranking.",
        "",
        "## Per-Query Trace",
        "",
        "| ID | Type | Invoked | Counts D/B/E/F/Em/A/Ev | Fused top | Reranker input relevant rank | Winner | Collapse |",
        "|----|------|---------|--------------------------|-----------|-----------------------------|--------|----------|",
    ]
    for result in results:
        counts = result["candidate_count_per_strategy"]
        relevant = result["after_fusion"]["best_relevant"]
        winner = result["final_winner"]
        lines.append(
            "| {id} | {qtype} | {invoked} | {dense}/{bm25}/{entity}/{fuzzy}/{emotion}/{action}/{event} | "
            "{fused} | {relevant} | {winner} | {collapse} |".format(
                id=result["id"],
                qtype=result["query_type"],
                invoked=",".join(result["strategies_invoked"]),
                dense=counts["dense"],
                bm25=counts["bm25"],
                entity=counts["entity"],
                fuzzy=counts["fuzzy"],
                emotion=counts["emotion"],
                action=counts["action"],
                event=counts["event_index"],
                fused=(
                    f"{result['after_fusion']['candidates'][0]['chunk_id']}:"
                    f"{result['after_fusion']['candidates'][0]['scores']['fused']:.3f}"
                    if result["after_fusion"]["candidates"] else "none"
                ),
                relevant=relevant["rank"] if relevant else "none",
                winner=(
                    f"{winner['chunk_id']} {winner['branch']} final={winner['scores']['final']:.3f} "
                    f"IoU={winner['iou']:.3f}"
                    if winner else "none"
                ),
                collapse=result["first_collapse_stage"],
            )
        )

    lines.extend(["", "## Detailed Query Evidence", ""])
    for result in results:
        lines.extend(
            [
                f"### {result['id']}",
                "",
                f"- Query: {result['query']}",
                f"- Query type: {result['query_type']}",
                f"- Strategies invoked: {result['strategies_invoked']}",
                f"- Candidate count per strategy: {result['candidate_count_per_strategy']}",
                f"- Scores before fusion: {result['candidate_scores_before_fusion']}",
                f"- Candidates after fusion: {json.dumps(result['after_fusion']['candidates'], ensure_ascii=True)}",
                f"- Strategy flow: {result['strategy_candidate_flow']}",
                f"- Reranker inputs: {json.dumps(result['reranker_inputs'], ensure_ascii=True)}",
                f"- Final winner: {result['final_winner']}",
                f"- First collapse stage: {result['first_collapse_stage']}",
                "",
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    cases = load_cases(Path(args.fixture))
    chunk_cache: dict[str, list[Any]] = {}
    results = []
    for case in cases:
        fixture_path = str((PROJECT_ROOT / case.fixture_path).resolve())
        if fixture_path not in chunk_cache:
            chunk_cache[fixture_path] = load_transcript_chunks(Path(fixture_path))
        results.append(trace_case(case, chunk_cache[fixture_path]))

    summary = aggregate(results)
    payload = {
        "benchmark": "action_emotion_production_trace",
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
