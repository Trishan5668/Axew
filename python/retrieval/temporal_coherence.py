"""
Temporal coherence modeling and window merging.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from python.retrieval.chunker import Chunk
from python.retrieval.native_temporal import merge_overlapping_windows_native


@dataclass
class TimeWindow:
    start_sec: float
    end_sec: float
    score: float = 0.0


def apply_temporal_coherence(
    ranked_chunks: List[Tuple[Chunk, float]],
    coherence_window_sec: float = 120.0,
    decay_factor: float = 0.05,
) -> List[Tuple[Chunk, float]]:
    if len(ranked_chunks) <= 1:
        return ranked_chunks

    adjusted: List[Tuple[Chunk, float]] = []
    for i, (chunk_i, score_i) in enumerate(ranked_chunks):
        bonus = 0.0
        center_i = (chunk_i.start_sec + chunk_i.end_sec) / 2
        for j, (chunk_j, score_j) in enumerate(ranked_chunks):
            if i == j:
                continue
            center_j = (chunk_j.start_sec + chunk_j.end_sec) / 2
            dist = abs(center_i - center_j)
            if dist <= coherence_window_sec:
                bonus += score_j * math.exp(-decay_factor * dist)
        adjusted.append((chunk_i, score_i + bonus))

    adjusted.sort(key=lambda x: x[1], reverse=True)
    return adjusted


def merge_overlapping_windows(
    windows: List[TimeWindow],
    overlap_ratio: float = 0.5,
) -> List[TimeWindow]:
    if not windows:
        return []

    triples = [(w.start_sec, w.end_sec, w.score) for w in windows]
    merged_triples = merge_overlapping_windows_native(triples)
    return [TimeWindow(start_sec=s, end_sec=e, score=sc) for s, e, sc in merged_triples]
