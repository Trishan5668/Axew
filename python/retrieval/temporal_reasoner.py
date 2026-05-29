"""Temporal modifier filtering for retrieval candidates."""

from __future__ import annotations

import re
from typing import List

from python.retrieval.event_matcher import ParsedQuery

TEMPORAL_PATTERNS = {
    "before_event": re.compile(r"\bbefore\s+(?:he|she|they|the)?\s*(\w+)", re.I),
    "after_event": re.compile(r"\bafter\s+(?:he|she|they|the)?\s*(\w+)", re.I),
    "first_time": re.compile(r"\bfirst\s+time\b|\bfirst\s+(?:he|she)", re.I),
    "last_time": re.compile(r"\blast\s+time\b|\blast\s+(?:he|she)", re.I),
    "when": re.compile(r"\bwhen\b", re.I),
    "moment_before": re.compile(r"\bmoment\s+before\b", re.I),
    "right_after": re.compile(r"\bright\s+after\b|\bimmediately\s+after\b", re.I),
}


class TemporalReasoner:
    def extract_modifiers(self, query: str) -> List[str]:
        mods = []
        for name, pat in TEMPORAL_PATTERNS.items():
            if pat.search(query):
                mods.append(name)
        return mods

    def apply_temporal_filter(
        self,
        query: ParsedQuery,
        candidates: List[dict],
        all_events: List[dict],
    ) -> List[dict]:
        if not query.temporal_modifiers:
            return candidates

        if "first_time" in query.temporal_modifiers and candidates:
            return [min(candidates, key=lambda c: c["start_sec"])]

        if "last_time" in query.temporal_modifiers and candidates:
            return [max(candidates, key=lambda c: c["start_sec"])]

        return candidates
