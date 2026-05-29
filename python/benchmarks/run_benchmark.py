#!/usr/bin/env python3
"""
Run semantic retrieval benchmarks and store JSON results.

Usage:
    python python/benchmarks/run_benchmark.py --tag baseline
    python python/benchmarks/run_benchmark.py --tag phase_12_complete --compare-to baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

os.environ.setdefault("AXEW_BENCHMARK", "1")

RESULTS_DIR = Path(__file__).parent / "results"
FIXTURE = PROJECT_ROOT / "python" / "evaluation" / "fixtures" / "interview_segments.json"


def _load_segments():
    with FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


def _baseline_retrieve(prompt: str, segments):
    """Embedding-only baseline (MiniLM cosine)."""
    from python.evaluation.benchmark import create_baseline_retriever

    fn = create_baseline_retriever(segments)
    out = fn(prompt)
    return _legacy_to_semantic(out)


_SEMANTIC_PIPELINE = None


def _get_semantic_pipeline(segments):
    global _SEMANTIC_PIPELINE
    if _SEMANTIC_PIPELINE is None:
        from python.retrieval.semantic_retrieval_pipeline import SemanticRetrievalPipeline

        _SEMANTIC_PIPELINE = SemanticRetrievalPipeline.from_segments(
            segments, video_id="benchmark"
        )
    return _SEMANTIC_PIPELINE


def _semantic_retrieve(prompt: str, segments):
    from python.benchmarks.retrieval_benchmark import SemanticRetrievalResult

    pipeline = _get_semantic_pipeline(segments)
    clips = pipeline.retrieve(prompt, top_k=5)
    if not clips:
        return _empty_result()
    best = clips[0]
    return SemanticRetrievalResult(
        start_sec=best.start_sec,
        end_sec=best.end_sec,
        confidence=best.confidence,
        entities_found=best.entities_found,
        events_found=best.events_found,
        monetary_found=best.monetary_found,
        speaker_action=best.speaker_breakdown.get("role") if best.speaker_breakdown else None,
        action_type=next(
            (e.split(":")[-1] for e in best.events_found if ":" in e),
            None,
        ),
        match_reasons=best.match_reasons,
        candidates=[
            {
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "confidence": c.confidence,
            }
            for c in clips
        ],
    )


def _legacy_to_semantic(out):
    from python.benchmarks.retrieval_benchmark import SemanticRetrievalResult

    return SemanticRetrievalResult(
        start_sec=out.start_sec,
        end_sec=out.end_sec,
        confidence=out.confidence,
        candidates=[
            {"start_sec": c.start_sec, "end_sec": c.end_sec, "confidence": c.confidence}
            for c in (out.candidates or [])
        ],
    )


def _empty_result():
    from python.benchmarks.retrieval_benchmark import SemanticRetrievalResult

    return SemanticRetrievalResult(0, 0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="AXEW retrieval benchmark runner")
    parser.add_argument("--tag", default="baseline", help="Result tag (e.g. baseline, phase_12_complete)")
    parser.add_argument("--output", default=str(RESULTS_DIR), help="Output directory")
    parser.add_argument("--compare-to", default=None, help="Prior tag to compare against")
    parser.add_argument("--mode", choices=["baseline", "semantic"], default="semantic")
    args = parser.parse_args()

    segments = _load_segments()
    if args.mode == "baseline":
        retrieve = lambda p: _baseline_retrieve(p, segments)
    else:
        retrieve = lambda p: _semantic_retrieve(p, segments)

    from python.benchmarks.retrieval_benchmark import BENCHMARK_CASES
    from python.benchmarks.metrics import compute_metrics

    metrics = compute_metrics(BENCHMARK_CASES, retrieve)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.tag}.json"

    payload = {
        "tag": args.tag,
        "mode": args.mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(BENCHMARK_CASES),
        "metrics": metrics.to_dict(),
    }

    if args.compare_to:
        prev_path = out_dir / f"{args.compare_to}.json"
        if prev_path.is_file():
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            prev_m = prev.get("metrics", {})
            curr_m = metrics.to_dict()
            deltas = {}
            for key in curr_m:
                if key in prev_m:
                    deltas[key] = round(curr_m[key] - prev_m[key], 4)
            payload["deltas_vs_" + args.compare_to] = deltas
            payload["regressions"] = [
                k for k, d in deltas.items() if d < -0.05
            ]

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
