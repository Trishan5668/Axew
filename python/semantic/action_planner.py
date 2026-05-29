"""Convert grounded semantic events into executable timeline actions."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Literal, Optional

from python.models.enriched import EnrichedTranscript
from python.retrieval.event_matcher import ParsedQuery
from python.retrieval.confidence_calibration import (
    compute_prefix_penalty,
    lexical_overlap_ratio,
)
from python.semantic.event_grounding import REACTION_VERBS, SPEECH_VERBS, TRANSFER_VERBS, SemanticEvent

ActionType = Literal["extract_clip", "remove_segment", "keep_segment", "highlight_segment"]
logger = logging.getLogger(__name__)


@dataclass
class TimelineAction:
    action_type: ActionType
    start_time: float
    end_time: float
    confidence: float
    reasoning: str


@dataclass
class EventScore:
    event_id: str
    source_chunk_id: str
    actor_score: float
    action_score: float
    object_score: float
    recipient_score: float
    monetary_score: float
    semantic_score: float
    temporal_score: float
    prefix_penalty: float
    final_score: float
    reasoning: List[str] = field(default_factory=list)


@dataclass
class PlanningResult:
    action: Optional[TimelineAction]
    execution_mode: Literal["auto", "candidate", "rejected"]
    best_event: Optional[SemanticEvent]
    best_score: float
    event_scores: List[EventScore] = field(default_factory=list)
    rejected_actions: List[Dict[str, object]] = field(default_factory=list)
    failure_reason: Optional[str] = None


class ActionPlanner:
    AUTO_THRESHOLD = 0.48
    CANDIDATE_THRESHOLD = 0.22

    def __init__(self) -> None:
        self.auto_threshold = self._read_threshold("AXEW_AUTO_THRESHOLD", self.AUTO_THRESHOLD)
        self.candidate_threshold = self._read_threshold(
            "AXEW_CANDIDATE_THRESHOLD",
            self.CANDIDATE_THRESHOLD,
        )

    def plan(
        self,
        intent: ParsedQuery,
        events: List[SemanticEvent],
        transcript: EnrichedTranscript,
    ) -> PlanningResult:
        if not events:
            logger.debug(
                "[ActionPlanner] rejected: no events available (auto=%.2f candidate=%.2f)",
                self.auto_threshold,
                self.candidate_threshold,
            )
            return PlanningResult(
                action=None,
                execution_mode="rejected",
                best_event=None,
                best_score=0.0,
                failure_reason="No grounded semantic events were available.",
            )

        total_duration = max(
            transcript.segments[-1].end_ms / 1000.0 if transcript.segments else 0.0,
            max((event.end_time for event in events), default=0.0),
        )

        scored: List[tuple[SemanticEvent, EventScore]] = []
        for event in events:
            score = self._score_event(intent, event, total_duration)
            scored.append((event, score))

        scored.sort(key=lambda item: item[1].final_score, reverse=True)
        best_event, best_score = scored[0]
        event_scores = [score for _, score in scored[:12]]

        if best_score.final_score >= self.auto_threshold:
            start, end = self._expand_window(best_event, transcript)
            action = TimelineAction(
                action_type=self._map_action_type(intent.intent_action),
                start_time=start,
                end_time=end,
                confidence=best_score.final_score,
                reasoning=" | ".join(best_score.reasoning[:4]),
            )
            return PlanningResult(
                action=action,
                execution_mode="auto",
                best_event=best_event,
                best_score=best_score.final_score,
                event_scores=event_scores,
                rejected_actions=self._rejected_actions(scored[1:6]),
            )

        has_entity_match = max(best_score.actor_score, best_score.object_score, best_score.recipient_score) >= 0.45
        has_monetary_match = best_score.monetary_score >= 0.45
        has_strong_event = best_event.confidence >= 0.72
        should_allow_candidate = (
            best_score.final_score >= self.candidate_threshold
            or has_entity_match
            or has_monetary_match
            or has_strong_event
        )
        logger.debug(
            "[ActionPlanner] threshold decision score=%.3f auto=%.2f candidate=%.2f entity=%s monetary=%s strong_event=%s -> %s",
            best_score.final_score,
            self.auto_threshold,
            self.candidate_threshold,
            has_entity_match,
            has_monetary_match,
            has_strong_event,
            "candidate" if should_allow_candidate else "rejected",
        )
        if should_allow_candidate:
            start, end = self._expand_window(best_event, transcript)
            action = TimelineAction(
                action_type="highlight_segment",
                start_time=start,
                end_time=end,
                confidence=best_score.final_score,
                reasoning="Candidate extraction: " + " | ".join(best_score.reasoning[:4]),
            )
            return PlanningResult(
                action=action,
                execution_mode="candidate",
                best_event=best_event,
                best_score=best_score.final_score,
                event_scores=event_scores,
                rejected_actions=self._rejected_actions(scored[1:6]),
                failure_reason=(
                    "Grounding succeeded with moderate confidence; surfaced as candidate instead of hard rejection."
                ),
            )

        return PlanningResult(
            action=None,
            execution_mode="rejected",
            best_event=best_event,
            best_score=best_score.final_score,
            event_scores=event_scores,
            rejected_actions=self._rejected_actions(scored[:6]),
            failure_reason="Semantic events were found, but alignment confidence stayed below candidate threshold.",
        )

    def _score_event(
        self,
        intent: ParsedQuery,
        event: SemanticEvent,
        total_duration: float,
    ) -> EventScore:
        reasons: List[str] = []

        actor_targets = [intent.subject] + intent.speaker_roles
        actor_score = self._best_match(actor_targets, [event.actor])
        if actor_score > 0:
            reasons.append(f"actor={actor_score:.2f}")

        action_targets = [intent.verb] + intent.action_types
        action_score = self._score_action(action_targets, event.action)
        if action_score > 0:
            reasons.append(f"action={action_score:.2f}")

        object_targets = [intent.object] + intent.entities
        object_score = self._best_match(object_targets, [event.object, event.transcript_text])
        if object_score > 0:
            reasons.append(f"object={object_score:.2f}")

        recipient_score = self._best_match([intent.recipient], [event.recipient, event.object])
        if recipient_score > 0:
            reasons.append(f"recipient={recipient_score:.2f}")

        monetary_score = self._score_money(intent.monetary, event.monetary_amount, event.object)
        if monetary_score > 0:
            reasons.append(f"money={monetary_score:.2f}")

        semantic_score = self._semantic_overlap(intent.raw_query, event.transcript_text)
        if semantic_score > 0:
            reasons.append(f"semantic={semantic_score:.2f}")

        temporal_score = self._temporal_score(intent, event)
        if temporal_score > 0:
            reasons.append(f"temporal={temporal_score:.2f}")

        prefix_penalty = compute_prefix_penalty(
            event.start_time,
            event.end_time,
            total_duration,
            action_score=action_score,
            monetary_score=monetary_score,
            contextual_score=semantic_score,
            entity_score=max(actor_score, object_score, recipient_score),
            lexical_overlap=lexical_overlap_ratio(intent.raw_query, event.transcript_text),
        )
        if prefix_penalty > 0:
            reasons.append(f"prefix_penalty=-{prefix_penalty:.2f}")

        final_score = (
            0.20 * actor_score
            + 0.24 * action_score
            + 0.10 * object_score
            + 0.16 * recipient_score
            + 0.17 * monetary_score
            + 0.08 * semantic_score
            + 0.05 * temporal_score
            + 0.10 * event.confidence
            - prefix_penalty
        )
        final_score = max(0.0, min(1.0, final_score))

        if event.confidence > 0.8 and final_score < self.candidate_threshold:
            reasons.append("grounded event strong, intent alignment weak")
        if not reasons:
            reasons.append("no meaningful alignment features")

        return EventScore(
            event_id=event.id,
            source_chunk_id=event.source_chunk_id,
            actor_score=round(actor_score, 4),
            action_score=round(action_score, 4),
            object_score=round(object_score, 4),
            recipient_score=round(recipient_score, 4),
            monetary_score=round(monetary_score, 4),
            semantic_score=round(semantic_score, 4),
            temporal_score=round(temporal_score, 4),
            prefix_penalty=round(prefix_penalty, 4),
            final_score=round(final_score, 4),
            reasoning=reasons,
        )

    def _expand_window(
        self,
        event: SemanticEvent,
        transcript: EnrichedTranscript,
    ) -> tuple[float, float]:
        segments = transcript.segments
        idx = next((i for i, seg in enumerate(segments) if seg.segment_id == event.source_chunk_id), -1)
        if idx < 0:
            return max(0.0, event.start_time - 1.0), event.end_time + 2.0

        start = segments[idx].start_ms / 1000.0
        end = segments[idx].end_ms / 1000.0

        if idx > 0:
            prev = segments[idx - 1]
            prev_gap = start - (prev.end_ms / 1000.0)
            if prev_gap <= 1.8 and (prev.text.rstrip()[-1:] not in ".?!" or self._is_setup_line(prev.text)):
                start = prev.start_ms / 1000.0

        max_steps = 2
        cursor = idx + 1
        while cursor < len(segments) and max_steps > 0:
            seg = segments[cursor]
            gap = (seg.start_ms / 1000.0) - end
            if gap > 2.5:
                break
            seg_text = seg.text.lower()
            same_turn = gap <= 0.8
            reaction = any(re.search(rf"\b{re.escape(verb)}\b", seg_text) for verb in REACTION_VERBS)
            follow_up = self._is_follow_up_line(seg_text)
            if same_turn or reaction or follow_up:
                end = seg.end_ms / 1000.0
                max_steps -= 1
                cursor += 1
                continue
            break

        duration = end - start
        if duration < 4.0:
            pad = (4.0 - duration) / 2.0
            start = max(0.0, start - pad)
            end = end + pad
        return round(start, 3), round(end, 3)

    def _score_action(self, targets: List[Optional[str]], action: str) -> float:
        target_tokens = [self._norm(t) for t in targets if t]
        if not target_tokens:
            return 0.0
        event_token = self._norm(action)
        if event_token in target_tokens:
            return 1.0

        query_actions = set(target_tokens)
        transfer_family = {"transfer", "give", "hand", "pass", "pay", "present"}
        laugh_family = {"laugh", "laughter", "giggle", "chuckle"}
        speak_family = {"speak", "say", "mention", "tell", "ask", "answer"}

        families = [transfer_family, laugh_family, speak_family]
        for family in families:
            if event_token in family and any(token in family for token in query_actions):
                return 0.88
        return max((SequenceMatcher(None, token, event_token).ratio() for token in query_actions), default=0.0)

    def _score_money(
        self,
        query_money: Optional[dict],
        event_money: Optional[str],
        event_object: Optional[str],
    ) -> float:
        if not query_money:
            return 0.0
        query_amount = float(query_money.get("amount", 0))
        query_currency = str(query_money.get("currency", "")).upper()
        haystack = " ".join(part for part in [event_money, event_object] if part).lower()
        if not haystack:
            return 0.0
        digits = re.findall(r"\d+(?:\.\d+)?", haystack)
        if any(abs(float(value) - query_amount) < 1.0 for value in digits):
            if query_currency and query_currency in {"INR", "USD", "GBP"}:
                return 1.0
            return 0.92
        if digits:
            return 0.4
        if query_currency == "INR" and re.search(r"rupee|rs\.?|inr", haystack):
            return 0.55
        return 0.0

    def _semantic_overlap(self, prompt: str, transcript_text: str) -> float:
        prompt_terms = {term for term in re.findall(r"\b[a-z0-9]{3,}\b", prompt.lower()) if term not in {"keep", "only", "part"}}
        text_terms = set(re.findall(r"\b[a-z0-9]{3,}\b", transcript_text.lower()))
        if not prompt_terms:
            return 0.0
        overlap = len(prompt_terms & text_terms) / len(prompt_terms)
        return min(1.0, overlap)

    def _temporal_score(self, intent: ParsedQuery, event: SemanticEvent) -> float:
        # Baseline lowered — a flat 0.45 inflated early-segment events.
        score = 0.12
        if "first_time" in intent.temporal_modifiers or "last_time" in intent.temporal_modifiers:
            score += 0.35
        duration = max(0.1, event.end_time - event.start_time)
        if duration <= 8.0 and "first_time" in intent.temporal_modifiers:
            score += 0.15
        if event.action in TRANSFER_VERBS | REACTION_VERBS:
            score += 0.08
        return min(1.0, score)

    def _best_match(self, left_values: List[Optional[str]], right_values: List[Optional[str]]) -> float:
        left = [self._norm(value) for value in left_values if value]
        right = [self._norm(value) for value in right_values if value]
        if not left or not right:
            return 0.0
        best = 0.0
        for lval in left:
            for rval in right:
                if not lval or not rval:
                    continue
                if lval == rval:
                    best = max(best, 1.0)
                    continue
                if lval in rval or rval in lval:
                    best = max(best, 0.88)
                    continue
                best = max(best, SequenceMatcher(None, lval, rval).ratio())
        return best

    def _rejected_actions(self, items: List[tuple[SemanticEvent, EventScore]]) -> List[Dict[str, object]]:
        rejected: List[Dict[str, object]] = []
        for event, score in items:
            rejected.append(
                {
                    "event_id": event.id,
                    "source_chunk_id": event.source_chunk_id,
                    "start_time": event.start_time,
                    "end_time": event.end_time,
                    "final_score": score.final_score,
                    "reasoning": score.reasoning,
                    "transcript_text": event.transcript_text[:220],
                }
            )
        return rejected

    def _map_action_type(self, intent_action: str) -> ActionType:
        mapping = {
            "keep_segment": "keep_segment",
            "extract_clip": "extract_clip",
            "remove_segment": "remove_segment",
        }
        return mapping.get(intent_action, "keep_segment")

    def _norm(self, value: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _is_setup_line(self, text: str) -> bool:
        lower = text.lower()
        return lower.startswith(("so ", "and ", "but ", "then ")) or "?" in lower

    def _is_follow_up_line(self, text: str) -> bool:
        return text.startswith(("and ", "then ", "so ", "because ")) or "laughter" in text or "applause" in text

    def _read_threshold(self, env_var: str, default: float) -> float:
        raw = os.environ.get(env_var)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError:
            logger.warning("[ActionPlanner] Invalid %s=%r, using %.2f", env_var, raw, default)
            return default
        if value <= 0 or value > 1:
            logger.warning("[ActionPlanner] Out-of-range %s=%r, using %.2f", env_var, raw, default)
            return default
        return value
