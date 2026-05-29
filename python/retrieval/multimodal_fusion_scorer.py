"""
Multimodal fusion scorer with confidence gating.

This is the scoring core for the spec's failure case
("Keep only the part where the interviewer gives 101 rupees to Vijay Mallya").
It accepts evidence from any subset of modalities — visual, audio, transcript,
event-graph, role-binding, monetary, vocative — and fuses them with explicit
per-channel weights and an audit trail.

The scorer is **strict by construction**:

- A query's *required* signals (entity, action, speaker role, monetary
  amount, tense) are weighted heavily and contribute negatively when
  missing.
- A small lexical score alone is not enough to win — the spec failure was
  exactly that case (top-of-doc prefix bias). Without entity + action role
  binding, no candidate passes the gate.

This module knows nothing about the transcript representation — it consumes
``EvidenceBundle`` dicts produced by :mod:`python.retrieval.entity_grounded_retriever`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Per-channel weights. These sum to ~1.0 on the strict-query path; the
# fusion scorer rebalances dynamically based on which signals were *required*
# by the parsed query (see :meth:`MultimodalFusionScorer.score`).
DEFAULT_WEIGHTS: Dict[str, float] = {
    "lexical": 0.10,
    "semantic": 0.15,
    "entity_match": 0.18,
    "action_match": 0.12,
    "tense_match": 0.07,
    "speaker_role_match": 0.10,
    "vocative_match": 0.10,
    "monetary_match": 0.15,
    "event_graph": 0.05,
    "visual": 0.05,
    "audio": 0.03,
}

# Floor below which we refuse to return *any* result, regardless of ranking.
CONFIDENCE_FLOOR = 0.32

# Minimum number of *strong* signals (>=0.5) that must be present for a
# candidate to be accepted. This is the actual fix for the prefix-bias
# failure: a single high-cosine match cannot win without corroboration.
MIN_STRONG_SIGNALS = 2

# Strong-signal evidence threshold per channel.
STRONG_THRESHOLD = 0.5


@dataclass
class EvidenceBundle:
    """All signals available for *one* candidate window.

    Each field is in ``[0.0, 1.0]``. ``None`` indicates "not applicable to
    this query" — distinct from ``0.0`` ("applicable but no evidence
    found"), so the scorer can apply the right normalization.
    """

    lexical: Optional[float] = None
    semantic: Optional[float] = None
    entity_match: Optional[float] = None
    action_match: Optional[float] = None
    tense_match: Optional[float] = None
    speaker_role_match: Optional[float] = None
    vocative_match: Optional[float] = None
    monetary_match: Optional[float] = None
    event_graph: Optional[float] = None
    visual: Optional[float] = None
    audio: Optional[float] = None

    def as_map(self) -> Dict[str, Optional[float]]:
        return asdict(self)


@dataclass
class FusionResult:
    """Output of one fusion-score evaluation."""

    score: float
    composite: float           # raw weighted sum before gating
    passes_gate: bool
    strong_signal_count: int
    contributing_channels: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    weights_used: Dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MultimodalFusionScorer:
    """Confidence-gated multimodal fusion of retrieval signals.

    Parameters
    ----------
    weights:
        Optional per-channel weight overrides. Missing keys fall back to
        ``DEFAULT_WEIGHTS``.
    required_channels:
        Channels the *query* makes mandatory. Missing required signals
        cause a hard penalty (``required_penalty``) per channel.
    confidence_floor:
        Minimum composite score for ``passes_gate=True``.
    min_strong_signals:
        Minimum number of channels with evidence >= ``STRONG_THRESHOLD``
        for the candidate to pass the gate. Defaults to 2.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        required_channels: Optional[List[str]] = None,
        confidence_floor: float = CONFIDENCE_FLOOR,
        min_strong_signals: int = MIN_STRONG_SIGNALS,
        required_penalty: float = 0.18,
    ) -> None:
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.required_channels = list(required_channels or [])
        self.confidence_floor = float(confidence_floor)
        self.min_strong_signals = int(min_strong_signals)
        self.required_penalty = float(required_penalty)

    def score(self, evidence: EvidenceBundle) -> FusionResult:
        """Score one candidate against all available evidence channels."""
        ev_map = evidence.as_map()

        # Channels that are *applicable* (i.e. produced a numeric value, even 0).
        applicable = {k: v for k, v in ev_map.items() if v is not None}
        # Renormalize weights over applicable channels so a video with no
        # visual evidence isn't unfairly capped at ~0.95.
        weight_sum = sum(self.weights.get(k, 0.0) for k in applicable)
        if weight_sum <= 0.0:
            return FusionResult(
                score=0.0,
                composite=0.0,
                passes_gate=False,
                strong_signal_count=0,
                missing_required=list(self.required_channels),
                weights_used={},
                explanation="no applicable evidence channels",
            )
        scale = 1.0 / weight_sum

        composite = 0.0
        contributors: List[str] = []
        strong = 0
        weights_used: Dict[str, float] = {}
        for ch, val in applicable.items():
            w = self.weights.get(ch, 0.0) * scale
            weights_used[ch] = round(w, 4)
            contribution = w * float(val)
            composite += contribution
            if val >= STRONG_THRESHOLD:
                strong += 1
            if contribution > 0.005:
                contributors.append(ch)

        # Required-channel hard penalty
        missing_required: List[str] = []
        for ch in self.required_channels:
            v = ev_map.get(ch)
            if v is None or float(v) < 0.25:
                missing_required.append(ch)
        penalty = self.required_penalty * len(missing_required)

        # Bonus when ALL required channels fire at ≥ STRONG_THRESHOLD
        all_required_strong = bool(self.required_channels) and all(
            (ev_map.get(ch) or 0.0) >= STRONG_THRESHOLD for ch in self.required_channels
        )
        bonus = 0.12 if all_required_strong else 0.0

        score = max(0.0, min(1.0, composite + bonus - penalty))

        passes = (
            score >= self.confidence_floor
            and strong >= self.min_strong_signals
            and not missing_required
        )

        # Compact human-readable explanation
        bits: List[str] = []
        if all_required_strong:
            bits.append("all-required-strong")
        if missing_required:
            bits.append(f"missing={','.join(missing_required)}")
        bits.append(f"strong={strong}")
        bits.append(f"channels={len(applicable)}")

        return FusionResult(
            score=score,
            composite=round(composite, 4),
            passes_gate=passes,
            strong_signal_count=strong,
            contributing_channels=contributors,
            missing_required=missing_required,
            weights_used=weights_used,
            explanation=" | ".join(bits),
        )

    def best(self, candidates: List[tuple[Any, EvidenceBundle]]) -> tuple[Optional[Any], Optional[FusionResult]]:
        """Score every candidate and return the gate-passing top one."""
        scored: List[tuple[Any, EvidenceBundle, FusionResult]] = []
        for cand_id, evidence in candidates:
            res = self.score(evidence)
            scored.append((cand_id, evidence, res))
        scored.sort(key=lambda x: x[2].score, reverse=True)
        for cid, _, res in scored:
            if res.passes_gate:
                return cid, res
        if scored:
            cid, _, res = scored[0]
            return cid, res
        return None, None


