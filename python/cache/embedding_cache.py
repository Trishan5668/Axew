"""Disk-backed embedding cache keyed by content hash with in-memory LRU."""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Two-tier cache: fast in-memory dict + persistent .npy files on disk."""

    def __init__(self, cache_dir: Optional[str] = None, model_name: str = "all-MiniLM-L6-v2") -> None:
        root = Path(cache_dir) if cache_dir else Path.home() / ".axew" / "embedding_cache"
        self.cache_dir = root / model_name.replace("/", "_")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        self._memory_cache: Dict[str, np.ndarray] = {}

    def _key(self, text: str) -> str:
        payload = f"{self.model_name}:{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def get(self, text: str) -> Optional[np.ndarray]:
        key = self._key(text)
        if key in self._memory_cache:
            return self._memory_cache[key]
        path = self.cache_dir / f"{key}.npy"
        if path.exists():
            try:
                arr = np.load(path)
                self._memory_cache[key] = arr
                return arr
            except Exception as e:
                logger.warning("Failed to load cached embedding %s: %s", key[:12], e)
                return None
        return None

    def set(self, text: str, embedding: np.ndarray) -> None:
        key = self._key(text)
        self._memory_cache[key] = embedding.astype(np.float32)
        try:
            np.save(self.cache_dir / f"{key}.npy", embedding.astype(np.float32))
        except Exception as e:
            logger.warning("Failed to persist embedding %s: %s", key[:12], e)

    def has(self, text: str) -> bool:
        key = self._key(text)
        if key in self._memory_cache:
            return True
        return (self.cache_dir / f"{key}.npy").exists()

    def clear_memory(self) -> None:
        self._memory_cache.clear()

    def stats(self) -> Dict[str, int]:
        disk_count = len(list(self.cache_dir.glob("*.npy")))
        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": disk_count,
        }


class BM25IndexCache:
    """Pickle-based BM25 index cache, invalidated on transcript checksum change."""

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        root = Path(cache_dir) if cache_dir else Path.home() / ".axew" / "bm25_cache"
        self.cache_dir = root
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _checksum(self, texts: list[str]) -> str:
        content = "\n".join(texts).encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]

    def _path(self, video_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in video_id)
        return self.cache_dir / f"{safe_id}.pkl"

    def get(self, video_id: str, texts: list[str]):
        path = self._path(video_id)
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
            if data.get("checksum") == self._checksum(texts):
                return data.get("index")
        except Exception as e:
            logger.warning("BM25 cache load failed for %s: %s", video_id, e)
        return None

    def set(self, video_id: str, texts: list[str], index) -> None:
        path = self._path(video_id)
        try:
            with path.open("wb") as f:
                pickle.dump({"checksum": self._checksum(texts), "index": index}, f)
        except Exception as e:
            logger.warning("BM25 cache save failed for %s: %s", video_id, e)
