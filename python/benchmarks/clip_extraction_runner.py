#!/usr/bin/env python3
"""
Clip-extraction benchmark runner.

Runs benchmarks/clip_extraction_benchmarks.json through the PRODUCTION
RetrievalPipeline (same path as apps/ai-service/routers/execution.py) and
produces:
  - a Benchmark Report (pass/fail, drift, failing stage)
  - the capability #10 structured production log per case
  - a machine-readable results JSON (for regression comparison)

Pass criterion: start_drift <= tolerance AND resolved window overlaps expected.

Usage:
    python python/benchmarks/clip_extraction_runner.py
    python python/benchmarks/clip_extraction_runner.py --tag prefix --compare-to ""
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

from python.models.transcript import TranscriptChunk
from python.retrieval.pipeline import RetrievalPipeline

BENCH_FILE = PROJECT_ROOT / "benchmarks" / "clip_extraction_benchmarks.json"
RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"
FIXTURES = {
    "interview_fixture": PROJECT_ROOT / "python" / "evaluation" / "fixtures" / "interview_segments.json",
}

PAD_PRE = 0.5
PAD_POST = 1.5


def _load_chunks(path: Path) -> list[TranscriptChunk]:
    segs = json.loads(path.read_text(encoding="utf-8"))
    return [TranscriptChunk.from_segment_dict(s, i) for i, s in enumerate(segs)]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def run(tag: str, compare_to: str | None) -> int:
    spec = json.loads(BENCH_FILE.read_text(encoding="utf-8"))
    benchmarks = spec["benchmarks"]

    chunk_cache: dict[str, list[TranscriptChunk]] = {}
    pipeline = RetrievalPipeline()

    results = []
    logs = []
    for b in benchmarks:
        vid = b["video_id"]
        if vid not in chunk_cache:
            chunk_cache[vid] = _load_chunks(FIXTURES[vid])
        chunks = chunk_cache[vid]

        failure_stage = None
        failure_reason = None
        try:
            res = pipeline.retrieve(b["prompt"], chunks)
            best = res.top_candidate
            tr = res.trace
            anchor_start = float(best.anchor_start)
            anchor_end = float(best.anchor_end)
            res_start = max(0.0, anchor_start - PAD_PRE)
            res_end = anchor_end + PAD_POST
        except Exception as e:  # noqa: BLE001
            res_start = res_end = 0.0
            anchor_start = anchor_end = 0.0
            best = None
            tr = None
            failure_stage = "pipeline"
            failure_reason = f"{type(e).__name__}: {e}"

        exp_s, exp_e, tol = b["expected_start_ts"], b["expected_end_ts"], b["tolerance_seconds"]
        start_drift = abs(res_start - exp_s)
        ov = _overlap(res_start, res_end, exp_s, exp_e)
        passed = failure_stage is None and start_drift <= tol and ov > 0.0

        if not passed and failure_stage is None:
            # classify failing stage from trace
            n_ret = len(tr.candidates_after_retrieval) if tr else 0
            in_top = any(
                _overlap(c["anchor_start"], c["anchor_end"], exp_s, exp_e) > 0
                for c in (tr.candidates_after_reranking[:3] if tr else [])
            )
            if n_ret == 0:
                failure_stage = "STAGE 2 - Retrieval"
                failure_reason = "no candidates retrieved"
            elif not any(
                _overlap(c["anchor_start"], c["anchor_end"], exp_s, exp_e) > 0
                for c in (tr.candidates_after_retrieval if tr else [])
            ):
                failure_stage = "STAGE 2 - Retrieval"
                failure_reason = "ground-truth region not in retrieved candidate set"
            elif in_top:
                failure_stage = "STAGE 4 - Reranking"
                failure_reason = "correct candidate retrieved & in top-3 but not ranked #1"
            else:
                failure_stage = "STAGE 4 - Reranking"
                failure_reason = "correct candidate retrieved but demoted out of top-3"

        results.append({
            "id": b["id"],
            "prompt": b["prompt"],
            "difficulty": b["difficulty"],
            "tags": b["tags"],
            "expected": [exp_s, exp_e],
            "resolved": [round(res_start, 1), round(res_end, 1)],
            "winner_chunk": best.chunk.id if best else None,
            "start_drift": round(start_drift, 1),
            "overlap_sec": round(ov, 1),
            "tolerance": tol,
            "passed": passed,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
        })
        logs.append({
            "prompt": b["prompt"],
            "intent": tr.decomposed.to_dict() if tr and tr.decomposed else None,
            "top_candidates": (tr.candidates_after_reranking[:5] if tr else []),
            "winner": best.to_dict() if best else None,
            "resolved_timestamps": [round(res_start, 2), round(res_end, 2)],
            "extraction_path": f"<ffmpeg -ss {res_start:.2f} -to {res_end:.2f}>",
            "stage_latencies": (dict(tr.stage_latencies, total_ms=tr.total_latency_ms) if tr else {}),
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
        })

    total = len(results)
    passed_n = sum(1 for r in results if r["passed"])
    pass_rate = passed_n / total if total else 0.0

    ts = datetime.now(timezone.utc).isoformat()
    print(f"BENCHMARK RESULTS - {ts}")
    print("=" * 32)
    print(f"Total:   {total}")
    print(f"Passed:  {passed_n}  ({pass_rate*100:.0f}%)")
    print(f"Failed:  {total - passed_n}  ({(1-pass_rate)*100:.0f}%)\n")
    fails = [r for r in results if not r["passed"]]
    if fails:
        print("FAILURES:")
        for r in fails:
            print(f"  {r['id']} [{r['difficulty']}] - {r['prompt']!r}")
            print(f"    Expected: {r['expected']}   Actual: {r['resolved']} (winner={r['winner_chunk']})")
            print(f"    Start drift: {r['start_drift']}s (tol {r['tolerance']}s)  overlap={r['overlap_sec']}s")
            print(f"    Failure Stage: {r['failure_stage']} - {r['failure_reason']}\n")
    else:
        print("No failures.\n")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"tag": tag, "timestamp": ts, "total": total, "passed": passed_n,
               "pass_rate": pass_rate, "results": results}
    (RESULTS_DIR / f"{tag}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (RESULTS_DIR / f"{tag}_logs.json").write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")

    if compare_to:
        prev_p = RESULTS_DIR / f"{compare_to}.json"
        if prev_p.is_file():
            prev = json.loads(prev_p.read_text(encoding="utf-8"))
            prev_pass = {r["id"]: r["passed"] for r in prev["results"]}
            regressions = [r["id"] for r in results if prev_pass.get(r["id"]) and not r["passed"]]
            print(f"REGRESSIONS vs {compare_to}: {regressions or 'None'}")
            print(f"Pass rate: {prev['pass_rate']*100:.0f}% -> {pass_rate*100:.0f}%")

    print(f"\nWrote {RESULTS_DIR / (tag + '.json')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="prefix")
    ap.add_argument("--compare-to", default=None)
    args = ap.parse_args()
    return run(args.tag, args.compare_to)


if __name__ == "__main__":
    raise SystemExit(main())
