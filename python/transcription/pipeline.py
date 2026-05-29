"""
End-to-end transcript processing pipeline.

Transcription -> Diarization -> Correction -> Chunking
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from python.models.transcript import TranscriptDocument, Utterance, Word
from python.retrieval.chunker import Chunk, build_all_chunks
from python.transcription.corrector import correct_utterances_batch, get_utterance_text
from python.transcription.diarization import diarize_audio, merge_transcription_and_diarization
from python.transcription.whisper_engine import transcribe_with_words

logger = logging.getLogger(__name__)


def segments_to_document(
    segments: List[Dict[str, Any]],
    video_id: str = "fixture",
) -> TranscriptDocument:
    """Build TranscriptDocument from flat API-style segments (for benchmarks/fixtures)."""
    words: List[Word] = []
    utterances: List[Utterance] = []

    for seg in segments:
        speaker = seg.get("speaker")
        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        seg_words = [
            Word(
                text=text,
                start=float(seg["start"]),
                end=float(seg["end"]),
                confidence=float(seg.get("confidence", 0.0)),
                speaker_id=speaker,
            )
        ]
        words.extend(seg_words)
        utterances.append(
            Utterance(
                words=seg_words,
                start=float(seg["start"]),
                end=float(seg["end"]),
                speaker_id=speaker,
                raw_text=text,
                corrected_text=text,
            )
        )

    duration = max((s["end"] for s in segments), default=0.0)
    speakers = sorted(set(s.get("speaker") for s in segments if s.get("speaker")))
    speaker_map = {spk: spk.replace("_", " ").title() for spk in speakers}

    from python.models.transcript import TranscriptSegment

    doc_segments = [
        TranscriptSegment(
            utterances=[u],
            start=u.start,
            end=u.end,
            speaker_id=u.speaker_id,
            segment_type="monologue",
        )
        for u in utterances
    ]

    return TranscriptDocument(
        video_id=video_id,
        duration_sec=float(duration),
        words=words,
        utterances=utterances,
        segments=doc_segments,
        speaker_map=speaker_map,
        metadata={"source": "segments_fixture"},
    )


async def process_media(
    media_path: str,
    video_id: str,
    model_name: Optional[str] = None,
    language: Optional[str] = None,
    skip_correction: bool = False,
    skip_topic_label: bool = True,
) -> Dict[str, Any]:
    """Full pipeline for a media file."""
    import sys
    from pathlib import Path

    ai_service = Path(__file__).resolve().parents[2] / "apps" / "ai-service"
    if str(ai_service) not in sys.path:
        sys.path.insert(0, str(ai_service))

    from config import settings
    from transcription import extract_audio_wav, find_ffmpeg, normalize_media_path

    path = normalize_media_path(media_path)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    cache_dir = Path(settings.cache_dir) / "audio"
    wav_path = extract_audio_wav(ffmpeg, path, cache_dir)

    whisper_result = await transcribe_with_words(str(path), model_name, language)
    diar_segments = await diarize_audio(str(wav_path))
    doc = merge_transcription_and_diarization(whisper_result, diar_segments, video_id)

    if not skip_correction:
        doc.utterances = await correct_utterances_batch(doc.utterances)

    all_chunks = await build_all_chunks(doc, skip_topic_label=skip_topic_label)

    return {
        "document": doc.model_dump(),
        "chunks": {k: [c.model_dump() for c in v] for k, v in all_chunks.items()},
        "chunk_counts": {k: len(v) for k, v in all_chunks.items()},
    }


async def process_segments(
    segments: List[Dict[str, Any]],
    video_id: str = "fixture",
    skip_correction: bool = True,
    skip_topic_label: bool = True,
    with_intelligence: bool = False,
) -> tuple[TranscriptDocument, Dict[str, List[Chunk]]]:
    """Process fixture/API segments through chunking pipeline."""
    if with_intelligence:
        from python.intelligence.extraction_pipeline import extract_intelligence

        artifacts = await extract_intelligence(
            segments, video_id, skip_topic_label=skip_topic_label
        )
        return artifacts.document, artifacts.chunks

    doc = segments_to_document(segments, video_id)

    if not skip_correction:
        doc.utterances = await correct_utterances_batch(doc.utterances)

    all_chunks = await build_all_chunks(doc, skip_topic_label=skip_topic_label)
    return doc, all_chunks
