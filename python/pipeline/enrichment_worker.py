"""Background enrichment after transcription."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from python.enrichment.builder import build_enriched_transcript

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    def __init__(self) -> None:
        self._status: Dict[str, Dict[str, Any]] = {}

    def status(self, video_id: str) -> Dict[str, Any]:
        return self._status.get(video_id, {"status": "idle", "progress": 0.0})

    async def run_async(
        self,
        video_id: str,
        segments: List[Dict[str, Any]],
        audio_path: Optional[str] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._status[video_id] = {"status": "enriching", "progress": 0.0}
        loop = asyncio.get_event_loop()

        def _progress(p: float) -> None:
            self._status[video_id] = {"status": "enriching", "progress": p}
            if on_progress:
                on_progress(p)

        with ThreadPoolExecutor(max_workers=2) as pool:
            _progress(0.2)
            await loop.run_in_executor(
                pool,
                lambda: build_enriched_transcript(segments, video_id=video_id, audio_path=audio_path),
            )
            _progress(1.0)

        self._status[video_id] = {"status": "ready", "progress": 1.0, "enriched": True}
