"""Enriched transcript dataclasses for semantic retrieval."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TranscriptWord:
    word: str
    start_ms: int
    end_ms: int
    confidence: float
    speaker_id: Optional[str] = None


@dataclass
class TranscriptSegment:
    text: str
    start_ms: int
    end_ms: int
    words: List[TranscriptWord]
    speaker_id: Optional[str] = None
    segment_id: str = ""


@dataclass
class ExtractedEntity:
    text: str
    entity_type: str
    start_ms: int
    end_ms: int
    segment_id: str
    confidence: float = 0.8
    normalized: str = ""


@dataclass
class ExtractedEvent:
    subject: str
    subject_entity_id: str
    verb: str
    action_type: str
    object_: str
    object_entity_id: str
    indirect_object: str
    raw_text: str
    start_ms: int
    end_ms: int
    segment_id: str
    confidence: float
    monetary_ref: Optional[str] = None


@dataclass
class MonetaryMention:
    raw_text: str
    amount_normalized: float
    currency: str
    start_ms: int
    end_ms: int
    segment_id: str
    confidence: float
    mention_id: str = ""


@dataclass
class Scene:
    scene_id: str
    start_ms: int
    end_ms: int
    segment_ids: List[str]
    dominant_speaker: Optional[str] = None
    entity_ids: List[str] = field(default_factory=list)
    event_ids: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    monetary_mention_ids: List[str] = field(default_factory=list)
    boundary_confidence: float = 0.5


@dataclass
class DiarizationSegment:
    speaker_id: str
    start_ms: int
    end_ms: int


@dataclass
class EnrichedTranscript:
    video_id: str
    segments: List[TranscriptSegment]
    entities: List[ExtractedEntity] = field(default_factory=list)
    events: List[ExtractedEvent] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    monetary_mentions: List[MonetaryMention] = field(default_factory=list)
    speaker_map: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnrichedTranscript":
        segments = [
            TranscriptSegment(
                text=s["text"],
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                words=[TranscriptWord(**w) for w in s.get("words", [])],
                speaker_id=s.get("speaker_id"),
                segment_id=s.get("segment_id", ""),
            )
            for s in data.get("segments", [])
        ]
        monetary = [MonetaryMention(**m) for m in data.get("monetary_mentions", [])]
        entities = [ExtractedEntity(**e) for e in data.get("entities", [])]
        events = []
        for ev in data.get("events", []):
            events.append(ExtractedEvent(**{**ev, "object_": ev.get("object_", ev.get("object_", ""))}))
        scenes = [Scene(**sc) for sc in data.get("scenes", [])]
        return cls(
            video_id=data.get("video_id", "default"),
            segments=segments,
            entities=entities,
            events=events,
            scenes=scenes,
            monetary_mentions=monetary,
            speaker_map=data.get("speaker_map", {}),
        )


def enriched_path(data_root: Path, video_id: str) -> Path:
    return data_root / video_id / "transcript_enriched.json"


def persist_enriched(transcript: EnrichedTranscript, data_root: Optional[Path] = None) -> Path:
    root = data_root or Path(__file__).resolve().parents[2] / "data"
    path = enriched_path(root, transcript.video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(transcript.to_dict(), indent=2), encoding="utf-8")
    return path


def load_enriched(video_id: str, data_root: Optional[Path] = None) -> Optional[EnrichedTranscript]:
    root = data_root or Path(__file__).resolve().parents[2] / "data"
    path = enriched_path(root, video_id)
    if not path.is_file():
        return None
    return EnrichedTranscript.from_dict(json.loads(path.read_text(encoding="utf-8")))
