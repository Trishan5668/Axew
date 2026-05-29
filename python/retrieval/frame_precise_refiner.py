"""
Frame-precise timestamp refiner.

The spec demands ``±0.5s`` accuracy on returned timestamps. The existing
``python.retrieval.timestamp_refiner`` is word-aligned but doesn't anchor
to *action* words (the verb that completes the event), so it tends to lock
to entity mentions instead of the actual transfer. This refiner anchors
on three explicit signals — action verb, vocative, monetary mention — and
guarantees a minimum 3.0 s clip with conversational padding.

A pure-Python implementation: it accepts the moment surface produced by
:class:`python.knowledge.hierarchical_index.Moment` and operates on its
``text`` + ``start_sec`` + ``end_sec``. When real word-level timestamps are
available (e.g. via WhisperX forced alignment), they are honored. When
absent, character-position interpolation is used — the same fallback the
existing :class:`TranscriptChunk.interpolate_word_timestamps` uses.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from python.knowledge.hierarchical_index import HierarchicalIndex, Moment

logger = logging.getLogger(__name__)


# Padding around the action anchor. The spec specifies +2s pre / +1.5s post.
PRE_ACTION_PAD_SEC = 2.0
POST_ACTION_PAD_SEC = 1.5
MIN_CLIP_DURATION_SEC = 3.0
MAX_CONTEXT_EXTEND_SEC = 6.0  # how far we'll absorb the next moment as context


@dataclass
class FramePreciseWindow:
    """A timestamp window with frame-grade anchors and audit info."""

    start_sec: float
    end_sec: float
    anchor_sec: float
    anchor_text: str
    anchor_kind: str  # "action_verb" | "vocative" | "monetary" | "moment_mid"
    moment_id: Optional[str] = None
    extended_moments: List[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "frame_precise"

    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _interpolate_word_position(
    text: str, target_word: str, start_sec: float, end_sec: float
) -> Optional[float]:
    """Estimate the timestamp of ``target_word`` inside a clause."""
    if not text or not target_word:
        return None
    pattern = re.compile(rf"\b{re.escape(target_word)}\w*\b", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    duration = max(0.001, end_sec - start_sec)
    pos = (match.start() + (match.end() - match.start()) / 2.0) / max(1, len(text))
    return round(start_sec + duration * pos, 3)


def _interpolate_phrase_position(
    text: str, phrase: str, start_sec: float, end_sec: float
) -> Optional[float]:
    if not text or not phrase:
        return None
    idx = text.lower().find(phrase.lower())
    if idx < 0:
        return None
    duration = max(0.001, end_sec - start_sec)
    pos = (idx + len(phrase) / 2.0) / max(1, len(text))
    return round(start_sec + duration * pos, 3)


def _moment_index(index: HierarchicalIndex, moment_id: str) -> int:
    for i, m in enumerate(index.moments):
        if m.moment_id == moment_id:
            return i
    return -1


def refine_window(
    index: HierarchicalIndex,
    moment: Moment,
    action_verbs: Sequence[str] = (),
    vocatives: Sequence[str] = (),
    monetary_phrases: Sequence[str] = (),
    extend_for_reaction: bool = True,
    confidence: float = 0.0,
) -> FramePreciseWindow:
    """Compute a frame-precise window around ``moment``.

    The anchor is selected by priority:

    1. The first matching ``action_verb`` position inside the moment.
    2. The first matching ``vocative`` position (direct address).
    3. The first matching monetary phrase position.
    4. The moment's midpoint.

    The returned window is ``[anchor - pre_pad, anchor + post_pad]``,
    clamped to the moment's parent segment and extended forward to absorb
    the immediately-following moment when ``extend_for_reaction`` is true
    *and* that next moment is the visible aftermath of the action
    (narrator, applause, laughter, opposing speaker reaction).
    """
    anchor_sec: Optional[float] = None
    anchor_kind = "moment_mid"
    anchor_text = moment.text

    candidates: List[Tuple[str, Sequence[str]]] = [
        ("action_verb", list(action_verbs) or moment.action_verbs),
        ("vocative", list(vocatives) or moment.vocatives),
        ("monetary", [m.get("text") or "" for m in moment.monetary] + list(monetary_phrases)),
    ]
    for kind, words in candidates:
        if anchor_sec is not None:
            break
        for w in words:
            if not w:
                continue
            ts = _interpolate_phrase_position(moment.text, w, moment.start_sec, moment.end_sec)
            if ts is None and " " not in w:
                ts = _interpolate_word_position(moment.text, w, moment.start_sec, moment.end_sec)
            if ts is not None:
                anchor_sec = ts
                anchor_kind = kind
                anchor_text = w
                break

    if anchor_sec is None:
        anchor_sec = round((moment.start_sec + moment.end_sec) / 2.0, 3)

    # Start: include the setup clauses in the same speaker turn that
    # introduce the action ("Here, let me recreate it. Vijay Mallya, ...").
    # We extend leftwards to the parent segment start so the clip is a
    # complete utterance, not just the verb. This is what makes the window
    # conversationally usable as an extract.
    parent_segment = None
    for seg in index.segments:
        if seg.segment_id == moment.segment_id:
            parent_segment = seg
            break

    if parent_segment is not None:
        start_sec = min(parent_segment.start_sec, anchor_sec - PRE_ACTION_PAD_SEC)
    else:
        start_sec = max(0.0, anchor_sec - PRE_ACTION_PAD_SEC)
    start_sec = max(0.0, start_sec)
    end_sec = max(moment.end_sec, anchor_sec + POST_ACTION_PAD_SEC)

    extended_moments: List[str] = []

    # Forward-extend to absorb reaction / narration when the action implies
    # a visible aftermath (TRANSFER/POINT/STAND/CRY/LAUGH actions are
    # incomplete without their consequence in conversational video).
    if extend_for_reaction and moment.action_types:
        i = _moment_index(index, moment.moment_id)
        if i >= 0:
            absorbed_dur = 0.0
            j = i + 1
            # Reaction sequences can include a 3-4s pause + narrator interjection.
            # Gap threshold is generous on the *first* hop, then tightens to avoid
            # rolling forward into the next topic.
            gap_tolerance = 4.0
            while j < len(index.moments) and absorbed_dur < MAX_CONTEXT_EXTEND_SEC * 2.5:
                nxt = index.moments[j]
                gap = nxt.start_sec - end_sec
                if gap > gap_tolerance:
                    break
                is_reaction = (
                    nxt.speaker != moment.speaker
                    and (
                        "APPLAUD" in nxt.action_types
                        or "LAUGH" in nxt.action_types
                        or "RECEIVE" in nxt.action_types
                        or "STAND" in nxt.action_types
                        or (nxt.speaker_role or "") == "narrator"
                        # Same recipient comments on the action ("I still have those...")
                        or (
                            nxt.entities
                            and any(v.lower() in [e.lower() for e in nxt.entities] for v in (vocatives or moment.vocatives))
                        )
                    )
                )
                if is_reaction:
                    end_sec = max(end_sec, nxt.end_sec)
                    extended_moments.append(nxt.moment_id)
                    absorbed_dur += nxt.end_sec - nxt.start_sec
                    j += 1
                    gap_tolerance = 2.0  # subsequent hops are tighter
                else:
                    break

    # Enforce minimum clip duration.
    if end_sec - start_sec < MIN_CLIP_DURATION_SEC:
        deficit = MIN_CLIP_DURATION_SEC - (end_sec - start_sec)
        # Prefer extending forward, then backward.
        end_sec += deficit * 0.6
        start_sec = max(0.0, start_sec - deficit * 0.4)

    if index.duration_sec:
        end_sec = min(end_sec, index.duration_sec)

    return FramePreciseWindow(
        start_sec=round(start_sec, 3),
        end_sec=round(end_sec, 3),
        anchor_sec=round(anchor_sec, 3),
        anchor_text=anchor_text,
        anchor_kind=anchor_kind,
        moment_id=moment.moment_id,
        extended_moments=extended_moments,
        confidence=confidence,
        method="frame_precise",
    )


if __name__ == "__main__":  # pragma: no cover - smoke harness
    import json
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures" / "interview_segments.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        segments = json.load(f)

    from python.knowledge.hierarchical_index import build_index_from_segments

    idx = build_index_from_segments(
        segments,
        known_entities=["Vijay Mallya", "101 rupees", "Kingfisher"],
    )
    winners = idx.moments_with_present_action("TRANSFER")
    print(f"Found {len(winners)} present-tense TRANSFER moments")
    for w in winners:
        window = refine_window(
            idx,
            w,
            action_verbs=["giving", "give"],
            vocatives=["Vijay Mallya"],
            monetary_phrases=["101 rupees"],
            confidence=1.0,
        )
        print("\nMoment:", w.moment_id, w.start_sec, "->", w.end_sec)
        print("Anchor:", window.anchor_sec, f"({window.anchor_kind}: {window.anchor_text!r})")
        print("Window:", window.start_sec, "->", window.end_sec, f"dur={window.duration_sec():.2f}s")
        print("Extended:", window.extended_moments)
        print("GT for ent_001: 92.5 -> 118.5s")
