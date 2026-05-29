"""Speaker diarization alignment and role classification."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from python.models.enriched import DiarizationSegment, TranscriptSegment, TranscriptWord
from python.transcription.diarization import (
    SpeakerSegment,
    assign_speaker_to_word,
    run_heuristic_diarization,
    run_pyannote_diarization,
)


class DiarizationEngine:
    def __init__(self, hf_token: Optional[str] = None) -> None:
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")

    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        try:
            if self.hf_token:
                raw = run_pyannote_diarization(audio_path, self.hf_token)
            else:
                raw = run_heuristic_diarization(audio_path)
        except Exception:
            raw = run_heuristic_diarization(audio_path)
        return [
            DiarizationSegment(
                speaker_id=s.speaker_id,
                start_ms=int(s.start * 1000),
                end_ms=int(s.end * 1000),
            )
            for s in raw
        ]


def align_speaker_to_words(
    words: List[TranscriptWord],
    diarization: List[DiarizationSegment],
) -> List[TranscriptWord]:
    """Assign speaker_id via maximum overlap; nearest segment if no overlap."""
    speaker_segs = [
        SpeakerSegment(start=d.start_ms / 1000.0, end=d.end_ms / 1000.0, speaker_id=d.speaker_id)
        for d in diarization
    ]
    from python.models.transcript import Word

    out: List[TranscriptWord] = []
    for w in words:
        pw = Word(
            text=w.word,
            start=w.start_ms / 1000.0,
            end=w.end_ms / 1000.0,
            confidence=w.confidence,
            speaker_id=w.speaker_id,
        )
        sid = assign_speaker_to_word(pw, speaker_segs)
        if not sid and speaker_segs:
            center = (w.start_ms + w.end_ms) / 2000.0
            nearest = min(speaker_segs, key=lambda s: abs((s.start + s.end) / 2 - center))
            sid = nearest.speaker_id
        out.append(
            TranscriptWord(
                word=w.word,
                start_ms=w.start_ms,
                end_ms=w.end_ms,
                confidence=w.confidence,
                speaker_id=sid,
            )
        )
    return out


def classify_speaker_roles(segments: List[TranscriptSegment]) -> Dict[str, str]:
    """
    Map speaker IDs to semantic roles (interviewer, named entity).
    Heuristic: more questions → interviewer; most-mentioned person name → entity role.
    """
    questions: Dict[str, int] = {}
    mentions: Dict[str, Dict[str, int]] = {}

    for seg in segments:
        sid = seg.speaker_id or "UNKNOWN"
        text = seg.text
        if "?" in text or re.search(r"\b(what|why|how|when|tell me|let's)\b", text, re.I):
            questions[sid] = questions.get(sid, 0) + 1
        for name in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
            mentions.setdefault(sid, {})
            mentions[sid][name] = mentions.get(sid, {}).get(name, 0) + 1

    role_map: Dict[str, str] = {}
    if questions:
        interviewer_id = max(questions, key=questions.get)
        role_map[interviewer_id] = "interviewer"

    # Named guest: person most mentioned by others
    global_mentions: Dict[str, int] = {}
    for seg in segments:
        for name in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", seg.text):
            global_mentions[name] = global_mentions.get(name, 0) + 1
    if global_mentions:
        top_name = max(global_mentions, key=global_mentions.get)
        for sid, m in mentions.items():
            if sid in role_map:
                continue
            if top_name in m or any(top_name.split()[0] in k for k in m):
                role_map[sid] = top_name

    for seg in segments:
        sid = seg.speaker_id
        if sid and sid not in role_map:
            role_map[sid] = sid

    # Fixture speaker labels from segment metadata
    return role_map
