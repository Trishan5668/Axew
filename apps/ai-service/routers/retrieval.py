"""Retrieval debug endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()


@router.get("/trace")
async def retrieval_trace(n: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    from python.retrieval.trace import get_traces

    traces = get_traces(n)
    return {
        "status": "ok",
        "count": len(traces),
        "traces": [trace.to_dict() for trace in traces],
        "summaries": [trace.summarize() for trace in traces],
    }
