"""Pydantic models for structured transcript representation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Word(BaseModel):
    text: str
    start: float
    end: float
    confidence: float
    speaker_id: Optional[str] = None


class WordTimestamp(BaseModel):
    """Word-level timestamp from Whisper output (word_timestamps=True)."""

    word: str
    start: float
    end: float
    confidence: float


class Utterance(BaseModel):
    words: List[Word]
    start: float
    end: float
    speaker_id: Optional[str] = None
    raw_text: str
    corrected_text: Optional[str] = None


class TranscriptChunk(BaseModel):
    """Chunk representation for retrieval pipeline with word-level timestamps."""

    id: str
    text: str
    start_time: float
    end_time: float
    speaker: Optional[str] = None
    words: List[WordTimestamp] = Field(default_factory=list)
    chunk_index: int = 0

    @classmethod
    def from_whisper_segment(cls, segment: Dict[str, Any], index: int) -> "TranscriptChunk":
        words = []
        if "words" in segment:
            words = [
                WordTimestamp(
                    word=w.get("word", "").strip(),
                    start=float(w.get("start", 0)),
                    end=float(w.get("end", 0)),
                    confidence=float(w.get("confidence", w.get("probability", 0.0))),
                )
                for w in segment["words"]
            ]
        return cls(
            id=segment.get("id", str(index)),
            text=segment.get("text", "").strip(),
            start_time=float(segment.get("start", 0)),
            end_time=float(segment.get("end", 0)),
            speaker=segment.get("speaker", segment.get("speaker_id")),
            words=words,
            chunk_index=index,
        )

    @classmethod
    def from_segment_dict(cls, seg: Dict[str, Any], index: int) -> "TranscriptChunk":
        """Create from the segment dict format used in API requests."""
        words = []
        if "words" in seg:
            words = [
                WordTimestamp(
                    word=w.get("word", "").strip(),
                    start=float(w.get("start", 0)),
                    end=float(w.get("end", 0)),
                    confidence=float(w.get("confidence", w.get("probability", 0.0))),
                )
                for w in seg["words"]
            ]
        return cls(
            id=seg.get("id", str(index)),
            text=seg.get("text", "").strip(),
            start_time=float(seg.get("start", seg.get("start_time", 0))),
            end_time=float(seg.get("end", seg.get("end_time", 0))),
            speaker=seg.get("speaker", seg.get("speaker_id")),
            words=words,
            chunk_index=index,
        )

    def interpolate_word_timestamps(self) -> None:
        """If words list is empty, interpolate from chunk boundaries."""
        if self.words or not self.text.strip():
            return
        tokens = self.text.split()
        if not tokens:
            return
        duration = self.end_time - self.start_time
        word_dur = duration / len(tokens)
        self.words = [
            WordTimestamp(
                word=tok,
                start=self.start_time + i * word_dur,
                end=self.start_time + (i + 1) * word_dur,
                confidence=0.5,
            )
            for i, tok in enumerate(tokens)
        ]


class TranscriptSegment(BaseModel):
    utterances: List[Utterance]
    start: float
    end: float
    speaker_id: Optional[str] = None
    topic_label: Optional[str] = None
    segment_type: Literal["monologue", "dialogue", "crosstalk", "silence"] = "dialogue"


class TranscriptDocument(BaseModel):
    video_id: str
    duration_sec: float
    words: List[Word] = Field(default_factory=list)
    utterances: List[Utterance] = Field(default_factory=list)
    segments: List[TranscriptSegment] = Field(default_factory=list)
    speaker_map: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
