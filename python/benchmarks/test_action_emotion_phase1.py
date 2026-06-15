import unittest

from python.benchmarks.action_emotion_phase1 import (
    BenchmarkCase,
    GroundTruth,
    categorize_failure,
    compare_successful_behavior,
    confidence_distribution,
    temporal_iou,
    winning_branch,
)


class ActionEmotionPhase1Tests(unittest.TestCase):
    def test_temporal_iou_partial_overlap(self):
        self.assertEqual(round(temporal_iou(10.0, 20.0, 15.0, 25.0), 4), 0.3333)

    def test_winning_branch_reports_strategy_origin(self):
        self.assertEqual(
            winning_branch({"score_dense": 0.1, "score_strategy": 0.9, "strategy_origins": ["emotion"]}),
            "strategy:emotion",
        )

    def test_categorize_high_confidence_wrong_emotion(self):
        case = BenchmarkCase(
            id="x",
            category="emotion",
            video_id="v",
            fixture_path="f",
            query="angry moment",
            ground_truth=GroundTruth(10.0, 20.0),
            primary_modality="paralinguistic_emotion",
            transcript_cue="",
            notes="",
        )
        result = {
            "status": "ok",
            "iou": 0.0,
            "confidence": 0.9,
            "retrieved": {"start": 30.0, "end": 40.0},
        }

        modes = categorize_failure(case, result)

        self.assertIn("emotion expressed via tone/visual not text", modes)
        self.assertIn("high confidence on wrong segment", modes)

    def test_confidence_distribution_counts_saturation(self):
        distribution = confidence_distribution([0.2, 0.4, 0.6, 1.0])

        self.assertEqual(distribution["saturated_at_1_count"], 1)
        self.assertEqual(distribution["median"], 0.5)

    def test_successful_behavior_comparison_ignores_prior_strategy_failures(self):
        before = [
            {
                "id": "clean",
                "status": "ok",
                "winning_branch": "bm25",
                "retrieved": {"start": 1.0, "end": 2.0, "text": "same"},
                "trace": {"strategy_errors": []},
            },
            {
                "id": "failed",
                "status": "ok",
                "winning_branch": "bm25",
                "retrieved": {"start": 3.0, "end": 4.0, "text": "old"},
                "trace": {"strategy_errors": [{"strategy": "emotion"}]},
            },
        ]
        after = [
            {
                "id": "clean",
                "status": "ok",
                "winning_branch": "bm25",
                "retrieved": {"start": 1.0, "end": 2.0, "text": "same"},
            },
            {
                "id": "failed",
                "status": "ok",
                "winning_branch": "strategy:emotion",
                "retrieved": {"start": 3.0, "end": 4.0, "text": "new"},
            },
        ]

        comparison = compare_successful_behavior(before, after)

        self.assertEqual(comparison["prior_successful_cases"], 1)
        self.assertEqual(comparison["identical_cases"], 1)
        self.assertEqual(comparison["changed_case_ids"], [])


if __name__ == "__main__":
    unittest.main()
