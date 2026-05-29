"""
Speaker ↔ face identity correlator.

Maps diarization speaker labels ("SPEAKER_00", "interviewer", ...) to known
face identities by timestamp-windowed overlap. When face tracks are not
available, the correlator falls back to a trivial 1:1 mapping
``speaker_label -> identity_with_same_id``, which is enough for retrieval to
reason about *who said what* even with zero visual data.

This module is the single point retrieval queries to ask "which named entity
is the speaker of this moment?" — the entity-grounded retriever needs that
edge to fire the role-bind heuristic ("interviewer gives ..." → speaker must
be the interviewer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from python.perception.face_identity import FaceTrack, IdentityRegistry

logger = logging.getLogger(__name__)

# A reasonable window to associate a face appearance with a speech turn.
# Anything longer than this risks crossing scene boundaries.
DEFAULT_OVERLAP_WINDOW_SEC = 0.5


@dataclass
class SpeakerFaceMapping:
    """One row of the speaker→face binding table."""

    speaker_label: str
    identity_id: Optional[str]
    display_name: Optional[str]
    confidence: float = 0.0
    overlap_seconds: float = 0.0
    method: str = "transcript_only"  # "face_overlap" | "transcript_only" | "manual"
    appearances: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker_label": self.speaker_label,
            "identity_id": self.identity_id,
            "display_name": self.display_name,
            "confidence": self.confidence,
            "overlap_seconds": self.overlap_seconds,
            "method": self.method,
            "appearances": list(self.appearances),
        }


def _speaker_appearances(
    segments: Iterable[Dict[str, Any]],
    speaker_label: str,
) -> List[Dict[str, Any]]:
    """Collect time windows where this speaker is active in the transcript."""
    out: List[Dict[str, Any]] = []
    for seg in segments:
        if seg.get("speaker") == speaker_label or seg.get("speaker_id") == speaker_label:
            out.append(
                {
                    "start": float(seg.get("start", 0.0)),
                    "end": float(seg.get("end", 0.0)),
                    "source": "diarization",
                }
            )
    return out


def correlate_speakers_to_faces(
    segments: List[Dict[str, Any]],
    registry: IdentityRegistry,
    window_sec: float = DEFAULT_OVERLAP_WINDOW_SEC,
    manual_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, SpeakerFaceMapping]:
    """Compute the speaker→identity mapping for a video.

    Three layers of evidence are combined, strongest first:

    1. ``manual_overrides`` — ``{speaker_label: identity_id}`` (UI binding)
    2. **Face overlap** — fraction of speaker turn covered by an identity's
       face appearance windows (``IoU`` over the union of intervals).
    3. **Transcript fallback** — when the speaker label is itself a person
       (e.g. ``"vijay_mallya"``, ``"interviewer"``) we try to ``resolve`` it
       in the registry directly.

    Always returns a mapping for *every* speaker label, even when no face
    evidence exists (``method='transcript_only'``, ``confidence=...``).
    """
    speaker_labels = sorted({
        s.get("speaker") or s.get("speaker_id")
        for s in segments
        if (s.get("speaker") or s.get("speaker_id"))
    })

    manual_overrides = manual_overrides or {}
    result: Dict[str, SpeakerFaceMapping] = {}

    for label in speaker_labels:
        appearances = _speaker_appearances(segments, label)
        speaker_duration = float(sum(a["end"] - a["start"] for a in appearances)) or 0.001

        # 1) manual binding wins outright
        if label in manual_overrides:
            ident_id = manual_overrides[label]
            track = registry.tracks.get(ident_id) or registry.resolve(ident_id)
            result[label] = SpeakerFaceMapping(
                speaker_label=label,
                identity_id=track.identity_id if track else ident_id,
                display_name=track.display_name if track else ident_id,
                confidence=1.0,
                overlap_seconds=speaker_duration,
                method="manual",
                appearances=appearances,
            )
            continue

        # 2) face-overlap evidence — require both an absolute minimum
        #    (≥1s) AND a meaningful fraction of the speaker's turn (≥40%).
        #    Without the fraction gate, window-expansion bleeds neighboring
        #    speakers (e.g. narrator) into other identities at trivial conf.
        best_track: Optional[FaceTrack] = None
        best_overlap = 0.0
        for track in registry.tracks.values():
            overlap = _interval_union_overlap(appearances, track.appearances, window_sec)
            if overlap > best_overlap:
                best_overlap = overlap
                best_track = track

        face_overlap_conf = min(1.0, best_overlap / speaker_duration) if best_track else 0.0
        if best_track and best_overlap > 1.0 and face_overlap_conf >= 0.4:
            result[label] = SpeakerFaceMapping(
                speaker_label=label,
                identity_id=best_track.identity_id,
                display_name=best_track.display_name,
                confidence=face_overlap_conf,
                overlap_seconds=best_overlap,
                method="face_overlap",
                appearances=appearances,
            )
            continue

        # 3) transcript-only resolution
        track = registry.resolve(label)
        if track:
            result[label] = SpeakerFaceMapping(
                speaker_label=label,
                identity_id=track.identity_id,
                display_name=track.display_name,
                confidence=0.65,
                overlap_seconds=0.0,
                method="transcript_only",
                appearances=appearances,
            )
        else:
            # Last-resort identity: synthetic
            result[label] = SpeakerFaceMapping(
                speaker_label=label,
                identity_id=None,
                display_name=label,
                confidence=0.3,
                overlap_seconds=0.0,
                method="transcript_only",
                appearances=appearances,
            )

    return result


def _interval_union_overlap(
    a: List[Dict[str, Any]],
    b: List[Dict[str, Any]],
    window_sec: float,
) -> float:
    """Total overlap (seconds) between two sets of [start,end] intervals."""
    total = 0.0
    for ai in a:
        a_start = ai["start"] - window_sec
        a_end = ai["end"] + window_sec
        for bi in b:
            b_start = float(bi.get("start", 0.0))
            b_end = float(bi.get("end", 0.0))
            inter = min(a_end, b_end) - max(a_start, b_start)
            if inter > 0:
                total += inter
    return total


if __name__ == "__main__":  # pragma: no cover - smoke harness
    import json
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures" / "interview_segments.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        segments = json.load(f)

    reg = IdentityRegistry(project_id="fixture", root=Path("./.axew_test_cache/fixture"))
    reg.register_from_transcript(
        identity_id="vijay_mallya",
        display_name="Vijay Mallya",
        aliases=["Vijay", "Mallya", "the businessman"],
        appearances=[{"start": s["start"], "end": s["end"]} for s in segments if s["speaker"] == "vijay_mallya"],
    )
    reg.register_from_transcript(
        identity_id="rajesh_kumar",
        display_name="Rajesh Kumar",
        aliases=["Rajesh", "interviewer", "host"],
        appearances=[{"start": s["start"], "end": s["end"]} for s in segments if s["speaker"] == "interviewer"],
    )

    mapping = correlate_speakers_to_faces(segments, reg)
    for label, m in mapping.items():
        print(f"{label:15s} -> {m.display_name!r:25s} via={m.method:18s} conf={m.confidence:.2f}")
