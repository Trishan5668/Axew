import unittest

from python.benchmarks.action_emotion_phase1 import BenchmarkCase, GroundTruth
from python.benchmarks.action_emotion_production_trace import (
    best_relevant,
    first_collapse_stage,
    rank_movement,
)


CASE = BenchmarkCase(
    id="case",
    category="action",
    video_id="video",
    fixture_path="fixture",
    query="query",
    ground_truth=GroundTruth(10.0, 20.0),
    primary_modality="visual_action",
    transcript_cue="",
    notes="",
)


class ProductionTraceTests(unittest.TestCase):
    def test_best_relevant_returns_matching_rank(self):
        candidates = [
            {"chunk_id": "wrong", "start": 0.0, "end": 5.0},
            {"chunk_id": "right", "start": 10.0, "end": 20.0},
        ]

        relevant = best_relevant(candidates, CASE)

        self.assertEqual(relevant["chunk_id"], "right")
        self.assertEqual(relevant["rank"], 2)

    def test_first_collapse_marks_fusion_ranking(self):
        wrong = {"chunk_id": "wrong", "start": 0.0, "end": 5.0}
        right = {"chunk_id": "right", "start": 10.0, "end": 20.0}

        stage = first_collapse_stage(
            CASE,
            merged=[wrong, right],
            retrieval=[wrong, right],
            expansion=[wrong, right],
            reranked=[wrong, right],
        )

        self.assertEqual(stage, "fusion_ranking")

    def test_rank_movement_separates_strategy_and_bm25_only(self):
        before = [
            {"chunk_id": "strategy", "strategy_origins": ["emotion"], "score_bm25": 0.5},
            {"chunk_id": "bm25", "strategy_origins": [], "score_bm25": 1.0},
        ]
        after = [before[1], before[0]]

        movement = rank_movement(before, after)

        self.assertEqual(movement["strategy"], [-1])
        self.assertEqual(movement["bm25_only"], [1])


if __name__ == "__main__":
    unittest.main()
