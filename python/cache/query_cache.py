"""
Query result cache — Phase 9.2.

Caches retrieval results keyed by video_id + query + top_k (TTL 1 hour).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.axew/query_cache")
TTL_SEC = 3600


def _get_cache():
    try:
        from diskcache import Cache

        return Cache(CACHE_DIR, size_limit=1 * 2**30)
    except ImportError:
        logger.debug("diskcache not installed; query cache disabled")
        return None


def cache_key(video_id: str, query: str, top_k: int) -> str:
    raw = f"{video_id}:{query}:{top_k}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get_cached(video_id: str, query: str, top_k: int) -> Optional[dict[str, Any]]:
    cache = _get_cache()
    if cache is None:
        return None
    key = cache_key(video_id, query, top_k)
    value = cache.get(key)
    if value is None:
        return None
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return None


def set_cached(video_id: str, query: str, top_k: int, payload: dict[str, Any]) -> None:
    cache = _get_cache()
    if cache is None:
        return
    key = cache_key(video_id, query, top_k)
    cache.set(key, json.dumps(payload), expire=TTL_SEC)
