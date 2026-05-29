#!/usr/bin/env python3
"""Focused benchmark for event grounding and executable action planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.retrieval.semantic_retrieval_pipeline import SemanticRetrievalPipeline

FIXTURE = PROJECT_ROOT / "python" / "evaluation" / "fixtures" / "interview_segments.json"

BENCHMARK_PROMPTS = {
    "EASY": "Find where Vijay Mallya speaks",
    "MEDIUM": "Find where interviewer laughs",
    "HARD": "Find where interviewer gives money",
    "ADVANCED": "Keep only the part where interviewer gives 101 rupees to Vijay Mallya",
}


def load_segments():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def main() -> int:
    segments = load_segments()
    pipeline = SemanticRetrievalPipeline.from_segments(segments, video_id="benchmark")

    results = {}
    for label, prompt in BENCHMARK_PROMPTS.items():
        clips = pipeline.retrieve(prompt, top_k=5)
        best = clips[0] if clips else None
        planner = best.debug_info.get("planner", {}) if best else {}
        results[label] = {
            "prompt": prompt,
            "best_clip": {
                "start_sec": best.start_sec,
                "end_sec": best.end_sec,
                "confidence": best.confidence,
                "suggested_action": best.suggested_action,
                "requires_confirmation": best.requires_confirmation,
                "reasoning": best.reasoning,
            }
            if best
            else None,
            "retrieval_scores": [
                {
                    "start_sec": clip.start_sec,
                    "end_sec": clip.end_sec,
                    "confidence": clip.confidence,
                    "events_found": clip.events_found,
                    "match_reasons": clip.match_reasons,
                }
                for clip in clips
            ],
            "event_matches": planner.get("event_scores", []),
            "planner_confidence": planner.get("best_score"),
            "execution_decision": {
                "mode": planner.get("execution_mode"),
                "action": planner.get("action"),
                "failure_reason": planner.get("failure_reason"),
            },
        }

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
