"""
Singleton registry for ML models — load once, reuse, unload under pressure.

Defaults to lightweight models (MiniLM-L6-v2, tiny cross-encoder) to keep
the AI service stable on CPU-only / low-RAM laptops.
Set AXEW_EMBED_MODEL=bge-large to opt-in to the heavy model.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Environment overrides
_EMBED_MODEL = os.environ.get("AXEW_EMBED_MODEL", "minilm")  # "minilm" | "bge-large"
_CROSS_MODEL = os.environ.get("AXEW_CROSS_MODEL", "tiny")  # "tiny" | "base" | "large"

LIGHTWEIGHT_BI_ENCODER = "all-MiniLM-L6-v2"
HEAVY_BI_ENCODER = "BAAI/bge-large-en-v1.5"

LIGHTWEIGHT_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
BASE_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-12-v2"
LARGE_CROSS_ENCODER = "cross-encoder/ms-marco-electra-base"


class ModelRegistry:
    _instance: Optional["ModelRegistry"] = None

    def __new__(cls) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._bi_encoder = None
        self._cross_encoder = None
        self._cross_encoder_large = None
        self._device = "cpu"
        self._bi_model_name: Optional[str] = None
        self._load_device()

    def _load_device(self) -> None:
        try:
            import torch

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            if self._device == "cpu":
                logger.info("CPU-only mode — using lightweight models by default")
        except ImportError:
            self._device = "cpu"

    @property
    def device(self) -> str:
        return self._device

    def get_bi_encoder(self):
        if self._bi_encoder is not None:
            self._touch("bi_encoder")
            return self._bi_encoder

        from python.resource_manager import should_use_lightweight, get_model_lifecycle

        prefer_light = self._device == "cpu" or _EMBED_MODEL != "bge-large" or should_use_lightweight()
        model_name = LIGHTWEIGHT_BI_ENCODER if prefer_light else HEAVY_BI_ENCODER

        try:
            from sentence_transformers import SentenceTransformer

            self._bi_encoder = SentenceTransformer(model_name, device=self._device)
            self._bi_model_name = model_name
            size_est = 90.0 if prefer_light else 420.0
            get_model_lifecycle().register("bi_encoder", self._bi_encoder, size_est)
            logger.info("Loaded bi-encoder: %s (~%.0f MB)", model_name, size_est)
        except Exception as e:
            if model_name != LIGHTWEIGHT_BI_ENCODER:
                logger.warning("Failed to load %s (%s), falling back to MiniLM", model_name, e)
                self._bi_encoder = SentenceTransformer(LIGHTWEIGHT_BI_ENCODER, device=self._device)
                self._bi_model_name = LIGHTWEIGHT_BI_ENCODER
                get_model_lifecycle().register("bi_encoder", self._bi_encoder, 90.0)
            else:
                raise
        return self._bi_encoder

    def get_cross_encoder(self, use_large: bool = False):
        from python.resource_manager import should_use_lightweight, should_skip_models, get_model_lifecycle

        if should_skip_models():
            return None

        from sentence_transformers import CrossEncoder

        if use_large and _CROSS_MODEL == "large" and not should_use_lightweight():
            if self._cross_encoder_large is None:
                try:
                    self._cross_encoder_large = CrossEncoder(LARGE_CROSS_ENCODER, device=self._device)
                    get_model_lifecycle().register("cross_encoder_large", self._cross_encoder_large, 440.0)
                except Exception as e:
                    logger.warning("Large cross-encoder failed: %s — using lightweight", e)
                    return self.get_cross_encoder(False)
            self._touch("cross_encoder_large")
            return self._cross_encoder_large

        if self._cross_encoder is None:
            model_name = LIGHTWEIGHT_CROSS_ENCODER if should_use_lightweight() else BASE_CROSS_ENCODER
            self._cross_encoder = CrossEncoder(model_name, device=self._device)
            size_est = 80.0 if "L-6" in model_name else 130.0
            get_model_lifecycle().register("cross_encoder", self._cross_encoder, size_est)
            logger.info("Loaded cross-encoder: %s (~%.0f MB)", model_name, size_est)
        self._touch("cross_encoder")
        return self._cross_encoder

    def unload_bi_encoder(self) -> None:
        if self._bi_encoder is not None:
            from python.resource_manager import get_model_lifecycle

            get_model_lifecycle().unload("bi_encoder")
            self._bi_encoder = None
            self._bi_model_name = None

    def unload_cross_encoders(self) -> None:
        from python.resource_manager import get_model_lifecycle

        if self._cross_encoder is not None:
            get_model_lifecycle().unload("cross_encoder")
            self._cross_encoder = None
        if self._cross_encoder_large is not None:
            get_model_lifecycle().unload("cross_encoder_large")
            self._cross_encoder_large = None

    def unload_all(self) -> None:
        self.unload_bi_encoder()
        self.unload_cross_encoders()

    def _touch(self, name: str) -> None:
        from python.resource_manager import get_model_lifecycle

        get_model_lifecycle().touch(name)
