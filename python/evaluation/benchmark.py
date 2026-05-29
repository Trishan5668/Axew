"""
Retrieval evaluation benchmark for AXEW.

Run baseline:
    python -m python.evaluation.benchmark

Or from project root:
    python python/evaluation/benchmark.py
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPORTS_DIR = Path(__file__).parent / "reports"


class Difficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    ADVERSARIAL = "ADVERSARIAL"


@dataclass
class RetrievalBenchmark:
    query: str
    expected_start_sec: float
    expected_end_sec: float
    expected_speaker: Optional[str]
    expected_entities: List[str]
    difficulty: Difficulty
    case_id: str = ""


@dataclass
class CandidateWindow:
    start_sec: float
    end_sec: float
    confidence: float


@dataclass
class RetrievalOutput:
    """Result from a retrieval function for one query."""

    start_sec: float
    end_sec: float
    confidence: float
    candidates: List[CandidateWindow] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    query: str
    difficulty: str
    temporal_iou: float
    start_error_sec: float
    end_error_sec: float
    timestamp_mae: float
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    ndcg_at_5: float
    predicted_start: float
    predicted_end: float
    confidence: float


@dataclass
class DifficultyBreakdown:
    count: int
    mean_temporal_iou: float
    mean_timestamp_mae: float
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    mean_ndcg_at_5: float


@dataclass
class EvaluationReport:
    timestamp: str
    phase: str
    total_cases: int
    mean_temporal_iou: float
    mean_timestamp_mae: float
    mean_start_error_sec: float
    mean_end_error_sec: float
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    mean_ndcg_at_5: float
    by_difficulty: Dict[str, DifficultyBreakdown]
    case_results: List[CaseResult]
    metadata: Dict[str, Any] = field(default_factory=dict)


class RetrievalFn(Protocol):
    def __call__(self, query: str) -> RetrievalOutput: ...


def temporal_iou(
    pred_start: float,
    pred_end: float,
    gt_start: float,
    gt_end: float,
) -> float:
    from python.retrieval.native_temporal import compute_temporal_iou

    return compute_temporal_iou(pred_start, pred_end, gt_start, gt_end)


def window_contains_gt(
    pred_start: float,
    pred_end: float,
    gt_start: float,
    gt_end: float,
    tolerance_sec: float = 3.0,
) -> bool:
    """Hit if predicted window overlaps GT with IoU >= 0.3 or start/end within tolerance."""
    iou = temporal_iou(pred_start, pred_end, gt_start, gt_end)
    if iou >= 0.3:
        return True
    start_ok = abs(pred_start - gt_start) <= tolerance_sec
    end_ok = abs(pred_end - gt_end) <= tolerance_sec
    return start_ok and end_ok


def ndcg_at_k(
    ranked: List[CandidateWindow],
    gt_start: float,
    gt_end: float,
    k: int = 5,
) -> float:
    if not ranked:
        return 0.0

    def relevance(start: float, end: float) -> float:
        return temporal_iou(start, end, gt_start, gt_end)

    dcg = 0.0
    for i, cand in enumerate(ranked[:k]):
        rel = relevance(cand.start_sec, cand.end_sec)
        if rel > 0:
            dcg += rel / math.log2(i + 2)

    ideal = sorted(
        [relevance(c.start_sec, c.end_sec) for c in ranked],
        reverse=True,
    )[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal) if rel > 0)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def evaluate_retrieval(
    retrieval_fn: RetrievalFn,
    benchmark_cases: List[RetrievalBenchmark],
    phase: str = "baseline",
) -> EvaluationReport:
    case_results: List[CaseResult] = []

    for bench in benchmark_cases:
        output = retrieval_fn(bench.query)
        candidates = output.candidates or [
            CandidateWindow(output.start_sec, output.end_sec, output.confidence)
        ]

        iou = temporal_iou(
            output.start_sec,
            output.end_sec,
            bench.expected_start_sec,
            bench.expected_end_sec,
        )
        start_err = abs(output.start_sec - bench.expected_start_sec)
        end_err = abs(output.end_sec - bench.expected_end_sec)
        mae = (start_err + end_err) / 2.0

        hit1 = window_contains_gt(
            candidates[0].start_sec if candidates else output.start_sec,
            candidates[0].end_sec if candidates else output.end_sec,
            bench.expected_start_sec,
            bench.expected_end_sec,
        )
        hit3 = any(
            window_contains_gt(c.start_sec, c.end_sec, bench.expected_start_sec, bench.expected_end_sec)
            for c in candidates[:3]
        )
        hit5 = any(
            window_contains_gt(c.start_sec, c.end_sec, bench.expected_start_sec, bench.expected_end_sec)
            for c in candidates[:5]
        )
        ndcg5 = ndcg_at_k(candidates, bench.expected_start_sec, bench.expected_end_sec, k=5)

        case_results.append(
            CaseResult(
                case_id=bench.case_id,
                query=bench.query,
                difficulty=bench.difficulty.value,
                temporal_iou=iou,
                start_error_sec=start_err,
                end_error_sec=end_err,
                timestamp_mae=mae,
                hit_at_1=hit1,
                hit_at_3=hit3,
                hit_at_5=hit5,
                ndcg_at_5=ndcg5,
                predicted_start=output.start_sec,
                predicted_end=output.end_sec,
                confidence=output.confidence,
            )
        )

    def aggregate(cases: List[CaseResult]) -> DifficultyBreakdown:
        if not cases:
            return DifficultyBreakdown(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        n = len(cases)
        return DifficultyBreakdown(
            count=n,
            mean_temporal_iou=sum(c.temporal_iou for c in cases) / n,
            mean_timestamp_mae=sum(c.timestamp_mae for c in cases) / n,
            hit_rate_at_1=sum(1 for c in cases if c.hit_at_1) / n,
            hit_rate_at_3=sum(1 for c in cases if c.hit_at_3) / n,
            hit_rate_at_5=sum(1 for c in cases if c.hit_at_5) / n,
            mean_ndcg_at_5=sum(c.ndcg_at_5 for c in cases) / n,
        )

    by_diff: Dict[str, DifficultyBreakdown] = {}
    for diff in Difficulty:
        subset = [c for c in case_results if c.difficulty == diff.value]
        by_diff[diff.value] = aggregate(subset)

    n = len(case_results)
    report = EvaluationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        phase=phase,
        total_cases=n,
        mean_temporal_iou=sum(c.temporal_iou for c in case_results) / n,
        mean_timestamp_mae=sum(c.timestamp_mae for c in case_results) / n,
        mean_start_error_sec=sum(c.start_error_sec for c in case_results) / n,
        mean_end_error_sec=sum(c.end_error_sec for c in case_results) / n,
        hit_rate_at_1=sum(1 for c in case_results if c.hit_at_1) / n,
        hit_rate_at_3=sum(1 for c in case_results if c.hit_at_3) / n,
        hit_rate_at_5=sum(1 for c in case_results if c.hit_at_5) / n,
        mean_ndcg_at_5=sum(c.ndcg_at_5 for c in case_results) / n,
        by_difficulty={k: v for k, v in by_diff.items()},
        case_results=case_results,
    )
    return report


def report_to_dict(report: EvaluationReport) -> Dict[str, Any]:
    def serialize(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: serialize(v) for k, v in asdict(obj).items()}
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        return obj

    return serialize(report)


def create_phase7_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 7: orchestrator + conversational context."""
    from python.evaluation.phase7_retriever import Phase7Retriever

    return Phase7Retriever(segments)


