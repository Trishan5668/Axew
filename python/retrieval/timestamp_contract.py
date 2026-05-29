"""Timestamp integrity contract for retrieval and extraction."""

from __future__ import annotations

from typing import Any


class RetrievalIntegrityError(Exception):
    """Raised when retrieval timestamps are missing, invalid, or mutated."""


class PlannerError(Exception):
    """Raised when planning cannot produce a valid clip without fallback."""


class TimestampContract:
    @staticmethod
    def validate_candidate(c: Any, stage: str) -> None:
        errors: list[str] = []
        if getattr(c, "expanded_start", None) is None:
            errors.append("expanded_start is None")
        if getattr(c, "expanded_end", None) is None:
            errors.append("expanded_end is None")
        if getattr(c, "expanded_start", None) is not None and getattr(c, "expanded_end", None) is not None:
            if c.expanded_end <= c.expanded_start:
                errors.append(f"end ({c.expanded_end}) <= start ({c.expanded_start})")
            if (c.expanded_end - c.expanded_start) > 300:
                errors.append("clip duration > 300s (suspicious)")
        if errors:
            raise RetrievalIntegrityError(
                f"[{stage}] Timestamp contract violated: {errors} | candidate={c}"
            )

    @staticmethod
    def validate_extraction_matches_retrieval(
        retrieval_start: float,
        retrieval_end: float,
        extraction_start: float,
        extraction_end: float,
        tolerance_seconds: float = 0.1,
    ) -> None:
        if abs(retrieval_start - extraction_start) > tolerance_seconds:
            raise RetrievalIntegrityError(
                f"Extraction start {extraction_start} differs from retrieval start "
                f"{retrieval_start} by > {tolerance_seconds}s"
            )
        if abs(retrieval_end - extraction_end) > tolerance_seconds:
            raise RetrievalIntegrityError(
                f"Extraction end {extraction_end} differs from retrieval end "
                f"{retrieval_end} by > {tolerance_seconds}s"
            )
