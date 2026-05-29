"""
Ground-truth benchmark cases and semantic retrieval metrics.

Run via: python python/benchmarks/run_benchmark.py --tag baseline
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MonetaryExpectation:
    amount: float
    currency: str


@dataclass
class BenchmarkExpected:
    speaker_action: Optional[str] = None
    speaker_target: Optional[str] = None
    action_type: Optional[str] = None
    monetary: Optional[MonetaryExpectation] = None
    clip_start: Optional[float] = None
    clip_end: Optional[float] = None
    timestamp_tolerance_ms: int = 2000
    entities: List[str] = field(default_factory=list)


@dataclass
class BenchmarkCase:
    id: str
    prompt: str
    expected: BenchmarkExpected
    # Temporal ground truth (seconds) from interview fixture
    expected_start_sec: Optional[float] = None
    expected_end_sec: Optional[float] = None


@dataclass
class RetrievalMetrics:
    timestamp_mae: float = 0.0
    timestamp_within_2s: float = 0.0
    entity_recall: float = 0.0
    action_recall: float = 0.0
    monetary_precision: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    speaker_accuracy: float = 0.0
    mean_temporal_iou: float = 0.0
    hit_rate_at_1: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticRetrievalResult:
    start_sec: float
    end_sec: float
    confidence: float
    entities_found: List[str] = field(default_factory=list)
    events_found: List[str] = field(default_factory=list)
    monetary_found: Optional[Dict[str, Any]] = None
    speaker_action: Optional[str] = None
    action_type: Optional[str] = None
    match_reasons: List[str] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)


BENCHMARK_CASES: List[BenchmarkCase] = [
    BenchmarkCase(
        id="monetary_transfer_001",
        prompt="Keep only the part where the interviewer gives 101 rupees to Vijay Mallya",
        expected=BenchmarkExpected(
            speaker_action="interviewer",
            speaker_target="Vijay Mallya",
            action_type="TRANSFER",
            monetary=MonetaryExpectation(amount=101, currency="INR"),
            clip_start=92.5,
            clip_end=118.5,
            entities=["Vijay Mallya", "101"],
        ),
        expected_start_sec=92.5,
        expected_end_sec=118.5,
    ),
    BenchmarkCase(
        id="monetary_transfer_002",
        prompt="Extract the part where the interviewer gives 101 rupees to Vijay Mallya",
        expected=BenchmarkExpected(
            speaker_action="interviewer",
            speaker_target="Vijay Mallya",
            action_type="TRANSFER",
            monetary=MonetaryExpectation(amount=101, currency="INR"),
            entities=["Vijay Mallya"],
        ),
        expected_start_sec=92.5,
        expected_end_sec=118.5,
    ),
    BenchmarkCase(
        id="temporal_first_001",
        prompt="First time Vijay Mallya mentions Kingfisher Airlines",
        expected=BenchmarkExpected(entities=["Kingfisher Airlines"]),
        expected_start_sec=28.0,
        expected_end_sec=45.5,
    ),
    BenchmarkCase(
        id="temporal_last_001",
        prompt="Last time he talks about coming home to India",
        expected=BenchmarkExpected(entities=["India", "home"]),
        expected_start_sec=725.0,
        expected_end_sec=740.0,
    ),
    BenchmarkCase(
        id="speaker_interviewer_001",
        prompt="When the interviewer asks about nine thousand crore rupees",
        expected=BenchmarkExpected(
            speaker_action="interviewer",
            monetary=MonetaryExpectation(amount=9000, currency="INR"),
            entities=["crore"],
        ),
        expected_start_sec=185.0,
        expected_end_sec=198.0,
    ),
    BenchmarkCase(
        id="emotion_cry_001",
        prompt="When Vijay Mallya cries or talks about crying",
        expected=BenchmarkExpected(action_type="SPEAK", entities=["Vijay Mallya"]),
        expected_start_sec=142.0,
        expected_end_sec=158.5,
    ),
    BenchmarkCase(
        id="emotion_laugh_001",
        prompt="Part where Vijay Mallya laughs about the launch party",
        expected=BenchmarkExpected(action_type="LAUGH", entities=["Vijay Mallya"]),
        expected_start_sec=55.0,
        expected_end_sec=68.3,
    ),
    BenchmarkCase(
        id="action_applause_001",
        prompt="When the audience applauds after the 101 rupees moment",
        expected=BenchmarkExpected(action_type="APPLAUD"),
        expected_start_sec=108.0,
        expected_end_sec=118.5,
    ),
    BenchmarkCase(
        id="entity_sbi_pnb_001",
        prompt="Find where SBI and PNB are mentioned as creditors",
        expected=BenchmarkExpected(entities=["SBI", "PNB"]),
        expected_start_sec=635.0,
        expected_end_sec=662.0,
    ),
    BenchmarkCase(
        id="entity_vittal_001",
        prompt="Part about Vittal Mallya and UB Group legacy",
        expected=BenchmarkExpected(entities=["Vittal Mallya", "UB Group"]),
        expected_start_sec=475.0,
        expected_end_sec=492.0,
    ),
    BenchmarkCase(
        id="monetary_fifty_crore_001",
        prompt="When he mentions fifty crore birthday party cost",
        expected=BenchmarkExpected(
            monetary=MonetaryExpectation(amount=50, currency="INR"),
            entities=["crore"],
        ),
        expected_start_sec=415.0,
        expected_end_sec=432.0,
    ),
    BenchmarkCase(
        id="action_stand_point_001",
        prompt="When Vijay Mallya stood up and pointed at the camera",
        expected=BenchmarkExpected(action_type="SPEAK", entities=["Vijay Mallya"]),
        expected_start_sec=755.0,
        expected_end_sec=770.0,
    ),
    BenchmarkCase(
        id="temporal_before_bankruptcy_001",
        prompt="Before he talks about bankruptcy pain",
        expected=BenchmarkExpected(entities=["bankruptcy"]),
        expected_start_sec=662.0,
        expected_end_sec=678.0,
    ),
    BenchmarkCase(
        id="speaker_mallya_air_deccan_001",
        prompt="When Vijay Mallya says Air Deccan was his worst decision",
        expected=BenchmarkExpected(
            speaker_action="vijay_mallya",
            entities=["Air Deccan"],
        ),
        expected_start_sec=810.0,
        expected_end_sec=825.0,
    ),
    BenchmarkCase(
        id="entity_sanjeev_kapoor_001",
        prompt="Sanjeev Kapoor designing the Kingfisher menu",
        expected=BenchmarkExpected(entities=["Sanjeev Kapoor", "Kingfisher"]),
        expected_start_sec=565.0,
        expected_end_sec=578.0,
    ),
    BenchmarkCase(
        id="emotion_fear_001",
        prompt="When he describes pure fear outside the courthouse",
        expected=BenchmarkExpected(entities=["fear", "courthouse"]),
        expected_start_sec=315.0,
        expected_end_sec=328.0,
    ),
    BenchmarkCase(
        id="monetary_101_recreate_001",
        prompt="Recreate the 101 rupees gesture on live television",
        expected=BenchmarkExpected(
            monetary=MonetaryExpectation(amount=101, currency="INR"),
            action_type="TRANSFER",
        ),
        expected_start_sec=92.5,
        expected_end_sec=108.0,
    ),
    BenchmarkCase(
        id="hook_viral_001",
        prompt="The viral clip with ten million views pointing at the lens",
        expected=BenchmarkExpected(entities=["ten million"]),
        expected_start_sec=755.0,
        expected_end_sec=770.0,
    ),
    BenchmarkCase(
        id="temporal_when_101_001",
        prompt="When the interviewer mentions the 101 rupees incident",
        expected=BenchmarkExpected(
            monetary=MonetaryExpectation(amount=101, currency="INR"),
            speaker_action="interviewer",
        ),
        expected_start_sec=68.3,
        expected_end_sec=78.0,
    ),
    BenchmarkCase(
        id="action_deny_001",
        prompt="When Vijay Mallya denies diverting funds to Formula One",
        expected=BenchmarkExpected(action_type="SPEAK", entities=["Formula One"]),
        expected_start_sec=228.0,
        expected_end_sec=245.0,
    ),
    BenchmarkCase(
        id="entity_force_india_001",
        prompt="Force India separate corporate entity financing",
        expected=BenchmarkExpected(entities=["Force India"]),
        expected_start_sec=228.0,
        expected_end_sec=245.0,
    ),
    BenchmarkCase(
        id="speaker_interviewer_welcome_001",
        prompt="Opening welcome by host Rajesh Kumar",
        expected=BenchmarkExpected(speaker_action="interviewer", entities=["Rajesh Kumar"]),
        expected_start_sec=0.0,
        expected_end_sec=8.5,
    ),
    BenchmarkCase(
        id="adversarial_similar_money_001",
        prompt="Nine thousand crore loans discussion not the 101 rupees stunt",
        expected=BenchmarkExpected(
            monetary=MonetaryExpectation(amount=9000, currency="INR"),
        ),
        expected_start_sec=185.0,
        expected_end_sec=215.5,
    ),
]
