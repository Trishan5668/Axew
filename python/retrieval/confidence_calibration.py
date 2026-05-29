"""
Retrieval confidence calibration — prefix bias, weak-set compression, opener caps.

Keeps scoring explainable without adding models or architectural churn.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from python.retrieval.event_matcher import ParsedQuery
    from python.retrieval.semantic_retrieval_pipeline import CandidateScoreBreakdown

logger = logging.getLogger(__name__)

OPENER_ABS_SEC = 5.0
OPENER_SHORT_END_SEC = 1.5
GENERIC_OPENER_PENALTY = 0.35
EARLY_WEAK_PENALTY = 0.30
OPENER_CONFIDENCE_CAP = 0.30
MIN_EXTRACT_CONFIDENCE = 0.28
MISSING_RERANK_CE = 0.0  # do not inflate with 0.5 when cross-encoder unavailable
WEAK_SET_SPREAD = 0.08
WEAK_SET_MAX = 0.38

FINANCIAL_TERMS = {
    "money",
    "rupee",
    "rupees",
    "cash",
    "payment",
    "paid",
    "pay",
    "finance",
    "crore",
    "loan",
    "amount",
    "transfer",
}


@dataclass
class CalibrationTrace:
    raw_final_score: float
    calibrated_final_score: float
    prefix_penalty: float
    opener_cap_applied: bool
    weak_set_compression: bool
    selection_reason: str


def is_semantically_specific_query(parsed: "ParsedQuery") -> bool:
    """Query expects a concrete moment, not a generic welcome/opening."""
    if parsed.monetary:
        return True
    if parsed.action_types:
        return True
    if parsed.verb and parsed.verb.lower() not in {"show", "find", "get", "keep"}:
        return True
    if parsed.object or parsed.recipient:
        return True
    if len(parsed.entities) >= 2:
        return True
    lower = parsed.raw_query.lower()
    if any(term in lower for term in FINANCIAL_TERMS):
        return True
    if re.search(r"\b\d+\s*(?:rupee|rs|crore|lakh|million|billion)\b", lower):
        return True
    return len(parsed.raw_query.split()) >= 8


def embedding_score_from_components(
    cross_encoder: float,
    fused_score: float,
    *,
    rerank_available: bool,
) -> float:
    fused = max(0.0, min(1.0, fused_score))
    if rerank_available:
        ce = max(0.0, min(1.0, cross_encoder))
        return max(0.0, min(1.0, 0.55 * ce + 0.45 * fused))
    # Missing rerank: never treat as neutral 0.5 — down-weight embedding channel.
    return max(0.0, min(1.0, 0.72 * fused))


def compute_prefix_penalty(
    start_sec: float,
    end_sec: float,
    duration_sec: float,
    *,
    action_score: float,
    monetary_score: float,
    contextual_score: float,
    entity_score: float,
    lexical_overlap: float,
) -> float:
    """Aggressive anti-prefix bias for early windows without strong evidence."""
    if duration_sec <= 0:
        duration_sec = max(end_sec, OPENER_ABS_SEC)
    in_opener = start_sec < OPENER_ABS_SEC or start_sec <= duration_sec * 0.05
    if not in_opener:
        return 0.0

    if has_strong_opener_evidence(
        action_score=action_score,
        monetary_score=monetary_score,
        contextual_score=contextual_score,
        entity_score=entity_score,
        lexical_overlap=lexical_overlap,
    ):
        return 0.0

    if end_sec <= OPENER_SHORT_END_SEC:
        return GENERIC_OPENER_PENALTY
    if start_sec < OPENER_ABS_SEC:
        return EARLY_WEAK_PENALTY
    return 0.22


def has_strong_opener_evidence(
    *,
    action_score: float,
    monetary_score: float,
    contextual_score: float,
    entity_score: float,
    lexical_overlap: float,
) -> bool:
    if action_score >= 0.78 or monetary_score >= 0.85:
        return True
    if lexical_overlap >= 0.55 and (action_score >= 0.55 or monetary_score >= 0.55):
        return True
    if entity_score >= 0.98 and lexical_overlap >= 0.40:
        return True
    if contextual_score >= 0.78 and lexical_overlap >= 0.45:
        return True
    return False


def lexical_overlap_ratio(prompt: str, text: str) -> float:
    stop = {
        "keep",
        "only",
        "part",
        "show",
        "find",
        "clip",
        "segment",
        "when",
        "where",
        "the",
        "and",
        "with",
    }
    prompt_terms = {
        t
        for t in re.findall(r"\b[a-z0-9]{3,}\b", prompt.lower())
        if t not in stop
    }
    if not prompt_terms:
        return 0.0
    text_terms = set(re.findall(r"\b[a-z0-9]{3,}\b", text.lower()))
    return len(prompt_terms & text_terms) / len(prompt_terms)


def cap_opener_confidence(
    confidence: float,
    start_sec: float,
    parsed: "ParsedQuery",
    breakdown: "CandidateScoreBreakdown",
    text: str,
) -> tuple[float, bool]:
    if start_sec >= OPENER_ABS_SEC or not is_semantically_specific_query(parsed):
        return confidence, False
    if has_strong_opener_evidence(
        action_score=breakdown.action_score,
        monetary_score=breakdown.monetary_score,
        contextual_score=breakdown.contextual_score,
        entity_score=breakdown.entity_score,
        lexical_overlap=lexical_overlap_ratio(parsed.raw_query, text),
    ):
        return confidence, False
    if confidence > OPENER_CONFIDENCE_CAP:
        return OPENER_CONFIDENCE_CAP, True
    return confidence, False


def calibrate_confidence_distribution(
    scores: Sequence[float],
) -> List[float]:
    """
    Percentile-style spread: weak clusters should not all sit near 0.45–0.55.
    """
    if not scores:
        return []
    ordered = sorted(scores, reverse=True)
    top = ordered[0]
    spread = top - ordered[-1] if len(ordered) > 1 else 0.0
    calibrated: List[float] = []

    for raw in scores:
        value = raw
        if top < WEAK_SET_MAX:
            scale = max(0.15, top / WEAK_SET_MAX)
            value *= scale
        if spread < WEAK_SET_SPREAD and len(ordered) > 1:
            # Tight cluster (e.g. 0.47–0.51): do not leave mediocre winners near 50%.
            if top > 0.35:
                value *= 0.32 / top
            rank = ordered.index(raw)
            rank_factor = 1.0 - (rank * 0.12)
            value = min(value, top * rank_factor)
        calibrated.append(max(0.0, min(1.0, round(value, 4))))
    return calibrated


def build_selection_reason(
    *,
    origin: str,
    rank: int,
    breakdown: Dict[str, Any],
    calibrated: float,
    raw: float,
    fallback_activated: bool,
    opener_cap: bool,
    weak_compression: bool,
) -> str:
    parts = [
        f"rank={rank}",
        f"origin={origin}",
        f"raw={raw:.3f}",
        f"calibrated={calibrated:.3f}",
    ]
    for key in (
        "embedding_score",
        "entity_score",
        "action_score",
        "monetary_score",
        "contextual_score",
        "prefix_penalty",
    ):
        if key in breakdown:
            parts.append(f"{key}={breakdown[key]}")
    if opener_cap:
        parts.append("opener_cap=0.30")
    if weak_compression:
        parts.append("weak_set_compression")
    if fallback_activated:
        parts.append("fallback=legacy_monetary")
    return " | ".join(parts)


def assert_opener_quality(
    parsed: "ParsedQuery",
    start_sec: float,
    confidence: float,
    breakdown: "CandidateScoreBreakdown",
    text: str,
) -> None:
    """Development assertion: specific queries must not over-score openers."""
    if start_sec >= OPENER_ABS_SEC or not is_semantically_specific_query(parsed):
        return
    if has_strong_opener_evidence(
        action_score=breakdown.action_score,
        monetary_score=breakdown.monetary_score,
        contextual_score=breakdown.contextual_score,
        entity_score=breakdown.entity_score,
        lexical_overlap=lexical_overlap_ratio(parsed.raw_query, text),
    ):
        return
    if confidence > OPENER_CONFIDENCE_CAP + 1e-6:
        logger.warning(
            "[calibration] opener cap violated: start=%.2fs conf=%.3f query=%r",
            start_sec,
            confidence,
            parsed.raw_query[:80],
        )
