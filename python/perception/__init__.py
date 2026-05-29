"""
Perception layer — visual / audio signal extractors.

This package is the integration surface for the spec's Phase 1-4 perception
modules (scene detection, face tracking, motion analysis, emotion detection).
None of those heavy dependencies (InsightFace, RAFT, MediaPipe, DeepFace,
SpeechBrain) are required to *import* this package — every module here
ships a working fallback that produces empty / heuristic output when the
real backends are absent.

The retrieval engine consumes these signals through stable dataclasses:

- :class:`FaceTrack`            (from face_identity)
- :class:`SpeakerFaceMapping`   (from speaker_face_correlator)
- :class:`MotionSignal`         (placeholder, populated by Phase 3)
- :class:`EmotionSignal`        (placeholder, populated by Phase 4)

When a real backend is installed, perception output is written to the
per-video cache directory (``~/.axew/cache/{video_id}/perception/``) and the
retrieval engine loads it via :func:`load_cached_perception`.
"""

from python.perception.face_identity import (
    FaceTrack,
    IdentityRegistry,
    PerceptionBackendStatus,
    detect_backend_status,
    load_identity_registry,
)
from python.perception.speaker_face_correlator import (
    SpeakerFaceMapping,
    correlate_speakers_to_faces,
)

__all__ = [
    "FaceTrack",
    "IdentityRegistry",
    "PerceptionBackendStatus",
    "detect_backend_status",
    "load_identity_registry",
    "SpeakerFaceMapping",
    "correlate_speakers_to_faces",
]
