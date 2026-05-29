"""
Multimodal index: frames, CLIP embeddings, scene descriptions, OCR.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from python.embeddings.embedder import EmbeddingEngine
from python.multimodal.clip_embedder import CLIPEmbedder
from python.multimodal.frame_extractor import FrameIndex, FrameRecord, extract_frames, extract_key_frames
from python.multimodal.ocr_engine import OCRResult, extract_ocr_from_frames
from python.multimodal.scene_describer import SceneDescription, describe_key_frames
from python.retrieval.chunker import Chunk
from python.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class MultimodalArtifacts:
    video_id: str
    frame_index: FrameIndex = field(default_factory=lambda: FrameIndex(""))
    clip: Optional[CLIPEmbedder] = None
    scene_descriptions: List[SceneDescription] = field(default_factory=list)
    ocr_results: List[OCRResult] = field(default_factory=list)
    scene_chunks: List[Chunk] = field(default_factory=list)
    ready: bool = False


async def build_multimodal_index(
    media_path: str,
    video_id: str,
    duration_sec: float,
    speaker_change_times: Optional[List[float]] = None,
    skip_ollama_scenes: bool = True,
) -> MultimodalArtifacts:
    artifacts = MultimodalArtifacts(video_id=video_id)
    artifacts.frame_index = extract_frames(media_path, video_id, fps=1.0)

    key_frames = extract_key_frames(
        media_path,
        video_id,
        speaker_change_times or [],
        [],
        duration_sec,
    )
    for kf in key_frames:
        artifacts.frame_index.add(kf)

    clip = CLIPEmbedder(video_id)
    clip.embed_frames(artifacts.frame_index)
    artifacts.clip = clip

    key_only = [f for f in artifacts.frame_index.frames if f.is_key_frame]
    if not skip_ollama_scenes:
        artifacts.scene_descriptions = await describe_key_frames(key_only)
    else:
        artifacts.scene_descriptions = []

    artifacts.ocr_results = extract_ocr_from_frames(key_only)

    # Build scene description chunks for dense index
    embedder = EmbeddingEngine()
    vector_store = VectorStore()
    scene_chunks: List[Chunk] = []

    for desc in artifacts.scene_descriptions:
        cid = f"scene_{int(desc.timestamp_sec * 1000)}"
        chunk = Chunk(
            chunk_id=cid,
            video_id=video_id,
            text=desc.description,
            start_sec=max(0.0, desc.timestamp_sec - 10),
            end_sec=desc.timestamp_sec + 10,
            chunk_type="scene_description",
        )
        embedder.embed_chunks([chunk])
        scene_chunks.append(chunk)

    for ocr in artifacts.ocr_results:
        cid = f"ocr_{int(ocr.timestamp_sec * 1000)}"
        chunk = Chunk(
            chunk_id=cid,
            video_id=video_id,
            text=ocr.text,
            start_sec=max(0.0, ocr.timestamp_sec - 10),
            end_sec=ocr.timestamp_sec + 10,
            chunk_type="scene_description",
            metadata={"source": "ocr"},
        )
        embedder.embed_chunks([chunk])
        scene_chunks.append(chunk)

    if scene_chunks:
        vector_store.upsert_chunks(scene_chunks, "scene_description", video_id)

    artifacts.scene_chunks = scene_chunks
    artifacts.ready = clip.frame_embeddings is not None
    return artifacts


def frames_to_windows(
    frame_results: List[Tuple[FrameRecord, float]],
    padding_sec: float = 10.0,
) -> List[Tuple[float, float, float]]:
    windows = []
    for rec, score in frame_results:
        windows.append(
            (max(0.0, rec.timestamp_sec - padding_sec), rec.timestamp_sec + padding_sec, score)
        )
    return windows


def merge_transcript_visual(
    transcript_results: list,
    visual_windows: List[Tuple[float, float, float]],
) -> list:
    """Merge transcript retrieval results with visual windows by RRF-like boost."""
    if not visual_windows:
        return transcript_results

    boosted = list(transcript_results)
    for i, item in enumerate(boosted):
        for vstart, vend, vscore in visual_windows:
            if item.start_sec <= vend and item.end_sec >= vstart:
                item.score_fused = getattr(item, "score_fused", 0) + vscore * 0.3
                break

    boosted.sort(key=lambda x: getattr(x, "score_fused", 0), reverse=True)
    return boosted