def save_report(report: EvaluationReport, phase: str = "baseline") -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{phase}_{ts}.json"

    def serialize(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: serialize(v) for k, v in asdict(obj).items()}
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        return obj

    with path.open("w", encoding="utf-8") as f:
        json.dump(serialize(report), f, indent=2)
    return path


def load_fixture_segments() -> List[Dict[str, Any]]:
    fixture_path = FIXTURES_DIR / "interview_segments.json"
    with fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Benchmark cases (30+ covering all query types from spec)
# ---------------------------------------------------------------------------

BENCHMARK_CASES: List[RetrievalBenchmark] = [
    # --- Named entity queries ---
    RetrievalBenchmark(
        case_id="ent_001",
        query="Extract the part where the interviewer gives 101 rupees to Vijay Mallya",
        expected_start_sec=92.5,
        expected_end_sec=118.5,
        expected_speaker="interviewer",
        expected_entities=["Vijay Mallya", "101 rupees"],
        difficulty=Difficulty.HARD,
    ),
    RetrievalBenchmark(
        case_id="ent_002",
        query="When does Vijay Mallya talk about Kingfisher Airlines launch in 2005",
        expected_start_sec=28.0,
        expected_end_sec=45.5,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya", "Kingfisher Airlines", "2005"],
        difficulty=Difficulty.EASY,
    ),
    RetrievalBenchmark(
        case_id="ent_003",
        query="Find where SBI and PNB are mentioned as creditors",
        expected_start_sec=635.0,
        expected_end_sec=662.0,
        expected_speaker="vijay_mallya",
        expected_entities=["SBI", "PNB"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="ent_004",
        query="Part about Vittal Mallya and the UB Group legacy",
        expected_start_sec=475.0,
        expected_end_sec=492.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vittal Mallya", "UB Group"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="ent_005",
        query="When Sanjeev Kapoor and the airline menu are discussed",
        expected_start_sec=565.0,
        expected_end_sec=578.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Sanjeev Kapoor"],
        difficulty=Difficulty.MEDIUM,
    ),
    # --- Emotional moment queries ---
    RetrievalBenchmark(
        case_id="emo_001",
        query="Keep only emotional moments where Vijay Mallya cries",
        expected_start_sec=142.0,
        expected_end_sec=158.5,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="emo_002",
        query="Find where he says he wants to come home and gets tearful",
        expected_start_sec=702.0,
        expected_end_sec=725.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="emo_003",
        query="The moment Vijay Mallya admits he was shocked by the court verdict",
        expected_start_sec=168.0,
        expected_end_sec=185.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.EASY,
    ),
    RetrievalBenchmark(
        case_id="emo_004",
        query="Find the fearful moment outside the courthouse with protesters",
        expected_start_sec=315.0,
        expected_end_sec=328.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="emo_005",
        query="Emotional apology to Kingfisher employees who lost jobs",
        expected_start_sec=372.0,
        expected_end_sec=388.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Kingfisher"],
        difficulty=Difficulty.EASY,
    ),
    # --- Action queries ---
    RetrievalBenchmark(
        case_id="act_001",
        query="When the interviewer hands over money to Vijay Mallya on live TV",
        expected_start_sec=92.5,
        expected_end_sec=118.5,
        expected_speaker="interviewer",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.HARD,
    ),
    RetrievalBenchmark(
        case_id="act_002",
        query="Find where Vijay Mallya stands up and points at the camera",
        expected_start_sec=755.0,
        expected_end_sec=770.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="act_003",
        query="When Vijay Mallya laughs about the launch party",
        expected_start_sec=55.0,
        expected_end_sec=68.3,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.EASY,
    ),
    RetrievalBenchmark(
        case_id="act_004",
        query="The audience applauding and cheering section",
        expected_start_sec=838.0,
        expected_end_sec=860.0,
        expected_speaker="narrator",
        expected_entities=[],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="act_005",
        query="When studio audience erupts in laughter after the 101 rupees stunt",
        expected_start_sec=108.0,
        expected_end_sec=118.5,
        expected_speaker="narrator",
        expected_entities=["101 rupees"],
        difficulty=Difficulty.HARD,
    ),
    # --- Temporal qualifier queries ---
    RetrievalBenchmark(
        case_id="tmp_001",
        query="First time Kingfisher Airlines is mentioned in the interview",
        expected_start_sec=28.0,
        expected_end_sec=45.5,
        expected_speaker="vijay_mallya",
        expected_entities=["Kingfisher Airlines"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="tmp_002",
        query="Last time the topic of employees who lost jobs comes up",
        expected_start_sec=372.0,
        expected_end_sec=388.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Kingfisher"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="tmp_003",
        query="Around ten minutes in when Kingfisher First class service is described",
        expected_start_sec=535.0,
        expected_end_sec=552.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Kingfisher First"],
        difficulty=Difficulty.HARD,
    ),
    RetrievalBenchmark(
        case_id="tmp_004",
        query="When the idea for Kingfisher was first conceived in 2003",
        expected_start_sec=342.0,
        expected_end_sec=358.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Kingfisher", "2003"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="tmp_005",
        query="The first mention of bankruptcy in the word association game",
        expected_start_sec=662.0,
        expected_end_sec=685.0,
        expected_speaker="interviewer",
        expected_entities=["bankruptcy"],
        difficulty=Difficulty.EASY,
    ),
    # --- Multi-speaker queries ---
    RetrievalBenchmark(
        case_id="spk_001",
        query="When the interviewer asks about the 101 rupees incident and Vijay responds",
        expected_start_sec=68.3,
        expected_end_sec=92.5,
        expected_speaker="interviewer",
        expected_entities=["101 rupees", "Vijay Mallya"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="spk_002",
        query="Exchange where interviewer calls his Dubai answer a politician's answer",
        expected_start_sec=608.0,
        expected_end_sec=635.0,
        expected_speaker="interviewer",
        expected_entities=[],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="spk_003",
        query="When the interviewer says the audience is gasping at fifty crore birthday cost",
        expected_start_sec=432.0,
        expected_end_sec=445.0,
        expected_speaker="interviewer",
        expected_entities=[],
        difficulty=Difficulty.EASY,
    ),
    # --- Scene / topical queries ---
    RetrievalBenchmark(
        case_id="scn_001",
        query="Part about the bankruptcy proceedings in London",
        expected_start_sec=130.0,
        expected_end_sec=158.5,
        expected_speaker="interviewer",
        expected_entities=["bankruptcy", "London"],
        difficulty=Difficulty.EASY,
    ),
    RetrievalBenchmark(
        case_id="scn_002",
        query="Discussion about nine thousand crore rupees in bank loans",
        expected_start_sec=185.0,
        expected_end_sec=215.5,
        expected_speaker="interviewer",
        expected_entities=["nine thousand crore"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="scn_003",
        query="The Air Deccan acquisition regret segment",
        expected_start_sec=810.0,
        expected_end_sec=825.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Air Deccan"],
        difficulty=Difficulty.EASY,
    ),
    RetrievalBenchmark(
        case_id="scn_004",
        query="Goa beach sixtieth birthday party with fifty crore cost",
        expected_start_sec=415.0,
        expected_end_sec=432.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Goa", "fifty crore"],
        difficulty=Difficulty.MEDIUM,
    ),
    RetrievalBenchmark(
        case_id="scn_005",
        query="Extradition hearings and walking along the Thames in London",
        expected_start_sec=285.0,
        expected_end_sec=302.0,
        expected_speaker="vijay_mallya",
        expected_entities=["London", "extradition"],
        difficulty=Difficulty.MEDIUM,
    ),
    # --- Adversarial / tricky queries ---
    RetrievalBenchmark(
        case_id="adv_001",
        query="When he received money from the host",
        expected_start_sec=92.5,
        expected_end_sec=118.5,
        expected_speaker="vijay_mallya",
        expected_entities=["Vijay Mallya"],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_002",
        query="The viral moment that got ten million views",
        expected_start_sec=755.0,
        expected_end_sec=782.0,
        expected_speaker="vijay_mallya",
        expected_entities=[],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_003",
        query="Strongest hook for a viral short from this interview",
        expected_start_sec=755.0,
        expected_end_sec=770.0,
        expected_speaker="vijay_mallya",
        expected_entities=[],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_004",
        query="Find the part about starting small with a single coin",
        expected_start_sec=92.5,
        expected_end_sec=108.0,
        expected_speaker="interviewer",
        expected_entities=[],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_005",
        query="When he denies diverting funds to Formula One",
        expected_start_sec=228.0,
        expected_end_sec=245.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Formula One"],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_006",
        query="Keep only the part where the businessman talks about his father dying",
        expected_start_sec=505.0,
        expected_end_sec=520.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Vittal Mallya"],
        difficulty=Difficulty.ADVERSARIAL,
    ),
    RetrievalBenchmark(
        case_id="adv_007",
        query="Find when Force India financing structure is explained",
        expected_start_sec=228.0,
        expected_end_sec=245.0,
        expected_speaker="vijay_mallya",
        expected_entities=["Force India"],
        difficulty=Difficulty.HARD,
    ),
    RetrievalBenchmark(
        case_id="adv_008",
        query="Closing segment where he says every empire starts with 101 rupees",
        expected_start_sec=838.0,
        expected_end_sec=850.0,
        expected_speaker="vijay_mallya",
        expected_entities=["101 rupees"],
        difficulty=Difficulty.MEDIUM,
    ),
]


def create_baseline_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Wrap current AXEW semantic search (all-MiniLM-L6-v2 cosine similarity)."""
    from python.evaluation.baseline_retriever import BaselineRetriever

    return BaselineRetriever(segments)


def create_phase1_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 1: hierarchical sentence-level chunk retrieval."""
    from python.evaluation.phase1_retriever import Phase1Retriever

    return Phase1Retriever(segments)


def create_phase2_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 2: entity and event-aware retrieval."""
    from python.evaluation.phase2_retriever import Phase2Retriever

    return Phase2Retriever(segments)


def create_phase3_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 3: hybrid BGE + BM25 retrieval."""
    from python.evaluation.phase34_retriever import Phase3Retriever

    return Phase3Retriever(segments)


def create_phase4_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 4: full multi-stage orchestrator."""
    from python.evaluation.phase34_retriever import Phase4Retriever

    return Phase4Retriever(segments)


def create_phase5_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 5: orchestrator + timestamp refinement."""
    from python.evaluation.phase56_retriever import Phase5Retriever

    return Phase5Retriever(segments)


def create_phase6_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 6: Phase 5 + multimodal when media available."""
    from python.evaluation.phase56_retriever import Phase6Retriever

    return Phase6Retriever(segments)


def create_phase16_retriever(segments: List[Dict[str, Any]]) -> RetrievalFn:
    """Phase 16: entity-grounded multimodal-aware deterministic retriever.

    Solves the spec's "VM 101 rupees" failure class via:
      * hierarchical moment/segment/scene re-chunking
      * tense + action + speaker-role + vocative + monetary scoring
      * confidence-gated multimodal fusion
      * frame-precise timestamp anchoring with reaction-window extension
    """
    from python.evaluation.phase16_retriever import Phase16Retriever

    return Phase16Retriever(segments)


def print_report_summary(report: EvaluationReport) -> None:
    print(f"\n{'=' * 60}")
    print(f"AXEW Retrieval Benchmark — {report.phase.upper()}")
    print(f"{'=' * 60}")
    print(f"Timestamp:          {report.timestamp}")
    print(f"Total cases:        {report.total_cases}")
    print(f"Mean Temporal IoU:  {report.mean_temporal_iou:.3f}")
    print(f"Mean Timestamp MAE: {report.mean_timestamp_mae:.2f}s")
    print(f"Hit Rate @1:        {report.hit_rate_at_1:.1%}")
    print(f"Hit Rate @3:        {report.hit_rate_at_3:.1%}")
    print(f"Hit Rate @5:        {report.hit_rate_at_5:.1%}")
    print(f"Mean NDCG@5:        {report.mean_ndcg_at_5:.3f}")
    print(f"\nBy difficulty:")
    for diff, stats in report.by_difficulty.items():
        if stats.count == 0:
            continue
        print(
            f"  {diff:12s} n={stats.count:2d}  "
            f"IoU={stats.mean_temporal_iou:.3f}  "
            f"Hit@1={stats.hit_rate_at_1:.1%}  "
            f"MAE={stats.mean_timestamp_mae:.1f}s"
        )
    print(f"{'=' * 60}\n")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="AXEW retrieval benchmark")
    parser.add_argument(
        "--phase",
        choices=[
            "baseline", "phase1", "phase2", "phase3", "phase4", "phase5",
            "phase6", "phase7", "phase16",
        ],
        default="baseline",
        help="Which retrieval pipeline to benchmark",
    )
    args = parser.parse_args()

    # Ensure project root is on sys.path
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    segments = load_fixture_segments()

    if args.phase == "phase16":
        retrieval_fn = create_phase16_retriever(segments)
        phase_name = "phase16"
    elif args.phase == "phase7":
        retrieval_fn = create_phase7_retriever(segments)
        phase_name = "phase7"
    elif args.phase == "phase6":
        retrieval_fn = create_phase6_retriever(segments)
        phase_name = "phase6"
    elif args.phase == "phase5":
        retrieval_fn = create_phase5_retriever(segments)
        phase_name = "phase5"
    elif args.phase == "phase4":
        retrieval_fn = create_phase4_retriever(segments)
        phase_name = "phase4"
    elif args.phase == "phase3":
        retrieval_fn = create_phase3_retriever(segments)
        phase_name = "phase3"
    elif args.phase == "phase2":
        retrieval_fn = create_phase2_retriever(segments)
        phase_name = "phase2"
    elif args.phase == "phase1":
        retrieval_fn = create_phase1_retriever(segments)
        phase_name = "phase1"
    else:
        retrieval_fn = create_baseline_retriever(segments)
        phase_name = "baseline"

    print(f"Running {phase_name} retrieval benchmark...")
    report = evaluate_retrieval(retrieval_fn, BENCHMARK_CASES, phase=phase_name)
    report_path = save_report(report, phase=phase_name)
    print_report_summary(report)
    print(f"Report saved to: {report_path}")

    # Highlight the critical test case
    critical = next((c for c in report.case_results if c.case_id == "ent_001"), None)
    if critical:
        print("Critical case (101 rupees -> Vijay Mallya):")
        print(f"  Hit@1: {critical.hit_at_1}")
        print(f"  IoU:   {critical.temporal_iou:.3f}")
        print(f"  MAE:   {critical.timestamp_mae:.1f}s")
        print(f"  Pred:  {critical.predicted_start:.1f}s – {critical.predicted_end:.1f}s")
        print(f"  GT:    92.5s – 118.5s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
