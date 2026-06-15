#!/usr/bin/env python3
"""
Phase 0 runtime trace harness.

Runs the PRODUCTION retrieval/extraction path (the same one used by
apps/ai-service/routers/execution.py::_intelligent_retrieve) against a
transcript fixture and emits, for every prompt:

  - a Stage-by-Stage Execution Trace (Stages 1-6)
  - the capability #10 structured production log

Usage:
    python python/benchmarks/trace_pipeline.py
    python python/benchmarks/trace_pipeline.py --fixture path/to/segments.json --prompt "..."

This script does NOT modify any pipeline component. It only observes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.models.transcript import TranscriptChunk
from python.retrieval.pipeline import RetrievalPipeline

DEFAULT_FIXTURE = PROJECT_ROOT / "python" / "evaluation" / "fixtures" / "interview_segments.json"

CANONICAL_PROMPTS = [
    "Find where he talks about debt.",
    "Find where the interviewer gives 101 rupees to Vijay Mallya.",
    "Extract the funniest moment.",
    "Find where the audience laughs.",
    "Find where the guest reacts to the statement.",
    "Find where startup funding is discussed.",
]

# Default extraction padding used by the desktop client (PlanActionsRequest.padding_seconds)
DEFAULT_PAD_PRE = 0.5
DEFAULT_PAD_POST = 1.5


def load_chunks(fixture: Path) -> list[TranscriptChunk]:
    segs = json.loads(fixture.read_text(encoding="utf-8"))
    return [TranscriptChunk.from_segment_dict(s, i) for i, s in enumerate(segs)]


def _stage(name: str, status: str, detail: str, latency_ms: float | None = None) -> str:
    lat = f"  ({latency_ms:.1f}ms)" if latency_ms is not None else ""
    return f"  {name:<28} {status:<9}{lat}  {detail}"


def trace_one(pipeline: RetrievalPipeline, prompt: str, chunks: list[TranscriptChunk]) -> dict:
    failure_stage = None
    failure_reason = None
    t0 = time.monotonic()
    try:
        result = pipeline.retrieve(prompt, chunks)
    except Exception as e:  # noqa: BLE001
        return {
            "prompt": prompt,
            "intent": None,
            "top_candidates": [],
            "winner": None,
            "resolved_timestamps": [0.0, 0.0],
            "extraction_path": None,
            "stage_latencies": {"total_ms": (time.monotonic() - t0) * 1000},
            "failure_stage": "pipeline",
            "failure_reason": f"{type(e).__name__}: {e}",
        }

    tr = result.trace
    dq = tr.decomposed
    best = result.top_candidate

    # Stage status derivation from the real trace
    n_ret = len(tr.candidates_after_retrieval)
    n_exp = len(tr.candidates_after_expansion)
    n_rank = len(tr.candidates_after_reranking)

    intent = {
        "entities": dq.entities if dq else [],
        "actions": dq.actions if dq else [],
        "monetary_refs": dq.monetary_refs if dq else [],
        "semantic_concepts": dq.semantic_concepts if dq else [],
        "search_terms": (dq.search_terms if dq else [])[:10],
        "entity_anchored": dq.entity_anchored if dq else False,
    }

    # Extraction window = ANCHOR (retrieval) window, padded — matches execution.py
    anchor_start = float(best.anchor_start)
    anchor_end = float(best.anchor_end)
    ext_start = max(0.0, anchor_start - DEFAULT_PAD_PRE)
    ext_end = anchor_end + DEFAULT_PAD_POST

    s1 = "PASS" if intent["search_terms"] else "DEGRADED"
    s2 = "PASS" if n_ret > 0 else "FAIL"
    s3 = "PASS" if n_exp > 0 else ("DEGRADED" if n_ret > 0 else "FAIL")
    s4 = "PASS" if n_rank > 0 else "FAIL"
    s5 = "PASS" if anchor_end > anchor_start else "FAIL"
    s6 = "PASS" if ext_end > ext_start else "FAIL"

    top_candidates = [
        {
            "chunk_id": c.chunk.id,
            "anchor": [round(float(c.anchor_start), 1), round(float(c.anchor_end), 1)],
            "expanded": [round(float(c.expanded_start), 1), round(float(c.expanded_end), 1)],
            "score_calibrated": round(c.score_calibrated, 3),
            "score_fused": round(c.score_fused, 3),
            "score_cross_encoder": round(c.score_cross_encoder, 3),
            "match_quality": c.match_quality,
            "text": c.chunk.text[:90],
        }
        for c in result.all_candidates[:5]
    ]

    print(f"\n{'='*100}\nPROMPT: {prompt!r}")
    print(_stage("STAGE 1 query_understanding", s1, f"entities={intent['entities']} actions={intent['actions']} money={intent['monetary_refs']} terms={intent['search_terms'][:6]}", tr.stage_latencies.get("decompose_ms")))
    print(_stage("STAGE 2 retrieval", s2, f"candidates={n_ret} top_id={top_candidates[0]['chunk_id'] if top_candidates else None}", tr.stage_latencies.get("retrieval_ms")))
    print(_stage("STAGE 3 event_grounding/expand", s3, f"expanded={n_exp}", tr.stage_latencies.get("expansion_ms")))
    print(_stage("STAGE 4 reranking", s4, f"ranked={n_rank} winner={best.chunk.id} cal={best.score_calibrated:.3f} quality={best.match_quality}", tr.stage_latencies.get("rerank_ms")))
    print(_stage("STAGE 5 timestamp_resolution", s5, f"anchor=[{anchor_start:.1f},{anchor_end:.1f}] expanded=[{best.expanded_start:.1f},{best.expanded_end:.1f}]"))
    print(_stage("STAGE 6 extraction_window", s6, f"extract=[{ext_start:.1f},{ext_end:.1f}] (pad -{DEFAULT_PAD_PRE}/+{DEFAULT_PAD_POST})"))
    print("  top-5 candidates:")
    for c in top_candidates:
        print(f"    {c['chunk_id']:<8} anchor={c['anchor']} cal={c['score_calibrated']:<6} ce={c['score_cross_encoder']:<6} {c['match_quality']:<14} {c['text']!r}")

    if s2 == "FAIL":
        failure_stage, failure_reason = "STAGE 2 - Retrieval", "no candidates after retrieval"
    elif s4 == "FAIL":
        failure_stage, failure_reason = "STAGE 4 - Reranking", "no candidates after reranking"
    elif s5 == "FAIL":
        failure_stage, failure_reason = "STAGE 5 - Timestamp Resolution", "invalid anchor window"

    return {
        "prompt": prompt,
        "intent": intent,
        "top_candidates": top_candidates,
        "winner": {
            "chunk_id": best.chunk.id,
            "anchor": [anchor_start, anchor_end],
            "expanded": [float(best.expanded_start), float(best.expanded_end)],
            "score_calibrated": best.score_calibrated,
            "match_quality": best.match_quality,
        },
        "resolved_timestamps": [ext_start, ext_end],
        "extraction_path": f"<ffmpeg -ss {ext_start:.2f} -to {ext_end:.2f}>",
        "stage_latencies": dict(tr.stage_latencies, total_ms=tr.total_latency_ms),
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    ap.add_argument("--prompt", default=None, help="single prompt (default: 6 canonical)")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    chunks = load_chunks(Path(args.fixture))
    pipeline = RetrievalPipeline()
    prompts = [args.prompt] if args.prompt else CANONICAL_PROMPTS

    logs = [trace_one(pipeline, p, chunks) for p in prompts]

    print(f"\n{'='*100}\nSTRUCTURED PRODUCTION LOGS (capability #10):")
    print(json.dumps(logs, indent=2, ensure_ascii=False))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
