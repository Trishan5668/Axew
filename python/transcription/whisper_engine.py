"""
Whisper transcription engine with word-level timestamps.

Wraps openai-whisper and parses output into the Word schema.
Raw word-level data is stored separately as ground truth for timestamp refinement.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from python.models.transcript import Word

logger = logging.getLogger(__name__)

# Allow importing ai-service modules when run from project root
_AI_SERVICE = Path(__file__).resolve().parents[2] / "apps" / "ai-service"
if str(_AI_SERVICE) not in sys.path:
    sys.path.insert(0, str(_AI_SERVICE))


def parse_whisper_words(segment: Dict[str, Any], speaker_id: Optional[str] = None) -> List[Word]:
    words: List[Word] = []
    for w in segment.get("words", []):
        text = str(w.get("word", w.get("text", ""))).strip()
        if not text:
            continue
        words.append(
            Word(
                text=text,
                start=float(w["start"]),
                end=float(w["end"]),
                confidence=float(w.get("probability", w.get("confidence", 0.0))),
                speaker_id=speaker_id,
            )
        )
    return words


def whisper_result_to_words(whisper_result: Dict[str, Any]) -> List[Word]:
    """Extract flat word list from Whisper transcribe() output."""
    all_words: List[Word] = []
    for seg in whisper_result.get("segments", []):
        all_words.extend(parse_whisper_words(seg))
    return all_words


async def transcribe_with_words(
    media_path: str,
    model_name: Optional[str] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcribe media with word_timestamps=True.

    Returns whisper result dict plus parsed `words` list and raw segment data.
    """
    from transcription import transcribe_media_async

    result = await transcribe_media_async(
        media_path,
        model_name=model_name,
        language=language,
        word_timestamps=True,
    )

    words = whisper_result_to_words({"segments": result.get("segments", [])})
    result["words"] = [w.model_dump() for w in words]
    result["word_count"] = len(words)
    return result


def segments_to_words(segments: List[Dict[str, Any]]) -> List[Word]:
    """Convert API-style segments (with optional words[]) to Word list."""
    words: List[Word] = []
    for seg in segments:
        if "words" in seg and seg["words"]:
            for w in seg["words"]:
                words.append(
                    Word(
                        text=str(w.get("word", w.get("text", ""))).strip(),
                        start=float(w["start"]),
                        end=float(w["end"]),
                        confidence=float(w.get("confidence", w.get("probability", 0.0))),
                        speaker_id=seg.get("speaker_id"),
                    )
                )
        else:
            # Fallback: treat whole segment as one word span
            text = str(seg.get("text", "")).strip()
            if text:
                words.append(
                    Word(
                        text=text,
                        start=float(seg["start"]),
                        end=float(seg["end"]),
                        confidence=float(seg.get("confidence", 0.0)),
                        speaker_id=seg.get("speaker_id"),
                    )
                )
    return words