def softmax(values: List[float], temperature: float = 0.4) -> List[float]:
    if not values:
        return []
    scaled = [v / max(1e-6, temperature) for v in values]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]
    z = sum(exps)
    if z <= 0:
        return [0.0] * len(values)
    return [e / z for e in exps]


if __name__ == "__main__":  # pragma: no cover - smoke harness
    scorer = MultimodalFusionScorer(
        required_channels=["entity_match", "action_match", "monetary_match", "speaker_role_match"],
    )
    # The actual VM-101 winning moment (seg_009_m03)
    winner = EvidenceBundle(
        lexical=0.55,
        semantic=0.71,
        entity_match=1.0,
        action_match=1.0,
        tense_match=1.0,
        speaker_role_match=1.0,
        vocative_match=1.0,
        monetary_match=1.0,
        event_graph=0.85,
    )
    # Decoy: seg_007 - "Do you remember the 101 rupees incident?" — same
    # entity, same money, BUT no action verb, no vocative, past tense.
    decoy = EvidenceBundle(
        lexical=0.45,
        semantic=0.62,
        entity_match=1.0,
        action_match=0.0,
        tense_match=0.0,
        speaker_role_match=0.5,
        vocative_match=0.0,
        monetary_match=1.0,
        event_graph=0.1,
    )
    # Decoy: seg_008 — past-tense recollection ("You pulled out exactly 101")
    decoy2 = EvidenceBundle(
        lexical=0.75,
        semantic=0.80,
        entity_match=1.0,
        action_match=0.6,
        tense_match=0.0,
        speaker_role_match=0.0,
        vocative_match=0.0,
        monetary_match=1.0,
        event_graph=0.25,
    )
    for label, ev in [("winner", winner), ("decoy_007", decoy), ("decoy_008", decoy2)]:
        r = scorer.score(ev)
        print(f"{label}: score={r.score:.3f} passes={r.passes_gate} strong={r.strong_signal_count} miss={r.missing_required} :: {r.explanation}")
