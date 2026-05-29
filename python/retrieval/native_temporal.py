"""
Rust-accelerated temporal operations with Python fallback — Phase 10.

Build optional native module:
    cd crates/axew-retrieval && maturin develop
"""

from __future__ import annotations

from typing import List, Tuple

_USE_NATIVE = False

try:
    import axew_retrieval as _native

    _USE_NATIVE = True
except ImportError:
    _native = None


def compute_temporal_iou(
    pred_start: float,
    pred_end: float,
    gt_start: float,
    gt_end: float,
) -> float:
    if _USE_NATIVE and _native is not None:
        return float(_native.compute_temporal_iou(pred_start, pred_end, gt_start, gt_end))

    intersection = max(0.0, min(pred_end, gt_end) - max(pred_start, gt_start))
    union = (pred_end - pred_start) + (gt_end - gt_start) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def merge_overlapping_windows_native(
    windows: List[Tuple[float, float, float]],
) -> List[Tuple[float, float, float]]:
    if _USE_NATIVE and _native is not None:
        return list(_native.merge_overlapping_windows(windows))

    if not windows:
        return []

    sorted_w = sorted(windows, key=lambda w: w[0])
    merged: List[Tuple[float, float, float]] = [sorted_w[0]]

    for start, end, score in sorted_w[1:]:
        ps, pe, pscore = merged[-1]
        overlap = max(0.0, min(pe, end) - max(ps, start))
        span = min(pe - ps, end - start)
        if span > 0 and overlap / span > 0.5:
            merged[-1] = (ps, max(pe, end), max(pscore, score))
        else:
            merged.append((start, end, score))

    return merged


def using_native() -> bool:
    return _USE_NATIVE
