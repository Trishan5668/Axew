"""Retrieval tracing and explainability store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from python.retrieval.types import DecomposedQuery


@dataclass
class RetrievalTrace:
    query_original: str
    decomposed: Optional[DecomposedQuery] = None
    candidates_after_retrieval: list[dict] = field(default_factory=list)
    candidates_after_expansion: list[dict] = field(default_factory=list)
    candidates_after_reranking: list[dict] = field(default_factory=list)
    opener_suppressions: list[dict] = field(default_factory=list)
    fallback_removals: list[str] = field(default_factory=list)
    timestamp_violations: list[str] = field(default_factory=list)
    final_result: Optional[dict] = None
    total_latency_ms: float = 0.0
    stage_latencies: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.decomposed is not None:
            data["decomposed"] = self.decomposed.to_dict()
        return data

    def summarize(self) -> str:
        final = self.final_result or {}
        return "\n".join([
            f"Query: {self.query_original}",
            f"Terms: {', '.join((self.decomposed.search_terms if self.decomposed else [])[:8])}",
            f"Candidates: retrieval={len(self.candidates_after_retrieval)} expansion={len(self.candidates_after_expansion)} rerank={len(self.candidates_after_reranking)}",
            f"Top: {final.get('expanded_start')}s-{final.get('expanded_end')}s {final.get('match_quality')}",
            f"Latency: {self.total_latency_ms:.1f}ms",
        ])


_TRACES: list[RetrievalTrace] = []


def add_trace(trace: RetrievalTrace) -> None:
    _TRACES.append(trace)
    del _TRACES[:-50]


def get_traces(n: int = 10) -> list[RetrievalTrace]:
    return _TRACES[-max(1, n):]
