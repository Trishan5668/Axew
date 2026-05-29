"""Compute RetrievalMetrics from semantic retrieval outputs."""

from __future__ import annotations

import math
import re
from typing import Callable, List, Optional

from python.benchmarks.retrieval_benchmark import (
    BenchmarkCase,
    RetrievalMetrics,
    SemanticRetrievalResult,
)
from python.evaluation.benchmark import ndcg_at_k, temporal_iou, window_contains_gt
from python.evaluation.benchmark import CandidateWindow


def _entity_recall(found: List[str], expected: List[str]) -> float:
    if not expected:
        return 1.0
    found_lower = " ".join(found).lower()
    hits = sum(
        1 for e in expected if e.lower() in found_lower or any(e.lower() in f.lower() for f in found)
    )
    return hits / len(expected)


def _action_recall(result: SemanticRetrievalResult, expected_type: Optional[str]) -> float:
    if not expected_type:
        return 1.0
    if result.action_type and result.action_type.upper() == expected_type.upper():
        return 1.0
    events = " ".join(result.events_found).upper()
    return 1.0 if expected_type.upper() in events else 0.0


def _monetary_match(
    result: SemanticRetrievalResult,
    amount: Optional[float],
    currency: Optional[str],
    tolerance: float = 0.01,
) -> float:
    if amount is None:
        return 1.0
    mf = result.monetary_found
    if not mf:
        return 0.0
    try:
        got_amount = float(mf.get("amount", -1))
        got_currency = str(mf.get("currency", "")).upper()
    except (TypeError, ValueError):
        return 0.0
    amount_ok = abs(got_amount - amount) <= max(tolerance, amount * 0.05)
    currency_ok = not currency or got_currency == currency.upper()
    return 1.0 if amount_ok and currency_ok else 0.0


def _speaker_match(result: SemanticRetrievalResult, expected_role: Optional[str]) -> float:
    if not expected_role:
        return 1.0
    if not result.speaker_action:
        return 0.0
    return 1.0 if expected_role.lower() in result.speaker_action.lower() else 0.0


def compute_metrics(
    cases: List[BenchmarkCase],
    retrieve_fn: Callable[[str], SemanticRetrievalResult],
) -> RetrievalMetrics:
    """Aggregate metrics across all benchmark cases."""
    if not cases:
        return RetrievalMetrics()

    ts_mae_list: List[float] = []
    within_2s: List[float] = []
    entity_recalls: List[float] = []
    action_recalls: List[float] = []
    monetary_precs: List[float] = []
    speaker_accs: List[float] = []
    reciprocal_ranks: List[float] = []
    ndcg_scores: List[float] = []
    ious: List[float] = []
    hits: List[float] = []

    for case in cases:
        result = retrieve_fn(case.prompt)
        exp = case.expected

        if case.expected_start_sec is not None and case.expected_end_sec is not None:
            gt_s, gt_e = case.expected_start_sec, case.expected_end_sec
            start_err = abs(result.start_sec - gt_s)
            end_err = abs(result.end_sec - gt_e)
            mae_sec = (start_err + end_err) / 2.0
            ts_mae_list.append(mae_sec * 1000.0)
            tol_sec = exp.timestamp_tolerance_ms / 1000.0
            within_2s.append(
                1.0 if start_err <= tol_sec and end_err <= tol_sec else 0.0
            )
            iou = temporal_iou(result.start_sec, result.end_sec, gt_s, gt_e)
            ious.append(iou)
            cands = [
                CandidateWindow(c["start_sec"], c["end_sec"], c.get("confidence", 0))
                for c in result.candidates
            ] or [CandidateWindow(result.start_sec, result.end_sec, result.confidence)]
            hits.append(
                1.0
                if window_contains_gt(
                    result.start_sec, result.end_sec, gt_s, gt_e
                )
                else 0.0
            )
            ndcg_scores.append(ndcg_at_k(cands, gt_s, gt_e, k=5))
            rr = 0.0
            for rank, c in enumerate(cands, start=1):
                if window_contains_gt(c.start_sec, c.end_sec, gt_s, gt_e):
                    rr = 1.0 / rank
                    break
            reciprocal_ranks.append(rr)

        entity_recalls.append(_entity_recall(result.entities_found, exp.entities))
        action_recalls.append(_action_recall(result, exp.action_type))
        if exp.monetary:
            monetary_precs.append(
                _monetary_match(result, exp.monetary.amount, exp.monetary.currency)
            )
        speaker_accs.append(_speaker_match(result, exp.speaker_action))

    n = len(cases)
    n_monetary = len(monetary_precs) or 1

    return RetrievalMetrics(
        timestamp_mae=sum(ts_mae_list) / max(len(ts_mae_list), 1),
        timestamp_within_2s=sum(within_2s) / max(len(within_2s), 1),
        entity_recall=sum(entity_recalls) / n,
        action_recall=sum(action_recalls) / n,
        monetary_precision=sum(monetary_precs) / n_monetary if monetary_precs else 1.0,
        mrr=sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1),
        ndcg_at_5=sum(ndcg_scores) / max(len(ndcg_scores), 1),
        speaker_accuracy=sum(speaker_accs) / n,
        mean_temporal_iou=sum(ious) / max(len(ious), 1),
        hit_rate_at_1=sum(hits) / max(len(hits), 1),
    )
