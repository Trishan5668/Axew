"""
Retrieval quality scoring and logging — Phase 8.1.

Logs every scored retrieval to ~/.axew/quality_log.jsonl
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from python.evaluation.benchmark import temporal_iou, window_contains_gt
from python.retrieval.confidence import ConfidenceBreakdown

logger = logging.getLogger(__name__)

QUALITY_LOG = Path(os.path.expanduser("~/.axew/quality_log.jsonl"))
OLLAMA_TIMEOUT = 30.0


class QualityScore(BaseModel):
    timestamp: str
    query: str
    video_id: str
    pred_start: float
    pred_end: float
    confidence: float
    confidence_grade: str = "MEDIUM"
    precision_at_1: Optional[bool] = None
    recall_at_5: Optional[bool] = None
    temporal_iou: Optional[float] = None
    semantic_coherence: Optional[float] = None
    user_feedback: Optional[str] = None
    session_id: Optional[str] = None
    pipeline_trace: List[str] = Field(default_factory=list)


class QualityScorer:
    def __init__(self, ollama_host: str = "http://localhost:11434") -> None:
        self.ollama_host = ollama_host.rstrip("/")
        QUALITY_LOG.parent.mkdir(parents=True, exist_ok=True)

    def score_retrieval(
        self,
        query: str,
        video_id: str,
        pred_start: float,
        pred_end: float,
        confidence: float,
        confidence_grade: str,
        segment_text: str = "",
        gt_start: Optional[float] = None,
        gt_end: Optional[float] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        pipeline_trace: Optional[List[str]] = None,
        user_feedback: Optional[str] = None,
    ) -> QualityScore:
        precision_at_1 = None
        recall_at_5 = None
        iou = None

        if gt_start is not None and gt_end is not None:
            iou = temporal_iou(pred_start, pred_end, gt_start, gt_end)
            precision_at_1 = window_contains_gt(pred_start, pred_end, gt_start, gt_end)
            if candidates:
                recall_at_5 = any(
                    window_contains_gt(c["start_sec"], c["end_sec"], gt_start, gt_end)
                    for c in candidates[:5]
                )

        semantic = self._semantic_coherence(query, segment_text) if segment_text else None

        score = QualityScore(
            timestamp=datetime.now(timezone.utc).isoformat(),
            query=query,
            video_id=video_id,
            pred_start=pred_start,
            pred_end=pred_end,
            confidence=confidence,
            confidence_grade=confidence_grade,
            precision_at_1=precision_at_1,
            recall_at_5=recall_at_5,
            temporal_iou=iou,
            semantic_coherence=semantic,
            user_feedback=user_feedback,
            session_id=session_id,
            pipeline_trace=pipeline_trace or [],
        )
        self._append_log(score)
        return score

    def record_feedback(
        self,
        session_id: str,
        feedback: str,
        query: str = "",
        video_id: str = "",
    ) -> None:
        entry = QualityScore(
            timestamp=datetime.now(timezone.utc).isoformat(),
            query=query,
            video_id=video_id,
            pred_start=0,
            pred_end=0,
            confidence=0,
            user_feedback=feedback,
            session_id=session_id,
        )
        self._append_log(entry)

    def rolling_dashboard(self, days: int = 7) -> Dict[str, Any]:
        """Aggregate quality log entries from the last N days."""
        if not QUALITY_LOG.is_file():
            return {"entries": 0, "mean_iou": 0.0, "mean_confidence": 0.0, "feedback_counts": {}}

        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        entries: List[QualityScore] = []
        for line in QUALITY_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = QualityScore.model_validate_json(line)
                ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00")).timestamp()
                if ts >= cutoff:
                    entries.append(entry)
            except Exception:
                continue

        ious = [e.temporal_iou for e in entries if e.temporal_iou is not None]
        confs = [e.confidence for e in entries if e.confidence > 0]
        feedback: Dict[str, int] = {}
        for e in entries:
            if e.user_feedback:
                feedback[e.user_feedback] = feedback.get(e.user_feedback, 0) + 1

        return {
            "entries": len(entries),
            "mean_iou": sum(ious) / len(ious) if ious else 0.0,
            "mean_confidence": sum(confs) / len(confs) if confs else 0.0,
            "feedback_counts": feedback,
            "days": days,
        }

    def _semantic_coherence(self, query: str, segment_text: str) -> float:
        """LLM judge 0-10 scaled to 0-1; heuristic fallback."""
        prompt = (
            f'Does this transcript excerpt answer the query "{query}"? '
            f'Excerpt: "{segment_text[:500]}" Score 0-10 only.'
        )
        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                resp = client.post(
                    f"{self.ollama_host}/api/generate",
                    json={"model": "llama3.2:3b", "prompt": prompt, "stream": False},
                )
                if resp.status_code == 200:
                    text = resp.json().get("response", "")
                    m = re.search(r"(\d+(?:\.\d+)?)", text)
                    if m:
                        return min(1.0, float(m.group(1)) / 10.0)
        except Exception as e:
            logger.debug("Ollama coherence judge unavailable: %s", e)

        q_terms = set(re.findall(r"\b\w{3,}\b", query.lower()))
        s_terms = set(re.findall(r"\b\w{3,}\b", segment_text.lower()))
        overlap = len(q_terms & s_terms)
        return min(1.0, overlap / max(len(q_terms), 1))

    def _append_log(self, score: QualityScore) -> None:
        with QUALITY_LOG.open("a", encoding="utf-8") as f:
            f.write(score.model_dump_json() + "\n")


def score_from_response(
    response: Any,
    video_id: str,
    segment_text: str = "",
    gt_start: Optional[float] = None,
    gt_end: Optional[float] = None,
) -> QualityScore:
    """Convenience wrapper for RetrievalResponse objects."""
    fw = response.final_window
    conf = response.confidence
    grade = conf.grade if conf else "MEDIUM"
    composite = conf.composite if conf else fw.confidence
    candidates = [
        {"start_sec": c.start_sec, "end_sec": c.end_sec}
        for c in (response.candidates or [])
    ]
    return QualityScorer().score_retrieval(
        query=response.query,
        video_id=video_id,
        pred_start=fw.start_sec,
        pred_end=fw.end_sec,
        confidence=composite,
        confidence_grade=grade,
        segment_text=segment_text,
        gt_start=gt_start,
        gt_end=gt_end,
        candidates=candidates,
        session_id=getattr(response, "session_id", None),
        pipeline_trace=response.pipeline_trace,
    )
