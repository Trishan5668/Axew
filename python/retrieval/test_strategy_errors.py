import unittest
from unittest.mock import patch

from python.retrieval.hybrid_retriever import HybridRetriever, StrategyRetrievalContext
from python.retrieval.timestamp_contract import (
    RetrievalLowConfidenceError,
    StrategyExecutionError,
)


class _ParsedQuery:
    original_query = "find the angry moment"


class StrategyErrorTests(unittest.TestCase):
    def test_strategy_execution_error_preserves_structured_fields(self):
        cause = NameError("missing symbol")

        error = StrategyExecutionError("query", "emotion", cause)

        self.assertEqual(error.query, "query")
        self.assertEqual(error.strategy_name, "emotion")
        self.assertEqual(error.exception_type, "NameError")
        self.assertEqual(error.exception_message, "missing symbol")

    def test_strategy_bridge_raises_typed_error(self):
        retriever = HybridRetriever()
        context = StrategyRetrievalContext(
            parsed_query=_ParsedQuery(),
            video_index=object(),
            use_emotion=True,
        )

        with patch(
            "python.retrieval.strategies.emotional.EmotionalStrategy.retrieve_candidates",
            side_effect=RuntimeError("strategy unavailable"),
        ):
            with self.assertRaises(StrategyExecutionError) as raised:
                retriever._merge_strategy_candidates(
                    pool={},
                    all_chunks=[object()],
                    segment_by_chunk_id={},
                    strategy_context=context,
                    top_k=5,
                )

        self.assertEqual(raised.exception.strategy_name, "emotion")
        self.assertEqual(raised.exception.exception_type, "RuntimeError")
        self.assertEqual(
            retriever.trace_events["strategy_errors"][0]["query"],
            "find the angry moment",
        )

    def test_low_confidence_error_is_typed(self):
        self.assertIsInstance(RetrievalLowConfidenceError("no candidates"), Exception)


if __name__ == "__main__":
    unittest.main()
