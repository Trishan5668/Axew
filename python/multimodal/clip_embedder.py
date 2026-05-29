"""
CLIP vision-language embeddings for frame and text search.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from python.multimodal.frame_extractor import FrameIndex, FrameRecord

logger = logging.getLogger(__name__)

CLIP_CACHE = Path(os.path.expanduser("~/.axew/clip_embeddings"))

_clip_model = None
_clip_processor = None


def _load_clip():
    global _clip_model, _clip_processor
    if _clip_model is None:
        try:
            from transformers import CLIPModel, CLIPProcessor

            model_name = "openai/clip-vit-large-patch14"
            _clip_processor = CLIPProcessor.from_pretrained(model_name)
            _clip_model = CLIPModel.from_pretrained(model_name)
            _clip_model.eval()
            logger.info("Loaded CLIP model %s", model_name)
        except Exception as e:
            _clip_model = False
            logger.warning("CLIP unavailable: %s", e)
    return _clip_model if _clip_model is not False else None, _clip_processor


class CLIPEmbedder:
    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.frame_embeddings: Optional[np.ndarray] = None
        self.frame_records: List[FrameRecord] = []
        CLIP_CACHE.mkdir(parents=True, exist_ok=True)

    @property
    def cache_path(self) -> Path:
        return CLIP_CACHE / f"{self.video_id}.npy"

    def embed_frames(self, frame_index: FrameIndex, batch_size: int = 16) -> None:
        model, processor = _load_clip()
        records = frame_index.sorted()
        self.frame_records = records

        if self.cache_path.is_file():
            self.frame_embeddings = np.load(self.cache_path)
            if len(self.frame_embeddings) == len(records):
                return

        if model is None or not records:
            return

        import torch
        from PIL import Image

        all_embs: List[np.ndarray] = []
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            images = []
            valid_idx = []
            for j, rec in enumerate(batch):
                try:
                    images.append(Image.open(rec.frame_path).convert("RGB"))
                    valid_idx.append(j)
                except Exception:
                    pass
            if not images:
                continue
            inputs = processor(images=images, return_tensors="pt", padding=True)
            with torch.no_grad():
                feats = model.get_image_features(**inputs)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            all_embs.append(feats.cpu().numpy())

        if all_embs:
            self.frame_embeddings = np.vstack(all_embs)
            np.save(self.cache_path, self.frame_embeddings)

    def embed_query_text(self, query: str) -> Optional[np.ndarray]:
        model, processor = _load_clip()
        if model is None:
            return None
        import torch

        inputs = processor(text=[query], return_tensors="pt", padding=True)
        with torch.no_grad():
            feats = model.get_text_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()[0]

    def search_frames_by_text(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[FrameRecord, float]]:
        if self.frame_embeddings is None or not self.frame_records:
            return []

        q = self.embed_query_text(query)
        if q is None:
            return []

        scores = self.frame_embeddings @ q
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)[:top_k]
        return [(self.frame_records[i], float(s)) for i, s in ranked]
