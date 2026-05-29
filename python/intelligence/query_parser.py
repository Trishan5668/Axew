"""
Query understanding — structured ParsedQuery before retrieval.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Literal, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

OLLAMA_TIMEOUT_SEC = 30.0

QueryType = Literal[
    "entity_action",
    "emotional",
    "temporal",
    "audience",
    "topical",
    "speaker_specific",
    "hook_detection",
    "generic",
]


class ParsedQuery(BaseModel):
    original_query: str
    query_type: QueryType = "generic"
    entities: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    temporal_qualifiers: List[str] = Field(default_factory=list)
    speaker_references: List[str] = Field(default_factory=list)
    monetary_amounts: List[str] = Field(default_factory=list)
    objects: List[str] = Field(default_factory=list)
    decomposed_subqueries: List[str] = Field(default_factory=list)
    retrieval_strategy: str = "hybrid"
    confidence: float = 0.5


class QueryParser:
    def __init__(self, ollama_host: str = "http://localhost:11434", model: str = "llama3.1:8b") -> None:
        self.ollama_host = ollama_host
        self.model = model

    async def parse_query(self, query: str) -> ParsedQuery:
        # On low-resource machines, skip Ollama entirely — the regex fallback
        # is fast, allocation-free, and sufficient for most retrieval queries.
        try:
            from python.resource_manager import should_use_lightweight

            if should_use_lightweight():
                return self._parse_fallback(query)
        except ImportError:
            pass

        try:
            parsed = await self._parse_ollama(query)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning("Ollama query parse failed: %s", e)
        return self._parse_fallback(query)

    async def _parse_ollama(self, query: str) -> Optional[ParsedQuery]:
        schema_hint = ParsedQuery.model_json_schema()
        prompt = (
            "You are a video retrieval query analyzer. Parse the user's query into structured components. "
            f"Return ONLY valid JSON matching this schema: {json.dumps(schema_hint, indent=0)[:1500]}. "
            f"User query: {query}"
        )
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{self.ollama_host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
            )
            if resp.status_code != 200:
                return None
            raw = (resp.json().get("response") or "").strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group())
            data["original_query"] = query
            return ParsedQuery(**{k: v for k, v in data.items() if k in ParsedQuery.model_fields})

    def _parse_fallback(self, query: str) -> ParsedQuery:
        lower = query.lower()
        entities: List[str] = []
        actions: List[str] = []
        emotions: List[str] = []
        temporal: List[str] = []
        monetary: List[str] = []
        speakers: List[str] = []

        for m in re.finditer(r"\b(\d+\s*(?:rupees?|crore|dollars?))\b", query, re.I):
            monetary.append(m.group(1))

        for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query):
            entities.append(m.group(1))

        name_patterns = [
            (r"vijay\s+mallya", "Vijay Mallya"),
            (r"kingfisher(?:\s+airlines)?", "Kingfisher Airlines"),
            (r"\bsbi\b", "SBI"),
            (r"\bpnb\b", "PNB"),
            (r"sanjeev\s+kapoor", "Sanjeev Kapoor"),
            (r"air\s+deccan", "Air Deccan"),
        ]
        for pat, name in name_patterns:
            if re.search(pat, lower):
                entities.append(name)

        action_verbs = [
            "give", "hand", "pay", "receive", "transfer", "present",
            "laugh", "cry", "point", "stand", "applaud", "cheer", "deny",
        ]
        actions = [v for v in action_verbs if v in lower]

        emotion_words = ["emotional", "cry", "tear", "fear", "laugh", "angry", "shocked", "joy", "sad"]
        emotions = [w for w in emotion_words if w in lower]

        if "first time" in lower:
            temporal.append("first")
        if "last time" in lower:
            temporal.append("last")
        if re.search(r"around\s+\d+\s+minutes", lower):
            temporal.append(re.search(r"around\s+\d+\s+minutes", lower).group())  # type: ignore

        if "interviewer" in lower or "host" in lower:
            speakers.append("interviewer")

        query_type: QueryType = "generic"
        if actions and (entities or monetary):
            query_type = "entity_action"
        elif emotions or "emotional" in lower:
            query_type = "emotional"
        elif temporal:
            query_type = "temporal"
        elif any(w in lower for w in ("audience", "applause", "cheering", "booing")):
            query_type = "audience"
        elif any(w in lower for w in ("viral", "hook", "short")):
            query_type = "hook_detection"
        elif speakers:
            query_type = "speaker_specific"

        strategy = {
            "entity_action": "entity_focused",
            "emotional": "emotion_focused",
            "audience": "emotion_focused",
            "temporal": "hybrid",
            "hook_detection": "hybrid",
        }.get(query_type, "hybrid")

        subqueries: List[str] = []
        if query_type == "entity_action" and entities:
            subqueries = [
                f"{a} involving {' and '.join(entities[:2])}" for a in actions[:2]
            ] or [query]

        return ParsedQuery(
            original_query=query,
            query_type=query_type,
            entities=list(dict.fromkeys(entities)),
            actions=actions,
            emotions=emotions,
            temporal_qualifiers=temporal,
            speaker_references=speakers,
            monetary_amounts=monetary,
            decomposed_subqueries=subqueries or [query],
            retrieval_strategy=strategy,
            confidence=0.65,
        )
