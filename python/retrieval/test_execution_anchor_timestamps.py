import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE_ROOT = PROJECT_ROOT / "apps" / "ai-service"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_ROOT))

from routers.execution import PlanActionsRequest, TranscriptSegmentInput, _intelligent_retrieve


class _FakeTrace:
    def to_dict(self):
        return {
            "final_result": {
                "chunk_id": "seg_009",
                "anchor_start": 92.5,
                "anchor_end": 108.0,
                "expanded_start": 68.3,
                "expanded_end": 130.0,
            }
        }


class _FakeRetrievalPipeline:
    def retrieve(self, prompt, chunks):
        chunk = SimpleNamespace(
            id="seg_009",
            text=(
                "That's right. I wanted to make a point about starting small. "
                "Here, let me recreate it. Vijay Mallya, I'm giving you 101 rupees right now."
            ),
        )
        candidate = SimpleNamespace(
            chunk=chunk,
            anchor_start=92.5,
            anchor_end=108.0,
            expanded_start=68.3,
            expanded_end=130.0,
            score_calibrated=0.97,
            match_quality="strong_match",
            match_explanation="fake strong match",
        )
        return SimpleNamespace(
            top_candidate=candidate,
            all_candidates=[candidate],
            trace=_FakeTrace(),
        )


class TestExecutionAnchorTimestamps(unittest.TestCase):
    def test_extraction_action_uses_anchor_not_expanded_context(self):
        import asyncio
        import python.retrieval.pipeline as retrieval_pipeline

        original_pipeline = retrieval_pipeline.RetrievalPipeline
        retrieval_pipeline.RetrievalPipeline = _FakeRetrievalPipeline

        async def run_case():
            return await _intelligent_retrieve(
                PlanActionsRequest(
                    prompt="Keep only the part where the interviewer gives 101 rupees to Vijay Mallya",
                    media_duration=900.0,
                    padding_seconds=0.4,
                    use_intelligence=True,
                    segments=[
                        TranscriptSegmentInput(
                            id="seg_007",
                            start=68.3,
                            end=78.0,
                            text="Do you remember the 101 rupees incident?",
                        ),
                        TranscriptSegmentInput(
                            id="seg_009",
                            start=92.5,
                            end=108.0,
                            text="Vijay Mallya, I'm giving you 101 rupees right now.",
                        ),
                        TranscriptSegmentInput(
                            id="seg_011",
                            start=118.5,
                            end=130.0,
                            text="I still have those 101 rupees framed in my office.",
                        ),
                    ],
                )
            )

        try:
            response = asyncio.run(run_case())
        finally:
            retrieval_pipeline.RetrievalPipeline = original_pipeline

        self.assertIsNotNone(response)
        self.assertEqual(response.actions[0].start, 92.5)
        self.assertEqual(response.actions[0].end, 108.0)
        self.assertEqual(response.matches[0].start, 68.3)
        self.assertEqual(response.matches[0].end, 130.0)
        self.assertEqual(
            response.debug["timestamp_boundary_trace"],
            {
                "anchor_start": 92.5,
                "anchor_end": 108.0,
                "expanded_start": 68.3,
                "expanded_end": 130.0,
                "action_start": 92.5,
                "action_end": 108.0,
                "ffmpeg_start": 92.5,
                "ffmpeg_end": 108.0,
                "first_end_divergence_from_anchor": "context_expansion",
                "end_matches_anchor_at_action": True,
                "end_matches_anchor_at_ffmpeg": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
