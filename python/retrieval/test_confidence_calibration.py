"""Unit tests for retrieval confidence calibration."""

from __future__ import annotations

import unittest

from python.retrieval.confidence_calibration import (
    OPENER_CONFIDENCE_CAP,
    calibrate_confidence_distribution,
    cap_opener_confidence,
    compute_prefix_penalty,
    embedding_score_from_components,
    is_semantically_specific_query,
    lexical_overlap_ratio,
)
from python.retrieval.event_matcher import ParsedQuery
from python.retrieval.semantic_retrieval_pipeline import CandidateScoreBreakdown


class TestConfidenceCalibration(unittest.TestCase):
    def test_missing_rerank_not_inflated_to_half(self) -> None:
        with_rerank = embedding_score_from_components(0.5, 0.4, rerank_available=True)
        without = embedding_score_from_components(0.5, 0.4, rerank_available=False)
        self.assertLess(without, with_rerank)
        self.assertLess(without, 0.45)

    def test_opener_penalty_generic_short_clip(self) -> None:
        penalty = compute_prefix_penalty(
            0.0,
            1.2,
            900.0,
            action_score=0.1,
            monetary_score=0.0,
            contextual_score=0.1,
            entity_score=0.5,
            lexical_overlap=0.1,
        )
        self.assertGreaterEqual(penalty, 0.35)

    def test_opener_penalty_waived_with_strong_action(self) -> None:
        penalty = compute_prefix_penalty(
            0.0,
            1.2,
            900.0,
            action_score=0.85,
            monetary_score=0.0,
            contextual_score=0.2,
            entity_score=0.5,
            lexical_overlap=0.2,
        )
        self.assertEqual(penalty, 0.0)

    def test_weak_set_compression(self) -> None:
        raw = [0.51, 0.49, 0.48, 0.47]
        calibrated = calibrate_confidence_distribution(raw)
        self.assertLess(max(calibrated), max(raw))
        self.assertLess(calibrated[0], 0.45)

    def test_opener_cap_for_specific_query(self) -> None:
        parsed = ParsedQuery(
            raw_query="when did the interviewer give Vijay Mallya 50 crore",
            monetary={"amount": 50.0, "currency": "INR"},
            action_types=["TRANSFER"],
            entities=["Vijay Mallya"],
        )
        breakdown = CandidateScoreBreakdown(
            embedding_score=0.4,
            entity_score=0.7,
            action_score=0.1,
            monetary_score=0.0,
            contextual_score=0.1,
            event_completeness_score=0.0,
            prefix_penalty=0.35,
            final_score=0.51,
        )
        capped, applied = cap_opener_confidence(0.51, 0.0, parsed, breakdown, "Vijay Mahalya sir welcome")
        self.assertTrue(applied)
        self.assertLessEqual(capped, OPENER_CONFIDENCE_CAP)

    def test_semantically_specific_query(self) -> None:
        self.assertTrue(
            is_semantically_specific_query(
                ParsedQuery(raw_query="give 50 crore to Vijay Mallya", monetary={"amount": 50, "currency": "INR"})
            )
        )
        self.assertFalse(is_semantically_specific_query(ParsedQuery(raw_query="show clip")))

    def test_lexical_overlap(self) -> None:
        ratio = lexical_overlap_ratio(
            "interviewer give Vijay Mallya fifty crore",
            "the interviewer handed Vijay Mallya fifty crore in cash",
        )
        self.assertGreater(ratio, 0.4)


if __name__ == "__main__":
    unittest.main()
