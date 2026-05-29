"""
Speaker diarization via pyannote.audio with heuristic fallback.

Requires HF_TOKEN in environment for pyannote/speaker-diarization-3.1.
Falls back to silence-gap + librosa acoustic change detection when unavailable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from python.models.transcript import TranscriptDocument, TranscriptSegment, Utterance, Word

logger = logging.getLogger(__name__)

CROSSTALK_OVERLAP_THRESHOLD = 0.20
CROSSTALK_MIN_DURATION_SEC = 2.0


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker_id: str


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speaker_to_word(word: Word, speaker_segments: List[SpeakerSegment]) -> Optional[str]:
    best_speaker: Optional[str] = None
    best_overlap = 0.0
    for seg in speaker_segments:
        ov = _overlap(word.start, word.end, seg.start, seg.end)
        if ov > best_overlap:
            best_overlap = ov
            best_speaker = seg.speaker_id
    return best_speaker


def run_pyannote_diarization(audio_path: str, hf_token: Optional[str] = None) -> List[SpeakerSegment]:
    token = hf_token or os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN not set")

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=token,
    )
    diarization = pipeline(audio_path)

    segments: List[SpeakerSegment] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            SpeakerSegment(
                start=float(turn.start),
                end=float(turn.end),
                speaker_id=str(speaker),
            )
        )
    return segments


def run_heuristic_diarization(audio_path: str) -> List[SpeakerSegment]:
    """
    Fallback: split on silence gaps >500ms and label speakers by acoustic change.
    """
    import numpy as np

    try:
        import librosa
    except ImportError:
        logger.warning("librosa not available; using single-speaker fallback")
        import soundfile as sf

        audio, sr = sf.read(audio_path, dtype="float32")
        duration = len(audio) / sr
        return [SpeakerSegment(0.0, duration, "SPEAKER_00")]

    y, sr = librosa.load(audio_path, sr=16000, mono=True)
    duration = len(y) / sr

    # Energy-based silence detection
    frame_length = 512
    hop = 256
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)

    silence_threshold = np.percentile(rms, 20)
    is_speech = rms > silence_threshold

    boundaries = [0.0]
    min_gap_sec = 0.5
    in_silence = False
    silence_start = 0.0

    for i, speech in enumerate(is_speech):
        t = float(times[i])
        if not speech and not in_silence:
            in_silence = True
            silence_start = t
        elif speech and in_silence:
            gap = t - silence_start
            if gap >= min_gap_sec:
                boundaries.append(t)
            in_silence = False

    boundaries.append(duration)
    boundaries = sorted(set(boundaries))

    segments: List[SpeakerSegment] = []
    speaker_idx = 0
    prev_centroid: Optional[np.ndarray] = None

    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if end - start < 0.3:
            continue

        s0 = int(start * sr)
        s1 = int(end * sr)
        chunk = y[s0:s1]
        if len(chunk) < sr * 0.2:
            continue

        centroid = np.mean(np.abs(np.fft.rfft(chunk[: min(len(chunk), sr)])))
        if prev_centroid is not None and abs(centroid - prev_centroid) / (prev_centroid + 1e-8) > 0.35:
            speaker_idx = (speaker_idx + 1) % 4

        segments.append(
            SpeakerSegment(start=start, end=end, speaker_id=f"SPEAKER_{speaker_idx:02d}")
        )
        prev_centroid = centroid

    if not segments:
        segments = [SpeakerSegment(0.0, duration, "SPEAKER_00")]

    return segments


def detect_crosstalk_regions(
    speaker_segments: List[SpeakerSegment],
    min_duration: float = CROSSTALK_MIN_DURATION_SEC,
    overlap_threshold: float = CROSSTALK_OVERLAP_THRESHOLD,
) -> List[Tuple[float, float]]:
    """Find regions where two speakers overlap >threshold for >min_duration seconds."""
    crosstalk: List[Tuple[float, float]] = []
    by_time: List[Tuple[float, float, str]] = [
        (s.start, s.end, s.speaker_id) for s in speaker_segments
    ]

    if len(by_time) < 2:
        return crosstalk

    # Sample at 100ms intervals
    max_end = max(s.end for s in speaker_segments)
    t = 0.0
    overlap_start: Optional[float] = None

    while t < max_end:
        active = set()
        for start, end, spk in by_time:
            if start <= t < end:
                active.add(spk)

        if len(active) >= 2:
            if overlap_start is None:
                overlap_start = t
        else:
            if overlap_start is not None and t - overlap_start >= min_duration:
                crosstalk.append((overlap_start, t))
            overlap_start = None

        t += 0.1

    if overlap_start is not None and max_end - overlap_start >= min_duration:
        crosstalk.append((overlap_start, max_end))

    return crosstalk


def words_to_utterances(words: List[Word], gap_sec: float = 0.8) -> List[Utterance]:
    if not words:
        return []

    utterances: List[Utterance] = []
    current_words: List[Word] = [words[0]]
    current_speaker = words[0].speaker_id

    for w in words[1:]:
        prev = current_words[-1]
        same_speaker = w.speaker_id == current_speaker
        small_gap = w.start - prev.end <= gap_sec
        if same_speaker and small_gap:
            current_words.append(w)
        else:
            utterances.append(_make_utterance(current_words))
            current_words = [w]
            current_speaker = w.speaker_id

    if current_words:
        utterances.append(_make_utterance(current_words))
    return utterances


def _make_utterance(words: List[Word]) -> Utterance:
    raw_text = " ".join(w.text for w in words).strip()
    return Utterance(
        words=words,
        start=words[0].start,
        end=words[-1].end,
        speaker_id=words[0].speaker_id,
        raw_text=raw_text,
    )


def merge_transcription_and_diarization(
    whisper_result: Dict[str, Any],
    diarization_segments: List[SpeakerSegment],
    video_id: str,
) -> TranscriptDocument:
    """Align word-level Whisper output to speaker segments."""
    from python.transcription.whisper_engine import whisper_result_to_words

    words = whisper_result_to_words(whisper_result)
    for word in words:
        word.speaker_id = assign_speaker_to_word(word, diarization_segments)

    utterances = words_to_utterances(words)
    crosstalk_regions = detect_crosstalk_regions(diarization_segments)

    def is_crosstalk(start: float, end: float) -> bool:
        for ct_start, ct_end in crosstalk_regions:
            if _overlap(start, end, ct_start, ct_end) > 0.5 * (end - start):
                return True
        return False

    segments: List[TranscriptSegment] = []
    if utterances:
        current_utts: List[Utterance] = [utterances[0]]
        current_speaker = utterances[0].speaker_id

        for utt in utterances[1:]:
            if utt.speaker_id == current_speaker and not is_crosstalk(utt.start, utt.end):
                current_utts.append(utt)
            else:
                seg_type = "crosstalk" if is_crosstalk(current_utts[0].start, current_utts[-1].end) else "monologue"
                if len(set(u.speaker_id for u in current_utts)) > 1:
                    seg_type = "dialogue"
                segments.append(
                    TranscriptSegment(
                        utterances=current_utts,
                        start=current_utts[0].start,
                        end=current_utts[-1].end,
                        speaker_id=current_speaker,
                        segment_type=seg_type,
                    )
                )
                current_utts = [utt]
                current_speaker = utt.speaker_id

        if current_utts:
            seg_type = "crosstalk" if is_crosstalk(current_utts[0].start, current_utts[-1].end) else "monologue"
            segments.append(
                TranscriptSegment(
                    utterances=current_utts,
                    start=current_utts[0].start,
                    end=current_utts[-1].end,
                    speaker_id=current_speaker,
                    segment_type=seg_type,
                )
            )

    speaker_map = {s.speaker_id: s.speaker_id for s in diarization_segments}
    unique_speakers = sorted(set(speaker_map.keys()))
    for i, spk in enumerate(unique_speakers):
        speaker_map[spk] = f"Speaker {i + 1}"

    duration = float(whisper_result.get("duration", 0.0))
    if not duration and words:
        duration = words[-1].end

    return TranscriptDocument(
        video_id=video_id,
        duration_sec=duration,
        words=words,
        utterances=utterances,
        segments=segments,
        speaker_map=speaker_map,
        metadata={"diarization_method": "pyannote" if len(diarization_segments) > 1 else "heuristic"},
    )


async def diarize_audio(audio_path: str) -> List[SpeakerSegment]:
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        try:
            return run_pyannote_diarization(audio_path, hf_token)
        except Exception as e:
            logger.warning("pyannote diarization failed, falling back to heuristic: %s", e)
    else:
        logger.warning("HF_TOKEN not set; using heuristic speaker diarization")

    return run_heuristic_diarization(audio_path)
