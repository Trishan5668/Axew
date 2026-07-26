"""Unit tests for phrase/topic retrieval regression guardrails."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from python.benchmarks.phrase_topic_regression import (
    DEFAULT_FIXTURE,
    DEFAULT_RESULTS,
    candidate_covered,
    ground_truth_rank,
    load_queries,
    run_benchmark,
    summarize,
    timestamp_valid,
)

PHRASE_IOU_TARGET = 0.90
TOPIC_IOU_TARGET = 0.85
CANDIDATE_COVERAGE_TARGET = 0.95


class _FakeCandidate:
    def __init__(self, start: float, end: float) -> None:
        self.anchor_start = start
        self.anchor_end = end


class PhraseTopicRegressionHelperTests(unittest.TestCase):
    def test_ground_truth_rank_returns_first_relevant_candidate(self):
        candidates = [
            _FakeCandidate(0.0, 5.0),
            _FakeCandidate(10.0, 20.0),
            _FakeCandidate(30.0, 40.0),
        ]

        self.assertEqual(ground_truth_rank(candidates, 12.0, 18.0), 2)

    def test_candidate_coverage_requires_relevant_window(self):
        candidates = [_FakeCandidate(0.0, 5.0), _FakeCandidate(10.0, 20.0)]

        self.assertTrue(candidate_covered(candidates, 10.0, 20.0))
        self.assertFalse(candidate_covered(candidates, 50.0, 60.0))

    def test_timestamp_valid_rejects_invalid_windows(self):
        self.assertTrue(timestamp_valid(1.0, 2.0))
        self.assertFalse(timestamp_valid(2.0, 2.0))
        self.assertFalse(timestamp_valid(float("nan"), 2.0))


class PhraseTopicRegressionIntegrationTests(unittest.TestCase):
    payload: dict
    summary: dict
    results: list[dict]

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = run_benchmark(
            fixture_path=DEFAULT_FIXTURE,
            results_path=DEFAULT_RESULTS,
        )
        cls.summary = cls.payload["summary"]
        cls.results = cls.payload["results"]

    def test_benchmark_executes_successfully(self):
        self.assertEqual(self.summary["error_queries"], 0)
        self.assertTrue(DEFAULT_RESULTS.is_file())
        self.assertEqual(len(load_queries(DEFAULT_FIXTURE)), self.summary["total_queries"])

    def test_phrase_queries_meet_iou_threshold(self):
        phrase_results = [result for result in self.results if result["type"] == "phrase"]
        phrase_pass_rate = sum(1 for result in phrase_results if result["iou_at_0_5"]) / len(phrase_results)

        self.assertGreaterEqual(phrase_pass_rate, PHRASE_IOU_TARGET)

    def test_topic_queries_meet_iou_threshold(self):
        topic_results = [result for result in self.results if result["type"] == "topic"]
        topic_pass_rate = sum(1 for result in topic_results if result["iou_at_0_5"]) / len(topic_results)

        self.assertGreaterEqual(topic_pass_rate, TOPIC_IOU_TARGET)

    def test_candidate_coverage_meets_threshold(self):
        self.assertGreaterEqual(
            self.summary["overall_candidate_coverage_rate"],
            CANDIDATE_COVERAGE_TARGET,
        )

    def test_timestamps_remain_valid(self):
        self.assertEqual(self.summary["timestamp_regressions"], 0)
        for result in self.results:
            self.assertTrue(result["timestamp_valid"])
            self.assertLess(result["winner_start"], result["winner_end"])
            self.assertGreaterEqual(result["winner_start"], 0.0)

    def test_confidence_values_are_finite(self):
        self.assertEqual(self.summary["confidence_nan_count"], 0)
        for result in self.results:
            self.assertTrue(result["confidence_finite"])
            self.assertTrue(math.isfinite(result["confidence"]))

    def test_each_result_records_branch_and_rank_fields(self):
        for result in self.results:
            self.assertIn("winning_branch", result)
            self.assertIn("ground_truth_rank", result)
            self.assertIn("candidate_coverage", result)


class PhraseTopicRegressionSummaryTests(unittest.TestCase):
    def test_summarize_counts_phrase_and_topic_buckets(self):
        results = [
            {
                "status": "ok",
                "type": "phrase",
                "iou": 1.0,
                "iou_at_0_5": True,
                "candidate_coverage": True,
                "timestamp_valid": True,
                "confidence_finite": True,
                "winning_branch": "bm25",
            },
            {
                "status": "ok",
                "type": "topic",
                "iou": 0.2,
                "iou_at_0_5": False,
                "candidate_coverage": False,
                "timestamp_valid": True,
                "confidence_finite": True,
                "winning_branch": "dense",
            },
        ]

        summary = summarize(results)

        self.assertEqual(summary["phrase"]["queries"], 1)
        self.assertEqual(summary["topic"]["queries"], 1)
        self.assertEqual(summary["phrase"]["iou_at_0_5_rate"], 1.0)
        self.assertEqual(summary["topic"]["iou_at_0_5_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
