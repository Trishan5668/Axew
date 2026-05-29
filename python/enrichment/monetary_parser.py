"""Monetary entity extraction from transcript text."""

from __future__ import annotations

import re
import uuid
from typing import List, Optional, Tuple

from python.models.enriched import MonetaryMention, TranscriptSegment, TranscriptWord

CURRENCY_PATTERNS = {
    "INR": [
        r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:rupee[s]?|rs\.?|₹|inr)\b",
        r"\b(?:rupee[s]?|rs\.?|₹)\s*(\d[\d,]*(?:\.\d+)?)\b",
        r"\b(\d+(?:\.\d+)?)\s*(?:lakh|lac)\b",
        r"\b(\d+(?:\.\d+)?)\s*crore\b",
    ],
    "USD": [
        r"\$\s*(\d[\d,]*(?:\.\d+)?)\b",
        r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:dollar[s]?|usd)\b",
    ],
    "GBP": [
        r"£\s*(\d[\d,]*(?:\.\d+)?)\b",
        r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:pound[s]?|gbp)\b",
    ],
}

SPOKEN_AMOUNT_PATTERN = re.compile(
    r"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|lakh|crore|million|billion"
    r")(?:\s+(?:and\s+)?(?:one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|lakh|crore|million|billion))*)\s+"
    r"(?:rupee[s]?|rs\.?|₹|inr|dollar[s]?|usd|pound[s]?|gbp)\b",
    re.IGNORECASE,
)

# Avoid matching bare numbers without currency context
BARE_NUMBER = re.compile(r"^\d[\d,]*(?:\.\d+)?$")


class MonetaryParser:
    def parse_segment(self, segment: TranscriptSegment) -> List[MonetaryMention]:
        mentions: List[MonetaryMention] = []
        text = segment.text
        for currency, patterns in CURRENCY_PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    raw = m.group(0)
                    amount_str = m.group(1).replace(",", "")
                    amount, unit = self._parse_amount(amount_str, raw)
                    amount = self._normalize_indian_amount(amount, unit)
                    start_ms, end_ms = self._align_span(m.start(), m.end(), segment)
                    mentions.append(
                        MonetaryMention(
                            raw_text=raw,
                            amount_normalized=amount,
                            currency=currency,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            segment_id=segment.segment_id,
                            confidence=0.92,
                            mention_id=str(uuid.uuid4())[:8],
                        )
                    )
        for m in SPOKEN_AMOUNT_PATTERN.finditer(text):
            spoken = m.group(1)
            amount = self._spoken_to_number(spoken)
            if amount is None:
                continue
            currency = "INR" if re.search(r"rupee|rs|₹|inr", m.group(0), re.I) else "USD"
            start_ms, end_ms = self._align_span(m.start(), m.end(), segment)
            mentions.append(
                MonetaryMention(
                    raw_text=m.group(0),
                    amount_normalized=float(amount),
                    currency=currency,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    segment_id=segment.segment_id,
                    confidence=0.85,
                    mention_id=str(uuid.uuid4())[:8],
                )
            )
        return self._dedupe(mentions)

    def parse_text(self, text: str) -> List[Tuple[float, str]]:
        """Parse query text for amount+currency pairs."""
        seg = TranscriptSegment(
            text=text,
            start_ms=0,
            end_ms=0,
            words=[],
            segment_id="query",
        )
        return [(m.amount_normalized, m.currency) for m in self.parse_segment(seg)]

    def query_amount(
        self,
        mentions: List[MonetaryMention],
        amount: float,
        currency: str,
        tolerance: float = 0.01,
    ) -> List[MonetaryMention]:
        out: List[MonetaryMention] = []
        for m in mentions:
            if isinstance(m, dict):
                m = MonetaryMention(**m)
            cur = str(m.currency).upper()
            if cur == currency.upper() and abs(m.amount_normalized - amount) <= max(
                tolerance, amount * 0.05
            ):
                out.append(m)
        return out

    def _parse_amount(self, amount_str: str, raw: str) -> Tuple[float, str]:
        unit = ""
        lower = raw.lower()
        if "crore" in lower:
            unit = "crore"
        elif "lakh" in lower or "lac" in lower:
            unit = "lakh"
        try:
            return float(amount_str), unit
        except ValueError:
            return 0.0, unit

    def _normalize_indian_amount(self, amount: float, unit: str) -> float:
        multipliers = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000}
        return amount * multipliers.get(unit.lower(), 1)

    def _spoken_to_number(self, text: str) -> Optional[float]:
        try:
            from word2number import w2n

            return float(w2n.word_to_num(text.lower()))
        except Exception:
            return None

    def _align_span(self, char_start: int, char_end: int, segment: TranscriptSegment) -> Tuple[int, int]:
        if not segment.words:
            return segment.start_ms, segment.end_ms
        text = segment.text
        cum = 0
        start_ms = segment.start_ms
        end_ms = segment.end_ms
        for w in segment.words:
            idx = text.find(w.word, cum)
            if idx < 0:
                cum += len(w.word) + 1
                continue
            w_end = idx + len(w.word)
            if idx <= char_start < w_end or (char_start <= idx < char_end):
                start_ms = w.start_ms
            if idx < char_end <= w_end or (char_start <= idx):
                end_ms = w.end_ms
            cum = w_end
        return start_ms, end_ms

    def _dedupe(self, mentions: List[MonetaryMention]) -> List[MonetaryMention]:
        seen: set = set()
        out: List[MonetaryMention] = []
        for m in mentions:
            key = (m.segment_id, round(m.amount_normalized, 2), m.currency)
            if key in seen:
                continue
            seen.add(key)
            out.append(m)
        return out
